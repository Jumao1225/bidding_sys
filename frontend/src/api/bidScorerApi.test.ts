import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BidDocumentUploadError, uploadBidDocument } from './bidScorerApi';

const apiFetchMock = vi.hoisted(() => vi.fn());

vi.mock('../utils/api', () => ({
  API_BASE_URL: 'http://test',
  apiFetch: apiFetchMock,
}));

describe('uploadBidDocument', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('服务端返回 500 时应保留错误详情和状态码', async () => {
    apiFetchMock.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'DoclingParser 解析失败' }), { status: 500 }),
    );

    const uploadPromise = uploadBidDocument(
      new File(['投标文件'], '投标文件.pdf', { type: 'application/pdf' }),
      'source-doc-1',
    );

    await expect(uploadPromise).rejects.toMatchObject({
      name: 'BidDocumentUploadError',
      message: 'DoclingParser 解析失败',
      status: 500,
    });
    await expect(uploadPromise).rejects.toBeInstanceOf(BidDocumentUploadError);
  });
});
