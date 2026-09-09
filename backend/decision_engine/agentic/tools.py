"""
ToolRegistry — 统一的工具注册表

内置工具（系统核心数据查询）+ Skill + MCP 全部统一为 OpenAI function-calling 格式。
内置工具硬编码注册，外部不可修改，防止 Skill 被篡改导致安全问题。
"""
import json
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


def _match_filters(attributes: dict, filters: dict) -> bool:
    """检查 attributes 是否满足所有筛选条件（精确匹配）"""
    if not filters:
        return True
    for key, value in filters.items():
        attr_val = attributes.get(key)
        if attr_val is None:
            return False
        # 统一转字符串比较，兼容 int/str 类型差异
        if str(attr_val) != str(value):
            return False
    return True


# ── 内置工具执行器 ──


def _execute_search_entities(params: dict) -> dict:
    """搜索知识图谱中的实体，支持属性筛选，返回完整属性"""
    from knowledge_graph.graph_manager import graph_manager

    query = params.get("query", "")
    if not query:
        return {"entities": [], "total": 0, "error": "缺少 query 参数"}

    limit = min(params.get("limit", 10), 50)
    entity_type = params.get("entity_type")
    entity_types = [entity_type] if entity_type else None
    filters = params.get("filters") or {}

    try:
        # 有 filters 时扩大搜索量，后过滤后截取
        fetch_limit = limit * 5 if filters else limit
        entities = graph_manager.search_entities(
            query=query, limit=fetch_limit, entity_types=entity_types
        )
        entities = _sanitize_neo4j_types(entities)

        if filters:
            entities = [
                e for e in entities
                if _match_filters(e.get("attributes", {}), filters)
            ][:limit]

        return {"entities": entities, "total": len(entities), "query": query,
                **({"filters_applied": filters} if filters else {})}
    except Exception as e:
        logger.error(f"[builtin:search_entities] 搜索失败: {e}")
        return {"entities": [], "total": 0, "error": str(e)}


def _execute_explore_neighbors(params: dict) -> dict:
    """从已知实体出发，沿关系遍历找到关联实体（含属性），支持属性筛选统计"""
    from knowledge_graph.graph_manager import graph_manager

    entity_name = params.get("entity_name", "")
    if not entity_name:
        return {"found": False, "error": "缺少 entity_name 参数"}

    predicate = params.get("predicate", "")
    direction = params.get("direction", "both")
    limit = min(params.get("limit", 20), 100)
    mode = params.get("mode", "auto")  # auto / detail / summary
    filters = params.get("filters") or {}

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

    # 4) 带 filters 时：获取所有邻居实体，过滤后统计
    if filters:
        return _build_filtered_result(
            entity, filtered, filtered_count, total_relations, filters
        )

    # 5) 决定模式：auto 时关系 > 20 条自动切换为 summary
    use_summary = mode == "summary" or (mode == "auto" and filtered_count > 20)

    if use_summary:
        return _build_neighbor_summary(entity, filtered, filtered_count, total_relations)

    # 6) detail 模式：获取邻居实体（含完整属性）
    neighbors = []
    for rel in filtered[:limit]:
        is_outgoing = rel.get("subject_id") == entity_id
        neighbor_id = rel.get("object_id") if is_outgoing else rel.get("subject_id")
        neighbor_name = rel.get("object") if is_outgoing else rel.get("subject")
        rel_direction = "outgoing" if is_outgoing else "incoming"

        neighbor_entity = None
        try:
            neighbor_entity = graph_manager.get_entity(neighbor_id)
        except Exception:
            pass

        neighbors.append({
            "entity": neighbor_entity or {"name": neighbor_name, "id": neighbor_id},
            "predicate": rel.get("predicate", ""),
            "direction": rel_direction,
            "description": rel.get("description", ""),
        })

    return _sanitize_neo4j_types({
        "found": True,
        "entity": entity,
        "total_count": filtered_count,
        "neighbors": neighbors,
        "total_relations": total_relations,
        "returned_neighbors": len(neighbors),
    })


def _build_neighbor_summary(entity: dict, filtered: list, filtered_count: int,
                            total_relations: int) -> dict:
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

        sample_neighbors.append({
            "entity": neighbor_entity or {"name": neighbor_name, "id": neighbor_id},
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
                           total_relations: int, filters: dict) -> dict:
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


def _execute_list_summaries(params: dict) -> dict:
    """搜索文档和数据库摘要，返回匹配数据源的高层概要"""
    from decision_engine.agentic.seed_retriever import _tokenize_question
    from decision_engine.contracts import AnalyzedQuery
    from decision_engine.retrievers.document_summary_retriever import DocumentSummaryRetriever
    from decision_engine.retrievers.database_summary_retriever import DatabaseSummaryRetriever

    query_str = params.get("query", "")
    if not query_str:
        return {"documents": [], "databases": [], "error": "缺少 query 参数"}

    summary_type = params.get("type", "all")
    limit = min(params.get("limit", 5), 10)

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
                "description": "搜索知识图谱中的实体，支持关键词匹配、类型过滤和属性筛选，返回实体完整属性（含 birth_date、salaries、titles 等详细数据）",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "entity_type": {"type": "string", "description": "实体类型过滤（如 departments、employees）"},
                        "limit": {"type": "integer", "description": "返回数量上限（默认10，最大50）"},
                        "filters": {"type": "object", "description": "属性精确筛选（键值对），如 {\"gender\": \"F\"}。对实体的 attributes 字段做精确匹配", "additionalProperties": True},
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
                "description": "从已知实体出发，沿关系遍历找到关联实体。支持属性筛选统计（如按性别计数）。用于查找部门员工、人员关联、统计人数等场景",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "起始实体名称"},
                        "predicate": {"type": "string", "description": "关系类型过滤（如 dept_emp、dept_manager、Foreign key）"},
                        "direction": {"type": "string", "description": "遍历方向: outgoing/incoming/both（默认 both）"},
                        "limit": {"type": "integer", "description": "返回邻居数量上限（默认20，最大100）"},
                        "mode": {"type": "string", "description": "返回模式: auto(自动)/detail(逐条)/summary(统计摘要)。关系多时建议用 summary 获取总数和样本"},
                        "filters": {"type": "object", "description": "对邻居实体的属性精确筛选，如 {\"gender\": \"F\"}。启用后统计匹配数量并返回 matched_count", "additionalProperties": True},
                    },
                    "required": ["entity_name"],
                },
            },
        },
        "executor": _execute_explore_neighbors,
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
