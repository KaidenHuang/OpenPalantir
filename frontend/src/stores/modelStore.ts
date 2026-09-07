/**
 * modelStore — 模型配置状态
 *
 * 管理 LLM 模型平台列表、配置、CRUD 操作。
 * 迁移自 ModelManagement。
 */
import { create } from 'zustand';
import { httpGet, httpPost, httpPut, httpDelete } from '../services/httpClient';
import { API_CONFIG } from '../config/apiConfig';
import type { ModelInfo, ModelPlatform, PlatformConfig } from './types';

interface ModelState {
  // 数据
  platforms: ModelPlatform[];
  models: ModelInfo[];
  selectedPlatform: string;
  config: PlatformConfig;
  ollamaModels: string[];

  // 缓存
  _lastFetched: number;
  _staleTime: number;

  // Actions
  fetchPlatforms: (signal?: AbortSignal) => Promise<void>;
  setSelectedPlatform: (platform: string) => void;
  setConfig: (config: Partial<PlatformConfig>) => void;
  fetchOllamaModels: (apiUrl: string, signal?: AbortSignal) => Promise<void>;
  createModel: (name: string, modelType: 'local' | 'cloud', signal?: AbortSignal) => Promise<void>;
  updateModel: (modelId: number, updates: Record<string, unknown>, signal?: AbortSignal) => Promise<void>;
  deleteModel: (modelId: number, signal?: AbortSignal) => Promise<void>;
  testConnection: (modelId: number, signal?: AbortSignal) => Promise<void>;
}

export const useModelStore = create<ModelState>()((set, get) => ({
  platforms: [],
  models: [],
  selectedPlatform: '',
  config: { apiUrl: '', apiKey: '', modelName: '' },
  ollamaModels: [],
  _lastFetched: 0,
  _staleTime: 30_000,

  fetchPlatforms: async (signal?: AbortSignal) => {
    const now = Date.now();
    if (now - get()._lastFetched < get()._staleTime) return;

    const response = await httpGet(API_CONFIG.endpoints.model.list, { signal });
    const rawModels: ModelInfo[] = response.data.models || [];

    // 按平台分组
    const grouped: Record<string, ModelInfo[]> = {};
    for (const m of rawModels) {
      const key = m.platform || 'ollama';
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(m);
    }

    const platformMap: Record<string, string> = {
      ollama: 'Ollama (本地)',
      openai: 'OpenAI',
      siliconflow: 'SiliconFlow',
      deepseek: 'DeepSeek',
    };

    const platforms: ModelPlatform[] = Object.entries(grouped).map(([key, models]) => ({
      key,
      label: platformMap[key] || key,
      apiUrl: '',
      apiKey: '',
      models,
    }));

    set({ platforms, models: rawModels, _lastFetched: now });
  },

  setSelectedPlatform: (platform) => set({ selectedPlatform: platform }),

  setConfig: (partial) => set((s) => ({ config: { ...s.config, ...partial } })),

  fetchOllamaModels: async (apiUrl, signal?: AbortSignal) => {
    try {
      const response = await httpGet(`${apiUrl}/api/tags`, { signal });
      set({ ollamaModels: (response.data.models || []).map((m: { name: string }) => m.name) });
    } catch {
      set({ ollamaModels: [] });
    }
  },

  createModel: async (name, modelType, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.model.create, {
      name,
      model_type: modelType,
      platform: get().selectedPlatform,
    }, { signal });
    set({ _lastFetched: 0 });
    await get().fetchPlatforms(signal);
  },

  updateModel: async (modelId, updates, signal?: AbortSignal) => {
    await httpPut(API_CONFIG.endpoints.model.update(modelId), updates, { signal });
    set({ _lastFetched: 0 });
    await get().fetchPlatforms(signal);
  },

  deleteModel: async (modelId, signal?: AbortSignal) => {
    await httpDelete(API_CONFIG.endpoints.model.delete(modelId), { signal });
    set({ _lastFetched: 0 });
    await get().fetchPlatforms(signal);
  },

  testConnection: async (modelId, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.model.testConnection(modelId), undefined, { signal });
  },
}));