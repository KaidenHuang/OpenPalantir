/**
 * graphStore — 图谱数据状态
 *
 * 管理 3D 力导向图的数据、过滤器、选中节点。
 * 迁移自 GraphVisualization。
 */
import { create } from 'zustand';
import { API_CONFIG } from '../config/apiConfig';
import type { GraphLink, GraphNode } from './types';

// 实体类型颜色映射
const entityTypeColors: Record<string, string> = {
  person: '#3498db',
  organization: '#e74c3c',
  location: '#27ae60',
  event: '#f39c12',
  concept: '#9b59b6',
  other: '#95A5A6',
};

// 关系类型颜色映射
const relationshipTypeColors: Record<string, string> = {
  leadership: '#3498db',
  cooperation: '#27ae60',
  competition: '#e74c3c',
  association: '#f39c12',
  investment: '#9b59b6',
  management: '#1abc9c',
  located: '#34495e',
};

interface GraphState {
  // 数据
  graphData: { nodes: GraphNode[]; links: GraphLink[] };
  availableTypes: Record<string, number>;
  totalNodeCount: number;
  totalEdgeCount: number;
  truncated: boolean;

  // 过滤器
  selectedEntityTypes: string[];
  minEdgeCount: number;

  // UI 状态
  loading: boolean;
  initialized: boolean;
  selectedNode: GraphNode | null;

  // 缓存
  _lastFetched: number;
  _staleTime: number;

  // Actions
  fetchGraphData: (types: string[], minEdges: number) => Promise<void>;
  setSelectedEntityTypes: (types: string[]) => void;
  setMinEdgeCount: (count: number) => void;
  setSelectedNode: (node: GraphNode | null) => void;
}

export const useGraphStore = create<GraphState>()((set, get) => ({
  graphData: { nodes: [], links: [] },
  availableTypes: {},
  totalNodeCount: 0,
  totalEdgeCount: 0,
  truncated: false,
  selectedEntityTypes: [],
  minEdgeCount: 1,
  loading: false,
  initialized: false,
  selectedNode: null,
  _lastFetched: 0,
  _staleTime: 30_000,

  fetchGraphData: async (types, minEdges) => {
    set({ loading: true });

    try {
      const params = new URLSearchParams();
      if (types.length > 0 && types.length < Object.keys(get().availableTypes).length) {
        params.set('entity_types', types.join(','));
      }
      params.set('min_edges', String(minEdges));
      params.set('max_nodes', '5000');

      const resp = await fetch(`${API_CONFIG.endpoints.graph.graphData}?${params.toString()}`);
      if (!resp.ok) throw new Error('API 调用失败');

      const result = await resp.json();
      if (result.status !== 'success' || !result.data) {
        throw new Error('API 返回数据异常');
      }

      const { nodes: rawNodes, edges: rawEdges, available_types, total_node_count, total_edge_count, truncated: isTruncated } = result.data;

      // 首次加载时初始化类型选择
      if (!get().initialized) {
        const allTypes = Object.keys(available_types);
        set({
          availableTypes: available_types,
          selectedEntityTypes: allTypes,
          initialized: true,
        });
      }

      // 转换为 GraphNode 格式
      const nodes: GraphNode[] = (rawNodes || []).map((node: Record<string, unknown>) => ({
        id: (node.id || node.name) as string,
        name: node.name as string,
        type: (node.type as string) || 'Entity',
        count: node.count ? Math.max(5, (node.count as number) * 2) : 10,
        color: entityTypeColors[node.type as string] || '#95A5A6',
      }));

      // 构建节点查找表
      const nodeIdSet = new Set(nodes.map(n => String(n.id)));
      const nodeNameToId = new Map<string, string>();
      nodes.forEach(n => {
        if (n.name) nodeNameToId.set(String(n.name), String(n.id));
      });

      // 去重边
      const linkMap = new Map<string, GraphLink>();
      (rawEdges || []).forEach((edge: Record<string, unknown>) => {
        const srcId = String(edge.subject_id || '') || nodeNameToId.get(String(edge.source || '')) || String(edge.source || '');
        const tgtId = String(edge.object_id || '') || nodeNameToId.get(String(edge.target || '')) || String(edge.target || '');
        const linkKey = `${srcId}_${tgtId}_${edge.type || 'association'}`;

        if (!linkMap.has(linkKey) && nodeIdSet.has(srcId) && nodeIdSet.has(tgtId)) {
          linkMap.set(linkKey, {
            source: srcId,
            target: tgtId,
            type: (edge.type as string) || 'association',
            confidence: (edge.confidence as number) || 0.5,
            width: Math.max(1, ((edge.confidence as number) || 0.5) * 5),
            color: relationshipTypeColors[edge.type as string] || '#95A5A6',
            subject_id: (edge.subject_id as string) || '',
            object_id: (edge.object_id as string) || '',
            occurrence_time: (edge.occurrence_time as string) || '',
            description: (edge.description as string) || '',
          });
        }
      });

      set({
        graphData: { nodes, links: Array.from(linkMap.values()) },
        totalNodeCount: total_node_count,
        totalEdgeCount: total_edge_count,
        truncated: isTruncated,
        loading: false,
        _lastFetched: Date.now(),
      });
    } catch (error) {
      if ((error as { name?: string }).name !== 'AbortError') {
        console.error('获取图谱数据失败:', error);
        set({ graphData: { nodes: [], links: [] }, loading: false });
      }
    }
  },

  setSelectedEntityTypes: (types) => set({ selectedEntityTypes: types }),
  setMinEdgeCount: (count) => set({ minEdgeCount: count }),
  setSelectedNode: (node) => set({ selectedNode: node }),
}));