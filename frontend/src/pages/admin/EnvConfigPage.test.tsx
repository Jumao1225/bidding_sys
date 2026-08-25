import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EnvConfigPage, getDraftStorageKey } from './EnvConfigPage';

const apiFetchMock = vi.hoisted(() => vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
  if (String(_input).endsWith('/api/v1/admin/tenants')) {
    return new Response(JSON.stringify([{ id: 'tenant-a', name: '租户 A' }, { id: 'tenant-b', name: '租户 B' }]), { status: 200 });
  }
  if (init?.method === 'PUT') {
    return new Response(JSON.stringify({ data: { values: JSON.parse(String(init.body)) } }), { status: 200 });
  }
  return new Response(JSON.stringify({ data: { values: {} } }), { status: 200 });
}));

vi.mock('../../utils/api', () => ({
  API_BASE_URL: 'http://test',
  apiFetch: apiFetchMock,
}));

describe('EnvConfigPage', () => {
  beforeEach(() => {
    localStorage.clear();
    apiFetchMock.mockClear();
  });

  it('应该展示配置分组并允许编辑后保存到后端', async () => {
    render(<EnvConfigPage />);

    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(3);
    expect(screen.getByText('文档 OCR 模型（MinerU）')).toBeInTheDocument();
    expect(screen.getByText('视觉模型')).toBeInTheDocument();
    expect(screen.queryByText('本地视觉模型')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '导入 .env' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '导出 .env' })).not.toBeInTheDocument();

    const modelNameInput = screen.getByLabelText('模型名称', { selector: '#env-LLM_MODEL_NAME' });
    fireEvent.change(modelNameInput, { target: { value: 'gpt-4.1' } });
    fireEvent.click(screen.getByRole('button', { name: '保存到后端' }));

    await waitFor(() => expect(screen.getByText('模型配置已保存到后端并立即生效')).toBeInTheDocument());
    expect(apiFetchMock).toHaveBeenCalledWith('http://test/api/v1/admin/model-config?tenant_id=', expect.objectContaining({ method: 'PUT' }));
    expect(localStorage.getItem(getDraftStorageKey())).toContain('gpt-4.1');
  });

  it('应该为不同用户生成相互隔离的草稿存储空间', () => {
    localStorage.setItem('bidding_user', JSON.stringify({ id: 'user-a' }));
    const firstUserKey = getDraftStorageKey();
    localStorage.setItem('bidding_user', JSON.stringify({ id: 'user-b' }));
    const secondUserKey = getDraftStorageKey();

    expect(firstUserKey).not.toBe(secondUserKey);
  });

  it('平台管理员应该能够切换租户并保存对应租户配置', async () => {
    localStorage.setItem('bidding_user', JSON.stringify({ id: 'platform-a', role: 'admin' }));
    render(<EnvConfigPage />);

    const tenantSelect = await screen.findByLabelText('配置租户');
    fireEvent.change(tenantSelect, { target: { value: 'tenant-b' } });
    fireEvent.click(screen.getByRole('button', { name: '保存到后端' }));

    await waitFor(() => expect(screen.getByText('模型配置已保存到后端并立即生效')).toBeInTheDocument());
    expect(apiFetchMock).toHaveBeenCalledWith('http://test/api/v1/admin/model-config?tenant_id=tenant-b', expect.objectContaining({ method: 'PUT' }));
  });
});
