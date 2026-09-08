"""
实体仓库 — 封装 Neo4j 实体节点的全部 CRUD 操作

从 GraphManager 中拆出，职责单一：实体增删改查。
GraphManager 作为薄门面委托调用本模块。
"""
import json
from typing import List, Dict, Any, Optional, Tuple
from config.neo4j_config import neo4j_conn
from system.logger import logger
from models.ids import compute_entity_id


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


class EntityRepository:
    """Neo4j 实体节点 CRUD"""

    # ── 写入 ──

    def add_entity(self, entity: Dict[str, Any], defer_cache: bool = False,
                   performance=None) -> Dict[str, Any]:
        """添加单个实体"""
        try:
            entity_name = entity.get("name")
            entity_type = entity.get("type", "Entity")

            if entity_type == 'time':
                logger.info(f"[add_entity] 跳过 time 类型实体: {entity_name}")
                return {"status": "skipped", "message": "time type entity is not allowed"}

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
                'description': entity.get('description', ''),
                'attributes': entity.get('attributes', '{}')
            }

            query = """
            MERGE (e:Entity {id: $id})
            SET e.name = $name, e.type = $type, e.count = $count,
                e.confidence = $confidence, e.byname = $byname,
                e.datasource = $datasource, e.description = $description,
                e.attributes = $attributes
            RETURN e.id as id, e.name as name
            """
            neo4j_conn.execute_query(query, params)

            if performance and not defer_cache:
                performance.clear_cache("graph:nodes:*")

            logger.info(f"[add_entity] 添加实体成功: {entity_name}")
            return {"status": "success", "id": entity_id, "name": entity_name}
        except Exception as e:
            logger.error(f"[add_entity] 添加实体失败: {str(e)}")
            raise

    def add_entities(self, entities: List[Dict[str, Any]], defer_cache: bool = False,
                     performance=None) -> Dict[str, Any]:
        """批量添加实体（UNWIND + CREATE）"""
        try:
            logger.info(f"[add_entities] 开始批量添加实体，数量: {len(entities)}")

            filtered = [e for e in entities if e.get('type') != 'time']
            if not filtered:
                logger.info("[add_entities] 没有需要添加的实体")
                return {"status": "success", "count": 0, "ids": []}

            entity_ids = []
            entity_list = []

            for entity in filtered:
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
                    'description': entity.get('description', ''),
                    'attributes': entity.get('attributes', '{}')
                })

            query = """
            UNWIND $entities AS e
            CREATE (n:Entity {id: e.id})
            SET n.name = e.name, n.type = e.type, n.count = e.count,
                n.confidence = e.confidence, n.byname = e.byname,
                n.datasource = e.datasource, n.description = e.description,
                n.attributes = e.attributes
            """
            neo4j_conn.execute_query(query, {"entities": entity_list})

            if performance and not defer_cache:
                performance.clear_cache("graph:nodes:*")

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
                WHERE ANY(p IN $source_filters WHERE node.datasource STARTS WITH p){type_clause}
                RETURN node{{.*}} as node, score
                ORDER BY score DESC LIMIT $limit
                """
                params["source_filters"] = source_filters
                params["entity_types"] = entity_types
            elif source_filters:
                cypher = """
                CALL db.index.fulltext.queryNodes('entities_fts', $query) YIELD node, score
                WHERE ANY(p IN $source_filters WHERE node.datasource STARTS WITH p)
                RETURN node{.*} as node, score
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
                conditions.append("ANY(p IN $source_filters WHERE n.datasource STARTS WITH p)")
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
            cypher = """
            MATCH (n:Entity)
            WHERE n.datasource STARTS WITH $prefix
            RETURN n{.*} as node LIMIT $limit
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

                    min_per_type = max(1, limit // (len(type_names) * 5))
                    reserved = min_per_type * len(type_names)
                    remaining_budget = max(0, limit - reserved)

                    entities = []
                    for t in type_names:
                        type_share = min_per_type
                        if remaining_budget > 0:
                            extra = int(remaining_budget * type_counts[t] / total)
                            type_share += extra

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
        """根据数据源获取实体（支持 URI 前缀匹配）"""
        try:
            is_prefix = "://" in datasource
            if is_prefix:
                query = "MATCH (n:Entity) WHERE n.datasource STARTS WITH $ds RETURN n{.*} as node"
            else:
                query = "MATCH (n:Entity) WHERE n.datasource = $ds RETURN n{.*} as node"
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
            MATCH path = (start:Entity {{id: $id}})-[:RELATED_TO*1..{safe_hops}]-(neighbor:Entity)
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
                     object_id: r.object_id
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

    # ── 更新 ──

    def update_entity(self, entity_id: str, props: Dict[str, Any],
                      defer_cache: bool = False, performance=None) -> bool:
        """更新实体属性"""
        try:
            query = "MATCH (n:Entity {id: $id}) SET n += $props RETURN n.id as id"
            result = neo4j_conn.execute_query(query, {"id": entity_id, "props": props})
            if performance and not defer_cache:
                performance.clear_cache("graph:nodes:*")
            return len(result) > 0
        except Exception as e:
            logger.error(f"更新实体失败: {e}")
            return False

    # ── 删除 ──

    def delete_entity(self, entity_id: str, defer_cache: bool = False,
                      performance=None) -> bool:
        """删除实体及关联关系"""
        try:
            query = "MATCH (n:Entity {id: $id}) DETACH DELETE n RETURN count(n) as deleted"
            result = neo4j_conn.execute_query(query, {"id": entity_id})
            if performance and not defer_cache:
                performance.clear_cache("graph:nodes:*")
                performance.clear_cache("graph:edges:*")
            return result and result[0].get('deleted', 0) > 0
        except Exception as e:
            logger.error(f"删除实体失败: {e}")
            return False

    def delete_entities_by_datasource(self, datasource_prefix: str,
                                      defer_cache: bool = False, performance=None) -> int:
        """删除指定数据源前缀的所有实体及关联关系"""
        try:
            count_query = """
            MATCH (n:Entity)
            WHERE n.datasource STARTS WITH $prefix
            RETURN count(n) as cnt
            """
            count_result = neo4j_conn.execute_query(count_query, {"prefix": datasource_prefix})
            deleted = count_result[0].get('cnt', 0) if count_result else 0

            if deleted > 0:
                delete_query = """
                MATCH (n:Entity)
                WHERE n.datasource STARTS WITH $prefix
                CALL {
                    WITH n
                    DETACH DELETE n
                } IN TRANSACTIONS
                OF 1000 ROWS
                """
                neo4j_conn.execute_query(delete_query, {"prefix": datasource_prefix})

            if performance and not defer_cache:
                performance.clear_cache("graph:nodes:*")
                performance.clear_cache("graph:edges:*")
            logger.info(f"[delete_entities_by_datasource] 清理数据源 '{datasource_prefix}'，删除实体 {deleted} 个")
            return deleted
        except Exception as e:
            logger.error(f"[delete_entities_by_datasource] 删除失败: {e}")
            raise
