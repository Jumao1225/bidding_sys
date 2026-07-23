import React, { useState } from 'react';
import { apiFetch } from '../utils/api';

interface DraftCardProps {
  documentId?: string;
  outline?: any;
  draftPath?: string;
  onReextract: () => void;
  isRetrying?: boolean;
}

export const DraftCard: React.FC<DraftCardProps> = ({
  documentId,
  outline,
  draftPath,
  onReextract,
  isRetrying = false
}) => {
  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState<string | null>(null);

  const activeId = documentId || localStorage.getItem('bidding_document_id') || undefined;
  const isAvailable = Boolean(activeId);
  const sections = outline?.outline || [];
  const formatNotes = outline?.formatting;

  const handleDownload = async () => {
    const targetDocId = activeId;
    if (!targetDocId || isDownloading) {
      if (!targetDocId) alert("未找到有效的文档 ID，请先上传并解析标书。");
      return;
    }
    
    setIsDownloading(true);
    setDownloadNotice('⚡ 正在根据招标文件格式实时编排与组装 Word 草稿，请稍候...');

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/analysis/draft/download/${targetDocId}`);

      if (!response.ok) {
        throw new Error(`下载失败 (${response.status})`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `投标书草稿_${targetDocId.slice(0, 8)}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setDownloadNotice('✅ 草稿已生成，已触发浏览器自动下载！');
      setTimeout(() => setDownloadNotice(null), 4000);
    } catch (err: any) {
      setDownloadNotice(`❌ 下载草稿失败: ${err.message || '未知错误'}`);
      setTimeout(() => setDownloadNotice(null), 5000);
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div className="bg-white/80 backdrop-blur-sm p-6 rounded-3xl shadow-sm border border-indigo-100 relative overflow-hidden group hover:shadow-md transition-all w-full">
      <div className="absolute top-0 right-0 w-64 h-64 bg-indigo-500/5 rounded-full blur-3xl -mr-20 -mt-20 group-hover:scale-110 transition-transform duration-500 pointer-events-none"></div>

      {/* Header */}
      <div className="flex items-center justify-between mb-5 border-b border-indigo-100/60 pb-4">
        <div className="flex items-center gap-3">
          <span className="p-2.5 bg-indigo-100 text-indigo-600 rounded-2xl text-xl font-bold shadow-sm">📄</span>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-slate-800 font-bold text-lg">投标书草稿生成与交付引擎</h3>
              <span className="px-2.5 py-0.5 bg-indigo-50 text-indigo-700 text-xs font-bold rounded-full border border-indigo-200">
                Word 引擎就绪
              </span>
            </div>
            <p className="text-slate-400 text-xs mt-0.5">按招标文件标准格式自动解析编排，生成专业级 .docx 投标书文件</p>
          </div>
        </div>

        <button
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            onReextract();
          }}
          disabled={isRetrying || isDownloading}
          className="px-4 py-2 text-xs font-bold text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 active:bg-indigo-200 border border-indigo-200/80 rounded-xl transition-all flex items-center gap-1.5 shadow-sm hover:shadow active:scale-95 disabled:opacity-40 cursor-pointer"
          title="重新触发 Writer Agent 起草生成"
        >
          <span className={isRetrying ? "animate-spin text-sm" : "text-sm"}>↻</span>
          <span>{isRetrying ? "重新编排中..." : "重新起草标书"}</span>
        </button>
      </div>

      {/* Dynamic Download & Re-extract Notice */}
      {isRetrying && (
        <div className="mb-4 p-3 bg-indigo-50/90 text-indigo-700 border border-indigo-200 rounded-xl text-xs font-medium flex items-center gap-2 animate-pulse">
          <span className="animate-spin text-indigo-600">↻</span>
          <span>⚡ Writer Agent 正在重新检索、分析并动态起草最新投标书，请稍候...</span>
        </div>
      )}

      {downloadNotice && !isRetrying && (
        <div className={`mb-4 p-3 rounded-xl text-xs font-medium border flex items-center gap-2 animate-fade-in transition-all ${
          downloadNotice.startsWith('⚡')
            ? 'bg-indigo-50 text-indigo-700 border-indigo-200 animate-pulse'
            : downloadNotice.startsWith('✅')
              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
              : 'bg-rose-50 text-rose-700 border-rose-200'
        }`}>
          <span>{downloadNotice}</span>
        </div>
      )}

      {/* Main Body: 2-Column Full Width Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
        
        {/* Left Side (8/12): Outline Preview & Structure Badges */}
        <div className="lg:col-span-8 bg-slate-50/70 rounded-2xl p-4 border border-slate-100 flex flex-col justify-between">
          <div className="flex items-center justify-between text-xs font-bold text-slate-600 mb-3 pb-2 border-b border-slate-200/60">
            <span className="flex items-center gap-1.5">
              <span>📑</span> 自动起草大纲目录 ({sections.length > 0 ? `${sections.length} 个章节` : '准备中'})
            </span>
            {outline?.source_chapter && (
              <span className="text-indigo-600 text-[11px] bg-indigo-50 px-2.5 py-0.5 rounded-full border border-indigo-100 font-medium">
                格式来源: {outline.source_chapter}
              </span>
            )}
          </div>

          {sections.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-40 overflow-y-auto pr-1 custom-scrollbar">
              {sections.map((item: any, idx: number) => (
                <div key={idx} className="flex items-center justify-between text-xs text-slate-700 bg-white p-2.5 rounded-xl border border-slate-100 shadow-2xs hover:border-indigo-100 transition-colors">
                  <span className="font-semibold text-slate-800 truncate max-w-[200px]" title={item.title}>
                    {item.number ? `${item.number} ` : ''}{item.title}
                  </span>
                  {item.mapping_hint && item.mapping_hint !== '_unknown' ? (
                    <span className="text-[10px] bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-md font-mono shrink-0 border border-emerald-100">
                      {item.mapping_hint}
                    </span>
                  ) : (
                    <span className="text-[10px] bg-slate-100 text-slate-400 px-1.5 py-0.5 rounded shrink-0">
                      内容已就绪
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-6">
              <p className="text-slate-600 text-sm font-semibold">
                {isAvailable ? "草稿已生成，包含专业完整的招投标通用书体结构" : "暂无草稿，请先上传标书文件"}
              </p>
              {formatNotes && (
                <p className="text-slate-400 text-xs mt-1.5">
                  格式规格: 宋体/黑体正文 | 页眉页脚自动克隆排版
                </p>
              )}
            </div>
          )}

          <div className="mt-3 pt-2 border-t border-slate-200/60 flex items-center justify-between text-xs text-slate-400">
            <span>克隆排版模式: 原文档样式克隆 + 智能图表填充</span>
            {formatNotes && (
              <span className="font-mono text-slate-500">
                {formatNotes.body_font || '宋体'} / {formatNotes.body_font_size || '小四'}
              </span>
            )}
          </div>
        </div>

        {/* Right Side (4/12): Primary Action Card */}
        <div className="lg:col-span-4 bg-gradient-to-br from-indigo-50/90 via-purple-50/40 to-slate-50 p-5 rounded-2xl border border-indigo-100 flex flex-col justify-between shadow-xs">
          <div>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-bold text-indigo-900 uppercase tracking-wider flex items-center gap-1">
                <span>🚀</span> 终极文件交付
              </span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed font-medium mb-4">
              已将提取的资质数据、工程算量、财务限价与响应条款全量注入 Word 组装引擎，点击一键导出。
            </p>
          </div>

          <div className="space-y-3 pt-3 border-t border-indigo-100/60">
            <button
              onClick={handleDownload}
              disabled={!isAvailable || isRetrying || isDownloading}
              className={`w-full py-3 px-4 font-bold text-sm rounded-xl shadow-sm transition-all flex items-center justify-center gap-2.5 disabled:opacity-50 disabled:cursor-not-allowed ${
                isDownloading 
                  ? 'bg-indigo-500 text-white cursor-wait animate-pulse ring-2 ring-indigo-300 ring-offset-1' 
                  : 'bg-indigo-600 hover:bg-indigo-700 hover:shadow-indigo-200 hover:shadow-lg text-white active:scale-98'
              }`}
            >
              {isDownloading ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span>正在编排组装 Word...</span>
                </>
              ) : (
                <>
                  <span className="text-base">📥</span>
                  <span>一键导出投标书草稿 (.docx)</span>
                </>
              )}
            </button>

            <div className="text-[11px] text-slate-400 text-center font-medium">
              {draftPath ? "✓ 支持使用 Word / WPS 随时编辑调整" : isAvailable ? "生成时间: 实时动态合成" : "等待分析落盘"}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
