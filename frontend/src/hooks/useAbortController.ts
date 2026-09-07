/**
 * useAbortController — 请求取消 Hook
 *
 * 提供两个 API：
 * - getComponentSignal(): 组件卸载时自动 abort，适合组件内所有请求共享生命周期
 * - getLatestSignal(key): 同 key 只保留最新请求，适合快速切换时取消前一个
 */
import { useEffect, useRef, useCallback } from 'react';

export function useAbortController() {
  const controllersRef = useRef<Map<string, AbortController>>(new Map());

  // 组件卸载时 abort 所有 controller
  useEffect(() => {
    const map = controllersRef.current;
    return () => {
      map.forEach(c => c.abort());
      map.clear();
    };
  }, []);

  /** 返回与组件生命周期绑定的 signal（每次调用创建新的） */
  const getComponentSignal = useCallback(() => {
    const key = '__component__';
    controllersRef.current.get(key)?.abort();
    const c = new AbortController();
    controllersRef.current.set(key, c);
    return c.signal;
  }, []);

  /** 同 key 只保留最新请求，自动取消上一个 */
  const getLatestSignal = useCallback((key: string) => {
    controllersRef.current.get(key)?.abort();
    const c = new AbortController();
    controllersRef.current.set(key, c);
    return c.signal;
  }, []);

  return { getComponentSignal, getLatestSignal };
}
