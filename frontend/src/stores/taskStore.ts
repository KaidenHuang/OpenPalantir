/**
 * taskStore — 任务管理状态
 *
 * 管理任务列表、选中任务、任务的 CRUD 操作。
 * 迁移自 TaskManagement/TaskList/TaskDetails/TaskCreation。
 */
import { create } from 'zustand';
import { httpGet, httpPost, httpDelete } from '../services/httpClient';
import { API_CONFIG } from '../config/apiConfig';
import type { Task } from './types';

interface TaskState {
  // 数据
  tasks: Task[];
  selectedTaskId: string | null;
  selectedTask: Task | null;
  loading: boolean;

  // 缓存
  _lastFetched: number;
  _staleTime: number;

  // Actions
  fetchTasks: (signal?: AbortSignal) => Promise<void>;
  fetchTaskDetail: (taskId: string, signal?: AbortSignal) => Promise<void>;
  setSelectedTaskId: (taskId: string | null) => void;
  createTask: (taskType: string, payload: Record<string, unknown>, signal?: AbortSignal) => Promise<string>;
  deleteTask: (taskId: string, signal?: AbortSignal) => Promise<void>;
  stopTask: (taskId: string, signal?: AbortSignal) => Promise<void>;
  clearSelection: () => void;
}

export const useTaskStore = create<TaskState>()((set, get) => ({
  tasks: [],
  selectedTaskId: null,
  selectedTask: null,
  loading: false,
  _lastFetched: 0,
  _staleTime: 10_000,

  fetchTasks: async (signal?: AbortSignal) => {
    const now = Date.now();
    if (now - get()._lastFetched < get()._staleTime) return;

    set({ loading: true });
    try {
      const response = await httpGet(API_CONFIG.endpoints.task.list, { signal });
      const sorted = (response.data.tasks as Task[]).sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
      set({ tasks: sorted, _lastFetched: now, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  fetchTaskDetail: async (taskId: string, signal?: AbortSignal) => {
    const response = await httpGet(API_CONFIG.endpoints.task.get(taskId), { signal });
    set({ selectedTask: response.data as Task, selectedTaskId: taskId });
  },

  setSelectedTaskId: (taskId) => {
    set({ selectedTaskId: taskId });
  },

  createTask: async (taskType, payload, signal?: AbortSignal) => {
    const response = await httpPost(API_CONFIG.endpoints.task.create, {
      task_type: taskType,
      payload,
    }, { signal });
    set({ _lastFetched: 0 });
    await get().fetchTasks(signal);
    return response.data.task_id as string;
  },

  deleteTask: async (taskId, signal?: AbortSignal) => {
    await httpDelete(API_CONFIG.endpoints.task.delete(taskId), { signal });
    set({ _lastFetched: 0 });
    await get().fetchTasks(signal);
  },

  stopTask: async (taskId, signal?: AbortSignal) => {
    await httpPost(API_CONFIG.endpoints.task.stop(taskId), undefined, { signal });
    set({ _lastFetched: 0 });
    await get().fetchTasks(signal);
  },

  clearSelection: () => {
    set({ selectedTaskId: null, selectedTask: null });
  },
}));