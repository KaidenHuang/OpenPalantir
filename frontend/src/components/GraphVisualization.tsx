import React, { useEffect, useCallback, useRef, useState, useMemo } from 'react';
import { Button } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import ForceGraph3D from 'react-force-graph-3d';
import { useGraphStore } from '../stores/graphStore';
import { useAbortController } from '../hooks/useAbortController';
import type { GraphNode } from '../stores/types';

// 实体类型颜色映射
const entityTypeColors: Record<string, string> = {
  person: '#3498db', organization: '#e74c3c', location: '#27ae60',
  event: '#f39c12', concept: '#9b59b6', other: '#95A5A6',
};

interface RelatedLinkInfo {
  targetName: string;
  targetType: string;
  type: string;
  confidence: number;
  occurrence_time?: string;
  description?: string;
}

const GraphVisualization: React.FC = () => {
  const {
    graphData, loading, selectedNode, selectedEntityTypes, availableTypes,
    minEdgeCount, totalNodeCount, totalEdgeCount, truncated, initialized,
    fetchGraphData, setSelectedEntityTypes, setMinEdgeCount, setSelectedNode,
    expandNeighbors,
  } = useGraphStore();

  const { getLatestSignal } = useAbortController();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string; nodeName: string } | null>(null);

  // 首次加载
  useEffect(() => {
    const signal = getLatestSignal('graph');
    fetchGraphData([], 1, signal);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 类型选择变化时重新请求（防抖 1000ms）
  useEffect(() => {
    if (!initialized) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const signal = getLatestSignal('graph');
      fetchGraphData(selectedEntityTypes, minEdgeCount, signal);
    }, 1000);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [selectedEntityTypes, minEdgeCount]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleNodeClick = useCallback((node: Record<string, unknown>) => {
    setSelectedNode(node as unknown as GraphNode);
    setContextMenu(null);
  }, [setSelectedNode]);

  const handleNodeRightClick = useCallback((node: Record<string, unknown>, event: MouseEvent) => {
    event.preventDefault();
    const nodeId = String(node.id || '');
    const nodeName = String(node.name || '');
    setContextMenu({ x: event.clientX, y: event.clientY, nodeId, nodeName });
  }, []);

  const handleExpandNeighbors = useCallback(async (nodeId: string, hops: number) => {
    setContextMenu(null);
    await expandNeighbors(nodeId, hops);
  }, [expandNeighbors]);

  // 点击空白处关闭右键菜单
  useEffect(() => {
    const closeMenu = () => setContextMenu(null);
    if (contextMenu) {
      window.addEventListener('click', closeMenu, { once: true });
      return () => window.removeEventListener('click', closeMenu);
    }
  }, [contextMenu]);

  const handleRefresh = () => {
    if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
    const signal = getLatestSignal('graph');
    fetchGraphData(selectedEntityTypes, minEdgeCount, signal);
  };

  // LOD: 按连接度计算节点大小，高度连接的节点更大
  const nodeDegreeMap = useMemo(() => {
    const deg = new Map<string, number>();
    for (const link of graphData.links) {
      const s = String(typeof link.source === 'object' ? (link.source as Record<string, unknown>).id : link.source);
      const t = String(typeof link.target === 'object' ? (link.target as Record<string, unknown>).id : link.target);
      deg.set(s, (deg.get(s) || 0) + 1);
      deg.set(t, (deg.get(t) || 0) + 1);
    }
    return deg;
  }, [graphData.links]);

  // 边聚合：同一对节点间的多条边合并为一条粗边
  const aggregatedLinks = useMemo(() => {
    if (graphData.links.length < 500) return null; // 少于 500 条边不聚合
    const map = new Map<string, typeof graphData.links[0] & { _count?: number }>();
    for (const link of graphData.links) {
      const s = String(typeof link.source === 'object' ? (link.source as Record<string, unknown>).id : link.source);
      const t = String(typeof link.target === 'object' ? (link.target as Record<string, unknown>).id : link.target);
      const key = s < t ? `${s}|${t}` : `${t}|${s}`;
      const existing = map.get(key);
      if (existing) {
        existing._count = (existing._count || 1) + 1;
        existing.width = Math.min(8, existing.width + 0.5);
      } else {
        map.set(key, { ...link, _count: 1 });
      }
    }
    return Array.from(map.values());
  }, [graphData.links]);

  const displayLinks = aggregatedLinks || graphData.links;

  if (loading && graphData.nodes.length === 0) {
    return <div className="graph-loading">加载中...</div>;
  }

  return (
    <div className="graph-visualization" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '80vh', width: '100%' }}>
      <div className="graph-controls" style={{ padding: '0 10px', marginTop: '-5px', marginBottom: '-25px', flexShrink: 0 }}>
        <div className="filter-section">
          <div className="filter-group" style={{ marginBottom: '10px' }}>
            <h4 style={{ margin: '0', fontSize: '14px' }}>实体类型</h4>
            <div className="filter-options" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {Object.entries(availableTypes).sort(([a], [b]) => {
                if (a === 'other') return 1;
                if (b === 'other') return -1;
                return a.localeCompare(b);
              }).map(([type, count]) => (
                <label key={type} className="filter-checkbox" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <input type="checkbox" checked={selectedEntityTypes.includes(type)}
                    onChange={(e) => {
                      const next = e.target.checked ? [...selectedEntityTypes, type] : selectedEntityTypes.filter(t => t !== type);
                      setSelectedEntityTypes(next);
                    }} />
                  <span className="filter-label" style={{ color: entityTypeColors[type] || '#95A5A6', fontSize: '13px' }}>
                    {type} ({count})
                  </span>
                </label>
              ))}
            </div>
          </div>
          <div className="filter-group" style={{ marginBottom: '15px' }}>
            <h4 style={{ margin: '0 0 0 0', fontSize: '14px' }}>最少关联边数</h4>
            <div style={{ display: 'flex', alignItems: 'center', gap: '20px', flexWrap: 'wrap' }}>
              <div className="strength-slider" style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, minWidth: '300px' }}>
                <input type="range" min="0" max="20" step="1" value={minEdgeCount}
                  onChange={(e) => setMinEdgeCount(parseInt(e.target.value))} style={{ flex: 1 }} />
                <span style={{ fontSize: '13px', minWidth: '70px' }}>最少: {minEdgeCount} 条</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '15px', flexWrap: 'wrap' }}>
                <h4 style={{ margin: '0', fontSize: '14px' }}>统计</h4>
                <p style={{ margin: '0', fontSize: '13px' }}>实体: {graphData.nodes.length}{totalNodeCount > 0 ? ` / ${totalNodeCount}` : ''}</p>
                <p style={{ margin: '0', fontSize: '13px' }}>关系: {graphData.links.length}{totalEdgeCount > 0 ? ` / ${totalEdgeCount}` : ''}</p>
                <Button icon={<SearchOutlined />} onClick={handleRefresh} size="small" loading={loading} disabled={loading}>查询</Button>
              </div>
            </div>
          </div>
        </div>
        {truncated && (
          <div style={{ padding: '8px 16px', marginBottom: '8px', backgroundColor: '#fff7e6', border: '1px solid #ffd591', borderRadius: '4px', fontSize: '13px', color: '#ad6800' }}>
            ⚠️ 实体总量 {totalNodeCount.toLocaleString()}，当前已按类型比例抽样显示 {graphData.nodes.length.toLocaleString()} 个实体。缩小过滤范围可查看更多。
          </div>
        )}
      </div>

      <div className="graph-container" style={{ flex: 1, minHeight: '500px', width: '100%', overflow: 'hidden' }}>
        <ForceGraph3D
          key="graph-viz-main"
          graphData={{ nodes: graphData.nodes, links: displayLinks } as unknown as { nodes: Record<string, unknown>[]; links: Record<string, unknown>[] }}
          nodeColor={(node: Record<string, unknown>) => node.color as string}
          nodeLabel={(node: Record<string, unknown>) => {
            const nid = String(node.id || '');
            const degree = nodeDegreeMap.get(nid) || 0;
            return `<b>${node.name}</b><br/>类型: ${node.type}<br/>连接数: ${degree}`;
          }}
          nodeVal={(node: Record<string, unknown>) => {
            const nid = String(node.id || '');
            const degree = nodeDegreeMap.get(nid) || 0;
            const baseSize = (node.count as number) || 5;
            // 连接度 >10 的节点放大，>30 更明显
            return Math.max(baseSize, Math.min(baseSize + degree * 0.8, 30));
          }}
          nodeOpacity={0.9}
          linkColor={(link: Record<string, unknown>) => {
            const color = link.color as string;
            const r = parseInt(color.slice(1, 3), 16);
            const g = parseInt(color.slice(3, 5), 16);
            const b = parseInt(color.slice(5, 7), 16);
            return `rgba(${r}, ${g}, ${b}, 0.5)`;
          }}
          linkWidth={(link: Record<string, unknown>) => link.width as number}
          linkOpacity={0.4}
          onNodeClick={handleNodeClick}
          onNodeRightClick={handleNodeRightClick}
          linkLabel={(link: Record<string, unknown>) => {
            const count = link._count as number | undefined;
            const countStr = count && count > 1 ? `<br/>合并: ${count} 条` : '';
            return `关系类型: ${link.type as string}<br/>置信度: ${(link.confidence as number).toFixed(2)}<br/>时间: ${link.occurrence_time as string || '-'}${link.description ? '<br/>描述: ' + (link.description as string) : ''}${countStr}`;
          }}
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

      {selectedNode && (
        <div className="node-details" style={{ padding: '15px', backgroundColor: '#fff', border: '1px solid #ddd', borderRadius: '8px', marginTop: '10px' }}>
          <h3 style={{ margin: '0 0 15px 0', fontSize: '18px', color: '#333' }}>节点详情</h3>
          <div style={{ marginBottom: '15px', paddingBottom: '15px', borderBottom: '1px solid #eee' }}>
            <p style={{ margin: '5px 0', fontSize: '14px' }}><strong>名称:</strong> {selectedNode.name}</p>
            <p style={{ margin: '5px 0', fontSize: '14px' }}><strong>类型:</strong>
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
                  const sid = String(typeof l.source === 'object' ? (l.source as unknown as Record<string, unknown>).id : l.source);
                  const tid = String(typeof l.target === 'object' ? (l.target as unknown as Record<string, unknown>).id : l.target);
                  const sn = String(typeof l.source === 'object' ? (l.source as unknown as Record<string, unknown>).name : l.source);
                  const tn = String(typeof l.target === 'object' ? (l.target as unknown as Record<string, unknown>).name : l.target);
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
                  const sid = String(typeof link.source === 'object' ? (link.source as unknown as Record<string, unknown>).id : link.source);
                  const tid = String(typeof link.target === 'object' ? (link.target as unknown as Record<string, unknown>).id : link.target);
                  const sn = String(typeof link.source === 'object' ? (link.source as unknown as Record<string, unknown>).name : link.source);
                  const tn = String(typeof link.target === 'object' ? (link.target as unknown as Record<string, unknown>).name : link.target);
                  return sid === selId || tid === selId || sn === selName || tn === selName;
                })
                .map(link => {
                  const sid = String(typeof link.source === 'object' ? (link.source as unknown as Record<string, unknown>).id : link.source);
                  const sn = String(typeof link.source === 'object' ? (link.source as unknown as Record<string, unknown>).name : link.source);
                  const tid = String(typeof link.target === 'object' ? (link.target as unknown as Record<string, unknown>).id : link.target);
                  const tn = String(typeof link.target === 'object' ? (link.target as unknown as Record<string, unknown>).name : link.target);
                  const isSource = sid === selId || sn === selName;
                  const targetId = isSource ? tid : sid;
                  const targetName = isSource ? tn : sn;
                  const targetNode = nodeById.get(targetId) || nodeByName.get(targetName);
                  return {
                    targetName: targetName || '', targetType: targetNode?.type || 'Unknown',
                    type: link.type, confidence: link.confidence,
                    occurrence_time: link.occurrence_time, description: link.description,
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
                        <span style={{ fontWeight: 'bold', fontSize: '14px', color: entityTypeColors[link.targetType] || '#95A5A6' }}>{link.targetName}</span>
                      </div>
                      <div style={{ fontSize: '12px', color: '#666', marginLeft: '5px' }}>
                        <div style={{ marginBottom: '3px' }}>关系类型: {link.type}</div>
                        <div style={{ marginBottom: '3px' }}>置信度: {link.confidence.toFixed(2)}</div>
                        <div style={{ marginBottom: '3px' }}>时间: {link.occurrence_time || '-'}</div>
                        {link.description && <div style={{ fontStyle: 'italic', color: '#555' }}>描述: {link.description}</div>}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })()}
          </div>
          <button onClick={() => setSelectedNode(null)} style={{ marginTop: '15px', padding: '8px 16px', backgroundColor: '#3498db', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>关闭</button>
        </div>
      )}

      {/* 右键菜单 */}
      {contextMenu && (
        <div
          style={{
            position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 9999,
            background: '#fff', border: '1px solid #d9d9d9', borderRadius: 6,
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)', padding: '4px 0', minWidth: 140,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <div style={{ padding: '4px 12px', fontSize: 12, color: '#999', borderBottom: '1px solid #f0f0f0' }}>
            {contextMenu.nodeName}
          </div>
          {[1, 2, 3].map(hops => (
            <div
              key={hops}
              style={{ padding: '6px 12px', fontSize: 13, cursor: 'pointer' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = '#f5f5f5')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
              onClick={() => handleExpandNeighbors(contextMenu.nodeId, hops)}
            >
              展开 {hops} 跳邻居
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default GraphVisualization;