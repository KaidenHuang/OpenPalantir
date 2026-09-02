/**
 * taskStore — 任务管理状态
 *
 * 管理任务列表、选中任务、任务的 CRUD 操作。
 * 迁移自 TaskManagement/TaskList/TaskDetails/TaskCreation。
 */
import { create } from 'zustand';
import axios from 'axios';
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
  fetchTasks: () => Promise<void>;
  fetchTaskDetail: (taskId: string) => Promise<void>;
  setSelectedTaskId: (taskId: string | null) => void;
  createTask: (taskType: string, payload: Record<string, unknown>) => Promise<string>;
  deleteTask: (taskId: string) => Promise<void>;
  stopTask: (taskId: string) => Promise<void>;
  clearSelection: () => void;
}

export const useTaskStore = create<TaskState>()((set, get) => ({
  tasks: [],
  selectedTaskId: null,
  selectedTask: null,
  loading: false,
  _lastFetched: 0,
  _staleTime: 10_000,

  fetchTasks: async () => {
    const now = Date.now();
    if (now - get()._lastFetched < get()._staleTime) return;

    set({ loading: true });
    try {
      const response = await axios.get(API_CONFIG.endpoints.task.list);
      const sorted = (response.data.tasks as Task[]).sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      );
      set({ tasks: sorted, _lastFetched: now, loading: false });
    } catch {
      set({ loading: false });
    }
  },

  fetchTaskDetail: async (taskId: string) => {
    const response = await axios.get(API_CONFIG.endpoints.task.get(taskId));
    set({ selectedTask: response.data as Task, selectedTaskId: taskId });
  },

  setSelectedTaskId: (taskId) => {
    set({ selectedTaskId: taskId });
  },

  createTask: async (taskType, payload) => {
    const response = await axios.post(API_CONFIG.endpoints.task.create, {
      task_type: taskType,
      payload,
    });
    // 创建后刷新列表
    set({ _lastFetched: 0 });
    await get().fetchTasks();
    return response.data.task_id as string;
  },

  deleteTask: async (taskId) => {
    await axios.delete(API_CONFIG.endpoints.task.delete(taskId));
    set({ _lastFetched: 0 });
    await get().fetchTasks();
  },

  stopTask: async (taskId) => {
    await axios.post(API_CONFIG.endpoints.task.stop(taskId));
    set({ _lastFetched: 0 });
    await get().fetchTasks();
  },

  clearSelection: () => {
    set({ selectedTaskId: null, selectedTask: null });
  },
}));