/**
 * modelStore — 模型配置状态
 *
 * 管理 LLM 模型平台列表、配置、CRUD 操作。
 * 迁移自 ModelManagement。
 */
import { create } from 'zustand';
import axios from 'axios';
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
  fetchPlatforms: () => Promise<void>;
  setSelectedPlatform: (platform: string) => void;
  setConfig: (config: Partial<PlatformConfig>) => void;
  fetchOllamaModels: (apiUrl: string) => Promise<void>;
  createModel: (name: string, modelType: 'local' | 'cloud') => Promise<void>;
  updateModel: (modelId: number, updates: Record<string, unknown>) => Promise<void>;
  deleteModel: (modelId: number) => Promise<void>;
  testConnection: (modelId: number) => Promise<void>;
}

export const useModelStore = create<ModelState>()((set, get) => ({
  platforms: [],
  models: [],
  selectedPlatform: '',
  config: { apiUrl: '', apiKey: '', modelName: '' },
  ollamaModels: [],
  _lastFetched: 0,
  _staleTime: 30_000,

  fetchPlatforms: async () => {
    const now = Date.now();
    if (now - get()._lastFetched < get()._staleTime) return;

    const response = await axios.get(API_CONFIG.endpoints.model.list);
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

  fetchOllamaModels: async (apiUrl) => {
    try {
      const response = await axios.get(`${apiUrl}/api/tags`);
      set({ ollamaModels: (response.data.models || []).map((m: { name: string }) => m.name) });
    } catch {
      set({ ollamaModels: [] });
    }
  },

  createModel: async (name, modelType) => {
    await axios.post(API_CONFIG.endpoints.model.create, {
      name,
      model_type: modelType,
      platform: get().selectedPlatform,
    });
    set({ _lastFetched: 0 });
    await get().fetchPlatforms();
  },

  updateModel: async (modelId, updates) => {
    await axios.put(API_CONFIG.endpoints.model.update(modelId), updates);
    set({ _lastFetched: 0 });
    await get().fetchPlatforms();
  },

  deleteModel: async (modelId) => {
    await axios.delete(API_CONFIG.endpoints.model.delete(modelId));
    set({ _lastFetched: 0 });
    await get().fetchPlatforms();
  },

  testConnection: async (modelId) => {
    await axios.post(API_CONFIG.endpoints.model.testConnection(modelId));
  },
}));