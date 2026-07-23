/**
 * 获取 API 基础路径，容错处理并自动补全 http:// 协议与端口
 */
export function getApiBaseUrl(): string {
  let url = (import.meta.env.VITE_API_BASE_URL || '').trim();
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url.replace(/\/+$/, '');
  }
  if (!url.includes(':')) {
    url = `${url}:8000`;
  }
  return `http://${url}`.replace(/\/+$/, '');
}

export const API_BASE_URL = getApiBaseUrl();

/**
 * 封装原生 fetch，自动注入 Auth Token 并拦截 401/403 错误
 */
export async function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = localStorage.getItem('bidding_token');
  
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(input, {
    ...init,
    headers,
  });

  if (response.status === 401) {
    // 触发自定义事件，让 AuthContext 监听到并执行退出登录操作
    const event = new CustomEvent('unauthorized_access');
    window.dispatchEvent(event);
  }

  return response;
}
