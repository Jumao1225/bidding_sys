import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BidScorerLab } from './BidScorerLab';
import { getBidUploadErrorMessage } from '../utils/bidScorerErrors';

const apiMocks = vi.hoisted(() => {
  class MockBidDocumentUploadError extends Error {
    readonly status: number;

    constructor(message: string, status: number) {
      super(message);
      this.name = 'BidDocumentUploadError';
      this.status = status;
    }
  }

  return {
    fetchTenderDocuments: vi.fn(),
    uploadBidDocument: vi.fn(),
    triggerBidScore: vi.fn(),
    getLatestScoreResult: vi.fn(),
    getScoreResultDetail: vi.fn(),
    deleteBidDocument: vi.fn(),
    rescoreCategory: vi.fn(),
    BidDocumentUploadError: MockBidDocumentUploadError,
  };
});

vi.mock('../api/bidScorerApi', () => ({
  ...apiMocks,
}));

vi.mock('../components/ChunkAnnotationWorkbench', () => ({
  ChunkAnnotationWorkbench: () => null,
}));

describe('BidScorerLab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.fetchTenderDocuments.mockResolvedValue([
      {
        id: 'source-doc-1',
        filename: '招标文件.pdf',
        status: 'completed',
        created_at: null,
      },
    ]);
  });

  it('上传解析遇到临时服务异常时应提示用户稍后重新点击上传按钮', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    apiMocks.uploadBidDocument.mockRejectedValue(
      new apiMocks.BidDocumentUploadError('DoclingParser 解析失败', 500),
    );

    render(<BidScorerLab />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: { files: [new File(['投标文件'], '投标文件.pdf', { type: 'application/pdf' })] },
    });

    const uploadButton = await screen.findByRole('button', { name: '上传并解析投标文件' });
    fireEvent.click(uploadButton);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '网络或文档解析服务暂时不稳定，本次上传未完成，请稍后重新点击“上传并解析投标文件”重试。',
    );
    expect(uploadButton).toBeEnabled();
    expect(screen.getByText(/投标文件.*投标文件\.pdf/)).toBeInTheDocument();

    consoleErrorSpy.mockRestore();
  });

  it('网络请求异常时应返回可执行的重试提示', () => {
    expect(getBidUploadErrorMessage(new TypeError('Failed to fetch'))).toBe(
      '网络连接暂时不稳定，本次上传未完成，请稍后重新点击“上传并解析投标文件”重试。',
    );
  });
});
