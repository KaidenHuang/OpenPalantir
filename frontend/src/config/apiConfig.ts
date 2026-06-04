// API配置文件
// 可以根据环境变量或其他方式动态调整API基础URL

// 使用Vite的环境变量机制
const API_BASE_URL = (import.meta as any).env.VITE_API_BASE_URL || 'http://localhost:8000';

export const API_CONFIG = {
  baseUrl: API_BASE_URL,
  endpoints: {
    filesystem: {
      browse: `${API_BASE_URL}/api/filesystem/browse`,
    },
    task: {
      create: `${API_BASE_URL}/api/task/create`,
      list: `${API_BASE_URL}/api/task/list`,
      get: (taskId: string) => `${API_BASE_URL}/api/task/${taskId}`,
      getResult: (taskId: string) => `${API_BASE_URL}/api/task/${taskId}/result`,
      delete: (taskId: string) => `${API_BASE_URL}/api/task/${taskId}`,
      stop: (taskId: string) => `${API_BASE_URL}/api/task/${taskId}/stop`
    },
    graph: {
      nodes: `${API_BASE_URL}/api/graph/nodes`,
      node: (entityId: string) => `${API_BASE_URL}/api/graph/nodes/${entityId}`,
      searchNodes: `${API_BASE_URL}/api/graph/nodes/search`,
      updateNode: (entityId: string) => `${API_BASE_URL}/api/graph/nodes/${entityId}`,
      deleteNode: (entityId: string) => `${API_BASE_URL}/api/graph/nodes/${entityId}`,
      nodeRelationships: (entityId: string) => `${API_BASE_URL}/api/graph/nodes/${entityId}/relationships`,
      addNode: `${API_BASE_URL}/api/graph/nodes`,
      addNodesBatch: `${API_BASE_URL}/api/graph/nodes/batch`,
      edges: `${API_BASE_URL}/api/graph/edges`,
      query: `${API_BASE_URL}/api/graph/query`,
      export: `${API_BASE_URL}/api/graph/export`,
      addRelationship: `${API_BASE_URL}/api/graph/relationships`,
      addRelationshipsBatch: `${API_BASE_URL}/api/graph/relationships/batch`,
      partition: `${API_BASE_URL}/api/graph/partition`,
      compress: `${API_BASE_URL}/api/graph/compress`,
      metaGraph: `${API_BASE_URL}/api/graph/meta-graph`,
      getEntityPartition: (entityName: string) => `${API_BASE_URL}/api/graph/partition/${entityName}`,
      optimizeSchema: `${API_BASE_URL}/api/graph/optimize/schema`,
      clearCache: `${API_BASE_URL}/api/graph/optimize/clear-cache`,
      getQueryPerformance: `${API_BASE_URL}/api/graph/optimize/query-performance`
    },
    model: {
      list: `${API_BASE_URL}/api/model/models`,
      get: (modelId: number) => `${API_BASE_URL}/api/model/models/${modelId}`,
      create: `${API_BASE_URL}/api/model/models`,
      update: (modelId: number) => `${API_BASE_URL}/api/model/models/${modelId}`,
      delete: (modelId: number) => `${API_BASE_URL}/api/model/models/${modelId}`,
      testConnection: (modelId: number) => `${API_BASE_URL}/api/model/models/${modelId}/test-connection`,
      enable: (modelId: number) => `${API_BASE_URL}/api/model/models/${modelId}/enable`
    },
    analysis: {
      path: `${API_BASE_URL}/api/analysis/path`,
      community: `${API_BASE_URL}/api/analysis/community`,
      centrality: `${API_BASE_URL}/api/analysis/centrality`,
      trend: `${API_BASE_URL}/api/analysis/trend`,
      report: `${API_BASE_URL}/api/analysis/report`
    },
    database: {
      connections: `${API_BASE_URL}/api/database/connections`,
      connection: (connectionId: string) => `${API_BASE_URL}/api/database/connections/${connectionId}`,
      testConnection: (connectionId: string) => `${API_BASE_URL}/api/database/connections/${connectionId}/test`,
      testConnectionConfig: `${API_BASE_URL}/api/database/test-connection`,
      restore: (connectionId: string) => `${API_BASE_URL}/api/database/connections/${connectionId}/restore`,
      analyze: (connectionId: string) => `${API_BASE_URL}/api/database/${connectionId}/analyze`,
      analysisResult: (connectionId: string) => `${API_BASE_URL}/api/database/${connectionId}/analysis-result`,
      summary: (connectionId: string) => `${API_BASE_URL}/api/database/${connectionId}/summary`,
      import: (connectionId: string) => `${API_BASE_URL}/api/database/${connectionId}/import`
    },
    decision: {
      ask: `${API_BASE_URL}/api/decision/ask`,
      session: (sessionId: string) => `${API_BASE_URL}/api/decision/session/${sessionId}`,
    },
    source: {
      list: `${API_BASE_URL}/api/sources`,
      create: `${API_BASE_URL}/api/sources`,
      delete: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}`,
      restore: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}/restore`,
      browse: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}/browse`,
      summarize: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}/summarize`,
      summary: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}/summary`,
      extract: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}/extract`,
      entities: (sourceId: string) => `${API_BASE_URL}/api/sources/${sourceId}/entities`,
    }
  }
};

export default API_CONFIG;