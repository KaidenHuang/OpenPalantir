"""
实体仓库 — 封装 Neo4j 实体节点的全部 CRUD 操作

从 GraphManager 中拆出，职责单一：实体增删改查。
GraphManager 作为薄门面委托调用本模块。
"""
import json
from typing import List, Dict, Any, Optional, Tuple
from config.neo4j_config import neo4j_conn
from knowledge_graph.graph_performance import graph_performance
from knowledge_graph.source_scope import (
    match_any_prefix, match_either, match_prefix, pure_uri, strip_prefix,
    strip_stale_evidence, union_sources,
)
from system.logger import logger
from system.metrics import GRAPH_WRITES
from models.ids import compute_entity_id


def allocate_type_quota(type_counts: Dict[str, int], budget: int) -> Dict[str, int]:
    """分层抽样配额公式（唯一应用点，viz 快照与实体分页共用）

    每类型先保底 min_per_type = max(1, budget // (类型数 × 5))，保证长尾类型可见；
    剩余预算按类型样本占比追加。返回 {type: 建议抽取数}，调用方自行 min 截断到存量。
    """
    if budget <= 0 or not type_counts:
        return {}
    total = sum(count for count in type_counts.values() if count > 0)
    if total <= 0:
        return {}
    type_names = sorted(type_counts.keys(), key=lambda t: type_counts[t], reverse=True)
    min_per_type = max(1, budget // (len(type_names) * 5))
    reserved = min_per_type * len(type_names)
    remaining_budget = max(0, budget - reserved)

    quotas: Dict[str, int] = {}
    for t in type_names:
        share = min_per_type
        if remaining_budget > 0:
            share += int(remaining_budget * type_counts[t] / total)
        quotas[t] = share
    return quotas


def _deserialize_attributes(node: dict) -> dict:
    """反序列化节点的 attributes JSON 字符串为 dict"""
    attrs = node.get("attributes")
    if isinstance(attrs, str):
        try:
            node["attributes"] = json.loads(attrs)
        except (json.JSONDecodeError, TypeError):
            node["attributes"] = {}
    elif attrs is None:
        node["attributes"] = {}
    return node


def _process_result_nodes(results: list, node_key: str = "node") -> List[Dict[str, Any]]:
    """批量处理查询结果节点：设置 entity_id + 反序列化 attributes"""
    entities = []
    for r in results:
        node = r[node_key]
        node['entity_id'] = node.get('id', '')
        _deserialize_attributes(node)
        entities.append(node)
    return entities


def _invalidate_cache(nodes: bool = False, edges: bool = False) -> None:
    """写入后的缓存失效 —— 收拢在仓库实现内部，调用方不再传 performance 参数。

    defer_cache（批量导入静默期）为 True 时由调用方自行在导入完成后整体失效。
    """
    if nodes:
        graph_performance.clear_cache("graph:nodes:*")
    if edges:
        graph_performance.clear_cache("graph:edges:*")
    if nodes or edges:
        # 图内容变了，既有分区结果/元图快照一并过期（partition key 也是 graph: 前缀族）
        graph_performance.clear_cache("graph:partition:*")

class EntityRepository:
    """Neo4j 实体节点 CRUD"""

    # ── 写入 ──

    def add_entity(self, entity: Dict[str, Any], defer_cache: bool = False) -> Dict[str, Any]:
        """添加单个实体（不做词表过滤，由调用方保证类型合法）"""
        try:
            entity_name = entity.get("name")
            entity_type = entity.get("type", "Entity")

            logger.info(f"[add_entity] 开始添加实体: {entity_name}, type={entity_type}")

            entity_id = compute_entity_id(entity_name)

            params = {
                'id': entity_id,
                'name': entity_name,
                'type': entity_type,
                'count': entity.get('count', 1),
                'confidence': entity.get('confidence', 1.0),
                'byname': entity.get('byname'),
                'datasource': entity.get('datasource', ''),
                'evidence': entity.get('evidence') or entity.get('datasource', ''),
                'description': entity.get('description', ''),
                'attributes': entity.get('attributes', '{}')
            }

            query = """
            MERGE (e:Entity {id: $id})
            ON CREATE SET e.created_at = datetime(), e.datasource = $datasource
            SET e.name = $name, e.type = $type, e.count = $count,
                e.confidence = $confidence, e.byname = $byname,
                e.description = $description
            SET e.attributes = CASE
                WHEN $attributes IS NULL OR $attributes = '{}'
                THEN coalesce(e.attributes, '{}')
                ELSE $attributes END
            SET e.datasources = """ + union_sources('e', '$evidence') + """
            RETURN e.id as id, e.name as name
            """
            neo4j_conn.execute_query(query, params)

            if not defer_cache:
                _invalidate_cache(nodes=True)

            logger.info(f"[add_entity] 添加实体成功: {entity_name}")
            return {"status": "success", "id": entity_id, "name": entity_name}
        except Exception as e:
            logger.error(f"[add_entity] 添加实体失败: {str(e)}")
            raise

    def add_entities(self, entities: List[Dict[str, Any]], defer_cache: bool = False) -> Dict[str, Any]:
        """批量添加实体（UNWIND + MERGE，按 id 幂等）。

        ids 与入参实体一一对应（含空列表）；词表外类型过滤不属于 repo 职责（在 entity_data_store 进料缝拦截）。
        """
        try:
            logger.info(f"[add_entities] 开始批量添加实体，数量: {len(entities)}")

            if not entities:
                logger.info("[add_entities] 没有需要添加的实体")
                return {"status": "success", "count": 0, "ids": []}

            entity_ids = []
            entity_list = []

            for entity in entities:
                entity_name = entity.get("name", "")
                eid = compute_entity_id(entity_name)
                entity_ids.append(eid)
                entity['id'] = eid
                entity_list.append({
                    'id': eid,
                    'name': entity.get("name", ""),
                    'type': entity.get("type", "Entity"),
                    'count': entity.get('count', 1),
                    'confidence': entity.get('confidence', 1.0),
                    'byname': entity.get('byname'),
                    'datasource': entity.get('datasource', ''),
                    'evidence': entity.get('evidence') or entity.get('datasource', ''),
                    'description': entity.get('description', ''),
                    'attributes': entity.get('attributes', '{}')
                })

            query = """
            UNWIND $entities AS e
            MERGE (n:Entity {id: e.id})
            ON CREATE SET n.created_at = datetime(), n.datasource = e.datasource
            SET n.name = e.name, n.type = e.type, n.count = e.count,
                n.confidence = e.confidence, n.byname = e.byname,
                n.description = e.description
            SET n.attributes = CASE
                WHEN e.attributes IS NULL OR e.attributes = '{}'
                THEN coalesce(n.attributes, '{}')
                ELSE e.attributes END
            SET n.datasources = """ + union_sources('n', 'e.evidence') + """
            """
            neo4j_conn.execute_query(query, {"entities": entity_list})

            # 业务指标：实体写入量（op=entities）
            GRAPH_WRITES.labels(op="entities").inc(len(entity_list))

            if not defer_cache:
                _invalidate_cache(nodes=True)

            logger.info(f"[add_entities] 批量添加实体成功，数量: {len(entity_ids)}")
            return {"status": "success", "count": len(entity_ids), "ids": entity_ids}
        except Exception as e:
            logger.error(f"[add_entities] 批量添加实体失败: {str(e)}")
            raise

    # ── 查询 ──

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """根据 ID 获取实体"""
        try:
            query = "MATCH (n:Entity {id: $id}) RETURN n{.*} as node"
            result = neo4j_conn.execute_query(query, {"id": entity_id})
            if not result:
                return None
            node = result[0]['node']
            node['entity_id'] = node.get('id', '')
            node['id'] = node.get('id', '')
            _deserialize_attributes(node)
            return node
        except Exception as e:
            logger.error(f"获取实体失败: {e}")
            return None

    def get_entities_batch(self, entity_ids: List[str], strict: bool = False) -> Dict[str, Dict[str, Any]]:
        """批量获取实体，单次 Cypher 查询，返回 {id: entity_dict}。

        超过 5000 个 ID 时自动分块查询；strict=True 时查询失败直接抛出（默认吞错返回已取部分）。"""
        if not entity_ids:
            return {}
        try:
            entities = {}
            chunk_size = 5000
            # strict: 批量读失败必须显式抛出而不是返回半空的字典 —— prune 等仲裁方依赖它与真实存活集合区分
            for i in range(0, len(entity_ids), chunk_size):
                chunk = entity_ids[i:i + chunk_size]
                query = """
                MATCH (n:Entity)
                WHERE n.id IN $ids
                RETURN n{.*} as node
                """
                result = neo4j_conn.execute_query(query, {"ids": chunk})
                for r in result:
                    node = r['node']
                    node['entity_id'] = node.get('id', '')
                    _deserialize_attributes(node)
                    entities[node['id']] = node
            return entities
        except Exception as e:
            logger.error(f"批量获取实体失败: {e}")
            if strict:
                raise
            return entities

    def search_entities(self, query: str, limit: int = 10, source_filters: List[str] = None,
                        entity_types: List[str] = None) -> List[Dict[str, Any]]:
        """搜索实体，优先全文索引，降级 CONTAINS"""
        type_clause = ""
        if entity_types:
            type_clause = " AND n.type IN $entity_types"

        try:
            params = {"query": query, "limit": limit}
            if source_filters and entity_types:
                cypher = f"""
                CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node, score
                WHERE {match_any_prefix('node', '$source_filters')}{type_clause}
                RETURN node{{.*}} as node, score
                ORDER BY score DESC LIMIT $limit
                """
                params["source_filters"] = source_filters
                params["entity_types"] = entity_types
            elif source_filters:
                cypher = f"""
                CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node, score
                WHERE {match_any_prefix('node', '$source_filters')}
                RETURN node{{.*}} as node, score
                ORDER BY score DESC LIMIT $limit
                """
                params["source_filters"] = source_filters
            elif entity_types:
                cypher = f"""
                CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node, score
                WHERE node.type IN $entity_types
                RETURN node{{.*}} as node, score
                ORDER BY score DESC LIMIT $limit
                """
                params["entity_types"] = entity_types
            else:
                cypher = """
                CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node, score
                RETURN node{.*} as node, score
                ORDER BY score DESC LIMIT $limit
                """
            result = neo4j_conn.execute_query(cypher, params)
            if result:
                entities = _process_result_nodes(result)
                for e, r in zip(entities, result):
                    e['similarity'] = min(1.0, float(r.get('score', 0)))
                return entities
        except Exception:
            pass

        # 降级：CONTAINS 搜索
        try:
            params = {"query": query, "limit": limit}
            conditions = ["(n.name CONTAINS $query OR n.description CONTAINS $query)"]
            if source_filters:
                conditions.append(match_any_prefix('n', '$source_filters'))
                params["source_filters"] = source_filters
            if entity_types:
                conditions.append("n.type IN $entity_types")
                params["entity_types"] = entity_types
            filter_clause = " AND ".join(conditions)
            cypher = f"""
            MATCH (n:Entity)
            WHERE {filter_clause}
            RETURN n{{.*}} as node LIMIT $limit
            """
            result = neo4j_conn.execute_query(cypher, params)
            return _process_result_nodes(result)
        except Exception as e:
            logger.error(f"搜索实体失败: {e}")
            return []

    def search_entities_by_datasource(self, datasource_prefix: str, limit: int = 100) -> List[Dict[str, Any]]:
        """按 datasource 前缀查询实体"""
        try:
            cypher = f"""
            MATCH (n:Entity)
            WHERE {match_prefix('n', '$prefix')}
            RETURN n{{.*}} as node LIMIT $limit
            """
            result = neo4j_conn.execute_query(cypher, {"prefix": datasource_prefix, "limit": limit})
            return _process_result_nodes(result)
        except Exception as e:
            logger.error(f"按 datasource 搜索实体失败: {e}")
            return []

    def search_entities_with_pagination(
        self, query: str, limit: int = 10, offset: int = 0,
        entity_type: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """分页搜索实体，返回 (entities, total_count)"""
        type_filter = "WHERE node.type = $entity_type" if entity_type else ""
        type_params = {"entity_type": entity_type} if entity_type else {}

        try:
            count_result = neo4j_conn.execute_query(
                f"CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node {type_filter} RETURN count(node) as total",
                {**{"query": query}, **type_params}
            )
            total = count_result[0]['total'] if count_result else 0

            result = neo4j_conn.execute_query(
                f"CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node, score {type_filter} RETURN node{{.*}} as node, score ORDER BY score DESC SKIP $offset LIMIT $limit",
                {**{"query": query, "offset": offset, "limit": limit}, **type_params}
            )
            entities = _process_result_nodes(result)
            for e, r in zip(entities, result):
                e['similarity'] = min(1.0, float(r.get('score', 0)))
            return entities, total
        except Exception:
            pass

        # 降级：CONTAINS 分页
        try:
            conditions = ["(toLower(n.name) CONTAINS toLower($query) OR toLower(n.description) CONTAINS toLower($query) OR toLower(n.datasource) CONTAINS toLower($query))"]
            params = {"query": query, "offset": offset, "limit": limit}
            if entity_type:
                conditions.append("n.type = $entity_type")
                params["entity_type"] = entity_type
            filter_clause = " AND ".join(conditions)

            count_result = neo4j_conn.execute_query(
                f"MATCH (n:Entity) WHERE {filter_clause} RETURN count(n) as total",
                params
            )
            total = count_result[0]['total'] if count_result else 0

            result = neo4j_conn.execute_query(
                f"MATCH (n:Entity) WHERE {filter_clause} RETURN n{{.*}} as node SKIP $offset LIMIT $limit",
                params
            )
            entities = _process_result_nodes(result)
            return entities, total
        except Exception as e:
            logger.error(f"分页搜索实体失败: {e}")
            return [], 0

    def get_nodes(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """获取图谱节点（轻量字段全量读；limit=5000 时走 Redis 快照缓存）"""
        safe_limit = min(max(1, limit), 50000)
        try:
            logger.info(f"[get_nodes] 开始获取图谱节点, limit={safe_limit}")

            if safe_limit == 5000:
                cached_nodes = graph_performance.get_cached_graph_data("nodes:all")
                if cached_nodes:
                    logger.info(f"[get_nodes] 从缓存获取节点: {len(cached_nodes)} 个")
                    return cached_nodes

            query = """
            MATCH (n)
            RETURN n.id as id, n.name as name, coalesce(n.type, labels(n)[0]) as type,
                   n.count as count, n.confidence as confidence, n.byname as byname
            LIMIT $limit
            """
            result = neo4j_conn.execute_query(query, {"limit": safe_limit})
            nodes = [{
                'id': record['id'],
                'name': record['name'],
                'type': record['type'],
                'count': record.get('count', 1),
                'confidence': record.get('confidence', 1.0),
                'byname': record.get('byname'),
            } for record in result]

            if safe_limit == 5000:
                graph_performance.cache_graph_data("nodes:all", nodes)

            logger.info(f"[get_nodes] 获取节点成功: {len(nodes)} 个")
            return nodes
        except Exception as e:
            logger.error(f"[get_nodes] 获取节点失败: {str(e)}")
            raise

    def list_entities(self, entity_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """列出实体，可按类型过滤"""
        try:
            if entity_type:
                query = "MATCH (n:Entity) WHERE n.type = $type RETURN n{.*} as node LIMIT $limit"
                params = {"type": entity_type, "limit": limit}
            else:
                query = "MATCH (n:Entity) RETURN n{.*} as node LIMIT $limit"
                params = {"limit": limit}
            result = neo4j_conn.execute_query(query, params)
            entities = _process_result_nodes(result)
            for e in entities:
                e['id'] = e.get('id', '')
            return entities
        except Exception as e:
            logger.error(f"列出实体失败: {e}")
            return []

    def list_entities_with_pagination(
        self, entity_type: Optional[str] = None, query: Optional[str] = None,
        limit: int = 10, offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """分页列出/搜索实体，支持类型过滤和关键词搜索"""
        # 无搜索 + 无类型过滤：分层抽样
        if not query and not entity_type:
            try:
                count_result = neo4j_conn.execute_query(
                    "MATCH (n:Entity) RETURN count(n) as total", {}
                )
                total = count_result[0]['total'] if count_result else 0

                if limit >= 1000 and total > limit:
                    type_dist = neo4j_conn.execute_query(
                        "MATCH (n:Entity) RETURN n.type as t, count(n) as c ORDER BY c DESC"
                    )
                    type_counts = {r['t']: r['c'] for r in type_dist}
                    type_names = list(type_counts.keys())
                    quotas = allocate_type_quota(type_counts, limit)

                    entities = []
                    for t in type_names:
                        type_share = min(quotas.get(t, 0), type_counts[t])

                        skip = max(0, offset - sum(
                            type_counts[tt] for tt in type_names
                            if type_names.index(tt) < type_names.index(t)
                        ))
                        if skip >= type_counts[t]:
                            continue

                        type_result = neo4j_conn.execute_query(
                            "MATCH (n:Entity) WHERE n.type = $type "
                            "RETURN n{.*} as node SKIP $skip LIMIT $l",
                            {"type": t, "skip": skip % type_counts[t] if skip > 0 else 0, "l": type_share}
                        )
                        for r in type_result:
                            node = r['node']
                            node['entity_id'] = node.get('id', '')
                            _deserialize_attributes(node)
                            entities.append(node)

                    if len(entities) < limit and offset == 0:
                        got_ids = {e.get('id', '') for e in entities}
                        fill_result = neo4j_conn.execute_query(
                            "MATCH (n:Entity) RETURN n{.*} as node LIMIT $l",
                            {"l": limit}
                        )
                        for r in fill_result:
                            node = r['node']
                            if node.get('id', '') not in got_ids and len(entities) < limit:
                                node['entity_id'] = node.get('id', '')
                                _deserialize_attributes(node)
                                entities.append(node)
                else:
                    result = neo4j_conn.execute_query(
                        "MATCH (n:Entity) RETURN n{.*} as node SKIP $offset LIMIT $limit",
                        {"offset": offset, "limit": limit}
                    )
                    entities = []
                    for r in result:
                        node = r['node']
                        node['entity_id'] = node.get('id', '')
                        _deserialize_attributes(node)
                        entities.append(node)

                return entities, total
            except Exception as e:
                logger.error(f"分页列出实体失败: {e}")
                return [], 0

        # 无搜索 + 有类型过滤
        if not query and entity_type:
            try:
                count_result = neo4j_conn.execute_query(
                    "MATCH (n:Entity) WHERE n.type = $type RETURN count(n) as total",
                    {"type": entity_type}
                )
                total = count_result[0]['total'] if count_result else 0
                result = neo4j_conn.execute_query(
                    "MATCH (n:Entity) WHERE n.type = $type RETURN n{.*} as node SKIP $offset LIMIT $limit",
                    {"type": entity_type, "offset": offset, "limit": limit}
                )
                entities = []
                for r in result:
                    node = r['node']
                    node['entity_id'] = node.get('id', '')
                    _deserialize_attributes(node)
                    entities.append(node)
                return entities, total
            except Exception as e:
                logger.error(f"分页列出实体失败: {e}")
                return [], 0

        # 有搜索：优先全文索引
        try:
            return self.search_entities_with_pagination(
                query=query, limit=limit, offset=offset, entity_type=entity_type,
            )
        except Exception:
            pass

        # 降级 CONTAINS
        try:
            conditions = ["(toLower(n.name) CONTAINS toLower($query) OR toLower(n.description) CONTAINS toLower($query) OR toLower(n.datasource) CONTAINS toLower($query))"]
            params = {"query": query, "offset": offset, "limit": limit}
            if entity_type:
                conditions.append("n.type = $type")
                params["type"] = entity_type
            filter_clause = " AND ".join(conditions)

            count_result = neo4j_conn.execute_query(
                f"MATCH (n:Entity) WHERE {filter_clause} RETURN count(n) as total",
                params
            )
            total = count_result[0]['total'] if count_result else 0

            result = neo4j_conn.execute_query(
                f"MATCH (n:Entity) WHERE {filter_clause} RETURN n{{.*}} as node SKIP $offset LIMIT $limit",
                params
            )
            entities = []
            for r in result:
                node = r['node']
                node['entity_id'] = node.get('id', '')
                _deserialize_attributes(node)
                entities.append(node)
            return entities, total
        except Exception as e:
            logger.error(f"分页搜索实体失败: {e}")
            return [], 0

    def get_entities_by_datasource(self, datasource: str) -> List[Dict[str, Any]]:
        """根据数据源获取实体（URI 前缀匹配，非 URI 则整串相等）"""
        try:
            if "://" in datasource:
                pred = match_either('n', '$ds')
            else:
                pred = "$ds IN coalesce(n.datasources, [])"
            query = f"MATCH (n:Entity) WHERE {pred} RETURN n{{.*}} as node"
            result = neo4j_conn.execute_query(query, {"ds": datasource})
            entities = _process_result_nodes(result)
            for e in entities:
                e['id'] = e.get('id', '')
            return entities
        except Exception as e:
            logger.error(f"根据数据源获取实体失败: {e}")
            return []

    def get_subgraph(self, entity_id: str, hops: int = 2, limit: int = 100) -> Dict[str, Any]:
        """获取实体的 N-hop 邻居子图

        返回 {nodes: [...], edges: [...]}，节点含完整属性，边含 predicate/confidence。
        """
        try:
            safe_hops = max(1, min(hops, 5))
            safe_limit = max(10, min(limit, 500))

            query = f"""
            MATCH path = (start:Entity {{id: $id}})-[*1..{safe_hops}]-(neighbor:Entity)
            WITH nodes(path) AS ns, relationships(path) AS rs
            UNWIND ns AS n
            WITH collect(DISTINCT n) AS all_nodes, collect(rs) AS all_rels
            UNWIND all_nodes AS node
            WITH collect(DISTINCT node)[..$limit] AS nodes, all_rels
            UNWIND all_rels AS rel_list
            UNWIND rel_list AS r
            RETURN nodes,
                   collect(DISTINCT {{
                     source: startNode(r).name,
                     target: endNode(r).name,
                     predicate: r.predicate,
                     confidence: r.confidence,
                     relationship_id: r.relationship_id,
                     description: r.description,
                     subject_id: r.subject_id,
                     object_id: r.object_id,
                     occurrence_time: r.occurrence_time
                   }}) AS edges
            """
            result = neo4j_conn.execute_query(query, {"id": entity_id, "limit": safe_limit})

            if not result:
                return {"nodes": [], "edges": []}

            record = result[0]
            nodes = []
            for node in record.get("nodes", []):
                node_dict = dict(node)
                node_dict["entity_id"] = node_dict.get("id", "")
                _deserialize_attributes(node_dict)
                nodes.append(node_dict)

            edges = record.get("edges", [])
            logger.info(f"[get_subgraph] entity_id={entity_id}, hops={safe_hops}, "
                        f"nodes={len(nodes)}, edges={len(edges)}")
            return {"nodes": nodes, "edges": edges}
        except Exception as e:
            logger.error(f"[get_subgraph] 获取子图失败: {e}")
            return {"nodes": [], "edges": []}

    # ── 属性合并 ──

    def merge_attributes(self, accumulator: Dict[str, Dict[str, list]],
                         mode: str = "replace", defer_cache: bool = False) -> int:
        """把属性记录合并进父实体的 attributes JSON（多属性表安全，不覆盖其他表的键）

        策略：批量读已有 attributes → Python 侧合并 → 批量写回（无 APOC 依赖）。

        Args:
            accumulator: {父实体名: {属性表名: [记录, ...]}}
            mode: "replace" = 该属性表键整体替换（全量导入语义）；
                  "append" = 记录追加进该表键已有列表（CDC 单事件语义）
        Returns:
            更新的实体数
        """
        if not accumulator:
            return 0

        try:
            # 1) 构建 entity_id → (parent_name, table_attrs) 映射
            id_to_parent: Dict[str, tuple] = {}
            batch_ids: List[str] = []
            for parent_name, table_attrs in accumulator.items():
                entity_id = compute_entity_id(parent_name)
                if id_to_parent.get(entity_id) is None:
                    batch_ids.append(entity_id)
                id_to_parent[entity_id] = (parent_name, table_attrs)

            # 2) 批量读取现有 attributes
            result = neo4j_conn.execute_query(
                "UNWIND $ids AS eid MATCH (e:Entity {id: eid}) "
                "RETURN e.id AS id, e.attributes AS attrs",
                {"ids": batch_ids}
            )
            existing: Dict[str, dict] = {}
            for record in result:
                raw = record["attrs"]
                if isinstance(raw, str):
                    try:
                        existing[record["id"]] = json.loads(raw)
                    except Exception:
                        existing[record["id"]] = {}
                elif isinstance(raw, dict):
                    existing[record["id"]] = raw

            # 3) 合并并批量写回
            update_batch = []
            from utils.json_utils import db_json_dumps
            for eid in batch_ids:
                _, table_attrs = id_to_parent[eid]
                attrs = existing.get(eid, {})
                for attr_table, rows in table_attrs.items():
                    if mode == "append":
                        current = attrs.get(attr_table)
                        if isinstance(current, list):
                            attrs[attr_table] = current + rows
                        elif current is None:
                            attrs[attr_table] = rows
                        else:
                            # 结构异常（应为 list）时退化为替换
                            attrs[attr_table] = rows
                    else:
                        attrs[attr_table] = rows
                update_batch.append({"id": eid, "attrs": db_json_dumps(attrs)})

            neo4j_conn.execute_query(
                "UNWIND $batch AS item "
                "MATCH (e:Entity {id: item.id}) "
                "SET e.attributes = item.attrs",
                {"batch": update_batch}
            )
            attributes = len(update_batch)
            if attributes:
                GRAPH_WRITES.labels(op="attributes").inc(attributes)
            if not defer_cache:
                _invalidate_cache(nodes=True, edges=False)
            return len(update_batch)
        except Exception as e:
            logger.error(f"[merge_attributes] 属性合并失败: {e}")
            raise

    # ── 更新 ──

    def update_entity(self, entity_id: str, props: Dict[str, Any],
                      defer_cache: bool = False) -> bool:
        """更新实体属性"""
        try:
            query = "MATCH (n:Entity {id: $id}) SET n += $props RETURN n.id as id"
            result = neo4j_conn.execute_query(query, {"id": entity_id, "props": props})
            if not defer_cache:
                _invalidate_cache(nodes=True)
            return len(result) > 0
        except Exception as e:
            logger.error(f"更新实体失败: {e}")
            return False

    # ── 删除 ──

    def delete_entity(self, entity_id: str, defer_cache: bool = False) -> bool:
        """删除实体及关联关系（无来源保护：管理操作用；CDC 行删除走 delete_entity_scoped）"""
        try:
            query = "MATCH (n:Entity {id: $id}) DETACH DELETE n RETURN count(n) as deleted"
            result = neo4j_conn.execute_query(query, {"id": entity_id})
            if not defer_cache:
                _invalidate_cache(nodes=True, edges=True)
            return result and result[0].get('deleted', 0) > 0
        except Exception as e:
            logger.error(f"删除实体失败: {e}")
            return False

    def delete_entity_scoped(self, entity_id: str, datasource_prefix: str,
                             defer_cache: bool = False) -> bool:
        """按来源摘除单个实体 —— CDC 行级删除专用（不允许绕过 source_scope 语义）

        先摘本来源对该实体全部邻边的佐证（佐证被清空的边删除），
        再摘实体佐证：其余来源佐证仍在的实体保留，清空且无剩余边时删除。
        """
        try:
            strip_edges = """
            MATCH (n:Entity {id: $id})-[r]-()
            WHERE ANY(d IN coalesce(r.datasources, []) WHERE d STARTS WITH $prefix)
            SET r.datasources = """ + strip_prefix('r', '$prefix') + """
            WITH r WHERE size(coalesce(r.datasources, [])) = 0
            DELETE r
            """
            neo4j_conn.execute_query(strip_edges, {"id": entity_id, "prefix": datasource_prefix})

            strip_node = """
            MATCH (n:Entity {id: $id})
            OPTIONAL MATCH (n)-[r]-()
            WITH n, count(r) AS rel_count, """ + strip_prefix('n', '$prefix') + """ AS remaining
            SET n.datasources = remaining
            SET n.datasource = split(coalesce(head(remaining), ''), '@')[0]
            WITH n, rel_count, remaining
            WHERE size(remaining) = 0 AND rel_count = 0
            DELETE n
            RETURN count(n) AS deleted
            """
            result = neo4j_conn.execute_query(strip_node, {"id": entity_id, "prefix": datasource_prefix})
            deleted = bool(result) and result[0].get('deleted', 0) > 0
            if not defer_cache:
                _invalidate_cache(nodes=True, edges=True)
            return deleted
        except Exception as e:
            logger.error(f"[delete_entity_scoped] 按来源删除实体失败: {e}")
            raise

    def recycle_datasource(self, datasource_prefix: str,
                           defer_cache: bool = False, keep_hash: str = None) -> int:
        """摘除某来源对全部实体的佐证，佐证清空则删除实体

        文档重跑/删除、数据库重新导入前的回收入口：
        被其他来源佐证的实体保留（仅从 datasources 去掉本来源），
        无来源可证的实体连同其边一起删除。

        keep_hash（代际回收）：文档刷新场景专用——
        只摘「本来源除新代外的全部佐证」，保留刚刚写入的新代佐证（URI@keep_hash），
        使「摘要 → 抽取 → 回收」的新顺序下抽取得再早也不被本次回收误伤。
        keep_hash=None 时维持旧行为（全摘）。
        """
        try:
            strip_expr = strip_stale_evidence('n') if keep_hash else strip_prefix('n')
            query = f"""
            MATCH (n:Entity)
            WHERE {match_prefix('n', '$prefix')}
            SET n.datasources = {strip_expr}
            SET n.datasource = {pure_uri('n')}
            WITH n WHERE size(coalesce(n.datasources, [])) = 0
            DETACH DELETE n
            RETURN count(n) AS deleted
            """
            params = {"prefix": datasource_prefix}
            if keep_hash:
                params["hash"] = keep_hash
            result = neo4j_conn.execute_query(query, params)
            deleted = result[0].get('deleted', 0) if result else 0

            if not defer_cache:
                _invalidate_cache(nodes=True, edges=True)
            logger.info(f"[recycle_datasource] 回收数据源 '{datasource_prefix}'，删除实体 {deleted} 个")
            return deleted
        except Exception as e:
            logger.error(f"[recycle_datasource] 回收失败: {e}")
            raise

    # ── 治理统计（只读聚合，供 ontology/governance 使用）──

    def type_usage(self) -> Dict[str, int]:
        """各实体类型的节点数，用于检测游离于本体词表之外的类型"""
        result = neo4j_conn.execute_query(
            "MATCH (n:Entity) RETURN n.type AS type, count(n) AS count ORDER BY count DESC")
        return {(r['type'] or ''): r['count'] for r in result}

    def isolated_entities(self, limit: int = 50) -> List[Dict[str, Any]]:
        """游离实体：无任何关系边，说明抽取只识别出名词、没建立关联"""
        result = neo4j_conn.execute_query(
            """
            MATCH (n:Entity) WHERE n._placeholder IS NULL AND NOT (n)-[]-()
            RETURN n.id AS entity_id, n.name AS name, n.type AS type,
                   n.datasource AS datasource
            ORDER BY n.name LIMIT $limit
            """, {"limit": limit})
        return [{'entity_id': r['entity_id'], 'name': r['name'], 'type': r['type'],
                 'datasource': r['datasource']} for r in result]

    def placeholder_entities(self, limit: int = 50) -> List[Dict[str, Any]]:
        """未回填的占位实体：只由关系端点创建、缺类型与描述，等文档抽取补齐"""
        result = neo4j_conn.execute_query(
            """
            MATCH (n:Entity) WHERE n._placeholder = true
            RETURN n.id AS entity_id, n.name AS name, n.datasource AS datasource
            ORDER BY n.name LIMIT $limit
            """, {"limit": limit})
        return [{'entity_id': r['entity_id'], 'name': r['name'],
                 'datasource': r['datasource']} for r in result]

    def count_missing_provenance(self) -> int:
        """无来源佐证的实体数 —— 来源不可追溯的存量数据"""
        result = neo4j_conn.execute_query(
            "MATCH (n:Entity) WHERE size(coalesce(n.datasources, [])) = 0 RETURN count(n) AS count")
        return result[0]['count'] if result else 0

    # ── 回填 ──

    def backfill_byname(self) -> int:
        """回填 byname 为空的实体。从 attributes JSON 中提取描述性字段作为 byname。
        优先选择含 'name' 的非主键字符串列，否则取第一个字符串值。
        """
        try:
            # 游标分批获取 byname 为空的实体（按下 id 递进，避免无候选产出时空转死循环）
            fetch_query = """
            MATCH (n:Entity)
            WHERE n.byname IS NULL AND n.attributes IS NOT NULL AND n.id > $last_id
            RETURN n.id AS id, n.attributes AS attrs
            ORDER BY n.id
            LIMIT 5000
            """
            updated = 0
            last_id = ""
            while True:
                result = neo4j_conn.execute_query(fetch_query, {"last_id": last_id})
                if not result:
                    break
                last_id = result[-1]["id"]

                batch = []
                for record in result:
                    entity_id = record["id"]
                    raw_attrs = record["attrs"]
                    if isinstance(raw_attrs, str):
                        try:
                            attrs = json.loads(raw_attrs)
                        except (json.JSONDecodeError, TypeError):
                            continue
                    elif isinstance(raw_attrs, dict):
                        attrs = raw_attrs
                    else:
                        continue

                    byname = None
                    name_candidates = []
                    for col, val in attrs.items():
                        if val is not None and isinstance(val, str):
                            if "name" in col.lower():
                                byname = val
                                break
                            name_candidates.append(val)
                    if byname is None and name_candidates:
                        byname = name_candidates[0]

                    if byname:
                        batch.append({"id": entity_id, "byname": byname})

                if batch:
                    neo4j_conn.execute_query(
                        "UNWIND $batch AS item "
                        "MATCH (n:Entity {id: item.id}) "
                        "SET n.byname = item.byname",
                        {"batch": batch}
                    )
                    updated += len(batch)

            if updated > 0:
                logger.info(f"[backfill_byname] 回填了 {updated} 个实体的 byname")
            return updated
        except Exception as e:
            logger.error(f"[backfill_byname] 回填失败: {e}")
            return 0


# 模块级单例 —— 调用方直接 import 使用，不再经 GraphManager 转发
entity_repo = EntityRepository()
