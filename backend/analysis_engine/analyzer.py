from knowledge_graph.graph_manager import graph_manager
import networkx as nx
import matplotlib.pyplot as plt
import community as community_louvain
from typing import List, Dict, Tuple

class Analyzer:
    """分析器"""
    
    def __init__(self):
        pass
    
    def analyze_path(self, source_entity, target_entity, k=1, weighted=False):
        """分析路径"""
        try:
            # 构建图
            G = self._build_graph()
            
            # 查找路径
            if source_entity in G and target_entity in G:
                try:
                    if k == 1:
                        # 单路径分析
                        if weighted:
                            # 加权路径
                            shortest_path = nx.shortest_path(G, source=source_entity, target=target_entity, weight='strength')
                            path_length = nx.shortest_path_length(G, source=source_entity, target=target_entity, weight='strength')
                        else:
                            # 非加权路径
                            shortest_path = nx.shortest_path(G, source=source_entity, target=target_entity)
                            path_length = nx.shortest_path_length(G, source=source_entity, target=target_entity)
                        
                        return {
                            'source': source_entity,
                            'target': target_entity,
                            'paths': [shortest_path],
                            'path_lengths': [path_length],
                            'total_paths': 1
                        }
                    else:
                        # 多路径分析
                        paths = []
                        path_lengths = []
                        
                        if weighted:
                            # 加权多路径（使用k_shortest_paths）
                            from networkx.algorithms.shortest_paths.generic import shortest_path
                            from networkx.algorithms.shortest_paths.weighted import multi_source_dijkstra
                            
                            # 实现加权多路径查找
                            # 这里使用简单的方法，查找k条最短路径
                            for i in range(k):
                                try:
                                    path = nx.shortest_path(G, source=source_entity, target=target_entity, weight='strength')
                                    length = nx.shortest_path_length(G, source=source_entity, target=target_entity, weight='strength')
                                    if path not in paths:
                                        paths.append(path)
                                        path_lengths.append(length)
                                    # 移除路径中的边以查找下一条路径
                                    if len(path) > 1:
                                        for j in range(len(path)-1):
                                            G.remove_edge(path[j], path[j+1])
                                except nx.NetworkXNoPath:
                                    break
                        else:
                            # 非加权多路径
                            all_paths = list(nx.all_shortest_paths(G, source=source_entity, target=target_entity))
                            paths = all_paths[:k]
                            path_lengths = [len(path)-1 for path in paths]
                        
                        if paths:
                            return {
                                'source': source_entity,
                                'target': target_entity,
                                'paths': paths,
                                'path_lengths': path_lengths,
                                'total_paths': len(paths)
                            }
                        else:
                            return {
                                'source': source_entity,
                                'target': target_entity,
                                'paths': [],
                                'path_lengths': [],
                                'total_paths': 0,
                                'message': 'No paths found'
                            }
                except nx.NetworkXNoPath:
                    return {
                        'source': source_entity,
                        'target': target_entity,
                        'paths': [],
                        'path_lengths': [],
                        'total_paths': 0,
                        'message': 'No path found'
                    }
            else:
                return {
                    'source': source_entity,
                    'target': target_entity,
                    'paths': [],
                    'path_lengths': [],
                    'total_paths': 0,
                    'message': 'Entities not found in graph'
                }
        except Exception as e:
            raise ValueError(f"路径分析失败: {str(e)}")
    
    def analyze_community(self):
        """分析社区"""
        try:
            # 构建图
            G = self._build_graph()
            
            # 将有向图转换为无向图（Louvain算法只支持无向图）
            G = G.to_undirected()
            
            # 使用Louvain算法检测社区
            partition = community_louvain.best_partition(G)
            
            # 整理社区结果
            communities = {}
            for node, community_id in partition.items():
                if community_id not in communities:
                    communities[community_id] = []
                communities[community_id].append(node)
            
            # 转换为列表格式并计算社区特征
            community_list = []
            for community_id, nodes in communities.items():
                # 创建社区子图
                community_subgraph = G.subgraph(nodes)
                
                # 计算社区密度
                density = nx.density(community_subgraph)
                
                # 计算社区内边数
                edge_count = community_subgraph.number_of_edges()
                
                # 计算社区中心性（使用度中心性）
                if len(nodes) > 0:
                    degree_centrality = nx.degree_centrality(community_subgraph)
                    # 找出社区内中心性最高的节点
                    top_nodes = sorted(degree_centrality.items(), key=lambda x: x[1], reverse=True)[:3]
                    key_entities = [{'node': node, 'centrality': centrality} for node, centrality in top_nodes]
                else:
                    key_entities = []
                
                # 计算社区类型分布
                type_distribution = {}
                for node in nodes:
                    node_type = G.nodes[node].get('type', 'unknown')
                    type_distribution[node_type] = type_distribution.get(node_type, 0) + 1
                
                community_list.append({
                    'community_id': community_id,
                    'nodes': nodes,
                    'size': len(nodes),
                    'density': density,
                    'edge_count': edge_count,
                    'key_entities': key_entities,
                    'type_distribution': type_distribution
                })
            
            # 按社区大小排序
            community_list.sort(key=lambda x: x['size'], reverse=True)
            
            return {
                'communities': community_list,
                'total_communities': len(community_list),
                'largest_community': community_list[0] if community_list else None
            }
        except Exception as e:
            raise ValueError(f"社区分析失败: {str(e)}")
    
    def analyze_centrality(self, centrality_types=None):
        """分析中心性"""
        try:
            # 构建图
            G = self._build_graph()
            
            # 默认计算所有中心性类型
            if centrality_types is None:
                centrality_types = ['degree', 'betweenness', 'closeness', 'pagerank', 'eigenvector']
            
            # 计算度中心性
            degree_centrality = {}  
            if 'degree' in centrality_types:
                degree_centrality = nx.degree_centrality(G)
            
            # 计算介数中心性
            betweenness_centrality = {}  
            if 'betweenness' in centrality_types:
                betweenness_centrality = nx.betweenness_centrality(G)
            
            # 计算 closeness 中心性
            closeness_centrality = {}  
            if 'closeness' in centrality_types:
                closeness_centrality = nx.closeness_centrality(G)
            
            # 计算 PageRank 中心性
            pagerank_centrality = {}  
            if 'pagerank' in centrality_types:
                pagerank_centrality = nx.pagerank(G, alpha=0.85)
            
            # 计算特征向量中心性
            eigenvector_centrality = {}  
            if 'eigenvector' in centrality_types:
                try:
                    eigenvector_centrality = nx.eigenvector_centrality(G, max_iter=1000)
                except nx.PowerIterationFailedConvergence:
                    # 如果收敛失败，使用空字典
                    pass
            
            # 整理结果
            nodes_centrality = []
            for node in G.nodes():
                node_data = {
                    'node': node,
                    'type': G.nodes[node].get('type', 'unknown')
                }
                
                if 'degree' in centrality_types:
                    node_data['degree_centrality'] = degree_centrality.get(node, 0)
                if 'betweenness' in centrality_types:
                    node_data['betweenness_centrality'] = betweenness_centrality.get(node, 0)
                if 'closeness' in centrality_types:
                    node_data['closeness_centrality'] = closeness_centrality.get(node, 0)
                if 'pagerank' in centrality_types:
                    node_data['pagerank_centrality'] = pagerank_centrality.get(node, 0)
                if 'eigenvector' in centrality_types:
                    node_data['eigenvector_centrality'] = eigenvector_centrality.get(node, 0)
                
                nodes_centrality.append(node_data)
            
            # 按度中心性排序
            nodes_centrality.sort(key=lambda x: x.get('degree_centrality', 0), reverse=True)
            
            # 生成各中心性类型的top节点
            top_nodes_by_type = {}
            for centrality_type in centrality_types:
                if centrality_type == 'degree':
                    key = 'degree_centrality'
                elif centrality_type == 'betweenness':
                    key = 'betweenness_centrality'
                elif centrality_type == 'closeness':
                    key = 'closeness_centrality'
                elif centrality_type == 'pagerank':
                    key = 'pagerank_centrality'
                elif centrality_type == 'eigenvector':
                    key = 'eigenvector_centrality'
                else:
                    continue
                
                sorted_nodes = sorted(nodes_centrality, key=lambda x: x.get(key, 0), reverse=True)
                top_nodes_by_type[centrality_type] = sorted_nodes[:10]
            
            return {
                'nodes': nodes_centrality,
                'top_nodes': nodes_centrality[:10],  # 返回前10个节点
                'top_nodes_by_type': top_nodes_by_type,
                'centrality_types': centrality_types
            }
        except Exception as e:
            raise ValueError(f"中心性分析失败: {str(e)}")
    
    def analyze_trend(self, time_range, metrics=None):
        """分析趋势"""
        try:
            # 默认指标
            if metrics is None:
                metrics = ['entity_count', 'relationship_count', 'community_count', 'centrality_trend']
            
            # 构建图
            G = self._build_graph()
            
            # 生成时间序列数据
            # 这里使用模拟数据，实际项目中应该从数据库获取真实的时间序列数据
            import datetime
            import random
            
            # 生成时间标签
            end_date = datetime.datetime.now()
            if time_range == 'last_7_days':
                days = 7
                labels = [(end_date - datetime.timedelta(days=i)).strftime('%m-%d') for i in range(days-1, -1, -1)]
            elif time_range == 'last_30_days':
                days = 30
                labels = [(end_date - datetime.timedelta(days=i)).strftime('%m-%d') for i in range(days-1, -1, -1)]
            elif time_range == 'last_3_months':
                months = 3
                labels = [(end_date - datetime.timedelta(days=i*30)).strftime('%Y-%m') for i in range(months-1, -1, -1)]
            elif time_range == 'last_12_months':
                months = 12
                labels = [(end_date - datetime.timedelta(days=i*30)).strftime('%Y-%m') for i in range(months-1, -1, -1)]
            else:
                # 默认最近5个月
                months = 5
                labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May']
            
            # 生成趋势数据
            trends = []
            
            if 'entity_count' in metrics:
                # 实体数量趋势
                base_count = len(G.nodes())
                values = [base_count + random.randint(-5, 10) for _ in labels]
                trends.append({
                    'metric': 'entity_count',
                    'label': '实体数量',
                    'values': values,
                    'labels': labels
                })
            
            if 'relationship_count' in metrics:
                # 关系数量趋势
                base_count = len(G.edges())
                values = [base_count + random.randint(-10, 20) for _ in labels]
                trends.append({
                    'metric': 'relationship_count',
                    'label': '关系数量',
                    'values': values,
                    'labels': labels
                })
            
            if 'community_count' in metrics:
                # 社区数量趋势
                from community import community_louvain
                # 将有向图转换为无向图（Louvain算法只支持无向图）
                undirected_G = G.to_undirected()
                partition = community_louvain.best_partition(undirected_G)
                base_count = len(set(partition.values()))
                values = [max(1, base_count + random.randint(-2, 3)) for _ in labels]
                trends.append({
                    'metric': 'community_count',
                    'label': '社区数量',
                    'values': values,
                    'labels': labels
                })
            
            if 'centrality_trend' in metrics:
                # 中心性趋势
                degree_centrality = nx.degree_centrality(G)
                top_node = max(degree_centrality, key=degree_centrality.get)
                base_centrality = degree_centrality[top_node]
                values = [base_centrality * (0.8 + random.random() * 0.4) for _ in labels]
                trends.append({
                    'metric': 'centrality_trend',
                    'label': '中心性趋势',
                    'values': values,
                    'labels': labels,
                    'node': top_node
                })
            
            return {
                'time_range': time_range,
                'metrics': metrics,
                'trends': trends,
                'generated_at': datetime.datetime.now().isoformat()
            }
        except Exception as e:
            raise ValueError(f"趋势分析失败: {str(e)}")
    
    def generate_report(self, analysis_type, format='html'):
        """生成分析报告"""
        try:
            from .report_generator import report_generator
            
            # 执行相应的分析
            if analysis_type == 'path':
                # 路径分析需要额外参数，这里使用默认值
                data = self.analyze_path('A', 'B')
            elif analysis_type == 'community':
                data = self.analyze_community()
            elif analysis_type == 'centrality':
                data = self.analyze_centrality()
            elif analysis_type == 'trend':
                data = self.analyze_trend('last_5_months')
            else:
                return {
                    'analysis_type': analysis_type,
                    'report': '不支持的分析类型'
                }
            
            # 使用报告生成器生成报告
            report_content = report_generator.generate_report(analysis_type, data, format=format)
            
            return {
                'analysis_type': analysis_type,
                'format': format,
                'report': report_content,
                'data': data
            }
        except Exception as e:
            raise ValueError(f"报告生成失败: {str(e)}")
    
    def _build_graph(self):
        """从图谱数据库构建NetworkX图"""
        # 获取节点和边
        nodes = graph_manager.get_nodes()
        edges = graph_manager.get_edges()
        
        # 创建NetworkX图
        G = nx.DiGraph()
        
        # 添加节点
        for node in nodes:
            G.add_node(node['name'], type=node['type'])
        
        # 添加边
        for edge in edges:
            G.add_edge(edge['source'], edge['target'], type=edge['type'], strength=edge.get('confidence', 0.5))
        
        return G

# 创建全局分析器实例
analyzer = Analyzer()