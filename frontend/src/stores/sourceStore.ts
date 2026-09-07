/**
 * sourceStore — 文档源管理状态
 *
 * 管理文档源列表、文件浏览、摘要、实体提取。
 * 迁移自 DocumentViewer。
 */
import { create } from 'zustand';
import { httpGet, httpPost, httpDelete } from '../services/httpClient';
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
  fetchSources: (showDeleted?: boolean, signal?: AbortSignal) => Promise<void>;
  setSelectedSourceId: (id: string | null) => void;
  browseFiles: (sourceId: string, path?: string, signal?: AbortSignal) => Promise<void>;
  setSelectedFile: (file: string | null) => void;
  fetchSummary: (sourceId: string, filePath: string, signal?: AbortSignal) => Promise<void>;
  fetchEntities: (sourceId: string, filePath: string, signal?: AbortSignal) => Promise<void>;
  createSource: (name: string, path: string, type: 'local' | 's3', signal?: AbortSignal) => Promise<void>;
  deleteSource: (sourceId: string, signal?: AbortSignal) => Promise<void>;
  restoreSource: (sourceId: string, signal?: AbortSignal) => Promise<void>;
  summarize: (sourceId: string, filePath: string, signal?: AbortSignal) => Promise<string>;
  extractEntities: (sourceId: string, filePath: string, signal?: AbortSignal) => Promise<void>;
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

  fetchSources: async (showDeleted = false, signal?: AbortSignal) => {
    const params = showDeleted ? { show_deleted: 'true' } : {};
    const response = await httpGet(API_CONFIG.endpoints.source.list, { params, signal });
    set({ sources: (response.data.sources || []) as DocumentSource[] });
  },

  setSelectedSourceId: (id) => set({ selectedSourceId: id }),

  browseFiles: async (sourceId, path = '', signal?: AbortSignal) => {
    const response = await httpGet(
      API_CONFIG.endpoints.source.browse(sourceId),
      { params: { prefix: path }, signal }
    );
    set({
      files: (response.data.entries || response.data.files || []) as FileEntry[],
      currentPath: (response.data.current_path as string) || path,
    });
  },

  setSelectedFile: (file) => set({ selectedFile: file }),

  fetchSummary: async (sourceId, filePath, signal?: AbortSignal) => {
    const response = await httpGet(
      API_CONFIG.endpoints.source.summary(sourceId),
      { params: { file: filePath }, signal }
    );
    set({ summary: response.data as SummaryData });
  },

  fetchEntities: async (sourceId, filePath, signal?: AbortSignal) => {
    const response = await httpGet(
      API_CONFIG.endpoints.source.entities(sourceId),
      { params: { file: filePath }, signal }
    );
    set({ entities: (response.data.entities || []) as Entity[] });
  },

  createSource: async (name, path, type, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.source.create, {
      name,
      path,
      source_type: type,
    }, { signal });
    await get().fetchSources(undefined, signal);
  },

  deleteSource: async (sourceId, signal?: AbortSignal) => {
    await httpDelete(API_CONFIG.endpoints.source.delete(sourceId), { signal });
    await get().fetchSources(undefined, signal);
  },

  restoreSource: async (sourceId, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.source.restore(sourceId), undefined, { signal });
    await get().fetchSources(undefined, signal);
  },

  summarize: async (sourceId, filePath, signal?: AbortSignal) => {
    const response = await httpPost(
      API_CONFIG.endpoints.source.summarize(sourceId),
      { file: filePath },
      { signal }
    );
    return response.data.task_id as string;
  },

  extractEntities: async (sourceId, filePath, signal?: AbortSignal) => {
    await httpPost(
      API_CONFIG.endpoints.source.extract(sourceId),
      { file: filePath },
      { signal }
    );
  },

  setTaskId: (id) => set({ taskId: id }),
  setSummary: (data: SummaryData | null) => set({ summary: data }),
  setEntities: (data: Entity[]) => set({ entities: data }),
}));