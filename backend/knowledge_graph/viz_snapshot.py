"""可视化快照 — 图谱可视化数据的读路径（/api/graph/graph-data）

五步流水线：类型计数 → 核心节点采样 → 内存分层抽样 → 关联点补齐 → 边收集。
分层抽样公式统一走 entity_repository.allocate_type_quota（唯一应用点）。
"""
import time
from typing import Any, Dict, List, Optional

from config.neo4j_config import neo4j_conn
from knowledge_graph.graph_performance import graph_performance
from knowledge_graph.entity_repository import allocate_type_quota, entity_repo
from knowledge_graph.relationship_repository import rel_repo
from system.logger import logger


def get_visualization_data(
    entity_types: Optional[List[str]] = None,
    min_edges: int = 1, max_nodes: int = 5000,
) -> Dict[str, Any]:
    """获取图谱可视化数据 — 服务端类型过滤 + 边数过滤 + 关联点补齐 + 分层抽样"""
    try:
        safe_min_edges = max(0, min(20, min_edges))
        t_total = time.time()
        logger.info(
            f"[viz] entity_types={entity_types}, "
            f"min_edges={safe_min_edges}, max_nodes={max_nodes}"
        )

        # Step 1: 获取可用类型及计数
        t0 = time.time()
        type_result = neo4j_conn.execute_query(
            "MATCH (n:Entity) RETURN n.type as type, count(n) as count ORDER BY type"
        )
        available_types: Dict[str, int] = {r['type']: r['count'] for r in type_result}
        total_node_count = sum(available_types.values())
        logger.info(f"[viz] Step1 类型计数: {len(available_types)} 种, {time.time()-t0:.2f}s")

        if entity_types is None:
            entity_types = list(available_types.keys())
        if not entity_types:
            return {
                "status": "success",
                "data": {
                    "nodes": [], "edges": [],
                    "available_types": available_types,
                    "total_node_count": total_node_count,
                    "total_edge_count": rel_repo.get_edge_count(),
                    "truncated": False,
                }
            }

        # Step 2: 核心节点（快速采样，避免 COUNT 子查询全表扫描）
        t0 = time.time()
        if safe_min_edges <= 1:
            # 快速路径: 只要有至少一条关系边即可（泛型 pattern，覆盖全部 LinkType）
            core_query = """
            MATCH (n:Entity)-[]-()
            WHERE n.type IN $entity_types
            WITH DISTINCT n
            LIMIT $max_nodes
            RETURN n{.*} as node
            """
            core_result = neo4j_conn.execute_query(
                core_query, {"entity_types": entity_types, "max_nodes": max_nodes}
            )
            core_nodes = [r['node'] for r in core_result]
            # 为选中的节点批量获取边数
            if core_nodes:
                ids = [n.get('id') for n in core_nodes if n.get('id')]
                if ids:
                    count_result = neo4j_conn.execute_query(
                        """MATCH (n:Entity) WHERE n.id IN $ids
                           RETURN n.id as id, COUNT { (n)-[]-() } as c""",
                        {"ids": ids}
                    )
                    count_map = {r['id']: r['c'] for r in count_result}
                    for n in core_nodes:
                        n['edge_count'] = count_map.get(n.get('id'), 0)
        else:
            # 精确路径: 需要计数，但 LIMIT 限制范围
            core_query = """
            MATCH (n:Entity)
            WHERE n.type IN $entity_types
            WITH n, COUNT { (n)-[]-() } as edge_count
            WHERE edge_count >= $min_edges
            RETURN n{.*} as node, edge_count
            LIMIT $max_nodes
            """
            core_result = neo4j_conn.execute_query(
                core_query, {"entity_types": entity_types, "min_edges": safe_min_edges,
                             "max_nodes": max_nodes}
            )
            core_nodes = [r['node'] for r in core_result]
        logger.info(f"[viz] Step2 核心节点: {len(core_nodes)} 个, {time.time()-t0:.2f}s")

        # Step 3: 分层抽样（配额公式统一走 allocate_type_quota）
        truncated = False
        if len(core_nodes) > max_nodes:
            truncated = True
            nodes_by_type: Dict[str, List[Dict[str, Any]]] = {}
            for node in core_nodes:
                t = node.get('type', 'other')
                nodes_by_type.setdefault(t, []).append(node)

            quotas = allocate_type_quota(
                {t: len(v) for t, v in nodes_by_type.items()}, max_nodes)
            sampled: List[Dict[str, Any]] = []
            for t, type_nodes in nodes_by_type.items():
                sampled.extend(type_nodes[:quotas.get(t, 0)])

            if len(sampled) < max_nodes:
                got_ids = {n.get('id') for n in sampled}
                for node in core_nodes:
                    if node.get('id') not in got_ids and len(sampled) < max_nodes:
                        got_ids.add(node.get('id'))
                        sampled.append(node)

            core_nodes = sampled

        # Step 4: 补齐关联节点（用 pattern match 代替 IN 子句）
        t0 = time.time()
        core_ids: List[str] = [n.get('id') for n in core_nodes if n.get('id')]
        all_nodes: List[Dict[str, Any]] = list(core_nodes)
        all_ids_set: set = set(core_ids)

        if core_ids:
            neighbor_result = neo4j_conn.execute_query(
                """MATCH (n:Entity)-[]-(neighbor:Entity)
                   WHERE n.id IN $core_ids AND NOT neighbor.id IN $core_ids
                   RETURN DISTINCT neighbor{.*} as node
                   LIMIT $max_neighbors""",
                {"core_ids": core_ids, "max_neighbors": max_nodes * 2}
            )
            for r in neighbor_result:
                node = r['node']
                nid = node.get('id')
                if nid and nid not in all_ids_set:
                    all_ids_set.add(nid)
                    all_nodes.append(node)
        logger.info(f"[viz] Step4 补齐后: {len(all_nodes)} 个节点, {time.time()-t0:.2f}s")

        # Step 5: 获取边（泛型关系匹配，从核心节点出发避免全图扫描）
        t0 = time.time()
        edges: List[Dict[str, Any]] = []
        if core_ids:
            edge_result = neo4j_conn.execute_query(
                """MATCH (a:Entity)-[r]->(b:Entity)
                   WHERE a.id IN $core_ids AND b.id IN $core_ids
                   RETURN a.id as source_id, b.id as target_id,
                          a.name as source, b.name as target,
                          r.predicate as type, r.confidence as confidence,
                          r.subject_id as subject_id, r.object_id as object_id,
                          r.occurrence_time as occurrence_time, r.description as description,
                          r.relationship_id as relationship_id""",
                {"core_ids": core_ids}
            )
            seen_edges = set()
            for record in edge_result:
                edge_key = (record.get('source_id'), record.get('target_id'),
                            record.get('relationship_id'))
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
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
        logger.info(f"[viz] Step5 边: {len(edges)} 条, {time.time()-t0:.2f}s")

        logger.info(f"[viz] 总计: {time.time()-t_total:.2f}s")
        return {
            "status": "success",
            "data": {
                "nodes": all_nodes, "edges": edges,
                "available_types": available_types,
                "total_node_count": total_node_count,
                "total_edge_count": rel_repo.get_edge_count(),
                "truncated": truncated,
            }
        }
    except Exception as e:
        logger.error(f"[get_visualization_data] 失败: {str(e)}")
        raise
