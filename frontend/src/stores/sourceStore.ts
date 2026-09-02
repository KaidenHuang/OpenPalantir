/**
 * sourceStore — 文档源管理状态
 *
 * 管理文档源列表、文件浏览、摘要、实体提取。
 * 迁移自 DocumentViewer。
 */
import { create } from 'zustand';
import axios from 'axios';
import { API_CONFIG } from '../config/apiConfig';
import type { DocumentSource, Entity, FileEntry, SummaryData } from './types';

interface SourceState {
  // 数据
  sources: DocumentSource[];
  selectedSourceId: string | null;
  files: FileEntry[];
  currentPath: string;
  selectedFile: string | null;
  summary: SummaryData | null;
  entities: Entity[];
  taskId: string | null;

  // 缓存
  _lastFetched: number;
  _staleTime: number;

  // Actions
  fetchSources: (showDeleted?: boolean) => Promise<void>;
  setSelectedSourceId: (id: string | null) => void;
  browseFiles: (sourceId: string, path?: string) => Promise<void>;
  setSelectedFile: (file: string | null) => void;
  fetchSummary: (sourceId: string, filePath: string) => Promise<void>;
  fetchEntities: (sourceId: string, filePath: string) => Promise<void>;
  createSource: (name: string, path: string, type: 'local' | 's3') => Promise<void>;
  deleteSource: (sourceId: string) => Promise<void>;
  restoreSource: (sourceId: string) => Promise<void>;
  summarize: (sourceId: string, filePath: string) => Promise<string>;
  extractEntities: (sourceId: string, filePath: string) => Promise<void>;
  setTaskId: (id: string | null) => void;
  setSummary: (data: SummaryData | null) => void;
  setEntities: (data: Entity[]) => void;
}

export const useSourceStore = create<SourceState>()((set, get) => ({
  sources: [],
  selectedSourceId: null,
  files: [],
  currentPath: '',
  selectedFile: null,
  summary: null,
  entities: [],
  taskId: null,
  _lastFetched: 0,
  _staleTime: 30_000,

  fetchSources: async (showDeleted = false) => {
    const params = showDeleted ? { show_deleted: 'true' } : {};
    const response = await axios.get(API_CONFIG.endpoints.source.list, { params });
    set({ sources: (response.data.sources || []) as DocumentSource[] });
  },

  setSelectedSourceId: (id) => set({ selectedSourceId: id }),

  browseFiles: async (sourceId, path = '') => {
    const response = await axios.get(
      API_CONFIG.endpoints.source.browse(sourceId),
      { params: { path } }
    );
    set({
      files: (response.data.files || []) as FileEntry[],
      currentPath: path,
    });
  },

  setSelectedFile: (file) => set({ selectedFile: file }),

  fetchSummary: async (sourceId, filePath) => {
    const response = await axios.get(
      API_CONFIG.endpoints.source.summary(sourceId),
      { params: { file: filePath } }
    );
    set({ summary: response.data as SummaryData });
  },

  fetchEntities: async (sourceId, filePath) => {
    const response = await axios.get(
      API_CONFIG.endpoints.source.entities(sourceId),
      { params: { file: filePath } }
    );
    set({ entities: (response.data.entities || []) as Entity[] });
  },

  createSource: async (name, path, type) => {
    await axios.post(API_CONFIG.endpoints.source.create, {
      name,
      path,
      source_type: type,
    });
    await get().fetchSources();
  },

  deleteSource: async (sourceId) => {
    await axios.delete(API_CONFIG.endpoints.source.delete(sourceId));
    await get().fetchSources();
  },

  restoreSource: async (sourceId) => {
    await axios.post(API_CONFIG.endpoints.source.restore(sourceId));
    await get().fetchSources();
  },

  summarize: async (sourceId, filePath) => {
    const response = await axios.post(
      API_CONFIG.endpoints.source.summarize(sourceId),
      { file: filePath }
    );
    return response.data.task_id as string;
  },

  extractEntities: async (sourceId, filePath) => {
    await axios.post(
      API_CONFIG.endpoints.source.extract(sourceId),
      { file: filePath }
    );
  },

  setTaskId: (id) => set({ taskId: id }),
  setSummary: (data: SummaryData | null) => set({ summary: data }),
  setEntities: (data: Entity[]) => set({ entities: data }),
}));