/**
 * httpClient — 集中式 HTTP 客户端
 *
 * 封装 axios，所有方法接受可选 signal 参数以支持请求取消。
 * 组件卸载时通过 AbortController 自动取消 in-flight 请求。
 */
import axios, { AxiosResponse } from 'axios';

/** 共享 axios 实例，统一超时配置 */
export const http = axios.create({
  timeout: 60_000,
});

/**
 * 后端响应是动态 JSON，调用方未显式传 T 时按松散对象处理。
 * 全项目唯一的宽松类型出口：需要类型安全时用 `httpGet<我的接口>(...)` 显式指定。
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type LooseJson = Record<string, any>;

/** GET 请求，支持 signal */
export const httpGet = <T = LooseJson>(
  url: string,
  opts?: { params?: Record<string, unknown>; signal?: AbortSignal }
): Promise<AxiosResponse<T>> => http.get<T>(url, { params: opts?.params, signal: opts?.signal });

/** POST 请求，支持 signal 与查询参数 */
export const httpPost = <T = LooseJson>(
  url: string,
  data?: unknown,
  opts?: { signal?: AbortSignal; params?: Record<string, unknown> }
): Promise<AxiosResponse<T>> => http.post<T>(url, data, { params: opts?.params, signal: opts?.signal });

/** PUT 请求，支持 signal */
export const httpPut = <T = LooseJson>(
  url: string,
  data?: unknown,
  opts?: { signal?: AbortSignal }
): Promise<AxiosResponse<T>> => http.put<T>(url, data, { signal: opts?.signal });

/** DELETE 请求，支持 signal */
export const httpDelete = <T = LooseJson>(
  url: string,
  opts?: { signal?: AbortSignal }
): Promise<AxiosResponse<T>> => http.delete<T>(url, { signal: opts?.signal });
