import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import ForceGraph3D from 'react-force-graph-3d';
import { API_CONFIG } from '../config/apiConfig';

// 数据模型
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

// 实体类型颜色映射
const entityTypeColors: { [key: string]: string } = {
  person: '#3498db',
  organization: '#e74c3c',
  location: '#27ae60',
  event: '#f39c12',
  concept: '#9b59b6',
  other: '#95A5A6'
};

// 关系类型颜色映射
const relationshipTypeColors: { [key: string]: string } = {
  leadership: '#3498db',
  cooperation: '#27ae60',
  competition: '#e74c3c',
  association: '#f39c12',
  investment: '#9b59b6',
  management: '#1abc9c',
  located: '#34495e'
};

const GraphVisualization: React.FC = () => {
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({
    nodes: [],
    links: []
  });
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [selectedEntityTypes, setSelectedEntityTypes] = useState<string[]>([]);
  const [availableTypes, setAvailableTypes] = useState<Record<string, number>>({});
  const [minEdgeCount, setMinEdgeCount] = useState(1);
  const [totalNodeCount, setTotalNodeCount] = useState(0);
  const [totalEdgeCount, setTotalEdgeCount] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [initialized, setInitialized] = useState(false);

  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 记录上次实际发送的 API 参数，避免相同参数重复请求
  const lastFetchedParamsRef = useRef<string>('');
  // 请求进行中锁 — 防止并发请求形成链式重复
  const fetchingRef = useRef(false);
  // 请求序列号 — 确保只有最新的请求结果才会更新 UI
  const requestIdRef = useRef(0);
  // AbortController — 组件卸载或手动刷新时取消进行中的请求
  const abortRef = useRef<AbortController | null>(null);

  // 核心：从后端获取已过滤的图谱数据
  const fetchGraphData = useCallback(async (
    types: string[],
    minEdges: number,
  ) => {
    // 请求进行中锁 — 防止并发请求形成链式重复
    if (fetchingRef.current) return;
    fetchingRef.current = true;

    // 递增请求序列号
    const requestId = ++requestIdRef.current;

    // 构建请求参数
    const params = new URLSearchParams();
    if (types.length > 0 && types.length < Object.keys(availableTypes).length) {
      params.set('entity_types', types.join(','));
    }
    params.set('min_edges', String(minEdges));
    params.set('max_nodes', '5000');
    const paramsStr = params.toString();

    // 跳过与上次请求完全相同的参数（如初始化触发的二次请求）
    if (paramsStr === lastFetchedParamsRef.current && initialized) {
      fetchingRef.current = false;
      return;
    }
    lastFetchedParamsRef.current = paramsStr;

    setLoading(true);
    abortRef.current = new AbortController();
    const signal = abortRef.current.signal;

    try {
      const resp = await fetch(
        `${API_CONFIG.endpoints.graph.graphData}?${paramsStr}`,
        { signal }
      );
      if (!resp.ok) throw new Error('API 调用失败');

      const result = await resp.json();
      if (result.status !== 'success' || !result.data) {
        throw new Error('API 返回数据异常');
      }

      // 如果已有更新的请求发起，丢弃当前结果
      if (requestId !== requestIdRef.current) return;

      const { nodes: rawNodes, edges: rawEdges, available_types, total_node_count, total_edge_count, truncated: isTruncated } = result.data;

      // 首次加载时初始化类型选择（仅设置状态，不再触发二次请求）
      if (!initialized) {
        setAvailableTypes(available_types);
        // 默认选中所有类型
        const allTypes = Object.keys(available_types);
        if (allTypes.length > 0) {
          // 预填 lastFetchedParamsRef，防止 useEffect #2 以全类型参数触发二次请求
          const allTypesParams = new URLSearchParams();
          allTypesParams.set('min_edges', String(minEdges));
          allTypesParams.set('max_nodes', '5000');
          lastFetchedParamsRef.current = allTypesParams.toString();
          setSelectedEntityTypes(allTypes);
        }
        setInitialized(true);
      }

      setTotalNodeCount(total_node_count);
      setTotalEdgeCount(total_edge_count);
      setTruncated(isTruncated);

      // 转换为 ForceGraph3D 所需格式
      const nodes: GraphNode[] = (rawNodes || []).map((node: any) => ({
        id: node.id || node.name,
        name: node.name,
        type: node.type || 'Entity',
        count: node.count ? Math.max(5, node.count * 2) : 10,
        color: entityTypeColors[node.type as keyof typeof entityTypeColors] || '#95A5A6'
      }));

      // 构建 ID 查找集合 + 名称→ID 映射（兼容旧关系缺少 subject_id/object_id 的情况）
      const nodeIdSet = new Set(nodes.map(n => String(n.id)));
      const nodeNameToId = new Map<string, string>();
      nodes.forEach(n => {
        if (n.name) nodeNameToId.set(String(n.name), String(n.id));
      });

      // 解析边的端点 ID：优先 UUID（subject_id/object_id），其次名称查表
      const resolveSrcId = (edge: any): string => {
        const sid = String(edge.subject_id || '');
        if (sid && nodeIdSet.has(sid)) return sid;
        const name = String(edge.source || '');
        if (name && nodeNameToId.has(name)) return nodeNameToId.get(name)!;
        return sid || name;
      };
      const resolveTgtId = (edge: any): string => {
        const oid = String(edge.object_id || '');
        if (oid && nodeIdSet.has(oid)) return oid;
        const name = String(edge.target || '');
        if (name && nodeNameToId.has(name)) return nodeNameToId.get(name)!;
        return oid || name;
      };

      // 去重边（按 srcId + tgtId + type 去重）
      const linkMap = new Map<string, GraphLink>();
      (rawEdges || []).forEach((edge: any) => {
        const srcId = resolveSrcId(edge);
        const tgtId = resolveTgtId(edge);
        const linkKey = `${srcId}_${tgtId}_${edge.type || 'association'}`;

        if (!linkMap.has(linkKey) && nodeIdSet.has(srcId) && nodeIdSet.has(tgtId)) {
          linkMap.set(linkKey, {
            source: srcId,
            target: tgtId,
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

      // 只有最新请求的结果才更新 UI（防止竞态）
      if (requestId === requestIdRef.current) {
        setGraphData({ nodes, links });
      }
    } catch (error: any) {
      // AbortError 是预期行为（组件卸载或手动刷新），静默处理
      if (error?.name !== 'AbortError') {
        console.error('获取图谱数据失败:', error);
        if (requestId === requestIdRef.current) {
          setGraphData({ nodes: [], links: [] });
        }
      }
    } finally {
      // 始终释放锁并关闭 loading（仅当本请求仍是最新时）
      if (requestId === requestIdRef.current) {
        setLoading(false);
      }
      fetchingRef.current = false;
    }
  }, [availableTypes, initialized, selectedEntityTypes.length]);

  // 首次加载
  useEffect(() => {
    fetchGraphData([], 1);
    return () => {
      // 组件卸载时取消进行中的请求
      if (abortRef.current) abortRef.current.abort();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 类型选择变化时重新请求（防抖 1000ms）
  useEffect(() => {
    if (!initialized) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      fetchGraphData(selectedEntityTypes, minEdgeCount);
    }, 1000);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [selectedEntityTypes, minEdgeCount]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node as GraphNode);
  }, []);

  const linkColorFn = useCallback((link: any) => {
    const r = parseInt(link.color.slice(1, 3), 16);
    const g = parseInt(link.color.slice(3, 5), 16);
    const b = parseInt(link.color.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, 0.6)`;
  }, []);

  const linkLabelFn = useCallback((link: any) => {
    return `关系类型: ${link.type}<br/>置信度: ${link.confidence.toFixed(2)}<br/>时间: ${link.occurrence_time || '-'}${link.description ? '<br/>描述: ' + link.description : ''}`;
  }, []);

  const nodeValFn = useCallback((node: any) => node.count, []);

  const handleRefresh = () => {
    // 取消防抖中的待执行请求，立即用最新过滤条件拉取
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    // 取消进行中的请求
    if (abortRef.current) abortRef.current.abort();
    fetchingRef.current = false;
    fetchGraphData(selectedEntityTypes, minEdgeCount);
  };

  if (loading && graphData.nodes.length === 0) {
    return <div className="graph-loading">加载中...</div>;
  }

  return (
    <div className="graph-visualization" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '80vh', width: '100%' }}>
      {/* 控制面板 */}
      <div className="graph-controls" style={{ padding: '0 10px', marginTop: '-5px', marginBottom: '-25px', flexShrink: 0 }}>
        <div className="filter-section">
          {/* 实体类型过滤 */}
          <div className="filter-group" style={{ marginBottom: '10px' }}>
            <h4 style={{ margin: '0', fontSize: '14px' }}>实体类型</h4>
            <div className="filter-options" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {Object.entries(availableTypes).sort(([a], [b]) => {
                if (a === 'other') return 1;
                if (b === 'other') return -1;
                return a.localeCompare(b);
              }).map(([type, count]) => (
                <label key={type} className="filter-checkbox" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <input
                    type="checkbox"
                    checked={selectedEntityTypes.includes(type)}
                    onChange={(e) => {
                      const next = e.target.checked
                        ? [...selectedEntityTypes, type]
                        : selectedEntityTypes.filter(t => t !== type);
                      setSelectedEntityTypes(next);
                    }}
                  />
                  <span className="filter-label" style={{ color: entityTypeColors[type] || '#95A5A6', fontSize: '13px' }}>
                    {type} ({count})
                  </span>
                </label>
              ))}
            </div>
          </div>

          {/* 边数滑块 + 统计 */}
          <div className="filter-group" style={{ marginBottom: '15px' }}>
            <h4 style={{ margin: '0 0 0 0', fontSize: '14px' }}>最少关联边数</h4>
            <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap' }}>
              <div className="strength-slider" style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: '300px' }}>
                <input
                  type="range"
                  min="0"
                  max="20"
                  step="1"
                  value={minEdgeCount}
                  onChange={(e) => setMinEdgeCount(parseInt(e.target.value))}
                  style={{ flex: 1 }}
                />
                <span style={{ fontSize: '13px', minWidth: '70px' }}>最少: {minEdgeCount} 条</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '15px', flexWrap: 'wrap' }}>
                <h4 style={{ margin: '0', fontSize: '14px' }}>统计</h4>
                <p style={{ margin: '0', fontSize: '13px' }}>
                  实体: {graphData.nodes.length}
                  {totalNodeCount > 0 ? ` / ${totalNodeCount}` : ''}
                </p>
                <p style={{ margin: '0', fontSize: '13px' }}>
                  关系: {graphData.links.length}
                  {totalEdgeCount > 0 ? ` / ${totalEdgeCount}` : ''}
                </p>
                <Button icon={<SearchOutlined />} onClick={handleRefresh} size="small" loading={loading} disabled={loading}>查询</Button>
              </div>
            </div>
          </div>
        </div>

        {truncated && (
          <div style={{
            padding: '8px 16px', marginBottom: '8px',
            backgroundColor: '#fff7e6', border: '1px solid #ffd591',
            borderRadius: '4px', fontSize: '13px', color: '#ad6800'
          }}>
            ⚠️ 实体总量 {totalNodeCount.toLocaleString()}，当前已按类型比例抽样显示 {graphData.nodes.length.toLocaleString()} 个实体。
            缩小过滤范围可查看更多。
          </div>
        )}
      </div>

      {/* 3D 力导向图 */}
      <div className="graph-container" style={{ flex: 1, minHeight: '500px', width: '100%', overflow: 'hidden' }}>
        <ForceGraph3D
          key="graph-viz-main"
          graphData={graphData}
          nodeColor={(node: any) => node.color}
          nodeLabel={(node: any) => node.name}
          nodeVal={nodeValFn}
          linkColor={linkColorFn}
          linkWidth={(link: any) => link.width}
          onNodeClick={handleNodeClick}
          linkLabel={linkLabelFn}
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={0.8}
          enableNodeDrag={true}
          backgroundColor="rgba(255, 255, 255, 0.95)"
          warmupTicks={40}
          cooldownTicks={60}
          cooldownTime={8000}
          d3AlphaDecay={0.02}
          d3VelocityDecay={0.3}
          d3AlphaMin={0.01}
        />
      </div>

      {/* 节点详情面板 */}
      {selectedNode && (
        <div className="node-details" style={{ padding: '15px', backgroundColor: '#fff', border: '1px solid #ddd', borderRadius: '8px', marginTop: '10px' }}>
          <h3 style={{ margin: '0 0 15px 0', fontSize: '18px', color: '#333' }}>节点详情</h3>
          <div style={{ marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid #eee' }}>
            <p style={{ margin: '5px 0', fontSize: '14px' }}><strong>名称:</strong> {selectedNode.name}</p>
            <p style={{ margin: '5px 0', fontSize: '14px' }}>
              <strong>类型:</strong>
              <span style={{ color: entityTypeColors[selectedNode.type] }}> {selectedNode.type}</span>
            </p>
            <p style={{ margin: '5px 0', fontSize: '14px' }}><strong>出现次数:</strong> {selectedNode.count}</p>
          </div>

          <div>
            <h4 style={{ margin: '0 0 10px 0', fontSize: '15px', color: '#555' }}>关联关系 ({
              (() => {
                const selId = String(selectedNode.id);
                const selName = String(selectedNode.name);
                return graphData.links.filter(l => {
                  const sid = String(typeof l.source === 'object' ? (l.source as any).id : l.source);
                  const tid = String(typeof l.target === 'object' ? (l.target as any).id : l.target);
                  const sn = String(typeof l.source === 'object' ? (l.source as any).name : l.source);
                  const tn = String(typeof l.target === 'object' ? (l.target as any).name : l.target);
                  return sid === selId || tid === selId || sn === selName || tn === selName;
                }).length;
              })()
            })</h4>

            {(() => {
              const selId = String(selectedNode.id);
              const selName = String(selectedNode.name);
              const nodeById = new Map(graphData.nodes.map(n => [String(n.id), n]));
              const nodeByName = new Map(graphData.nodes.map(n => [String(n.name), n]));

              const relatedLinks: RelatedLinkInfo[] = graphData.links
                .filter(link => {
                  const sid = String(typeof link.source === 'object' ? (link.source as any).id : link.source);
                  const tid = String(typeof link.target === 'object' ? (link.target as any).id : link.target);
                  const sn = String(typeof link.source === 'object' ? (link.source as any).name : link.source);
                  const tn = String(typeof link.target === 'object' ? (link.target as any).name : link.target);
                  return sid === selId || tid === selId || sn === selName || tn === selName;
                })
                .map(link => {
                  const sid = String(typeof link.source === 'object' ? (link.source as any).id : link.source);
                  const sn = String(typeof link.source === 'object' ? (link.source as any).name : link.source);
                  const tid = String(typeof link.target === 'object' ? (link.target as any).id : link.target);
                  const tn = String(typeof link.target === 'object' ? (link.target as any).name : link.target);

                  const isSource = sid === selId || sn === selName;
                  const targetId = isSource ? tid : sid;
                  const targetName = isSource ? tn : sn;
                  const targetNode = nodeById.get(targetId) || nodeByName.get(targetName);

                  return {
                    targetName: targetName || '',
                    targetType: targetNode?.type || 'Unknown',
                    type: link.type,
                    confidence: link.confidence,
                    occurrence_time: link.occurrence_time,
                    description: link.description
                  };
                });

              if (relatedLinks.length === 0) {
                return <p style={{ margin: '5px 0', fontSize: '14px', color: '#999' }}>暂无关联关系</p>;
              }

              return (
                <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                  {relatedLinks.map((link, index) => (
                    <div key={index} style={{ marginBottom: '10px', padding: '10px', backgroundColor: '#f9f9f9', borderRadius: '4px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                        <span style={{ fontWeight: 'bold', fontSize: '14px' }}>{selectedNode.name}</span>
                        <span style={{ color: '#999', fontSize: '12px' }}>-{link.type}-&gt;</span>
                        <span style={{
                          fontWeight: 'bold', fontSize: '14px',
                          color: entityTypeColors[link.targetType] || '#95A5A6'
                        }}>
                          {link.targetName}
                        </span>
                      </div>
                      <div style={{ fontSize: '12px', color: '#666', marginLeft: '5px' }}>
                        <div style={{ marginBottom: '3px' }}>关系类型: {link.type}</div>
                        <div style={{ marginBottom: '3px' }}>置信度: {link.confidence.toFixed(2)}</div>
                        <div style={{ marginBottom: '3px' }}>时间: {link.occurrence_time || '-'}</div>
                        {link.description && (
                          <div style={{ fontStyle: 'italic', color: '#555' }}>描述: {link.description}</div>
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
            style={{ marginTop: '15px', padding: '8px 16px', backgroundColor: '#3498db', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            关闭
          </button>
        </div>
      )}
    </div>
  );
};

export default GraphVisualization;
