from typing import Dict, List, Any
import datetime

class ReportGenerator:
    """报告生成器"""
    
    def __init__(self):
        pass
    
    def generate_report(self, analysis_type: str, data: Dict[str, Any], format: str = 'html'):
        """生成分析报告"""
        if format == 'html':
            return self._generate_html_report(analysis_type, data)
        elif format == 'markdown':
            return self._generate_markdown_report(analysis_type, data)
        else:
            raise ValueError(f"不支持的报告格式: {format}")
    
    def _generate_html_report(self, analysis_type: str, data: Dict[str, Any]) -> str:
        """生成HTML格式报告"""
        html_parts = []
        
        # 报告头部
        html_parts.append('''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OpenPalantir 分析报告</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background-color: #4CAF50;
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .section {
            background-color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        h1, h2, h3 {
            color: #333;
        }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .metric-card {
            background-color: #f9f9f9;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #4CAF50;
        }
        .metric-value {
            font-size: 24px;
            font-weight: bold;
            color: #4CAF50;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }
        th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        .footer {
            text-align: center;
            margin-top: 40px;
            color: #666;
            font-size: 14px;
        }
    </style>
</head>
<body>
''')
        
        # 报告标题
        html_parts.append(f'''
    <div class="header">
        <h1>OpenPalantir 分析报告</h1>
        <p>分析类型: {self._get_analysis_type_name(analysis_type)}</p>
        <p>生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
''')
        
        # 根据分析类型生成不同的报告内容
        if analysis_type == 'path':
            html_parts.append(self._generate_path_html(data))
        elif analysis_type == 'community':
            html_parts.append(self._generate_community_html(data))
        elif analysis_type == 'centrality':
            html_parts.append(self._generate_centrality_html(data))
        elif analysis_type == 'trend':
            html_parts.append(self._generate_trend_html(data))
        
        # 报告尾部
        html_parts.append('''
    <div class="footer">
        <p>报告由 OpenPalantir 系统自动生成</p>
    </div>
</body>
</html>
''')
        
        return ''.join(html_parts)
    
    def _generate_markdown_report(self, analysis_type: str, data: Dict[str, Any]) -> str:
        """生成Markdown格式报告"""
        md_parts = []
        
        # 报告头部
        md_parts.append(f"# OpenPalantir 分析报告")
        md_parts.append(f"- 分析类型: {self._get_analysis_type_name(analysis_type)}")
        md_parts.append(f"- 生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        md_parts.append("")
        
        # 根据分析类型生成不同的报告内容
        if analysis_type == 'path':
            md_parts.extend(self._generate_path_md(data))
        elif analysis_type == 'community':
            md_parts.extend(self._generate_community_md(data))
        elif analysis_type == 'centrality':
            md_parts.extend(self._generate_centrality_md(data))
        elif analysis_type == 'trend':
            md_parts.extend(self._generate_trend_md(data))
        
        return '\n'.join(md_parts)
    
    def _get_analysis_type_name(self, analysis_type: str) -> str:
        """获取分析类型的中文名称"""
        type_map = {
            'path': '路径分析',
            'community': '社区分析',
            'centrality': '中心性分析',
            'trend': '趋势分析'
        }
        return type_map.get(analysis_type, analysis_type)
    
    def _generate_path_html(self, data: Dict[str, Any]) -> str:
        """生成路径分析HTML报告"""
        html = []
        html.append('<div class="section">')
        html.append('<h2>路径分析结果</h2>')
        html.append(f'<p><strong>源实体:</strong> {data.get("source", "N/A")}</p>')
        html.append(f'<p><strong>目标实体:</strong> {data.get("target", "N/A")}</p>')
        html.append(f'<p><strong>找到路径数:</strong> {data.get("total_paths", 0)}</p>')
        
        if data.get('paths'):
            html.append('<h3>路径列表</h3>')
            html.append('<table>')
            html.append('<tr><th>路径</th><th>长度</th></tr>')
            for i, (path, length) in enumerate(zip(data['paths'], data['path_lengths'])):
                path_str = ' → '.join(path)
                html.append(f'<tr><td>{path_str}</td><td>{length}</td></tr>')
            html.append('</table>')
        html.append('</div>')
        return ''.join(html)
    
    def _generate_community_html(self, data: Dict[str, Any]) -> str:
        """生成社区分析HTML报告"""
        html = []
        html.append('<div class="section">')
        html.append('<h2>社区分析结果</h2>')
        html.append(f'<p><strong>社区总数:</strong> {data.get("total_communities", 0)}</p>')
        
        if data.get('largest_community'):
            largest = data['largest_community']
            html.append('<h3>最大社区</h3>')
            html.append(f'<p><strong>社区ID:</strong> {largest.get("community_id", "N/A")}</p>')
            html.append(f'<p><strong>节点数量:</strong> {largest.get("size", 0)}</p>')
            html.append(f'<p><strong>密度:</strong> {largest.get("density", 0):.4f}</p>')
            html.append(f'<p><strong>边数:</strong> {largest.get("edge_count", 0)}</p>')
        
        if data.get('communities'):
            html.append('<h3>社区列表</h3>')
            for community in data['communities'][:5]:  # 只显示前5个社区
                html.append('<div class="metric-card">')
                html.append(f'<h4>社区 {community.get("community_id", "N/A")}</h4>')
                html.append(f'<p>节点数: {community.get("size", 0)}</p>')
                html.append(f'<p>密度: {community.get("density", 0):.4f}</p>')
                if community.get('key_entities'):
                    key_entities = [entity['node'] for entity in community['key_entities'][:3]]
                    html.append(f'<p>关键实体: {", ".join(key_entities)}</p>')
                html.append('</div>')
        html.append('</div>')
        return ''.join(html)
    
    def _generate_centrality_html(self, data: Dict[str, Any]) -> str:
        """生成中心性分析HTML报告"""
        html = []
        html.append('<div class="section">')
        html.append('<h2>中心性分析结果</h2>')
        
        if data.get('top_nodes_by_type'):
            for centrality_type, nodes in data['top_nodes_by_type'].items():
                html.append(f'<h3>{self._get_centrality_type_name(centrality_type)}前10名</h3>')
                html.append('<table>')
                html.append('<tr><th>实体</th><th>中心性值</th></tr>')
                for node in nodes[:10]:
                    value = node.get(f"{centrality_type}_centrality", 0)
                    html.append(f'<tr><td>{node.get("node", "N/A")}</td><td>{value:.4f}</td></tr>')
                html.append('</table>')
        html.append('</div>')
        return ''.join(html)
    
    def _generate_trend_html(self, data: Dict[str, Any]) -> str:
        """生成趋势分析HTML报告"""
        html = []
        html.append('<div class="section">')
        html.append('<h2>趋势分析结果</h2>')
        html.append(f'<p><strong>时间范围:</strong> {data.get("time_range", "N/A")}</p>')
        
        if data.get('trends'):
            for trend in data['trends']:
                html.append(f'<h3>{trend.get("label", trend.get("metric"))}</h3>')
                html.append('<div class="metrics">')
                for label, value in zip(trend.get('labels', []), trend.get('values', [])):
                    html.append('<div class="metric-card">')
                    html.append(f'<p>{label}</p>')
                    html.append(f'<p class="metric-value">{value}</p>')
                    html.append('</div>')
                html.append('</div>')
        html.append('</div>')
        return ''.join(html)
    
    def _generate_path_md(self, data: Dict[str, Any]) -> List[str]:
        """生成路径分析Markdown报告"""
        md = []
        md.append('## 路径分析结果')
        md.append(f'- 源实体: {data.get("source", "N/A")}')
        md.append(f'- 目标实体: {data.get("target", "N/A")}')
        md.append(f'- 找到路径数: {data.get("total_paths", 0)}')
        md.append('')
        
        if data.get('paths'):
            md.append('### 路径列表')
            md.append('| 路径 | 长度 |')
            md.append('|------|------|')
            for path, length in zip(data['paths'], data['path_lengths']):
                path_str = ' → '.join(path)
                md.append(f'| {path_str} | {length} |')
        md.append('')
        return md
    
    def _generate_community_md(self, data: Dict[str, Any]) -> List[str]:
        """生成社区分析Markdown报告"""
        md = []
        md.append('## 社区分析结果')
        md.append(f'- 社区总数: {data.get("total_communities", 0)}')
        md.append('')
        
        if data.get('largest_community'):
            largest = data['largest_community']
            md.append('### 最大社区')
            md.append(f'- 社区ID: {largest.get("community_id", "N/A")}')
            md.append(f'- 节点数量: {largest.get("size", 0)}')
            md.append(f'- 密度: {largest.get("density", 0):.4f}')
            md.append(f'- 边数: {largest.get("edge_count", 0)}')
            md.append('')
        
        if data.get('communities'):
            md.append('### 社区列表（前5个）')
            for community in data['communities'][:5]:
                md.append(f'#### 社区 {community.get("community_id", "N/A")}')
                md.append(f'- 节点数: {community.get("size", 0)}')
                md.append(f'- 密度: {community.get("density", 0):.4f}')
                if community.get('key_entities'):
                    key_entities = [entity['node'] for entity in community['key_entities'][:3]]
                    md.append(f'- 关键实体: {", ".join(key_entities)}')
                md.append('')
        return md
    
    def _generate_centrality_md(self, data: Dict[str, Any]) -> List[str]:
        """生成中心性分析Markdown报告"""
        md = []
        md.append('## 中心性分析结果')
        md.append('')
        
        if data.get('top_nodes_by_type'):
            for centrality_type, nodes in data['top_nodes_by_type'].items():
                md.append(f'### {self._get_centrality_type_name(centrality_type)}前10名')
                md.append('| 实体 | 中心性值 |')
                md.append('|------|----------|')
                for node in nodes[:10]:
                    value = node.get(f"{centrality_type}_centrality", 0)
                    md.append(f'| {node.get("node", "N/A")} | {value:.4f} |')
                md.append('')
        return md
    
    def _generate_trend_md(self, data: Dict[str, Any]) -> List[str]:
        """生成趋势分析Markdown报告"""
        md = []
        md.append('## 趋势分析结果')
        md.append(f'- 时间范围: {data.get("time_range", "N/A")}')
        md.append('')
        
        if data.get('trends'):
            for trend in data['trends']:
                md.append(f'### {trend.get("label", trend.get("metric"))}')
                md.append('| 时间 | 值 |')
                md.append('|------|-----|')
                for label, value in zip(trend.get('labels', []), trend.get('values', [])):
                    md.append(f'| {label} | {value} |')
                md.append('')
        return md
    
    def _get_centrality_type_name(self, centrality_type: str) -> str:
        """获取中心性类型的中文名称"""
        type_map = {
            'degree': '度中心性',
            'betweenness': '介数中心性',
            'closeness': '接近中心性',
            'pagerank': 'PageRank中心性',
            'eigenvector': '特征向量中心性'
        }
        return type_map.get(centrality_type, centrality_type)

# 创建全局报告生成器实例
report_generator = ReportGenerator()
