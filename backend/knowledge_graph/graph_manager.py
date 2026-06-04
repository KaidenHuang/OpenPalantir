import json
from typing import List, Dict, Any, Optional, Tuple
from config.neo4j_config import neo4j_conn
from knowledge_graph.graph_partition import graph_partition
from knowledge_graph.graph_performance import graph_performance
from system.logger import logger
import networkx as nx

def _summarize_params(params: dict) -> str:
    """摘要打印查询参数，避免长列表撑爆日志"""
    parts = []
    for k, v in params.items():
        if isinstance(v, list):
            if len(v) > 5:
                parts.append(f"{k}=[{len(v)} items: {', '.join(str(x)[:60] for x in v[:3])}...]")
            else:
                parts.append(f"{k}=[{', '.join(str(x)[:120] for x in v)}]")
        elif isinstance(v, str) and len(v) > 120:
            parts.append(f"{k}={v[:120]}...")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


class GraphManager:
    def __init__(self):
        """初始化图谱管理器"""
        self.partition = graph_partition
        self.performance = graph_performance
        self._defer_cache = False

    def set_defer_cache(self, defer: bool):
        """设置是否延迟缓存清除（分批导入时启用）"""
        self._defer_cache = defer

    def _maybe_clear_cache(self, pattern: str):
        """根据 defer 状态决定是否清缓存"""
        if not self._defer_cache:
            self.performance.clear_cache(pattern)

    def get_nodes(self) -> List[Dict[str, Any]]:
        """获取图谱节点"""
        try:
            logger.info("[get_nodes] 开始获取图谱节点")
            
            # 尝试从缓存获取
            cached_nodes = self.performance.get_cached_graph_data("nodes:all")
            if cached_nodes:
                logger.info(f"[get_nodes] 从缓存获取节点: {len(cached_nodes)} 个")
                return cached_nodes

            # 从数据库获取
            query = """
            MATCH (n)
            RETURN n.id as id, n.name as name, coalesce(n.type, labels(n)[0]) as type, n.count as count, n.confidence as confidence, n.byname as byname
            """
            result = neo4j_conn.execute_query(query)

            nodes = []
            for record in result:
                node = {
                    'id': record['id'],
                    'name': record['name'],
                    'type': record['type'],
                    'count': record.get('count', 1),
                    'confidence': record.get('confidence', 1.0),
                    'byname': record.get('byname')
                }
                nodes.append(node)

            # 缓存结果
            self.performance.cache_graph_data("nodes:all", nodes)

            logger.info(f"[get_nodes] 获取节点成功: {len(nodes)} 个")
            return nodes
        except Exception as e:
            logger.error(f"[get_nodes] 获取节点失败: {str(e)}")
            raise

    def get_edges(self) -> List[Dict[str, Any]]:
        """获取图谱边"""
        try:
            logger.info("[get_edges] 开始获取图谱边")

            # 尝试从缓存获取
            cached_edges = self.performance.get_cached_graph_data("edges:all")
            if cached_edges:
                logger.info(f"[get_edges] 从缓存获取边: {len(cached_edges)} 条")
                return cached_edges

            # 从数据库获取
            query = """
            MATCH (s)-[r]->(t)
            RETURN s.name as source, t.name as target, r.predicate as type, r.confidence as confidence, r.subject_id as subject_id, r.object_id as object_id, r.occurrence_time as occurrence_time, r.description as description, r.relationship_id as relationship_id
            """
            result = neo4j_conn.execute_query(query)

            edges = []
            for record in result:
                edge = {
                    'source': record['source'],
                    'target': record['target'],
                    'type': record.get('type', 'REL'),
                    'confidence': record.get('confidence', 0.5),
                    'subject_id': record.get('subject_id'),
                    'object_id': record.get('object_id'),
                    'occurrence_time': record.get('occurrence_time'),
                    'description': record.get('description'),
                    'relationship_id': record.get('relationship_id')
                }
                edges.append(edge)

            # 缓存结果
            self.performance.cache_graph_data("edges:all", edges)

            logger.info(f"[get_edges] 获取边成功: {len(edges)} 条")
            return edges
        except Exception as e:
            logger.error(f"[get_edges] 获取边失败: {str(e)}")
            raise

    def query_graph(self, query: str, params: Dict = None) -> List[Dict[str, Any]]:
        """查询图谱"""
        try:
            # 优化查询
            optimized_query = self.performance.optimize_query(query)

            # 执行查询
            result = neo4j_conn.execute_query(optimized_query, parameters=params)

            # 转换结果格式
            results = []
            for record in result:
                record_dict = {}
                for key in record.keys():
                    record_dict[key] = record[key]
                results.append(record_dict)

            return results
        except Exception as e:
            log_params = _summarize_params(params) if params else ""
            logger.error(f"[query_graph] 查询失败: {query}  params: {log_params}  error: {str(e)}")
            raise

    def add_entity(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """添加实体"""
        try:
            entity_name = entity.get("name")
            entity_type = entity.get("type", "Entity")
            
            # 过滤 time 类型实体
            if entity_type == 'time':
                logger.info(f"[add_entity] 跳过 time 类型实体: {entity_name}")
                return {"status": "skipped", "message": "time type entity is not allowed"}
            
            logger.info(f"[add_entity] 开始添加实体: {entity_name}, type={entity_type}")

            # 生成实体ID
            import uuid
            entity_id = str(uuid.uuid4())

            # 构建参数
            params = {
                'id': entity_id,
                'name': entity_name,
                'type': entity_type,
                'count': entity.get('count', 1),
                'confidence': entity.get('confidence', 1.0),
                'byname': entity.get('byname'),
                'datasource': entity.get('datasource', ''),
                'description': entity.get('description', '')
            }

            # 统一使用 :Entity 标签，type 作为属性存储
            query = """
            MERGE (e:Entity {id: $id})
            SET e.name = $name, e.type = $type, e.count = $count,
                e.confidence = $confidence, e.byname = $byname,
                e.datasource = $datasource, e.description = $description
            RETURN e.id as id, e.name as name
            """

            # 执行查询
            result = neo4j_conn.execute_query(query, params)

            # 清除缓存
            self.performance.clear_cache("graph:nodes:*")

            logger.info(f"[add_entity] 添加实体成功: {entity_name}")
            return {"status": "success", "id": entity_id, "name": entity_name}
        except Exception as e:
            logger.error(f"[add_entity] 添加实体失败: {str(e)}")
            raise

    def add_entities(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加实体（UNWIND 批量写入，统一使用 :Entity 标签）"""
        try:
            logger.info(f"[add_entities] 开始批量添加实体，数量: {len(entities)}")

            filtered_entities = [e for e in entities if e.get('type') != 'time']

            if not filtered_entities:
                logger.info("[add_entities] 没有需要添加的实体")
                return {"status": "success", "count": 0, "ids": []}

            import uuid
            entity_ids = []
            entity_list = []

            for entity in filtered_entities:
                entity_id = str(uuid.uuid4())
                entity_ids.append(entity_id)
                entity['id'] = entity_id
                entity_list.append({
                    'id': entity_id,
                    'name': entity.get("name", ""),
                    'type': entity.get("type", "Entity"),
                    'count': entity.get('count', 1),
                    'confidence': entity.get('confidence', 1.0),
                    'byname': entity.get('byname'),
                    'datasource': entity.get('datasource', ''),
                    'description': entity.get('description', '')
                })

            # UNWIND 单次 round-trip 写入所有实体
            # 使用 CREATE 而非 MERGE：所有实体 ID 均为新生成 UUID，无需存在性检查
            query = """
            UNWIND $entities AS e
            CREATE (n:Entity {id: e.id})
            SET n.name = e.name, n.type = e.type, n.count = e.count,
                n.confidence = e.confidence, n.byname = e.byname,
                n.datasource = e.datasource, n.description = e.description
            """
            neo4j_conn.execute_query(query, {"entities": entity_list})

            self._maybe_clear_cache("graph:nodes:*")

            logger.info(f"[add_entities] 批量添加实体成功，数量: {len(entity_ids)}")
            return {"status": "success", "count": len(entity_ids), "ids": entity_ids}
        except Exception as e:
            logger.error(f"[add_entities] 批量添加实体失败: {str(e)}")
            raise

    def add_relationship(self, relationship: Dict[str, Any]) -> Dict[str, Any]:
        """添加关系"""
        try:
            subject = relationship.get("subject")
            object_name = relationship.get("object")
            predicate = relationship.get("predicate", "RELATES_TO")
            relationship_id = relationship.get("relationship_id")
            logger.info(f"[add_relationship] 开始添加关系: {subject} -{predicate}-> {object_name}, ID: {relationship_id}")

            # 构建参数
            params = {
                'source': subject,
                'target': object_name,
                'predicate': predicate,
                'relationship_id': relationship_id,
                'confidence': relationship.get('confidence', 0.5),
                'subject_id': relationship.get('subject_id', ''),
                'object_id': relationship.get('object_id', ''),
                'occurrence_time': relationship.get('occurrence_time'),
                'description': relationship.get('description')
            }

            # 构建查询（使用 relationship_id 作为唯一标识，:Entity 标签命中索引）
            query = """
            MATCH (s:Entity {name: $source})
            MATCH (t:Entity {name: $target})
            MERGE (s)-[r:RELATED_TO {relationship_id: $relationship_id}]->(t)
            SET r.predicate = $predicate, r.confidence = $confidence, r.subject_id = $subject_id, r.object_id = $object_id, r.occurrence_time = $occurrence_time, r.description = $description
            RETURN type(r) as type
            """

            # 执行查询
            result = neo4j_conn.execute_query(query, params)

            # 清除缓存
            self.performance.clear_cache("graph:edges:*")

            logger.info(f"[add_relationship] 添加关系成功: {subject} -{predicate}-> {object_name}")
            return {"status": "success", "predicate": predicate}
        except Exception as e:
            logger.error(f"[add_relationship] 添加关系失败: {str(e)}")
            raise

    def add_relationships(self, relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加关系（UNWIND 批量写入，:Entity 标签命中索引）"""
        try:
            logger.info(f"[add_relationships] 开始批量添加关系，数量: {len(relationships)}")

            if not relationships:
                logger.info("[add_relationships] 没有需要添加的关系")
                return {"status": "success", "count": 0}

            rel_list = []
            for rel in relationships:
                rel_list.append({
                    'source': rel.get("subject", ""),
                    'target': rel.get("object", ""),
                    'predicate': rel.get("predicate", "RELATES_TO"),
                    'relationship_id': rel.get("relationship_id", ""),
                    'confidence': rel.get('confidence', 0.5),
                    'subject_id': rel.get('subject_id', ''),
                    'object_id': rel.get('object_id', ''),
                    'occurrence_time': rel.get('occurrence_time'),
                    'description': rel.get('description')
                })

            # UNWIND 单次 round-trip 写入所有关系
            query = """
            UNWIND $relationships AS r
            MATCH (s:Entity {name: r.source})
            MATCH (t:Entity {name: r.target})
            MERGE (s)-[rel:RELATED_TO {relationship_id: r.relationship_id}]->(t)
            SET rel.predicate = r.predicate, rel.confidence = r.confidence,
                rel.subject_id = r.subject_id, rel.object_id = r.object_id,
                rel.occurrence_time = r.occurrence_time, rel.description = r.description
            """
            neo4j_conn.execute_query(query, {"relationships": rel_list})

            self._maybe_clear_cache("graph:edges:*")

            logger.info(f"[add_relationships] 批量添加关系完成，成功: {len(relationships)}")
            return {"status": "success", "count": len(relationships), "failed_count": 0}
        except Exception as e:
            logger.error(f"[add_relationships] 批量添加关系失败: {str(e)}")
            raise

    def partition_graph(self, method: str = "louvain", **kwargs) -> Dict[str, Any]:
        """分区图谱"""
        try:
            logger.info(f"[partition_graph] 开始分区图谱: method={method}")

            # 获取当前图谱数据
            nodes = self.get_nodes()
            edges = self.get_edges()

            # 构建NetworkX图
            graph = nx.Graph()
            for node in nodes:
                graph.add_node(node['name'], **node)
            for edge in edges:
                graph.add_edge(edge['source'], edge['target'], weight=edge.get('confidence', 1.0))

            # 执行分区
            partition = self.partition.partition_graph(graph, method, **kwargs)

            # 分析分区结果
            analysis = self.partition.analyze_partition(graph, partition)

            # 缓存分区结果
            self.performance.cache_graph_data(f"partition:{method}", partition)

            result = {
                "status": "success",
                "method": method,
                "partition": partition,
                "analysis": analysis
            }

            logger.info(f"[partition_graph] 分区成功: {len(partition)} 个分区")
            return result
        except Exception as e:
            logger.error(f"[partition_graph] 分区失败: {str(e)}")
            raise

    def compress_graph(self, compression_ratio: float = 0.5) -> Dict[str, Any]:
        """压缩图谱"""
        try:
            logger.info(f"[compress_graph] 开始压缩图谱: compression_ratio={compression_ratio}")

            # 获取当前图谱数据
            nodes = self.get_nodes()
            edges = self.get_edges()

            # 构建NetworkX图
            graph = nx.Graph()
            for node in nodes:
                graph.add_node(node['name'], **node)
            for edge in edges:
                graph.add_edge(edge['source'], edge['target'], weight=edge.get('confidence', 1.0))

            # 执行压缩
            compressed_graph, compression_info = self.partition.compress_graph(graph, compression_ratio)

            result = {
                "status": "success",
                "compression_ratio": compression_info['compression_ratio'],
                "kept_edges": compression_info['kept_edges'],
                "total_edges": compression_info['total_edges'],
                "nodes_count": len(compressed_graph.nodes),
                "edges_count": len(compressed_graph.edges)
            }

            logger.info(f"[compress_graph] 压缩成功: 实际压缩率={compression_info['compression_ratio']:.2f}")
            return result
        except Exception as e:
            logger.error(f"[compress_graph] 压缩失败: {str(e)}")
            raise

    def create_meta_graph(self) -> Dict[str, Any]:
        """创建元图谱"""
        try:
            logger.info("[create_meta_graph] 开始创建元图谱")

            # 获取当前图谱数据
            nodes = self.get_nodes()
            edges = self.get_edges()

            # 构建NetworkX图
            graph = nx.Graph()
            for node in nodes:
                graph.add_node(node['name'], **node)
            for edge in edges:
                graph.add_edge(edge['source'], edge['target'], weight=edge.get('confidence', 1.0))

            # 先进行分区
            partition = self.partition.partition_graph(graph, "louvain")

            # 创建元图谱
            meta_graph = self.partition.create_meta_graph(graph, partition)

            # 转换结果格式
            meta_nodes = []
            for node in meta_graph.nodes(data=True):
                meta_nodes.append({
                    'name': node[0],
                    'size': node[1].get('size', 0)
                })

            meta_edges = []
            for edge in meta_graph.edges(data=True):
                meta_edges.append({
                    'source': edge[0],
                    'target': edge[1],
                    'weight': edge[2].get('weight', 1.0)
                })

            result = {
                "status": "success",
                "meta_nodes": meta_nodes,
                "meta_edges": meta_edges,
                "number_of_partitions": len(partition)
            }

            logger.info(f"[create_meta_graph] 创建成功: {len(meta_nodes)} 个元节点, {len(meta_edges)} 条元边")
            return result
        except Exception as e:
            logger.error(f"[create_meta_graph] 创建失败: {str(e)}")
            raise

    def get_partition(self, entity_name: str) -> Dict[str, Any]:
        """获取实体所在的分区"""
        try:
            logger.info(f"[get_partition] 开始获取实体分区: {entity_name}")

            # 获取分区信息（从缓存或重新计算）
            partition = self.performance.get_cached_graph_data("partition:louvain")
            if not partition:
                # 如果没有缓存，执行分区
                partition_result = self.partition_graph("louvain")
                partition = partition_result["partition"]

            # 查找实体所在的分区
            entity_partition = None
            for partition_id, nodes in partition.items():
                if entity_name in nodes:
                    entity_partition = partition_id
                    break

            if entity_partition is None:
                logger.warning(f"[get_partition] 实体 {entity_name} 未找到任何分区")
                return {"status": "not_found", "message": f"实体 {entity_name} 未找到任何分区"}

            result = {
                "status": "success",
                "entity_name": entity_name,
                "partition_id": entity_partition,
                "partition_size": len(partition[entity_partition])
            }

            logger.info(f"[get_partition] 获取成功: {entity_name} 在分区 {entity_partition}")
            return result
        except Exception as e:
            logger.error(f"[get_partition] 获取失败: {str(e)}")
            raise

    def batch_add_entities(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加实体（直接调用 add_entities UNWIND 批量写入）"""
        logger.info(f"[batch_add_entities] 开始批量添加实体: {len(entities)} 个")
        return self.add_entities(entities)

    def batch_add_relationships(self, relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        """批量添加关系（直接调用 add_relationships UNWIND 批量写入）"""
        logger.info(f"[batch_add_relationships] 开始批量添加关系: {len(relationships)} 条")
        return self.add_relationships(relationships)

    def optimize_schema(self) -> Dict[str, Any]:
        """优化图谱schema"""
        logger.info("[optimize_schema] 开始优化图谱schema")
        result = self.performance.create_indexes()
        if result['status'] == 'success':
            logger.info("[optimize_schema] 优化成功")
        else:
            logger.error(f"[optimize_schema] 优化失败: {result['message']}")
        return result

    def clear_cache(self) -> Dict[str, Any]:
        """清除缓存"""
        logger.info("[clear_cache] 开始清除缓存")
        result = self.performance.clear_cache("graph:*")
        logger.info(f"[clear_cache] 清除完成: {result['message']}")
        return result

    def get_query_performance(self, query: str) -> Dict[str, Any]:
        """获取查询性能信息"""
        logger.info(f"[get_query_performance] 开始获取查询性能: {query}")
        result = self.performance.get_query_performance(query)
        if result['status'] == 'success':
            logger.info(f"[get_query_performance] 获取成功: 执行时间={result['execution_time']:.4f}秒")
        else:
            logger.error(f"[get_query_performance] 获取失败: {result['message']}")
        return result

    # ── Entity/Relationship CRUD (migrated from EntityKnowledgeBase) ──

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
            return node
        except Exception as e:
            logger.error(f"获取实体失败: {e}")
            return None

    def search_entities(self, query: str, limit: int = 10, source_filters: List[str] = None,
                        entity_types: List[str] = None) -> List[Dict[str, Any]]:
        """搜索实体，优先全文索引，降级 CONTAINS

        Args:
            query: 搜索文本
            limit: 返回上限
            source_filters: datasource 前缀过滤列表
            entity_types: 实体类型过滤列表（如 ["person", "organization"]）
        """
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
                entities = []
                for r in result:
                    node = r['node']
                    node['entity_id'] = node.get('id', '')
                    node['similarity'] = min(1.0, float(r.get('score', 0)))
                    entities.append(node)
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
            entities = []
            for r in result:
                node = r['node']
                node['entity_id'] = node.get('id', '')
                entities.append(node)
            return entities
        except Exception as e:
            logger.error(f"搜索实体失败: {e}")
            return []

    def search_entities_by_datasource(self, datasource_prefix: str, limit: int = 100) -> List[Dict[str, Any]]:
        """按 datasource 前缀查询实体（用于数据库路径：查出某表的所有行实体）"""
        try:
            cypher = """
            MATCH (n:Entity)
            WHERE n.datasource STARTS WITH $prefix
            RETURN n{.*} as node LIMIT $limit
            """
            result = neo4j_conn.execute_query(cypher, {"prefix": datasource_prefix, "limit": limit})
            entities = []
            for r in result:
                node = r['node']
                node['entity_id'] = node.get('id', '')
                entities.append(node)
            return entities
        except Exception as e:
            logger.error(f"按 datasource 搜索实体失败: {e}")
            return []

    def search_entities_with_pagination(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0,
        entity_type: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """分页搜索实体，返回 (entities, total_count)，可选 entity_type 过滤"""
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
            entities = []
            for r in result:
                node = r['node']
                node['entity_id'] = node.get('id', '')
                node['similarity'] = min(1.0, float(r.get('score', 0)))
                entities.append(node)
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
            entities = [r['node'] for r in result]
            return entities, total
        except Exception as e:
            logger.error(f"分页搜索实体失败: {e}")
            return [], 0

    def update_entity(self, entity_id: str, props: Dict[str, Any]) -> bool:
        """更新实体属性"""
        try:
            query = "MATCH (n:Entity {id: $id}) SET n += $props RETURN n.id as id"
            result = neo4j_conn.execute_query(query, {"id": entity_id, "props": props})
            self._maybe_clear_cache("graph:nodes:*")
            return len(result) > 0
        except Exception as e:
            logger.error(f"更新实体失败: {e}")
            return False

    def delete_entity(self, entity_id: str) -> bool:
        """删除实体及关联关系"""
        try:
            query = "MATCH (n:Entity {id: $id}) DETACH DELETE n RETURN count(n) as deleted"
            result = neo4j_conn.execute_query(query, {"id": entity_id})
            self._maybe_clear_cache("graph:nodes:*")
            self._maybe_clear_cache("graph:edges:*")
            return result and result[0].get('deleted', 0) > 0
        except Exception as e:
            logger.error(f"删除实体失败: {e}")
            return False

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
            entities = []
            for r in result:
                node = r['node']
                node['entity_id'] = node.get('id', '')
                node['id'] = node.get('id', '')
                entities.append(node)
            return entities
        except Exception as e:
            logger.error(f"列出实体失败: {e}")
            return []

    def list_entities_with_pagination(
        self,
        entity_type: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """分页列出/搜索实体，支持类型过滤和关键词搜索，返回 (entities, total_count)"""
        # 无搜索关键词 + 无类型过滤：纯分页
        if not query and not entity_type:
            try:
                count_result = neo4j_conn.execute_query(
                    "MATCH (n:Entity) RETURN count(n) as total",
                    {}
                )
                total = count_result[0]['total'] if count_result else 0
                result = neo4j_conn.execute_query(
                    "MATCH (n:Entity) RETURN n{.*} as node SKIP $offset LIMIT $limit",
                    {"offset": offset, "limit": limit}
                )
                entities = [{'entity_id': r['node'].get('id', ''), **r['node']} for r in result]
                return entities, total
            except Exception as e:
                logger.error(f"分页列出实体失败: {e}")
                return [], 0

        # 无搜索关键词 + 有类型过滤：按类型分页
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
                entities = [{'entity_id': r['node'].get('id', ''), **r['node']} for r in result]
                return entities, total
            except Exception as e:
                logger.error(f"分页列出实体失败: {e}")
                return [], 0

        # 有搜索关键词：优先全文索引，降级 CONTAINS
        try:
            return self.search_entities_with_pagination(
                query=query, limit=limit, offset=offset,
                entity_type=entity_type,
            )
        except Exception:
            pass

        # 降级：CONTAINS（大小写不敏感 + 含 datasource 字段）
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
            entities = [{'entity_id': r['node'].get('id', ''), **r['node']} for r in result]
            return entities, total
        except Exception as e:
            logger.error(f"分页搜索实体失败: {e}")
            return [], 0

    def list_relationships(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出所有关系"""
        try:
            query = """
            MATCH (s:Entity)-[r:RELATED_TO]->(t:Entity)
            RETURN s.name as subject, s.id as subject_id,
                   t.name as object, t.id as object_id,
                   r.predicate as predicate, r.relationship_id as relationship_id,
                   r.description as description, r.occurrence_time as occurrence_time,
                   r.confidence as confidence
            LIMIT $limit
            """
            result = neo4j_conn.execute_query(query, {"limit": limit})
            rels = []
            for r in result:
                rels.append({
                    'id': r['relationship_id'],
                    'subject': r['subject'],
                    'subject_id': r['subject_id'],
                    'object': r['object'],
                    'object_id': r['object_id'],
                    'predicate': r.get('predicate', 'RELATES_TO'),
                    'relationship_id': r['relationship_id'],
                    'description': r.get('description', ''),
                    'occurrence_time': r.get('occurrence_time', ''),
                    'confidence': r.get('confidence', 0.5),
                })
            return rels
        except Exception as e:
            logger.error(f"列出关系失败: {e}")
            return []

    def get_entity_relationships(self, entity_id: str) -> List[Dict[str, Any]]:
        """获取实体关联的所有关系"""
        try:
            query = """
            MATCH (s:Entity)-[r:RELATED_TO]->(t:Entity)
            WHERE s.id = $id OR t.id = $id
            RETURN s.name as subject, s.id as subject_id,
                   t.name as object, t.id as object_id,
                   r.predicate as predicate, r.relationship_id as relationship_id,
                   r.description as description, r.occurrence_time as occurrence_time,
                   r.confidence as confidence
            """
            result = neo4j_conn.execute_query(query, {"id": entity_id})
            rels = []
            for r in result:
                rels.append({
                    'id': r['relationship_id'],
                    'subject': r['subject'],
                    'subject_id': r['subject_id'],
                    'object': r['object'],
                    'object_id': r['object_id'],
                    'predicate': r.get('predicate', 'RELATES_TO'),
                    'relationship_id': r['relationship_id'],
                    'description': r.get('description', ''),
                    'occurrence_time': r.get('occurrence_time', ''),
                    'confidence': r.get('confidence', 0.5),
                })
            return rels
        except Exception as e:
            logger.error(f"获取实体关系失败: {e}")
            return []

    def get_entities_by_datasource(self, datasource: str) -> List[Dict[str, Any]]:
        """根据数据源获取实体（支持 URI 前缀匹配）"""
        try:
            is_prefix = "://" in datasource
            if is_prefix:
                query = "MATCH (n:Entity) WHERE n.datasource STARTS WITH $ds RETURN n{.*} as node"
            else:
                query = "MATCH (n:Entity) WHERE n.datasource = $ds RETURN n{.*} as node"
            result = neo4j_conn.execute_query(query, {"ds": datasource})
            entities = []
            for r in result:
                node = r['node']
                node['entity_id'] = node.get('id', '')
                node['id'] = node.get('id', '')
                entities.append(node)
            return entities
        except Exception as e:
            logger.error(f"根据数据源获取实体失败: {e}")
            return []


# 创建全局图谱管理器实例
graph_manager = GraphManager()
