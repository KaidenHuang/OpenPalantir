import React, { useState, useEffect, useMemo } from 'react';
import { Button } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import ForceGraph3D from 'react-force-graph-3d';
import { API_CONFIG } from '../config/apiConfig';

// 定义数据模型
interface GraphNode {
  id: string;
  name: string;
  type: string;
  count: number;
  color: string;
}

interface GraphLink {
  source: string;
  target: string;
  type: string;
  confidence: number;
  width: number;
  color: string;
  subject_id?: string;
  object_id?: string;
  occurrence_time?: string;
  description?: string;
}

interface RelatedLinkInfo {
  targetName: string;
  targetType: string;
  type: string;
  confidence: number;
  occurrence_time?: string;
  description?: string;
}

const GraphVisualization: React.FC = () => {
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({
    nodes: [],
    links: []
  });
  const [loading, setLoading] = useState(true);
  const [dataLoaded, setDataLoaded] = useState(false);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEntityTypes, setSelectedEntityTypes] = useState<string[]>([]);
  const [availableEntityTypes, setAvailableEntityTypes] = useState<string[]>([]);
  const [minConfidence, setMinConfidence] = useState(0.3);

  // 实体类型颜色映射（移除 time 类型）
  const entityTypeColors: { [key: string]: string } = {
    person: '#3498db',
    organization: '#e74c3c',
    location: '#27ae60',
    event: '#f39c12',
    concept: '#9b59b6',
    other: '#95A5A6'
  };

  // 关系类型颜色映射
  const relationshipTypeColors = {
    leadership: '#3498db',
    cooperation: '#27ae60',
    competition: '#e74c3c',
    association: '#f39c12',
    investment: '#9b59b6',
    management: '#1abc9c',
    located: '#34495e'
  };

  // 加载数据
  useEffect(() => {
    const fetchGraphData = async () => {
      try {
        setLoading(true);
        
        const [nodesResponse, edgesResponse] = await Promise.all([
          fetch(`${API_CONFIG.endpoints.graph.nodes}?limit=10000`),
          fetch(API_CONFIG.endpoints.graph.edges)
        ]);
        
        if (!nodesResponse.ok || !edgesResponse.ok) {
          throw new Error('API调用失败');
        }
        
        const nodesData = await nodesResponse.json();
        const edgesData = await edgesResponse.json();
        
        const nodesList = nodesData.data?.entities || nodesData.nodes || [];
        console.log('获取到的节点数据:', nodesList);
        console.log('获取到的边数据:', edgesData.edges);

        const nodes = nodesList.map((node: any) => ({
          id: node.id || node.name,
          name: node.name,
          type: node.type || 'Entity',
          count: node.count ? Math.max(5, node.count * 2) : 10,
          color: entityTypeColors[node.type as keyof typeof entityTypeColors] || '#95A5A6'
        }));

        // 从数据中提取所有实体类型，默认全部选中
        const uniqueTypes = [...new Set(nodes.map((n: any) => n.type))] as string[];
        setAvailableEntityTypes(uniqueTypes);
        setSelectedEntityTypes(prev => prev.length === 0 ? uniqueTypes : prev);
        
        const nodeNameToId = new Map();
        nodes.forEach(node => {
          nodeNameToId.set(node.name, node.id);
        });
        
        const linkMap = new Map<string, any>();
        edgesData.edges.forEach((edge: any) => {
          const linkKey = `${edge.source}_${edge.target}_${edge.type || 'association'}`;
          if (!linkMap.has(linkKey)) {
            linkMap.set(linkKey, {
              source: nodeNameToId.get(edge.source) || edge.source,
              target: nodeNameToId.get(edge.target) || edge.target,
              type: edge.type || 'association',
              confidence: edge.confidence || 0.5,
              width: Math.max(1, (edge.confidence || 0.5) * 5),
              color: relationshipTypeColors[edge.type as keyof typeof relationshipTypeColors] || '#95A5A6',
              subject_id: edge.subject_id || '',
              object_id: edge.object_id || '',
              occurrence_time: edge.occurrence_time || '',
              description: edge.description || ''
            });
          }
        });
        const links = Array.from(linkMap.values());
        
        console.log('转换后的节点数据:', nodes);
        console.log('转换后的边数据:', links);
        
        setGraphData({ nodes, links });
        setDataLoaded(true);
        setLoading(false);
      } catch (error) {
        console.error('Error fetching graph data:', error);
        setTimeout(() => {
          setGraphData({ nodes: [], links: [] });
          setDataLoaded(true);
          setLoading(false);
        }, 500);
      }
    };

    if (!dataLoaded) {
      fetchGraphData();
    }
  }, [dataLoaded]);

  const handleNodeClick = (node: any) => {
    setSelectedNode(node as GraphNode);
  };

  const filteredData = useMemo(() => {
    console.log('重新计算过滤数据...');
    console.log('原始节点数据:', graphData.nodes);
    console.log('原始边数据:', graphData.links);
    console.log('选中的实体类型:', selectedEntityTypes);
    console.log('最小关系置信度:', minConfidence);
    
    const filteredNodes = selectedEntityTypes.length === 0
      ? graphData.nodes
      : graphData.nodes.filter(node => selectedEntityTypes.includes(node.type));
    console.log('过滤后的节点数据:', filteredNodes);
    
    const filteredLinks = graphData.links.filter(link => {
      const sourceExists = filteredNodes.some(node => 
        String(node.id) === String(link.source) || 
        String(node.name) === String(link.source) ||
        String(node.id) === String(link.subject_id)
      );
      const targetExists = filteredNodes.some(node => 
        String(node.id) === String(link.target) || 
        String(node.name) === String(link.target) ||
        String(node.id) === String(link.object_id)
      );
      const confidenceValid = link.confidence >= minConfidence;
      
      console.log(`检查关系: ${link.source} -> ${link.target}, 置信度: ${link.confidence}`);
      console.log(`  源节点存在: ${sourceExists}, 目标节点存在: ${targetExists}, 置信度有效: ${confidenceValid}`);
      
      return sourceExists && targetExists && confidenceValid;
    });
    
    console.log('过滤后的边数据:', filteredLinks);
    
    const result = {
      nodes: filteredNodes,
      links: filteredLinks
    };
    
    console.log('最终过滤后的数据:', result);
    return result;
  }, [graphData, selectedEntityTypes, minConfidence]);

  const handleRefresh = () => {
    setDataLoaded(false);
    setLoading(true);
  };

  if (loading) {
    return <div className="graph-loading">加载中...</div>;
  }

  return (
    <div className="graph-visualization" style={{display: 'flex', flexDirection: 'column', height: '100%', minHeight: '80vh', width: '100%'}}>
      <div className="graph-controls" style={{padding: '0 10px', marginTop: '-5px', marginBottom: '-25px', flexShrink: 0}}>
        <div className="filter-section">
          <div className="filter-group" style={{marginBottom: '10px'}}>
            <h4 style={{margin: '0', fontSize: '14px'}}>实体类型</h4>
            <div className="filter-options" style={{display: 'flex', flexWrap: 'wrap', gap: '8px'}}>
              {availableEntityTypes.map((type) => (
                <label key={type} className="filter-checkbox" style={{display: 'flex', alignItems: 'center', gap: '4px'}}>
                  <input
                    type="checkbox"
                    checked={selectedEntityTypes.includes(type)}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedEntityTypes([...selectedEntityTypes, type]);
                      } else {
                        setSelectedEntityTypes(selectedEntityTypes.filter(t => t !== type));
                      }
                    }}
                  />
                  <span className="filter-label" style={{ color: entityTypeColors[type as keyof typeof entityTypeColors] || '#95A5A6', fontSize: '13px' }}>
                    {type} ({graphData.nodes.filter(n => n.type === type).length})
                  </span>
                </label>
              ))}
            </div>
          </div>
          <div className="filter-group" style={{marginBottom: '15px'}}>
            <h4 style={{margin: '0 0 0 0', fontSize: '14px'}}>关系置信度</h4>
            <div style={{display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap'}}>
              <div className="strength-slider" style={{display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: '300px'}}>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={minConfidence}
                  onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
                  style={{flex: 1}}
                />
                <span style={{fontSize: '13px', minWidth: '70px'}}>最小值: {minConfidence.toFixed(1)}</span>
              </div>
              <div style={{display: 'flex', alignItems: 'center', gap: '15px'}}>
                <h4 style={{margin: '0', fontSize: '14px'}}>统计信息</h4>
                <p style={{margin: '0', fontSize: '13px'}}>实体数量: {filteredData.nodes.length}/{graphData.nodes.length}</p>
                <p style={{margin: '0', fontSize: '13px'}}>关系数量: {filteredData.links.length}/{graphData.links.length}</p>
                <Button icon={<ReloadOutlined />} onClick={handleRefresh} size="small">刷新</Button>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="graph-container" style={{flex: 1, minHeight: '500px', width: '100%', overflow: 'hidden'}}>
        <ForceGraph3D
          key={`${filteredData.nodes.length}-${filteredData.links.length}`}
          graphData={filteredData}
          nodeColor={(node) => node.color}
          nodeLabel={(node) => node.name}
          nodeVal={(node) => node.count}
          linkColor={(link) => {
            const hexToRgba = (hex: string, alpha: number) => {
              const r = parseInt(hex.slice(1, 3), 16);
              const g = parseInt(hex.slice(3, 5), 16);
              const b = parseInt(hex.slice(5, 7), 16);
              return `rgba(${r}, ${g}, ${b}, ${alpha})`;
            };
            return hexToRgba(link.color, 0.6);
          }}
          linkWidth={(link) => link.width}
          onNodeClick={handleNodeClick}
          linkLabel={(link) => {
            const labelParts = [];
            labelParts.push(`关系类型: ${link.type}`);
            labelParts.push(`置信度: ${link.confidence.toFixed(2)}`);
            labelParts.push(`时间: ${link.occurrence_time || '-'}`);
            if (link.description) {
              labelParts.push(`描述: ${link.description}`);
            }
            return labelParts.join('<br/>');
          }}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={0.8}
          enableNodeDrag={true}
          enableZoomPan={true}
          enableRotate={true}
          backgroundColor="rgba(255, 255, 255, 0.95)"
          force3D={{ 
            gravity: 0.05, 
            charge: -500, 
            linkDistance: 300 
          }}
        />
      </div>
      {selectedNode && (
        <div className="node-details" style={{padding: '15px', backgroundColor: '#fff', border: '1px solid #ddd', borderRadius: '8px', marginTop: '10px'}}>
          <h3 style={{margin: '0 0 15px 0', fontSize: '18px', color: '#333'}}>节点详情</h3>
          <div style={{marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid #eee'}}>
            <p style={{margin: '5px 0', fontSize: '14px'}}><strong>名称:</strong> {selectedNode.name}</p>
            <p style={{margin: '5px 0', fontSize: '14px'}}><strong>类型:</strong> <span style={{color: entityTypeColors[selectedNode.type as keyof typeof entityTypeColors]}}>{selectedNode.type}</span></p>
            <p style={{margin: '5px 0', fontSize: '14px'}}><strong>出现次数:</strong> {selectedNode.count}</p>
          </div>
          
          <div>
            <h4 style={{margin: '0 0 10px 0', fontSize: '15px', color: '#555'}}>关联关系 ({(() => {
              const relatedLinks = filteredData.links.filter(link => {
                const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
                const targetId = typeof link.target === 'object' ? link.target.id : link.target;
                const sourceName = typeof link.source === 'object' ? link.source.name : link.source;
                const targetName = typeof link.target === 'object' ? link.target.name : link.target;
                
                const matchSourceId = String(sourceId) === String(selectedNode.id);
                const matchTargetId = String(targetId) === String(selectedNode.id);
                const matchSourceName = String(sourceName) === String(selectedNode.name);
                const matchTargetName = String(targetName) === String(selectedNode.name);
                return matchSourceId || matchTargetId || matchSourceName || matchTargetName;
              });
              return relatedLinks.length;
            })()})</h4>
            
            {(() => {
              const relatedLinks: RelatedLinkInfo[] = filteredData.links
                .filter(link => {
                  const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
                  const targetId = typeof link.target === 'object' ? link.target.id : link.target;
                  const sourceName = typeof link.source === 'object' ? link.source.name : link.source;
                  const targetName = typeof link.target === 'object' ? link.target.name : link.target;
                  
                  const matchSourceId = String(sourceId) === String(selectedNode.id);
                  const matchTargetId = String(targetId) === String(selectedNode.id);
                  const matchSourceName = String(sourceName) === String(selectedNode.name);
                  const matchTargetName = String(targetName) === String(selectedNode.name);
                  return matchSourceId || matchTargetId || matchSourceName || matchTargetName;
                })
                .map(link => {
                  const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
                  const sourceName = typeof link.source === 'object' ? link.source.name : link.source;
                  const targetId = typeof link.target === 'object' ? link.target.id : link.target;
                  const targetName = typeof link.target === 'object' ? link.target.name : link.target;
                  
                  const isSource = String(sourceId) === String(selectedNode.id) || String(sourceName) === String(selectedNode.name);
                  const targetNode = isSource 
                    ? filteredData.nodes.find(n => String(n.id) === String(targetId) || String(n.name) === String(targetName))
                    : filteredData.nodes.find(n => String(n.id) === String(sourceId) || String(n.name) === String(sourceName));
                  
                  return {
                    targetName: isSource ? (targetName as string) : (sourceName as string),
                    targetType: targetNode?.type || 'Unknown',
                    type: link.type,
                    confidence: link.confidence,
                    occurrence_time: link.occurrence_time,
                    description: link.description
                  };
                });
              
              if (relatedLinks.length === 0) {
                return <p style={{margin: '5px 0', fontSize: '14px', color: '#999'}}>暂无关联关系</p>;
              }
              
              return (
                <div style={{maxHeight: '300px', overflowY: 'auto'}}>
                  {relatedLinks.map((link, index) => (
                    <div key={index} style={{marginBottom: '10px', padding: '10px', backgroundColor: '#f9f9f9', borderRadius: '4px'}}>
                      <div style={{display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px'}}>
                        <span style={{fontWeight: 'bold', fontSize: '14px'}}>{selectedNode.name}</span>
                        <span style={{color: '#999', fontSize: '12px'}}>-{link.type}-&gt;</span>
                        <span style={{fontWeight: 'bold', fontSize: '14px', color: entityTypeColors[link.targetType as keyof typeof entityTypeColors] || '#95A5A6'}}>
                          {link.targetName}
                        </span>
                      </div>
                      <div style={{fontSize: '12px', color: '#666', marginLeft: '5px'}}>
                        <div style={{marginBottom: '3px'}}>关系类型: {link.type}</div>
                        <div style={{marginBottom: '3px'}}>置信度: {link.confidence.toFixed(2)}</div>
                        <div style={{marginBottom: '3px'}}>时间: {link.occurrence_time || '-'}</div>
                        {link.description && (
                          <div style={{fontStyle: 'italic', color: '#555'}}>描述: {link.description}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </div>
          
          <button 
            onClick={() => setSelectedNode(null)} 
            style={{marginTop: '15px', padding: '8px 16px', backgroundColor: '#3498db', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer'}}
          >
            关闭
          </button>
        </div>
      )}
    </div>
  );
};

export default GraphVisualization;