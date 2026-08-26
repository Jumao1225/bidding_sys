import { useMemo, useState, memo } from 'react';
import DocViewer, { DocViewerRenderers } from "@cyntler/react-doc-viewer";
import "@cyntler/react-doc-viewer/dist/index.css";
import { LocalDocxRenderer } from './LocalDocxRenderer';
import { Document, Page, pdfjs } from 'react-pdf';
import { Virtuoso } from 'react-virtuoso';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

// 必须配置 pdf.js worker
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

export interface SmartDocViewerProps {
  documents: { uri: string; fileName: string; fileType: string }[];
  zoomLevel?: number;
}

const RENDERERS = [LocalDocxRenderer, ...DocViewerRenderers];

type PdfFileSource = string | {
  url: string;
  httpHeaders: {
    Authorization: string;
  };
};

/**
 * 根据文档地址和登录令牌生成 PDF 源配置。
 */
export function build_pdf_file_source(uri: string, token: string | null): PdfFileSource {
  if (!token) {
    return uri;
  }

  return {
    url: uri,
    httpHeaders: { Authorization: `Bearer ${token}` },
  };
}

export const SmartDocViewer = memo(function SmartDocViewer({ documents, zoomLevel = 100 }: SmartDocViewerProps) {
  const doc = documents[0];
  const [numPages, setNumPages] = useState<number>(0);
  const [pdfError, setPdfError] = useState<string>('');
  const document_uri = doc?.uri ?? '';
  const token = localStorage.getItem('bidding_token');
  // 保持 file 对象引用稳定，避免 react-pdf 在父组件重渲染时重复加载同一 PDF。
  const pdf_file = useMemo(
    () => build_pdf_file_source(document_uri, token),
    [document_uri, token],
  );

  if (!doc) {
    return <div className="flex items-center justify-center h-full text-slate-400">无文件</div>;
  }

  const isPdf = doc.fileType?.toLowerCase() === 'pdf' || doc.fileName?.toLowerCase().endsWith('.pdf');
  const scale = zoomLevel / 100;

  if (isPdf) {
    const targetWidth = Math.round(850 * scale);

    return (
      <div className="flex-1 w-full h-full bg-[#f3f4f6] overflow-auto custom-scrollbar">
        <Document
          file={pdf_file}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          onLoadError={(error) => setPdfError(error.message)}
          className="h-full w-full flex flex-col"
          loading={<div className="p-10 text-slate-500 text-center w-full font-medium">🚀 正在加载极速 PDF 引擎...</div>}
        >
          {pdfError && <div className="p-10 text-red-500 text-center">PDF 加载失败: {pdfError}</div>}
          {numPages > 0 && (
            <Virtuoso
              style={{ height: '100%', width: '100%' }}
              totalCount={numPages}
              className="custom-scrollbar"
              itemContent={(index) => (
                <div className="flex justify-center my-6 mx-auto overflow-visible">
                  <Page
                    pageNumber={index + 1}
                    renderTextLayer={true}
                    renderAnnotationLayer={true}
                    className="shadow-lg bg-white"
                    width={targetWidth}
                    loading={
                      <div className="h-[1200px] w-[850px] bg-white animate-pulse shadow-md flex flex-col items-center justify-center text-slate-400">
                        <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-200 border-t-blue-600 mb-4"></div>
                        渲染第 {index + 1} 页...
                      </div>
                    }
                  />
                </div>
              )}
            />
          )}
        </Document>
      </div>
    );
  }

  // Word 文档 (Docx) 退回原渲染器，支持动态 zoom 缩放与双向滚动
  const docx_token = localStorage.getItem('bidding_token');
  const requestHeaders: Record<string, string> = docx_token
    ? { Authorization: `Bearer ${docx_token}` }
    : {};

  return (
    <div 
      className="flex-1 w-full bg-[#f3f4f6] h-full overflow-auto custom-scrollbar smart-doc-container"
      style={{
        zoom: scale
      }}
    >
      <style>{`
        /* 核心优化：利用 content-visibility 自动跳过屏幕外 DOCX 节点的重排与绘制 */
        .smart-doc-container .document-container, 
        .smart-doc-container .docx-wrapper > section {
          content-visibility: auto;
          contain-intrinsic-size: 1000px;
        }
      `}</style>
      <DocViewer 
        documents={documents}
        pluginRenderers={RENDERERS}
        requestHeaders={requestHeaders}
        style={{ height: "100%", width: "100%" }}
        config={{
          header: {
            disableHeader: true,
            disableFileName: true,
            retainURLParams: false
          }
        }}
      />
    </div>
  );
});
