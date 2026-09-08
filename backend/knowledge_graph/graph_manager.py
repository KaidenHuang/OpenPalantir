"""
图谱管理器 — 薄门面（Facade）

委托 EntityRepository 和 RelationshipRepository 处理实体/关系 CRUD，
自身只保留图级别操作（可视化、分区、压缩、性能优化）。
"""
import json
from typing import List, Dict, Any, Optional, Tuple
from config.neo4j_config import neo4j_conn
from knowledge_graph.graph_partition import graph_partition
from knowledge_graph.graph_performance import graph_performance
from knowledge_graph.entity_repository import EntityRepository
from knowledge_graph.relationship_repository import RelationshipRepository
from system.logger import logger
from models.ids import compute_entity_id
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
        self.entity_repo = EntityRepository()
        self.rel_repo = RelationshipRepository()
        self.partition = graph_partition
        self.performance = graph_performance
        self._defer_cache = False

    def set_defer_cache(self, defer: bool):
        """设置是否延迟缓存清除（分批导入时启用）"""
        self._defer_cache = defer

    # ── 实体 CRUD（委托 entity_repo）──

    @staticmethod
    def _compute_entity_id(name: str) -> str:
        return compute_entity_id(name)

    def add_entity(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        return self.entity_repo.add_entity(
            entity, defer_cache=self._defer_cache, performance=self.performance)

    def add_entities(self, entities: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.entity_repo.add_entities(
            entities, defer_cache=self._defer_cache, performance=self.performance)

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return self.entity_repo.get_entity(entity_id)

    def search_entities(self, query: str, limit: int = 10, source_filters: List[str] = None,
                        entity_types: List[str] = None) -> List[Dict[str, Any]]:
        return self.entity_repo.search_entities(query, limit, source_filters, entity_types)

    def search_entities_by_datasource(self, datasource_prefix: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.entity_repo.search_entities_by_datasource(datasource_prefix, limit)

    def search_entities_with_pagination(self, query: str, limit: int = 10, offset: int = 0,
                                        entity_type: Optional[str] = None) -> Tuple[List[Dict[str, Any]], int]:
        return self.entity_repo.search_entities_with_pagination(query, limit, offset, entity_type)

    def update_entity(self, entity_id: str, props: Dict[str, Any]) -> bool:
        return self.entity_repo.update_entity(
            entity_id, props, defer_cache=self._defer_cache, performance=self.performance)

    def delete_entity(self, entity_id: str) -> bool:
        return self.entity_repo.delete_entity(
            entity_id, defer_cache=self._defer_cache, performance=self.performance)

    def delete_entities_by_datasource(self, datasource_prefix: str) -> int:
        return self.entity_repo.delete_entities_by_datasource(
            datasource_prefix, defer_cache=self._defer_cache, performance=self.performance)

    def list_entities(self, entity_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self.entity_repo.list_entities(entity_type, limit)

    def list_entities_with_pagination(self, entity_type: Optional[str] = None,
                                       query: Optional[str] = None, limit: int = 10,
                                       offset: int = 0) -> Tuple[List[Dict[str, Any]], int]:
        return self.entity_repo.list_entities_with_pagination(entity_type, query, limit, offset)

    def get_entities_by_datasource(self, datasource: str) -> List[Dict[str, Any]]:
        return self.entity_repo.get_entities_by_datasource(datasource)

    def get_subgraph(self, entity_id: str, hops: int = 2, limit: int = 100) -> Dict[str, Any]:
        return self.entity_repo.get_subgraph(entity_id, hops, limit)

    # ── 关系 CRUD（委托 rel_repo）──

    def get_edges(self, limit: int = 5000) -> List[Dict[str, Any]]:
        return self.rel_repo.get_edges(limit, performance=self.performance)

    def get_edge_count(self) -> int:
        return self.rel_repo.get_edge_count()

    def add_relationship(self, relationship: Dict[str, Any]) -> Dict[str, Any]:
        return self.rel_repo.add_relationship(relationship, performance=self.performance)

    def add_relationships(self, relationships: List[Dict[str, Any]], use_create: bool = False) -> Dict[str, Any]:
        return self.rel_repo.add_relationships(
            relationships, use_create=use_create,
            defer_cache=self._defer_cache, performance=self.performance)

    def list_relationships(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self.rel_repo.list_relationships(limit)

    def get_entity_relationships(self, entity_id: str) -> List[Dict[str, Any]]:
        return self.rel_repo.get_entity_relationships(entity_id)

    def update_relationship(self, relationship_id: str, props: Dict[str, Any]) -> bool:
        return self.rel_repo.update_relationship(relationship_id, props, performance=self.performance)

    def delete_relationship(self, relationship_id: str) -> bool:
        return self.rel_repo.delete_relationship(relationship_id, performance=self.performance)

    # ── 图查询 ──

    def get_nodes(self, limit: int = 5000) -> List[Dict[str, Any]]:
        """获取图谱节点"""
        safe_limit = min(max(1, limit), 50000)
        try:
            logger.info(f"[get_nodes] 开始获取图谱节点, limit={safe_limit}")

            if safe_limit == 5000:
                cached_nodes = self.performance.get_cached_graph_data("nodes:all")
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

            nodes = []
            for record in result:
                nodes.append({
                    'id': record['id'],
                    'name': record['name'],
                    'type': record['type'],
                    'count': record.get('count', 1),
                    'confidence': record.get('confidence', 1.0),
                    'byname': record.get('byname')
                })

            if safe_limit == 5000:
                self.performance.cache_graph_data("nodes:all", nodes)

            logger.info(f"[get_nodes] 获取节点成功: {len(nodes)} 个")
            return nodes
        except Exception as e:
            logger.error(f"[get_nodes] 获取节点失败: {str(e)}")
            raise

    def query_graph(self, query: str, params: Dict = None) -> List[Dict[str, Any]]:
        """查询图谱"""
        try:
            optimized_query = self.performance.optimize_query(query)
            result = neo4j_conn.execute_query(optimized_query, parameters=params)
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

    # ── 图操作（分区/压缩/元图）──

    def partition_graph(self, method: str = "louvain", **kwargs) -> Dict[str, Any]:
        """分区图谱"""
        try:
            logger.info(f"[partition_graph] 开始分区图谱: method={method}")
            nodes = self.get_nodes()
            edges = self.get_edges()

            graph = nx.Graph()
            for node in nodes:
                graph.add_node(node['name'], **node)
            for edge in edges:
                graph.add_edge(edge['source'], edge['target'], weight=edge.get('confidence', 1.0))

            partition = self.partition.partition_graph(graph, method, **kwargs)
            analysis = self.partition.analyze_partition(graph, partition)
            self.performance.cache_graph_data(f"partition:{method}", partition)

            logger.info(f"[partition_graph] 分区成功: {len(partition)} 个分区")
            return {"status": "success", "method": method, "partition": partition, "analysis": analysis}
        except Exception as e:
            logger.error(f"[partition_graph] 分区失败: {str(e)}")
            raise

    def compress_graph(self, compression_ratio: float = 0.5) -> Dict[str, Any]:
        """压缩图谱"""
        try:
            logger.info(f"[compress_graph] 开始压缩图谱: compression_ratio={compression_ratio}")
            nodes = self.get_nodes()
            edges = self.get_edges()

            graph = nx.Graph()
            for node in nodes:
                graph.add_node(node['name'], **node)
            for edge in edges:
                graph.add_edge(edge['source'], edge['target'], weight=edge.get('confidence', 1.0))

            compressed_graph, compression_info = self.partition.compress_graph(graph, compression_ratio)

            logger.info(f"[compress_graph] 压缩成功: 实际压缩率={compression_info['compression_ratio']:.2f}")
            return {
                "status": "success",
                "compression_ratio": compression_info['compression_ratio'],
                "kept_edges": compression_info['kept_edges'],
                "total_edges": compression_info['total_edges'],
                "nodes_count": len(compressed_graph.nodes),
                "edges_count": len(compressed_graph.edges)
            }
        except Exception as e:
            logger.error(f"[compress_graph] 压缩失败: {str(e)}")
            raise

    def create_meta_graph(self) -> Dict[str, Any]:
        """创建元图谱"""
        try:
            logger.info("[create_meta_graph] 开始创建元图谱")
            nodes = self.get_nodes()
            edges = self.get_edges()

            graph = nx.Graph()
            for node in nodes:
                graph.add_node(node['name'], **node)
            for edge in edges:
                graph.add_edge(edge['source'], edge['target'], weight=edge.get('confidence', 1.0))

            partition = self.partition.partition_graph(graph, "louvain")
            meta_graph = self.partition.create_meta_graph(graph, partition)

            meta_nodes = [{'name': n[0], 'size': n[1].get('size', 0)} for n in meta_graph.nodes(data=True)]
            meta_edges = [{'source': e[0], 'target': e[1], 'weight': e[2].get('weight', 1.0)} for e in meta_graph.edges(data=True)]

            logger.info(f"[create_meta_graph] 创建成功: {len(meta_nodes)} 个元节点, {len(meta_edges)} 条元边")
            return {
                "status": "success", "meta_nodes": meta_nodes, "meta_edges": meta_edges,
                "number_of_partitions": len(partition)
            }
        except Exception as e:
            logger.error(f"[create_meta_graph] 创建失败: {str(e)}")
            raise

    def get_partition(self, entity_name: str) -> Dict[str, Any]:
        """获取实体所在的分区"""
        try:
            logger.info(f"[get_partition] 开始获取实体分区: {entity_name}")
            partition = self.performance.get_cached_graph_data("partition:louvain")
            if not partition:
                partition_result = self.partition_graph("louvain")
                partition = partition_result["partition"]

            entity_partition = None
            for partition_id, nodes in partition.items():
                if entity_name in nodes:
                    entity_partition = partition_id
                    break

            if entity_partition is None:
                return {"status": "not_found", "message": f"实体 {entity_name} 未找到任何分区"}

            return {
                "status": "success", "entity_name": entity_name,
                "partition_id": entity_partition,
                "partition_size": len(partition[entity_partition])
            }
        except Exception as e:
            logger.error(f"[get_partition] 获取失败: {str(e)}")
            raise

    # ── 性能/缓存 ──

    def optimize_schema(self) -> Dict[str, Any]:
        logger.info("[optimize_schema] 开始优化图谱schema")
        result = self.performance.create_indexes()
        return result

    def clear_cache(self) -> Dict[str, Any]:
        logger.info("[clear_cache] 开始清除缓存")
        result = self.performance.clear_cache("graph:*")
        return result

    def get_query_performance(self, query: str) -> Dict[str, Any]:
        logger.info(f"[get_query_performance] 开始获取查询性能: {query}")
        return self.performance.get_query_performance(query)

    # ── 可视化数据 ──

    def get_graph_visualization_data(
        self, entity_types: Optional[List[str]] = None,
        min_edges: int = 1, max_nodes: int = 5000,
    ) -> Dict[str, Any]:
        """获取图谱可视化数据 — 服务端类型过滤 + 边数过滤 + 关联点补齐 + 分层抽样"""
        try:
            safe_min_edges = max(0, min(20, min_edges))
            logger.info(
                f"[get_graph_visualization_data] entity_types={entity_types}, "
                f"min_edges={safe_min_edges}, max_nodes={max_nodes}"
            )

            # Step 1: 获取可用类型及计数
            type_result = neo4j_conn.execute_query(
                "MATCH (n:Entity) RETURN n.type as type, count(n) as count ORDER BY type"
            )
            available_types: Dict[str, int] = {r['type']: r['count'] for r in type_result}
            total_node_count = sum(available_types.values())

            if entity_types is None:
                entity_types = list(available_types.keys())
            if not entity_types:
                return {
                    "status": "success",
                    "data": {
                        "nodes": [], "edges": [],
                        "available_types": available_types,
                        "total_node_count": total_node_count,
                        "total_edge_count": self.get_edge_count(),
                        "truncated": False,
                    }
                }

            # Step 2: 核心节点（类型过滤 + 边数过滤）
            core_query = """
            MATCH (n:Entity)
            WHERE n.type IN $entity_types
            WITH n, COUNT { (n)-[:RELATED_TO]-() } as edge_count
            WHERE edge_count >= $min_edges
            RETURN n{.*} as node, edge_count
            """
            core_result = neo4j_conn.execute_query(
                core_query, {"entity_types": entity_types, "min_edges": safe_min_edges}
            )
            core_nodes: List[Dict[str, Any]] = [r['node'] for r in core_result]

            # Step 3: 分层抽样
            truncated = False
            if len(core_nodes) > max_nodes:
                truncated = True
                nodes_by_type: Dict[str, List[Dict[str, Any]]] = {}
                for node in core_nodes:
                    t = node.get('type', 'other')
                    nodes_by_type.setdefault(t, []).append(node)

                type_names = sorted(nodes_by_type.keys(), key=lambda t: len(nodes_by_type[t]), reverse=True)
                min_per_type = max(1, max_nodes // (len(type_names) * 5))
                reserved = min_per_type * len(type_names)
                remaining_budget = max(0, max_nodes - reserved)

                sampled: List[Dict[str, Any]] = []
                for t in type_names:
                    type_total = len(nodes_by_type[t])
                    type_share = min_per_type
                    if remaining_budget > 0:
                        extra = int(remaining_budget * type_total / len(core_nodes))
                        type_share += extra
                    type_share = min(type_share, type_total)
                    sampled.extend(nodes_by_type[t][:type_share])

                if len(sampled) < max_nodes:
                    got_ids = {n.get('id') for n in sampled}
                    for node in core_nodes:
                        if node.get('id') not in got_ids and len(sampled) < max_nodes:
                            got_ids.add(node.get('id'))
                            sampled.append(node)

                core_nodes = sampled

            # Step 4: 补齐关联节点
            core_ids: List[str] = [n.get('id') for n in core_nodes if n.get('id')]
            all_nodes: List[Dict[str, Any]] = list(core_nodes)
            all_ids_set: set = set(core_ids)

            if safe_min_edges > 0 and core_ids:
                neighbor_result = neo4j_conn.execute_query(
                    """MATCH (n:Entity) WHERE n.id IN $core_ids
                       MATCH (n)-[]-(neighbor:Entity)
                       WHERE NOT neighbor.id IN $core_ids
                       RETURN DISTINCT neighbor{.*} as node""",
                    {"core_ids": core_ids}
                )
                for r in neighbor_result:
                    node = r['node']
                    nid = node.get('id')
                    if nid and nid not in all_ids_set:
                        all_ids_set.add(nid)
                        all_nodes.append(node)

            # Step 5: 获取边
            all_ids = list(all_ids_set)
            edges: List[Dict[str, Any]] = []
            if all_ids:
                edge_result = neo4j_conn.execute_query(
                    """MATCH (a:Entity)-[r]->(b:Entity)
                       WHERE a.id IN $all_ids AND b.id IN $all_ids
                       RETURN a.name as source, b.name as target,
                              r.predicate as type, r.confidence as confidence,
                              r.subject_id as subject_id, r.object_id as object_id,
                              r.occurrence_time as occurrence_time, r.description as description,
                              r.relationship_id as relationship_id""",
                    {"all_ids": all_ids}
                )
                for record in edge_result:
                    edges.append({
                        'source': record['source'], 'target': record['target'],
                        'type': record.get('type', 'REL'),
                        'confidence': record.get('confidence', 0.5),
                        'subject_id': record.get('subject_id'),
                        'object_id': record.get('object_id'),
                        'occurrence_time': record.get('occurrence_time'),
                        'description': record.get('description'),
                        'relationship_id': record.get('relationship_id'),
                    })

            return {
                "status": "success",
                "data": {
                    "nodes": all_nodes, "edges": edges,
                    "available_types": available_types,
                    "total_node_count": total_node_count,
                    "total_edge_count": self.get_edge_count(),
                    "truncated": truncated,
                }
            }
        except Exception as e:
            logger.error(f"[get_graph_visualization_data] 失败: {str(e)}")
            raise


# 全局实例
graph_manager = GraphManager()
