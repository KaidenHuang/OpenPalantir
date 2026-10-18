"""图拓扑 — 图级别操作：分区、压缩、元图

从 GraphManager 的「图操作」区落位：先读全量节点/边（两仓库）构建 NetworkX 图，
再委托 GraphPartition 完成计算。构图逻辑三处重复，收敛为 _build_graph。
分区结果经 graph_performance 缓存（partition:{method}）。
"""
from typing import Any, Dict

import networkx as nx

from knowledge_graph.entity_repository import entity_repo
from knowledge_graph.graph_partition import graph_partition
from knowledge_graph.graph_performance import graph_performance
from knowledge_graph.relationship_repository import rel_repo
from system.logger import logger


def _build_graph(nodes: list, edges: list) -> nx.Graph:
    """节点/边列表 → NetworkX 无向图（weight = confidence）"""
    graph = nx.Graph()
    for node in nodes:
        graph.add_node(node['name'], **node)
    for edge in edges:
        graph.add_edge(edge['source'], edge['target'],
                       weight=edge.get('confidence', 1.0))
    return graph


def partition_graph(method: str = "louvain", **kwargs) -> Dict[str, Any]:
    """分区图谱"""
    try:
        logger.info(f"[partition_graph] 开始分区图谱: method={method}")
        graph = _build_graph(entity_repo.get_nodes(), rel_repo.get_edges())

        partition = graph_partition.partition_graph(graph, method, **kwargs)
        analysis = graph_partition.analyze_partition(graph, partition)
        graph_performance.cache_graph_data(f"partition:{method}", partition)

        logger.info(f"[partition_graph] 分区成功: {len(partition)} 个分区")
        return {"status": "success", "method": method, "partition": partition,
                "analysis": analysis}
    except Exception as e:
        logger.error(f"[partition_graph] 分区失败: {str(e)}")
        raise


def compress_graph(compression_ratio: float = 0.5) -> Dict[str, Any]:
    """压缩图谱（按边权重保留高权重边）"""
    try:
        logger.info(f"[compress_graph] 开始压缩图谱: compression_ratio={compression_ratio}")
        graph = _build_graph(entity_repo.get_nodes(), rel_repo.get_edges())

        compressed_graph, info = graph_partition.compress_graph(graph, compression_ratio)

        logger.info(f"[compress_graph] 压缩成功: 实际压缩率={info['compression_ratio']:.2f}")
        return {
            "status": "success",
            "compression_ratio": info['compression_ratio'],
            "kept_edges": info['kept_edges'],
            "total_edges": info['total_edges'],
            "nodes_count": len(compressed_graph.nodes),
            "edges_count": len(compressed_graph.edges)
        }
    except Exception as e:
        logger.error(f"[compress_graph] 压缩失败: {str(e)}")
        raise


def create_meta_graph() -> Dict[str, Any]:
    """创建元图谱（Louvain 分区 → 分区级元节点）"""
    try:
        logger.info("[create_meta_graph] 开始创建元图谱")
        graph = _build_graph(entity_repo.get_nodes(), rel_repo.get_edges())

        partition = graph_partition.partition_graph(graph, "louvain")
        meta_graph = graph_partition.create_meta_graph(graph, partition)

        meta_nodes = [{'name': n[0], 'size': n[1].get('size', 0)}
                      for n in meta_graph.nodes(data=True)]
        meta_edges = [{'source': e[0], 'target': e[1], 'weight': e[2].get('weight', 1.0)}
                      for e in meta_graph.edges(data=True)]

        logger.info(f"[create_meta_graph] 创建成功: {len(meta_nodes)} 个元节点, "
                    f"{len(meta_edges)} 条元边")
        return {
            "status": "success", "meta_nodes": meta_nodes, "meta_edges": meta_edges,
            "number_of_partitions": len(partition)
        }
    except Exception as e:
        logger.error(f"[create_meta_graph] 创建失败: {str(e)}")
        raise


def get_partition(entity_name: str) -> Dict[str, Any]:
    """获取实体所在的分区（优先读缓存，未命中现算）"""
    try:
        logger.info(f"[get_partition] 开始获取实体分区: {entity_name}")
        partition = graph_performance.get_cached_graph_data("partition:louvain")
        if not partition:
            partition = partition_graph("louvain")["partition"]

        entity_partition = None
        for partition_id, nodes in partition.items():
            if entity_name in nodes:
                entity_partition = partition_id
                break

        if entity_partition is None:
            return {"status": "not_found",
                    "message": f"实体 {entity_name} 未找到任何分区"}

        return {
            "status": "success", "entity_name": entity_name,
            "partition_id": entity_partition,
            "partition_size": len(partition[entity_partition])
        }
    except Exception as e:
        logger.error(f"[get_partition] 获取失败: {str(e)}")
        raise
