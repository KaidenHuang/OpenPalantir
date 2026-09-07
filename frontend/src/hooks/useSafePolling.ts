/**
 * useSafePolling — 安全轮询 Hook
 *
 * 解决 setInterval 的两个常见问题：
 * 1. 组件卸载后回调仍执行（通过 active 标志阻止）
 * 2. 闭包捕获陈旧变量（通过 callback ref 始终拿到最新回调）
 */
import { useEffect, useRef } from 'react';

export function useSafePolling(
  callback: () => Promise<void> | void,
  intervalMs: number,
  enabled: boolean,
) {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) return;
    let active = true;

    const tick = async () => {
      if (!active) return;
      try {
        await callbackRef.current();
      } catch {
        // 轮询回调异常不应中断轮询，由调用方在 callback 内处理
      }
    };

    const id = setInterval(tick, intervalMs);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [intervalMs, enabled]);
}
