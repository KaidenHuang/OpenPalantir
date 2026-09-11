"""
ToolRegistry — 统一的工具注册表

内置工具（系统核心数据查询）+ Skill + MCP 全部统一为 OpenAI function-calling 格式。
内置工具硬编码注册，外部不可修改，防止 Skill 被篡改导致安全问题。
"""
import json
import re
import time
from typing import Any

from decision_engine.agentic.types import Observation
from system.logger import logger


def _sanitize_neo4j_types(obj):
    """递归清理 Neo4j 特殊类型（DateTime 等），转为 JSON 可序列化类型"""
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_neo4j_types(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_neo4j_types(v) for v in obj]
    # neo4j.time.DateTime / neo4j.time.Date 等 → str
    return str(obj)


def _try_number(val) -> Any:
    """尝试将值转为数值类型（int → float），失败返回 None"""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return val
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            try:
                return float(val)
            except ValueError:
                pass
    return None


def _eval_operator(op: str, attr_val, target) -> bool:
    """求值单个操作符"""
    if op == "$ne":
        return str(attr_val) != str(target)
    if op == "$in":
        if not isinstance(target, list):
            return False
        return str(attr_val) in [str(t) for t in target]
    if op == "$regex":
        try:
            return bool(re.search(str(target), str(attr_val)))
        except re.error:
            return False
    # $gt, $lt, $gte, $lte — 优先数值比较，回退到字符串比较
    a_num = _try_number(attr_val)
    t_num = _try_number(target)
    if a_num is not None and t_num is not None:
        a_cmp, t_cmp = a_num, t_num
    else:
        a_cmp, t_cmp = str(attr_val), str(target)
    if op == "$gt":
        return a_cmp > t_cmp
    if op == "$lt":
        return a_cmp < t_cmp
    if op == "$gte":
        return a_cmp >= t_cmp
    if op == "$lte":
        return a_cmp <= t_cmp
    return False


def _match_filters(attributes: dict, filters: dict) -> bool:
    """检查 attributes 是否满足所有筛选条件。

    支持两种格式：
    - 精确匹配（向后兼容）：{"gender": "F"}
    - 操作符语法：{"salary": {"$gt": 10000}}，支持 $gt/$lt/$gte/$lte/$ne/$in/$regex
    - 复合操作符：{"salary": {"$gte": 5000, "$lte": 10000}}
    """
    if not filters:
        return True
    for key, condition in filters.items():
        attr_val = attributes.get(key)
        if attr_val is None:
            return False
        # 操作符语法：condition 是 dict 且包含 $ 开头的 key
        if isinstance(condition, dict) and any(k.startswith("$") for k in condition):
            for op, target in condition.items():
                if not op.startswith("$"):
                    continue
                if not _eval_operator(op, attr_val, target):
                    return False
        else:
            # 精确匹配（向后兼容）
            if str(attr_val) != str(condition):
                return False
    return True


def _extract_numeric_value(raw, field: str):
    """从属性值中提取数值。处理三种情况：
    1. 标量（int/float/str）→ 直接 _try_number
    2. 数组（如 salaries）→ 取最新记录，提取 field 对应的值
    3. 字典 → 提取 field 对应的值
    """
    if raw is None:
        return None
    # 标量
    num = _try_number(raw)
    if num is not None:
        return num
    # 数组：取最新记录（最后一条或 to_date 最大的）
    if isinstance(raw, list) and raw:
        latest = raw[-1]  # 默认取最后一条
        if isinstance(latest, dict):
            # 尝试按 to_date 排序取最新
            dated = [r for r in raw if isinstance(r, dict) and r.get("to_date")]
            if dated:
                latest = max(dated, key=lambda r: str(r["to_date"]))
            val = latest.get(field)
            if val is not None:
                return _try_number(val)
            # 兜底：取第一个数值字段
            for v in latest.values():
                n = _try_number(v)
                if n is not None:
                    return n
    # 字典
    if isinstance(raw, dict):
        val = raw.get(field)
        if val is not None:
            return _try_number(val)
    return None


def _apply_field_selection(entity: dict, fields: list) -> dict:
    """仅保留 attributes 中指定的字段，减少返回数据量"""
    if not fields:
        return entity
    attrs = entity.get("attributes", {})
    if isinstance(attrs, str):
        return entity
    filtered_attrs = {k: v for k, v in attrs.items() if k in fields}
    return {**entity, "attributes": filtered_attrs}


def _sort_entities(entities: list, sort_by: dict) -> list:
    """按指定属性字段排序，数值优先，None 值排末尾"""
    if not sort_by or not sort_by.get("field"):
        return entities
    field = sort_by["field"]
    reverse = sort_by.get("order", "asc") == "desc"

    # 分组：有值和无值分开排，保证 None 始终排末尾
    has_val = []
    no_val = []
    for e in entities:
        val = e.get("attributes", {}).get(field)
        if val is None:
            no_val.append(e)
        else:
            has_val.append(e)

    def sort_key(e):
        val = e.get("attributes", {}).get(field)
        num = _try_number(val)
        if num is not None:
            return (0, num, "")
        return (1, 0, str(val))

    has_val.sort(key=sort_key, reverse=reverse)
    return has_val + no_val


def _tool_cfg() -> dict:
    """获取工具配置（延迟导入避免循环依赖）"""
    from decision_engine.config import get_config
    return get_config().get("tools", {})


# ── 内置工具执行器 ──


def _execute_search_entities(params: dict) -> dict:
    """搜索知识图谱中的实体，支持属性筛选、分页、排序、字段选择"""
    from knowledge_graph.graph_manager import graph_manager

    query = params.get("query", "")
    if not query:
        return {"entities": [], "total": 0, "error": "缺少 query 参数"}

    cfg = _tool_cfg()
    default_limit = cfg.get("search_default_limit", 10)
    max_limit = cfg.get("search_max_limit", 50)
    limit = min(params.get("limit", default_limit), max_limit)
    offset = params.get("offset", 0)
    entity_type = params.get("entity_type")
    entity_types = [entity_type] if entity_type else None
    filters = params.get("filters") or {}
    fields = params.get("fields") or []
    sort_by = params.get("sort_by") or {}

    try:
        # 有 filters 时扩大搜索量，后过滤后截取
        fetch_limit = limit * 5 if filters else limit

        # offset > 0 时使用分页查询
        total_available = None
        if offset > 0:
            entities, total_available = graph_manager.search_entities_with_pagination(
                query=query, limit=fetch_limit, offset=offset, entity_type=entity_type
            )
        else:
            entities = graph_manager.search_entities(
                query=query, limit=fetch_limit, entity_types=entity_types
            )
        entities = _sanitize_neo4j_types(entities)

        if filters:
            entities = [
                e for e in entities
                if _match_filters(e.get("attributes", {}), filters)
            ][:limit]

        if sort_by:
            entities = _sort_entities(entities, sort_by)

        if fields:
            entities = [_apply_field_selection(e, fields) for e in entities]

        result = {"entities": entities, "total": len(entities), "query": query}
        if total_available is not None:
            result["total_available"] = total_available
        if offset > 0:
            result["offset"] = offset
        if filters:
            result["filters_applied"] = filters
        return result
    except Exception as e:
        logger.error(f"[builtin:search_entities] 搜索失败: {e}")
        return {"entities": [], "total": 0, "error": str(e)}


def _execute_explore_neighbors(params: dict) -> dict:
    """从已知实体出发，沿关系遍历找到关联实体（含属性），支持属性筛选统计和聚合"""
    from knowledge_graph.graph_manager import graph_manager

    entity_name = params.get("entity_name", "")
    if not entity_name:
        return {"found": False, "error": "缺少 entity_name 参数"}

    cfg = _tool_cfg()
    default_limit = cfg.get("neighbors_default_limit", 20)
    max_limit = cfg.get("neighbors_max_limit", 100)

    predicate = params.get("predicate", "")
    direction = params.get("direction", "both")
    limit = min(params.get("limit", default_limit), max_limit)
    mode = params.get("mode", "auto")  # auto / detail / summary / aggregate
    filters = params.get("filters") or {}
    fields = params.get("fields") or []
    sort_by = params.get("sort_by") or {}
    aggregate = params.get("aggregate") or {}

    # 兜底：LLM 可能把 op/field/group_by 放在顶层而非嵌套在 aggregate 内
    if not aggregate and mode == "aggregate" and params.get("op"):
        aggregate = {"op": params["op"]}
        if params.get("field"):
            aggregate["field"] = params["field"]
        if params.get("group_by"):
            aggregate["group_by"] = params["group_by"]
        logger.info(f"[explore_neighbors] 兜底: 从顶层参数构造 aggregate={aggregate}")

    # 1) 找起始实体
    try:
        found = graph_manager.search_entities(query=entity_name, limit=5)
    except Exception as e:
        return {"found": False, "error": f"搜索起始实体失败: {e}"}

    if not found:
        return {"found": False, "error": f"未找到实体: {entity_name}"}

    entity = found[0]
    entity_id = entity.get("entity_id", entity.get("id", ""))

    # 2) 获取所有关系
    try:
        relationships = graph_manager.get_entity_relationships(entity_id)
    except Exception as e:
        return {"found": True, "entity": entity, "neighbors": [], "error": f"获取关系失败: {e}"}

    total_relations = len(relationships)

    # 3) Python 侧过滤：predicate + direction
    filtered = []
    for rel in relationships:
        if predicate and rel.get("predicate", "") != predicate:
            continue
        is_outgoing = rel.get("subject_id") == entity_id
        if direction == "outgoing" and not is_outgoing:
            continue
        if direction == "incoming" and is_outgoing:
            continue
        filtered.append(rel)

    filtered_count = len(filtered)

    # 4) aggregate 模式
    if mode == "aggregate" and aggregate:
        return _build_aggregate_result(
            entity, filtered, filtered_count, total_relations, aggregate, filters
        )

    # 5) 带 filters 时：获取所有邻居实体，过滤后统计
    if filters:
        return _build_filtered_result(
            entity, filtered, filtered_count, total_relations, filters, fields
        )

    # 6) 决定模式：auto 时关系 > 20 条自动切换为 summary
    use_summary = mode == "summary" or (mode == "auto" and filtered_count > 20)

    if use_summary:
        return _build_neighbor_summary(entity, filtered, filtered_count, total_relations, fields)

    # 7) detail 模式：批量获取邻居实体（含完整属性）
    neighbor_ids = []
    rel_map = {}
    for rel in filtered[:limit]:
        is_outgoing = rel.get("subject_id") == entity_id
        neighbor_id = rel.get("object_id") if is_outgoing else rel.get("subject_id")
        neighbor_ids.append(neighbor_id)
        rel_map[neighbor_id] = {
            "predicate": rel.get("predicate", ""),
            "direction": "outgoing" if is_outgoing else "incoming",
            "description": rel.get("description", ""),
        }

    batch_entities = graph_manager.get_entities_batch(neighbor_ids) if neighbor_ids else {}

    neighbors = []
    for nid in neighbor_ids:
        ent = batch_entities.get(nid, {"name": nid, "id": nid})
        neighbors.append({
            "entity": ent,
            "predicate": rel_map[nid]["predicate"],
            "direction": rel_map[nid]["direction"],
            "description": rel_map[nid]["description"],
        })

    if sort_by:
        neighbors = _sort_entities(
            [n["entity"] for n in neighbors], sort_by
        )
        # 重新组装排序后的邻居
        entity_map = {e.get("entity_id", e.get("id", "")): e for e in neighbors}
        sorted_neighbors = []
        for nid in [e.get("entity_id", e.get("id", "")) for e in neighbors]:
            if nid in rel_map:
                sorted_neighbors.append({
                    "entity": entity_map.get(nid, {"id": nid}),
                    "predicate": rel_map[nid]["predicate"],
                    "direction": rel_map[nid]["direction"],
                    "description": rel_map[nid]["description"],
                })
        neighbors = sorted_neighbors

    if fields:
        for n in neighbors:
            n["entity"] = _apply_field_selection(n["entity"], fields)

    return _sanitize_neo4j_types({
        "found": True,
        "entity": entity,
        "total_count": filtered_count,
        "neighbors": neighbors,
        "total_relations": total_relations,
        "returned_neighbors": len(neighbors),
    })


def _build_neighbor_summary(entity: dict, filtered: list, filtered_count: int,
                            total_relations: int, fields: list = None) -> dict:
    """关系数量大时，返回统计摘要而非逐条数据"""
    from knowledge_graph.graph_manager import graph_manager

    # 取少量样本（最多 5 个）来展示数据结构
    sample_neighbors = []
    for rel in filtered[:5]:
        is_outgoing = rel.get("subject_id") == entity.get("entity_id", entity.get("id", ""))
        neighbor_id = rel.get("object_id") if is_outgoing else rel.get("subject_id")
        neighbor_name = rel.get("object") if is_outgoing else rel.get("subject")

        neighbor_entity = None
        try:
            neighbor_entity = graph_manager.get_entity(neighbor_id)
        except Exception:
            pass

        ent = neighbor_entity or {"name": neighbor_name, "id": neighbor_id}
        if fields:
            ent = _apply_field_selection(ent, fields)
        sample_neighbors.append({
            "entity": ent,
            "predicate": rel.get("predicate", ""),
            "direction": "outgoing" if is_outgoing else "incoming",
        })

    # 按 predicate 分组统计
    predicate_counts = {}
    for rel in filtered:
        p = rel.get("predicate", "unknown")
        predicate_counts[p] = predicate_counts.get(p, 0) + 1

    return _sanitize_neo4j_types({
        "found": True,
        "entity": entity,
        "mode": "summary",
        "total_count": filtered_count,
        "total_relations": total_relations,
        "predicate_breakdown": predicate_counts,
        "sample_neighbors": sample_neighbors,
        "note": f"共 {filtered_count} 条关系，已返回 {len(sample_neighbors)} 个样本。"
                f"如需更多细节请用 mode='detail' 或调整 predicate/limit 参数。",
    })


def _build_filtered_result(entity: dict, filtered: list, filtered_count: int,
                           total_relations: int, filters: dict,
                           fields: list = None) -> dict:
    """带属性筛选时：批量获取所有邻居实体，过滤后返回统计结果"""
    from knowledge_graph.graph_manager import graph_manager

    entity_id = entity.get("entity_id", entity.get("id", ""))

    # 收集所有邻居 ID
    neighbor_ids = []
    rel_map = {}  # neighbor_id → rel info
    for rel in filtered:
        is_outgoing = rel.get("subject_id") == entity_id
        neighbor_id = rel.get("object_id") if is_outgoing else rel.get("subject_id")
        neighbor_ids.append(neighbor_id)
        rel_map[neighbor_id] = {
            "predicate": rel.get("predicate", ""),
            "direction": "outgoing" if is_outgoing else "incoming",
        }

    # 批量获取实体（单次 Cypher 查询）
    batch_entities = graph_manager.get_entities_batch(neighbor_ids)

    # 组装邻居列表
    all_neighbors = []
    for nid in neighbor_ids:
        ent = batch_entities.get(nid, {"name": nid, "id": nid})
        all_neighbors.append({
            "entity": ent,
            "predicate": rel_map[nid]["predicate"],
            "direction": rel_map[nid]["direction"],
        })

    # 应用属性筛选
    matched = [
        n for n in all_neighbors
        if _match_filters(n["entity"].get("attributes", {}), filters)
    ]

    # 应用字段选择
    if fields:
        for n in matched:
            n["entity"] = _apply_field_selection(n["entity"], fields)

    # 按 predicate 分组统计
    predicate_counts = {}
    for rel in filtered:
        p = rel.get("predicate", "unknown")
        predicate_counts[p] = predicate_counts.get(p, 0) + 1

    return _sanitize_neo4j_types({
        "found": True,
        "entity": entity,
        "mode": "filtered",
        "total_count": filtered_count,
        "matched_count": len(matched),
        "matched_samples": matched[:10],
        "predicate_breakdown": predicate_counts,
        "filters_applied": filters,
        "note": f"共 {filtered_count} 条关系，匹配筛选条件 {len(matched)} 条。"
                f"已返回 {min(len(matched), 10)} 个样本。",
    })


def _build_aggregate_result(entity: dict, filtered: list, filtered_count: int,
                            total_relations: int, aggregate: dict,
                            filters: dict = None) -> dict:
    """聚合模式：批量获取邻居实体，对指定属性做 COUNT/SUM/AVG/MIN/MAX 统计"""
    from knowledge_graph.graph_manager import graph_manager

    entity_id = entity.get("entity_id", entity.get("id", ""))
    op = aggregate.get("op", "COUNT")
    field = aggregate.get("field", "")
    group_by = aggregate.get("group_by", "")

    # 收集邻居 ID
    neighbor_ids = []
    for rel in filtered:
        is_outgoing = rel.get("subject_id") == entity_id
        neighbor_id = rel.get("object_id") if is_outgoing else rel.get("subject_id")
        neighbor_ids.append(neighbor_id)

    # 批量获取实体
    batch_entities = graph_manager.get_entities_batch(neighbor_ids) if neighbor_ids else {}

    # 组装并过滤
    all_entities = []
    for nid in neighbor_ids:
        ent = batch_entities.get(nid, {"name": nid, "id": nid})
        if filters and not _match_filters(ent.get("attributes", {}), filters):
            continue
        all_entities.append(ent)

    matched_count = len(all_entities)

    # COUNT 操作
    if op == "COUNT":
        if group_by:
            groups = {}
            for ent in all_entities:
                key = str(ent.get("attributes", {}).get(group_by, "unknown"))
                groups[key] = groups.get(key, 0) + 1
            return _sanitize_neo4j_types({
                "found": True, "entity": entity, "mode": "aggregate",
                "total_neighbors": filtered_count, "matched_neighbors": matched_count,
                "result": {"op": "COUNT", "value": matched_count,
                           "group_by": group_by, "groups": groups},
            })
        return _sanitize_neo4j_types({
            "found": True, "entity": entity, "mode": "aggregate",
            "total_neighbors": filtered_count, "matched_neighbors": matched_count,
            "result": {"op": "COUNT", "value": matched_count},
        })

    # SUM/AVG/MIN/MAX — 需要数值字段
    if not field:
        return {"found": True, "entity": entity, "mode": "aggregate",
                "result": {"op": op, "error": f"{op} 操作需要指定 field 参数"}}

    # 提取数值（支持标量和嵌套数组字段）
    values = []
    for ent in all_entities:
        raw = ent.get("attributes", {}).get(field)
        if raw is not None:
            num = _extract_numeric_value(raw, field)
            if num is not None:
                values.append(num)

    if not values:
        return _sanitize_neo4j_types({
            "found": True, "entity": entity, "mode": "aggregate",
            "total_neighbors": filtered_count, "matched_neighbors": matched_count,
            "result": {"op": op, "field": field, "value": None,
                       "error": f"未找到有效的数值数据（字段: {field}）"},
        })

    def _compute(vals):
        if op == "SUM":
            return sum(vals)
        if op == "AVG":
            return round(sum(vals) / len(vals), 2)
        if op == "MIN":
            return min(vals)
        if op == "MAX":
            return max(vals)
        return None

    result_data = {"op": op, "field": field, "value": _compute(values)}

    if group_by:
        groups = {}
        group_values = {}
        for ent in all_entities:
            raw = ent.get("attributes", {}).get(field)
            key = str(ent.get("attributes", {}).get(group_by, "unknown"))
            if raw is not None:
                num = _extract_numeric_value(raw, field)
                if num is not None:
                    group_values.setdefault(key, []).append(num)
        for key, vals in group_values.items():
            groups[key] = _compute(vals)
        result_data["group_by"] = group_by
        result_data["groups"] = groups

    return _sanitize_neo4j_types({
        "found": True, "entity": entity, "mode": "aggregate",
        "total_neighbors": filtered_count, "matched_neighbors": matched_count,
        "result": result_data,
    })


def _execute_explore_subgraph(params: dict) -> dict:
    """多跳遍历（1-5 hops），从起始实体出发遍历子图，返回节点和边"""
    from knowledge_graph.graph_manager import graph_manager

    entity_name = params.get("entity_name", "")
    if not entity_name:
        return {"found": False, "error": "缺少 entity_name 参数"}

    cfg = _tool_cfg()
    max_hops = cfg.get("subgraph_max_hops", 5)
    max_limit = cfg.get("subgraph_max_limit", 200)

    hops = min(params.get("hops", 2), max_hops)
    limit = min(params.get("limit", 100), max_limit)
    predicate_filter = params.get("predicate_filter", "")
    fields = params.get("fields") or []

    # 1) 找起始实体
    try:
        found = graph_manager.search_entities(query=entity_name, limit=5)
    except Exception as e:
        return {"found": False, "error": f"搜索起始实体失败: {e}"}

    if not found:
        return {"found": False, "error": f"未找到实体: {entity_name}"}

    entity = found[0]
    entity_id = entity.get("entity_id", entity.get("id", ""))

    # 2) 获取子图
    try:
        subgraph = graph_manager.get_subgraph(entity_id, hops=hops, limit=limit)
    except Exception as e:
        return {"found": True, "entity": entity, "error": f"子图查询失败: {e}"}

    nodes = subgraph.get("nodes", [])
    edges = subgraph.get("edges", [])

    # 3) 按 predicate 过滤边
    if predicate_filter:
        edges = [e for e in edges if e.get("predicate", "") == predicate_filter]
        # 保留有边连接的节点 + 起始节点
        connected_ids = set()
        connected_ids.add(entity_id)
        for e in edges:
            connected_ids.add(e.get("source_id", ""))
            connected_ids.add(e.get("target_id", ""))
        nodes = [n for n in nodes if n.get("id", "") in connected_ids]

    # 4) 精简输出：只保留关键字段
    concise_nodes = []
    for n in nodes:
        node = {"name": n.get("name", ""), "type": n.get("type", ""), "id": n.get("id", "")}
        if fields:
            attrs = n.get("attributes", {})
            if isinstance(attrs, str):
                try:
                    attrs = json.loads(attrs)
                except (json.JSONDecodeError, TypeError):
                    attrs = {}
            node["attributes"] = {k: v for k, v in attrs.items() if k in fields}
        elif n.get("attributes"):
            node["attributes"] = n["attributes"]
        concise_nodes.append(node)

    concise_edges = []
    for e in edges:
        concise_edges.append({
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "predicate": e.get("predicate", ""),
            "occurrence_time": e.get("occurrence_time"),
        })

    return _sanitize_neo4j_types({
        "found": True,
        "entity": entity,
        "hops": hops,
        "node_count": len(concise_nodes),
        "edge_count": len(concise_edges),
        "nodes": concise_nodes,
        "edges": concise_edges,
    })


def _execute_list_summaries(params: dict) -> dict:
    """搜索文档和数据库摘要，返回匹配数据源的高层概要"""
    from decision_engine.agentic.seed_retriever import _tokenize_question
    from decision_engine.contracts import AnalyzedQuery
    from decision_engine.retrievers.document_summary_retriever import DocumentSummaryRetriever
    from decision_engine.retrievers.database_summary_retriever import DatabaseSummaryRetriever

    query_str = params.get("query", "")
    if not query_str:
        return {"documents": [], "databases": [], "error": "缺少 query 参数"}

    cfg = _tool_cfg()
    default_limit = cfg.get("summaries_default_limit", 5)
    max_limit = cfg.get("summaries_max_limit", 10)

    summary_type = params.get("type", "all")
    limit = min(params.get("limit", default_limit), max_limit)

    keywords = _tokenize_question(query_str)
    query = AnalyzedQuery(entities=keywords, intent="general")

    results = {"documents": [], "databases": []}

    if summary_type in ("all", "document"):
        try:
            doc_ev = DocumentSummaryRetriever().retrieve(query, {})
            # 去重：只保留文档级摘要（按 datasource 去重），不含段落级
            seen = set()
            for ev in sorted(doc_ev, key=lambda e: e.relevance_score, reverse=True):
                ds = ev.metadata.get("datasource", "")
                if ds not in seen:
                    seen.add(ds)
                    results["documents"].append({
                        "datasource": ds,
                        "name": ev.content.get("doc_name", ev.source_id),
                        "description": ev.content.get("doc_description", ""),
                    })
                if len(results["documents"]) >= limit:
                    break
        except Exception as e:
            logger.warning(f"[builtin:list_summaries] 文档检索失败: {e}")
            results["documents_error"] = str(e)

    if summary_type in ("all", "database"):
        try:
            db_ev = DatabaseSummaryRetriever().retrieve(query, {})
            # 只保留数据库级摘要：datasource 格式为 DBS://uuid/db_name（不含表名）
            seen = set()
            for ev in sorted(db_ev, key=lambda e: e.relevance_score, reverse=True):
                ds = ev.metadata.get("datasource", "")
                # 过滤掉表级 URI（DBS://uuid/db_name/table_name 有三段路径）
                if not ds or ds.count("/") > 3:
                    continue
                if ds not in seen:
                    seen.add(ds)
                    results["databases"].append({
                        "datasource": ds,
                        "name": ev.content.get("db_name", ev.source_id),
                        "description": ev.content.get("db_description", ""),
                        "business_domain": ev.content.get("business_domain", ""),
                    })
                if len(results["databases"]) >= limit:
                    break
        except Exception as e:
            logger.warning(f"[builtin:list_summaries] 数据库检索失败: {e}")
            results["databases_error"] = str(e)

    return results


def _execute_get_summary_detail(params: dict) -> dict:
    """获取指定数据源的详细结构（文档段落或数据库表结构）

    兼容库级 URI（DBS://uuid/db_name）和表级 URI（DBS://uuid/db_name/table_name），
    始终返回整个数据库/文档的完整结构。
    """
    from glob import glob as glob_func
    import os

    datasource = params.get("datasource", "")
    if not datasource:
        return {"error": "请提供 datasource 参数"}

    # 解析 URI：DOC://... 或 DBS://...
    if datasource.startswith("DOC://"):
        resource_type = "DOC"
    elif datasource.startswith("DBS://"):
        resource_type = "DBS"
    else:
        return {"error": f"不支持的 datasource 格式: {datasource}"}

    # 提取 UUID（第一段路径），忽略后续的 db_name/table_name
    summaries_dir = os.path.join(
        os.path.dirname(__file__), "..", "..", "data", "summaries"
    )
    uri_body = datasource.split("://")[1]
    uuid = uri_body.split("/", 1)[0]
    target_dir = os.path.join(os.path.abspath(summaries_dir), resource_type, uuid)

    json_files = glob_func(os.path.join(target_dir, "*.json"))
    if not json_files:
        return {"error": f"未找到 datasource={datasource} 对应的摘要文件"}

    with open(json_files[0], "r", encoding="utf-8") as f:
        data = json.load(f)

    # 返回规范化的库级/文档级 datasource
    if resource_type == "DOC":
        canonical_ds = f"DOC://{uuid}/{data.get('doc_name', '')}"
        return {
            "type": "document",
            "datasource": canonical_ds,
            "name": data.get("doc_name", ""),
            "description": data.get("doc_description", ""),
            "structure": data.get("structure", []),
        }
    else:  # DBS
        db_name = data.get("db_name", "")
        canonical_ds = f"DBS://{uuid}/{db_name}" if db_name else datasource
        return {
            "type": "database",
            "datasource": canonical_ds,
            "name": db_name,
            "description": data.get("db_description", ""),
            "business_domain": data.get("business_domain", ""),
            "tables": data.get("structure", []),
        }


# ── 内置工具定义（OpenAI function-calling 格式）──

_BUILTIN_TOOLS = {
    "search_entities": {
        "definition": {
            "type": "function",
            "function": {
                "name": "search_entities",
                "description": "搜索知识图谱中的实体，支持关键词匹配、类型过滤和属性筛选。支持操作符过滤（$gt/$lt/$gte/$lte/$ne/$in/$regex）、分页、排序和字段选择",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "entity_type": {"type": "string", "description": "实体类型过滤（如 departments、employees）"},
                        "limit": {"type": "integer", "description": "返回数量上限（默认10）"},
                        "offset": {"type": "integer", "description": "分页偏移量（默认0）。设为10可获取下一批结果"},
                        "filters": {"type": "object", "description": "属性筛选。精确匹配如 {\"gender\": \"F\"}；操作符如 {\"salary\": {\"$gt\": 10000}}；复合如 {\"hire_date\": {\"$gte\": \"2023-01-01\"}}。支持 $gt/$lt/$gte/$lte/$ne/$in/$regex", "additionalProperties": True},
                        "fields": {"type": "array", "items": {"type": "string"}, "description": "仅返回指定属性字段（如 [\"salary\", \"gender\"]），减少响应大小。省略则返回全部"},
                        "sort_by": {"type": "object", "description": "按属性字段排序", "properties": {"field": {"type": "string", "description": "排序字段"}, "order": {"type": "string", "enum": ["asc", "desc"], "description": "排序方向，默认 asc"}}},
                    },
                    "required": ["query"],
                },
            },
        },
        "executor": _execute_search_entities,
    },
    "explore_neighbors": {
        "definition": {
            "type": "function",
            "function": {
                "name": "explore_neighbors",
                "description": "从已知实体出发，沿关系遍历找到关联实体。支持属性筛选统计、聚合（COUNT/SUM/AVG/MIN/MAX）、分组统计。用于查找部门员工、统计人数、计算平均薪资等场景",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "起始实体名称"},
                        "predicate": {"type": "string", "description": "关系类型过滤（如 dept_emp、dept_manager、Foreign key）"},
                        "direction": {"type": "string", "description": "遍历方向: outgoing/incoming/both（默认 both）"},
                        "limit": {"type": "integer", "description": "返回邻居数量上限（默认20）"},
                        "mode": {"type": "string", "description": "返回模式: auto(自动)/detail(逐条)/summary(统计摘要)/aggregate(聚合计算)。关系多时建议用 summary；统计用 aggregate"},
                        "filters": {"type": "object", "description": "对邻居实体的属性筛选。精确匹配如 {\"gender\": \"F\"}；操作符如 {\"salary\": {\"$gt\": 10000}}。启用后统计匹配数量", "additionalProperties": True},
                        "fields": {"type": "array", "items": {"type": "string"}, "description": "仅返回指定属性字段，减少响应大小"},
                        "sort_by": {"type": "object", "description": "按属性字段排序", "properties": {"field": {"type": "string"}, "order": {"type": "string", "enum": ["asc", "desc"]}}},
                        "aggregate": {"type": "object", "description": "聚合配置（mode=aggregate 时必须嵌套在此对象内）。计算邻居实体属性的统计值。数组字段（如 salaries）自动取最新记录", "properties": {"op": {"type": "string", "enum": ["COUNT", "SUM", "AVG", "MIN", "MAX"], "description": "聚合操作"}, "field": {"type": "string", "description": "聚合字段名（COUNT 时不需要）。注意字段名需与 attributes 中的键一致（如 salaries 表的字段用 salaries，不是 salary）"}, "group_by": {"type": "string", "description": "分组字段（可选），如按 gender 分组统计"}}},
                    },
                    "required": ["entity_name"],
                },
            },
        },
        "executor": _execute_explore_neighbors,
    },
    "explore_subgraph": {
        "definition": {
            "type": "function",
            "function": {
                "name": "explore_subgraph",
                "description": "多跳遍历（1-5 hops），从起始实体出发遍历子图，返回节点和边。用于组织层级、间接关系、关联链路等场景",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "起始实体名称"},
                        "hops": {"type": "integer", "description": "跳数（1-5，默认2）。1=直接关系，2=间接关系"},
                        "limit": {"type": "integer", "description": "最大返回节点数（默认100，最大200）"},
                        "predicate_filter": {"type": "string", "description": "仅包含指定类型的边（如 dept_emp）。省略则包含所有类型"},
                        "fields": {"type": "array", "items": {"type": "string"}, "description": "仅返回节点的指定属性字段"},
                    },
                    "required": ["entity_name"],
                },
            },
        },
        "executor": _execute_explore_subgraph,
    },
    "list_summaries": {
        "definition": {
            "type": "function",
            "function": {
                "name": "list_summaries",
                "description": (
                    "【应首先调用】搜索系统中已有的文档和数据库，返回匹配数据源的名称和描述。"
                    "用于发现有哪些可用数据源。返回结果中的 datasource 字段"
                    "可用于 get_summary_detail 工具获取详细信息。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "type": {"type": "string", "enum": ["all", "document", "database"],
                                 "description": "搜索类型，默认 all"},
                        "limit": {"type": "integer", "description": "每类最大返回数，默认 5"},
                    },
                    "required": ["query"],
                },
            },
        },
        "executor": _execute_list_summaries,
    },
    "get_summary_detail": {
        "definition": {
            "type": "function",
            "function": {
                "name": "get_summary_detail",
                "description": (
                    "获取指定文档的段落结构或数据库的表结构详情。"
                    "datasource 参数来自 list_summaries 返回的 datasource 字段。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "datasource": {"type": "string",
                                       "description": "数据源 URI（来自 list_summaries 返回结果）"},
                    },
                    "required": ["datasource"],
                },
            },
        },
        "executor": _execute_get_summary_detail,
    },
}


class ToolRegistry:
    """统一的工具注册表 — 内置 + Skill + MCP"""

    def __init__(self, skill_registry, mcp_manager=None):
        self._skill_registry = skill_registry
        self._mcp_manager = mcp_manager
        self._builtin_tools = _BUILTIN_TOOLS

    def get_definitions(self, domain: str) -> list:
        """获取 OpenAI 兼容的 tools 列表（内置 + Skill + MCP）"""
        tools = []

        # 内置工具（始终存在）
        for tool_info in self._builtin_tools.values():
            tools.append(tool_info["definition"])

        # Skill 工具
        try:
            tools += self._skill_registry.get_tool_definitions(domain)
        except Exception as e:
            logger.warning(f"[tools] Skill 工具加载失败: {e}")

        # MCP 工具
        if self._mcp_manager:
            try:
                tools += self._mcp_manager.get_tool_definitions()
            except Exception as e:
                logger.warning(f"[tools] MCP 工具加载失败: {e}")

        return tools

    def execute(self, name: str, params: dict) -> Observation:
        """执行工具，统一返回 Observation"""
        start = time.time()
        tool_call_id = ""

        try:
            # 优先级：内置工具 → MCP → Skill
            if name in self._builtin_tools:
                result = self._builtin_tools[name]["executor"](params)
                summary = self._summarize_generic(result)
            elif self._mcp_manager and self._is_mcp_tool(name):
                result = self._mcp_manager.execute(name, params)
                summary = self._summarize_mcp(result)
            else:
                result = self._skill_registry.execute(name, params)
                skill = self._skill_registry.get(name)
                if skill and hasattr(result, "summarize"):
                    summary = skill.summarize(result)
                else:
                    summary = self._summarize_generic(result)
            success = True
        except Exception as e:
            logger.error(f"[tools] 工具 {name} 执行失败: {e}")
            result = {"error": str(e), "success": False}
            summary = f"工具执行失败: {e}"
            success = False

        elapsed = (time.time() - start) * 1000

        return Observation(
            tool_name=name,
            params=params,
            summary=summary,
            full_result=result if isinstance(result, dict) else {"data": str(result)},
            tool_call_id=tool_call_id,
            execution_time_ms=elapsed,
            success=success,
        )

    def _is_mcp_tool(self, name: str) -> bool:
        """判断是否为 MCP 工具（命名格式：{server}__{tool}）"""
        if self._mcp_manager and hasattr(self._mcp_manager, "is_mcp_tool"):
            return self._mcp_manager.is_mcp_tool(name)
        return "__" in name

    def _summarize_mcp(self, result: Any) -> str:
        """MCP 工具结果摘要（MCP 返回 dict）"""
        if not result:
            return "（无结果）"
        if isinstance(result, dict):
            if result.get("error"):
                return f"工具执行失败: {result['error']}"
            if "data" in result:
                data = result["data"]
                if isinstance(data, list):
                    return f"返回 {len(data)} 条记录"
                text = str(data)
                return text[:497] + "..." if len(text) > 500 else text
        return self._summarize_generic(result)

    @staticmethod
    def _summarize_generic(result: Any) -> str:
        """通用兜底摘要"""
        if not result:
            return "（无结果）"
        text = str(result)
        return text[:497] + "..." if len(text) > 500 else text
