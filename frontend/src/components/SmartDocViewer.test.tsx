import { describe, expect, it, vi } from 'vitest';

vi.mock('@cyntler/react-doc-viewer', () => ({
  default: () => null,
  DocViewerRenderers: [],
}));

vi.mock('./LocalDocxRenderer', () => ({
  LocalDocxRenderer: {},
}));

vi.mock('react-pdf', () => ({
  Document: () => null,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {} },
}));

vi.mock('react-virtuoso', () => ({
  Virtuoso: () => null,
}));

import { build_pdf_file_source, PDF_DOCUMENT_OPTIONS } from './SmartDocViewer';

describe('build_pdf_file_source', () => {
  it('存在登录令牌时应生成携带鉴权头的 PDF 源配置', () => {
    expect(build_pdf_file_source('/api/v1/analysis/download/document-1', 'test-token')).toEqual({
      url: '/api/v1/analysis/download/document-1',
      httpHeaders: { Authorization: 'Bearer test-token' },
    });
  });

  it('不存在登录令牌时应直接使用文档地址', () => {
    expect(build_pdf_file_source('/api/v1/analysis/download/document-1', null)).toBe(
      '/api/v1/analysis/download/document-1',
    );
  });

  it('应为特殊编码 PDF 配置本地字符映射与标准字体资源', () => {
    expect(PDF_DOCUMENT_OPTIONS).toEqual({
      cMapUrl: '/cmaps/',
      cMapPacked: true,
      standardFontDataUrl: '/standard_fonts/',
    });
  });
});
