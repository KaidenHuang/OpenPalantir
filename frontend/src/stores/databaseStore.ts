/**
 * databaseStore — 数据库连接管理状态
 *
 * 管理数据库连接、Schema 分析、图谱导入。
 * 迁移自 DatabaseManagement 和 ERDiagram。
 */
import { create } from 'zustand';
import axios from 'axios';
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
  fetchConnections: (showDeleted?: boolean) => Promise<void>;
  setSelectedConnection: (conn: DatabaseConnection | null) => void;
  fetchDatabases: (connectionId: string) => Promise<void>;
  fetchSchema: (connectionId: string) => Promise<void>;
  fetchSummary: (connectionId: string) => Promise<void>;
  createConnection: (data: Record<string, unknown>) => Promise<void>;
  updateConnection: (id: string, data: Record<string, unknown>) => Promise<void>;
  deleteConnection: (id: string) => Promise<void>;
  restoreConnection: (id: string) => Promise<void>;
  testConnection: (config: Record<string, unknown>) => Promise<void>;
  analyzeSchema: (connectionId: string) => Promise<string>;
  importToGraph: (connectionId: string) => Promise<string>;
  configureCdc: (connectionId: string) => Promise<void>;
  startCdc: (connectionId: string) => Promise<void>;
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

  fetchConnections: async (showDeleted = false) => {
    const params = showDeleted ? { show_deleted: 'true' } : {};
    const response = await axios.get(API_CONFIG.endpoints.database.connections, { params });
    set({
      connections: (response.data.connections || []) as DatabaseConnection[],
      _lastFetched: Date.now(),
    });
  },

  setSelectedConnection: (conn) => set({ selectedConnection: conn }),

  fetchDatabases: async (connectionId) => {
    const response = await axios.get(
      API_CONFIG.endpoints.database.connection(connectionId) + '/databases'
    );
    set({ databases: (response.data.databases || []) as DatabaseItem[] });
  },

  fetchSchema: async (connectionId) => {
    const response = await axios.get(
      API_CONFIG.endpoints.database.analysisResult(connectionId)
    );
    set({ schemaResult: response.data as SchemaResult });
  },

  fetchSummary: async (connectionId) => {
    const response = await axios.get(
      API_CONFIG.endpoints.database.summary(connectionId)
    );
    set({ dbSummary: response.data as DbSummary });
  },

  createConnection: async (data) => {
    await axios.post(API_CONFIG.endpoints.database.connections, data);
    set({ _lastFetched: 0 });
    await get().fetchConnections();
  },

  updateConnection: async (id, data) => {
    await axios.put(API_CONFIG.endpoints.database.connection(id), data);
    set({ _lastFetched: 0 });
    await get().fetchConnections();
  },

  deleteConnection: async (id) => {
    await axios.delete(API_CONFIG.endpoints.database.connection(id));
    set({ _lastFetched: 0 });
    await get().fetchConnections();
  },

  restoreConnection: async (id) => {
    await axios.post(API_CONFIG.endpoints.database.restore(id));
    set({ _lastFetched: 0 });
    await get().fetchConnections();
  },

  testConnection: async (config) => {
    await axios.post(API_CONFIG.endpoints.database.testConnectionConfig, config);
  },

  analyzeSchema: async (connectionId) => {
    const response = await axios.post(
      API_CONFIG.endpoints.database.analyze(connectionId)
    );
    return response.data.task_id as string;
  },

  importToGraph: async (connectionId) => {
    const response = await axios.post(
      API_CONFIG.endpoints.database.import(connectionId)
    );
    return response.data.task_id as string;
  },

  configureCdc: async (connectionId) => {
    await axios.post(API_CONFIG.endpoints.cdc.configure(connectionId));
  },

  startCdc: async (connectionId) => {
    await axios.post(API_CONFIG.endpoints.cdc.startTask(connectionId));
  },

  setImportTaskId: (id) => set({ importTaskId: id }),
}));