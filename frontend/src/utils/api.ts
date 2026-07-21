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
