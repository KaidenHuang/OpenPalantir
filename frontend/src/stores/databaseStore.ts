/**
 * databaseStore — 数据库连接管理状态
 *
 * 管理数据库连接、Schema 分析、图谱导入。
 * 迁移自 DatabaseManagement 和 ERDiagram。
 */
import { create } from 'zustand';
import { httpGet, httpPost, httpPut, httpDelete } from '../services/httpClient';
import { API_CONFIG } from '../config/apiConfig';
import type { DatabaseConnection, DatabaseItem, DbSummary, SchemaResult } from './types';

interface DatabaseState {
  // 数据
  connections: DatabaseConnection[];
  selectedConnection: DatabaseConnection | null;
  schemaResult: SchemaResult | null;
  dbSummary: DbSummary | null;
  databases: DatabaseItem[];
  selectedDatabase: string | null;
  importTaskId: string | null;

  // 缓存
  _lastFetched: number;
  _staleTime: number;

  // Actions
  fetchConnections: (showDeleted?: boolean, signal?: AbortSignal) => Promise<void>;
  setSelectedConnection: (conn: DatabaseConnection | null) => void;
  fetchDatabases: (connectionId: string, signal?: AbortSignal) => Promise<void>;
  fetchSchema: (connectionId: string, signal?: AbortSignal) => Promise<void>;
  fetchSummary: (connectionId: string, signal?: AbortSignal) => Promise<void>;
  createConnection: (data: Record<string, unknown>, signal?: AbortSignal) => Promise<void>;
  updateConnection: (id: string, data: Record<string, unknown>, signal?: AbortSignal) => Promise<void>;
  deleteConnection: (id: string, signal?: AbortSignal) => Promise<void>;
  restoreConnection: (id: string, signal?: AbortSignal) => Promise<void>;
  testConnection: (config: Record<string, unknown>, signal?: AbortSignal) => Promise<void>;
  analyzeSchema: (connectionId: string, signal?: AbortSignal) => Promise<string>;
  importToGraph: (connectionId: string, signal?: AbortSignal) => Promise<string>;
  configureCdc: (connectionId: string, signal?: AbortSignal) => Promise<void>;
  startCdc: (connectionId: string, signal?: AbortSignal) => Promise<void>;
  setImportTaskId: (id: string | null) => void;
}

export const useDatabaseStore = create<DatabaseState>()((set, get) => ({
  connections: [],
  selectedConnection: null,
  schemaResult: null,
  dbSummary: null,
  databases: [],
  selectedDatabase: null,
  importTaskId: null,
  _lastFetched: 0,
  _staleTime: 30_000,

  fetchConnections: async (showDeleted = false, signal?: AbortSignal) => {
    const params = showDeleted ? { show_deleted: 'true' } : {};
    const response = await httpGet(API_CONFIG.endpoints.database.connections, { params, signal });
    set({
      connections: (response.data.connections || []) as DatabaseConnection[],
      _lastFetched: Date.now(),
    });
  },

  setSelectedConnection: (conn) => set({ selectedConnection: conn }),

  fetchDatabases: async (connectionId, signal?: AbortSignal) => {
    const response = await httpGet(
      API_CONFIG.endpoints.database.connection(connectionId) + '/databases',
      { signal }
    );
    set({ databases: (response.data.databases || []) as DatabaseItem[] });
  },

  fetchSchema: async (connectionId, signal?: AbortSignal) => {
    const response = await httpGet(
      API_CONFIG.endpoints.database.analysisResult(connectionId),
      { signal }
    );
    set({ schemaResult: response.data as SchemaResult });
  },

  fetchSummary: async (connectionId, signal?: AbortSignal) => {
    const response = await httpGet(
      API_CONFIG.endpoints.database.summary(connectionId),
      { signal }
    );
    set({ dbSummary: response.data as DbSummary });
  },

  createConnection: async (data, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.database.connections, data, { signal });
    set({ _lastFetched: 0 });
    await get().fetchConnections(undefined, signal);
  },

  updateConnection: async (id, data, signal?: AbortSignal) => {
    await httpPut(API_CONFIG.endpoints.database.connection(id), data, { signal });
    set({ _lastFetched: 0 });
    await get().fetchConnections(undefined, signal);
  },

  deleteConnection: async (id, signal?: AbortSignal) => {
    await httpDelete(API_CONFIG.endpoints.database.connection(id), { signal });
    set({ _lastFetched: 0 });
    await get().fetchConnections(undefined, signal);
  },

  restoreConnection: async (id, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.database.restore(id), undefined, { signal });
    set({ _lastFetched: 0 });
    await get().fetchConnections(undefined, signal);
  },

  testConnection: async (config, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.database.testConnectionConfig, config, { signal });
  },

  analyzeSchema: async (connectionId, signal?: AbortSignal) => {
    const response = await httpPost(
      API_CONFIG.endpoints.database.analyze(connectionId),
      undefined,
      { signal }
    );
    return response.data.task_id as string;
  },

  importToGraph: async (connectionId, signal?: AbortSignal) => {
    const response = await httpPost(
      API_CONFIG.endpoints.database.import(connectionId),
      undefined,
      { signal }
    );
    return response.data.task_id as string;
  },

  configureCdc: async (connectionId, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.cdc.configure(connectionId), undefined, { signal });
  },

  startCdc: async (connectionId, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.cdc.startTask(connectionId), undefined, { signal });
  },

  setImportTaskId: (id) => set({ importTaskId: id }),
}));