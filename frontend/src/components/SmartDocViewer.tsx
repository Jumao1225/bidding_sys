import React, { useState } from 'react';
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
}

export function SmartDocViewer({ documents }: SmartDocViewerProps) {
  const doc = documents[0];
  const [numPages, setNumPages] = useState<number>(0);
  const [pdfError, setPdfError] = useState<string>('');

  if (!doc) {
    return <div className="flex items-center justify-center h-full text-slate-400">无文件</div>;
  }

  const isPdf = doc.fileType?.toLowerCase() === 'pdf' || doc.fileName?.toLowerCase().endsWith('.pdf');

  if (isPdf) {
    return (
      <div className="flex-1 w-full h-full bg-[#f3f4f6]">
        <Document
          file={doc.uri}
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
                <div className="flex justify-center my-6 mx-auto overflow-hidden">
                  <Page
                    pageNumber={index + 1}
                    renderTextLayer={true}
                    renderAnnotationLayer={true}
                    className="shadow-lg bg-white"
                    width={850}
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

  // Word 文档 (Docx) 退回原渲染器，但加上 content-visibility 优化
  return (
    <div className="flex-1 w-full bg-[#f3f4f6] h-full overflow-y-auto custom-scrollbar smart-doc-container">
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
        pluginRenderers={[LocalDocxRenderer, ...DocViewerRenderers]}
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
}
