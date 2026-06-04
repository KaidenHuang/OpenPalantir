import networkx as nx
import community as community_louvain
from typing import Dict, List, Tuple, Any
from system.logger import logger

class GraphPartition:
    def __init__(self):
        """初始化图谱分区器"""
        pass
    
    def partition_graph(self, graph: nx.Graph, method: str = "louvain", **kwargs) -> Dict[int, List[str]]:
        """分区图谱"""
        try:
            logger.info(f"[partition_graph] 开始分区图谱: method={method}")
            
            if method == "louvain":
                result = self._louvain_partition(graph, **kwargs)
            elif method == "kmeans":
                result = self._kmeans_partition(graph, **kwargs)
            elif method == "spectral":
                result = self._spectral_partition(graph, **kwargs)
            else:
                raise ValueError(f"不支持的分区方法: {method}")
            
            logger.info(f"[partition_graph] 分区图谱成功: method={method}, 分区数={len(result)}")
            return result
        except Exception as e:
            logger.error(f"[partition_graph] 分区图谱失败: {str(e)}")
            raise
    
    def _louvain_partition(self, graph: nx.Graph, resolution: float = 1.0) -> Dict[int, List[str]]:
        """使用Louvain算法分区"""
        # 使用community库的Louvain算法
        partition = community_louvain.best_partition(graph, resolution=resolution)
        
        # 转换为分区到节点的映射
        partition_nodes = {}
        for node, community_id in partition.items():
            if community_id not in partition_nodes:
                partition_nodes[community_id] = []
            partition_nodes[community_id].append(node)
        
        return partition_nodes
    
    def _kmeans_partition(self, graph: nx.Graph, k: int = 5) -> Dict[int, List[str]]:
        """使用K-means算法分区"""
        import numpy as np
        from sklearn.cluster import KMeans
        
        # 获取节点列表
        nodes = list(graph.nodes())
        if len(nodes) < k:
            # 如果节点数少于k，每个节点一个分区
            return {i: [nodes[i]] for i in range(len(nodes))}
        
        # 生成节点嵌入（使用度中心性作为简单特征）
        node_features = []
        for node in nodes:
            degree = graph.degree(node)
            # 可以添加更多特征，如聚类系数、中心性等
            node_features.append([degree])
        
        # 使用K-means聚类
        kmeans = KMeans(n_clusters=k, random_state=42)
        labels = kmeans.fit_predict(node_features)
        
        # 转换为分区到节点的映射
        partition_nodes = {}
        for i, node in enumerate(nodes):
            cluster_id = labels[i]
            if cluster_id not in partition_nodes:
                partition_nodes[cluster_id] = []
            partition_nodes[cluster_id].append(node)
        
        return partition_nodes
    
    def _spectral_partition(self, graph: nx.Graph, k: int = 5) -> Dict[int, List[str]]:
        """使用谱聚类算法分区"""
        import numpy as np
        from sklearn.cluster import SpectralClustering
        
        # 获取节点列表
        nodes = list(graph.nodes())
        if len(nodes) < k:
            # 如果节点数少于k，每个节点一个分区
            return {i: [nodes[i]] for i in range(len(nodes))}
        
        # 生成邻接矩阵
        adj_matrix = nx.to_numpy_array(graph, nodelist=nodes)
        
        # 使用谱聚类
        spectral = SpectralClustering(n_clusters=k, affinity='precomputed', random_state=42)
        labels = spectral.fit_predict(adj_matrix)
        
        # 转换为分区到节点的映射
        partition_nodes = {}
        for i, node in enumerate(nodes):
            cluster_id = labels[i]
            if cluster_id not in partition_nodes:
                partition_nodes[cluster_id] = []
            partition_nodes[cluster_id].append(node)
        
        return partition_nodes
    
    def compress_graph(self, graph: nx.Graph, compression_ratio: float = 0.5) -> Tuple[nx.Graph, Dict[str, Any]]:
        """压缩图谱"""
        try:
            logger.info(f"[compress_graph] 开始压缩图谱: compression_ratio={compression_ratio}")
            
            # 计算需要保留的边数
            total_edges = graph.number_of_edges()
            edges_to_keep = int(total_edges * compression_ratio)
            
            if edges_to_keep < 1:
                logger.info("[compress_graph] 边数不足，返回空图谱")
                return nx.Graph(), {"compression_ratio": 0.0}
            
            # 基于边的重要性排序（这里使用权重或度中心性）
            edges_with_weight = []
            for u, v, data in graph.edges(data=True):
                weight = data.get('weight', 1.0)
                # 可以使用更复杂的边重要性计算方法
                edges_with_weight.append((u, v, weight))
            
            # 按权重排序，保留权重高的边
            edges_with_weight.sort(key=lambda x: x[2], reverse=True)
            kept_edges = edges_with_weight[:edges_to_keep]
            
            # 创建压缩后的图谱
            compressed_graph = nx.Graph()
            compressed_graph.add_nodes_from(graph.nodes(data=True))
            for u, v, weight in kept_edges:
                compressed_graph.add_edge(u, v, weight=weight)
            
            # 计算实际压缩率
            actual_compression = 1.0 - (len(kept_edges) / total_edges)
            
            compression_info = {"compression_ratio": actual_compression, "kept_edges": len(kept_edges), "total_edges": total_edges}
            logger.info(f"[compress_graph] 压缩图谱成功: 实际压缩率={actual_compression:.2f}, 保留边数={len(kept_edges)}/{total_edges}")
            return compressed_graph, compression_info
        except Exception as e:
            logger.error(f"[compress_graph] 压缩图谱失败: {str(e)}")
            raise
    
    def create_meta_graph(self, graph: nx.Graph, partition: Dict[int, List[str]]) -> nx.Graph:
        """创建元图谱"""
        try:
            logger.info("[create_meta_graph] 开始创建元图谱")
            
            meta_graph = nx.Graph()
            
            # 添加元节点（每个分区作为一个元节点）
            for partition_id, nodes in partition.items():
                meta_graph.add_node(f"partition_{partition_id}", size=len(nodes))
            
            # 添加元边（基于分区之间的连接）
            inter_partition_edges = {}
            for u, v, data in graph.edges(data=True):
                # 找到u和v所在的分区
                u_partition = None
                v_partition = None
                for partition_id, nodes in partition.items():
                    if u in nodes:
                        u_partition = partition_id
                    if v in nodes:
                        v_partition = partition_id
                    if u_partition and v_partition:
                        break
                
                # 如果u和v在不同的分区，添加元边
                if u_partition and v_partition and u_partition != v_partition:
                    edge_key = tuple(sorted([u_partition, v_partition]))
                    if edge_key not in inter_partition_edges:
                        inter_partition_edges[edge_key] = 0
                    inter_partition_edges[edge_key] += data.get('weight', 1.0)
            
            # 添加元边到元图谱
            for (p1, p2), weight in inter_partition_edges.items():
                meta_graph.add_edge(f"partition_{p1}", f"partition_{p2}", weight=weight)
            
            logger.info(f"[create_meta_graph] 创建元图谱成功: 元节点数={len(meta_graph.nodes)}, 元边数={len(meta_graph.edges)}")
            return meta_graph
        except Exception as e:
            logger.error(f"[create_meta_graph] 创建元图谱失败: {str(e)}")
            raise
    
    def analyze_partition(self, graph: nx.Graph, partition: Dict[int, List[str]]) -> Dict[str, Any]:
        """分析分区结果"""
        analysis = {
            "number_of_partitions": len(partition),
            "partition_sizes": {k: len(v) for k, v in partition.items()},
            "modularity": self._calculate_modularity(graph, partition),
            "average_partition_size": sum(len(v) for v in partition.values()) / len(partition) if partition else 0
        }
        
        return analysis
    
    def _calculate_modularity(self, graph: nx.Graph, partition: Dict[int, List[str]]) -> float:
        """计算分区的模块度"""
        # 转换分区格式为节点到分区的映射
        node_to_partition = {}
        for partition_id, nodes in partition.items():
            for node in nodes:
                node_to_partition[node] = partition_id
        
        # 使用community库计算模块度
        return community_louvain.modularity(node_to_partition, graph)

# 创建全局图谱分区器实例
graph_partition = GraphPartition()