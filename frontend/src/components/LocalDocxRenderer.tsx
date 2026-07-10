import React, { useEffect, useRef, useState } from 'react';
import type { DocRenderer } from "@cyntler/react-doc-viewer";
import { renderAsync } from 'docx-preview';

export const LocalDocxRenderer: DocRenderer = ({ mainState: { currentDocument } }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentDocument || !containerRef.current) return;

    let isMounted = true;
    setLoading(true);
    setError(null);

    // 获取文件流
    fetch(currentDocument.uri)
      .then(res => {
        if (!res.ok) throw new Error("获取文件失败");
        return res.blob();
      })
      .then(blob => {
        if (!isMounted || !containerRef.current) return;
        // docx-preview 本地渲染
        return renderAsync(blob, containerRef.current, null, {
          className: 'docx-preview-container',
          inWrapper: true,
          ignoreWidth: false,
          ignoreHeight: false,
          ignoreFonts: false,
          breakPages: true
        });
      })
      .then(() => {
        if (isMounted) setLoading(false);
      })
      .catch(err => {
        console.error("渲染 DOCX 失败:", err);
        if (isMounted) {
          setError("本地渲染 DOCX 文件失败");
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [currentDocument]);

  return (
    <div className="relative w-full h-full bg-[#f3f4f6] overflow-hidden rounded-xl">
      {loading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/80 backdrop-blur-sm z-10">
          <div className="animate-spin rounded-full h-10 w-10 border-4 border-blue-100 border-t-blue-600 mb-3"></div>
          <p className="text-slate-500 font-bold text-sm">正在本地高速渲染文档...</p>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white z-10 text-rose-500">
          <span className="text-4xl mb-2">⚠️</span>
          <p className="font-bold">{error}</p>
        </div>
      )}
      {/* docx-preview 会向这个 div 中注入渲染内容 */}
      <div 
        ref={containerRef} 
        className="w-full h-full overflow-auto custom-scrollbar" 
      />
    </div>
  );
};

// 声明支持的文件类型和权重（高权重可以覆盖默认的在线预览插件）
LocalDocxRenderer.fileTypes = [
  "docx", 
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
];
LocalDocxRenderer.weight = 10;
