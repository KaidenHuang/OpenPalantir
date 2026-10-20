/**
 * sourceStore — 文档源管理状态
 *
 * 管理文档源列表、文件浏览、摘要、实体提取。
 * 迁移自 DocumentViewer。
 */
import { create } from 'zustand';
import { httpGet, httpPost, httpDelete } from '../services/httpClient';
import { API_CONFIG } from '../config/apiConfig';
import type { DocumentSource, Entity, FileEntry, SummaryData, FileStat } from './types';

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
  inventory: Record<string, FileStat>;

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
  summarizeBatch: (sourceId: string, files: string[] | null, force: boolean, label: string | undefined, signal?: AbortSignal) => Promise<string>;
  extractBatch: (sourceId: string, files: string[] | null, domain: string, label: string | undefined, signal?: AbortSignal) => Promise<string>;
  fetchInventory: (sourceId: string, signal?: AbortSignal) => Promise<Record<string, FileStat>>;
  setTaskId: (id: string | null) => void;
  setSummary: (data: SummaryData | null) => void;
  setEntities: (data: Entity[]) => void;
  setInventory: (data: Record<string, FileStat>) => void;
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
  inventory: {},
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

  summarizeBatch: async (sourceId, files, force = false, label, signal?: AbortSignal) => {
    const body: Record<string, unknown> = { force };
    if (files) body.files = files;
    if (label) body.label = label;
    const response = await httpPost(
      API_CONFIG.endpoints.source.summarizeBatch(sourceId),
      body,
      { signal }
    );
    return response.data.task_id as string;
  },

  extractBatch: async (sourceId, files, domain = 'general', label, signal?: AbortSignal) => {
    const body: Record<string, unknown> = { domain };
    if (files) body.files = files;
    if (label) body.label = label;
    const response = await httpPost(
      API_CONFIG.endpoints.source.extractBatch(sourceId),
      body,
      { signal }
    );
    return response.data.task_id as string;
  },

  fetchInventory: async (sourceId, signal?: AbortSignal) => {
    const map: Record<string, FileStat> = {};
    try {
      const response = await httpGet(API_CONFIG.endpoints.source.inventory(sourceId), { signal });
      for (const item of (response.data.files || []) as FileStat[]) {
        map[item.path] = item;
      }
    } catch {
      // inventory 不可用时降级为空映射（状态藏不显示，不阻塞浏览）
    }
    return map;
  },

  setTaskId: (id) => set({ taskId: id }),
  setSummary: (data: SummaryData | null) => set({ summary: data }),
  setEntities: (data: Entity[]) => set({ entities: data }),
  setInventory: (data) => set({ inventory: data }),
}));