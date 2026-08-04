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
  const [isDownloadingSummary, setIsDownloadingSummary] = useState(false);
  const [isExtractingFormat, setIsExtractingFormat] = useState(false);
  const [isFillingFormat, setIsFillingFormat] = useState(false);
  const [downloadNotice, setDownloadNotice] = useState<string | null>(null);
  const [showAuditModal, setShowAuditModal] = useState(false);
  const [auditReportData, setAuditReportData] = useState<any>(null);
  const [isLoadingAudit, setIsLoadingAudit] = useState(false);

  const activeId = documentId || localStorage.getItem('bidding_document_id') || undefined;
  const isAvailable = Boolean(activeId);
  const sections = outline?.outline || [];
  const formatNotes = outline?.formatting;

  const handleExtractBidFormat = async () => {
    const targetDocId = activeId;
    if (!targetDocId || isExtractingFormat) {
      if (!targetDocId) alert("未找到有效的文档 ID，请先上传并解析标书。");
      return;
    }
    
    setIsExtractingFormat(true);
    setDownloadNotice('⚡ 正在提取招标文件中的全套《投标文件格式》并整理导出，请稍候...');

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/bidding/extract-bid-format/${targetDocId}`);

      if (!response.ok) {
        throw new Error(`提取失败 (${response.status})`);
      }

      const modeHeader = response.headers.get('X-Extraction-Mode');
      const modeText = modeHeader === 'native_docx' ? '原生 Word 切片' : 'LLM 结构化重建';

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `投标文件格式模板_${targetDocId.slice(0, 8)}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setDownloadNotice(`✅ 全套《投标文件格式》提取完成（模式: ${modeText}），已导出 Word！`);
      setTimeout(() => setDownloadNotice(null), 5000);
    } catch (err: any) {
      setDownloadNotice(`❌ 提取投标文件格式失败: ${err.message || '未知错误'}`);
      setTimeout(() => setDownloadNotice(null), 5000);
    } finally {
      setIsExtractingFormat(false);
    }
  };

  const handleHumanFillBidFormat = async () => {
    const targetDocId = activeId;
    if (!targetDocId || isFillingFormat) {
      if (!targetDocId) alert("未找到有效的文档 ID，请先上传并解析标书。");
      return;
    }
    
    setIsFillingFormat(true);
    setDownloadNotice('⚡ 拟人化 Agent 正在全文感知空白槽位，自主匹配 SQL 工具查库并原位写盘中...');

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      
      // 1. 调用 POST 获取结构化 Audit 审计数据
      const response = await apiFetch(`${baseUrl}/api/v1/bidding/human-fill-bid-format/${targetDocId}`, {
        method: 'POST'
      });

      if (!response.ok) {
        throw new Error(`拟人化填报失败 (${response.status})`);
      }

      const resData = await response.json();
      const filledCount = resData.total_slots_filled || 0;

      // 2. 调用 GET /download 接口下载最终填报完成的 Word (.docx) 文件
      const dlResponse = await apiFetch(`${baseUrl}/api/v1/bidding/human-fill-bid-format/${targetDocId}/download`);
      if (dlResponse.ok) {
        const blob = await dlResponse.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `【已拟人化智能填报】投标文件格式_${targetDocId.slice(0, 8)}.docx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
      }

      setDownloadNotice(`✅ 拟人化 Agent 成功完成槽位感知与填报（共识别填报 ${filledCount} 个槽位），已自动下载 Word！`);
      setTimeout(() => setDownloadNotice(null), 8000);
    } catch (err: any) {
      setDownloadNotice(`❌ 拟人化 Agent 填报失败: ${err.message || '未知错误'}`);
      setTimeout(() => setDownloadNotice(null), 6000);
    } finally {
      setIsFillingFormat(false);
    }
  };


  const handleFillBidFormat = async () => {
    const targetDocId = activeId;
    if (!targetDocId || isFillingFormat) {
      if (!targetDocId) alert("未找到有效的文档 ID，请先上传并解析标书。");
      return;
    }
    
    setIsFillingFormat(true);
    setDownloadNotice('⚡ BidFillerAgent 正在自主调用 Tools 查取公司资质库、财务控制价与日程，填报生成 Word 中...');

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/bidding/fill-bid-format/${targetDocId}`);

      if (!response.ok) {
        throw new Error(`自动填报失败 (${response.status})`);
      }

      const filledCountHeader = response.headers.get('X-Filled-Fields-Count') || '0';

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `【已智能填报草案】投标文件格式_${targetDocId.slice(0, 8)}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setDownloadNotice(`✅ Agent 成功自动查库填报 ${filledCountHeader} 个待填项，且保留了原处下划线，已导出 Word！`);
      setTimeout(() => setDownloadNotice(null), 6000);
    } catch (err: any) {
      setDownloadNotice(`❌ 自动填报标书失败: ${err.message || '未知错误'}`);
      setTimeout(() => setDownloadNotice(null), 6000);
    } finally {
      setIsFillingFormat(false);
    }
  };

  const handleViewAuditReport = async () => {
    const targetDocId = activeId;
    if (!targetDocId) {
      alert("未找到有效的文档 ID");
      return;
    }

    setIsLoadingAudit(true);
    setShowAuditModal(true);

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/bidding/fill-bid-format/${targetDocId}/audit-report`);
      if (!response.ok) throw new Error("获取核查报告失败");
      const data = await response.json();
      setAuditReportData(data);
    } catch (err: any) {
      alert(`获取核查报告失败: ${err.message}`);
    } finally {
      setIsLoadingAudit(false);
    }
  };

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

  const handleDownloadOpeningSummary = async () => {
    const targetDocId = activeId;
    if (!targetDocId || isDownloadingSummary) {
      if (!targetDocId) alert("未找到有效的文档 ID，请先上传并解析标书。");
      return;
    }
    
    setIsDownloadingSummary(true);
    setDownloadNotice('⚡ 正在直接从原文档定位、提取并原位修改【开标一览表】，请稍候...');

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/analysis/opening-summary/download/${targetDocId}?t=${Date.now()}`);

      if (!response.ok) {
        throw new Error(`生成/下载失败 (${response.status})`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `开标一览表_${targetDocId.slice(0, 8)}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setDownloadNotice('✅ 《开标一览表》提取与修改完成，已自动导出 Word！');
      setTimeout(() => setDownloadNotice(null), 4000);
    } catch (err: any) {
      setDownloadNotice(`❌ 提取开标一览表失败: ${err.message || '未知错误'}`);
      setTimeout(() => setDownloadNotice(null), 5000);
    } finally {
      setIsDownloadingSummary(false);
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
                Word & Agent 引擎就绪
              </span>
            </div>
            <p className="text-slate-400 text-xs mt-0.5">按招标文件标准格式自动解析编排，基于 Agent 自主 Tool Calling 完成全自动填报与反查</p>
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
          <div className="mb-2">
            <div className="flex items-center justify-between font-bold text-slate-800 text-sm mb-1.5">
              <span className="flex items-center gap-2 text-emerald-700 font-extrabold">
                <span>📋</span> 投标文件格式提取引擎
              </span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed font-medium mb-4">
              直接精确定位并提取原始招标文件中的全套《投标文件格式/响应格式》为 Word (.docx) 文档，100% 保持原文排版与表格结构。
            </p>
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
                <span>🚀</span> 终极文件交付与 Agent 智能填报
              </span>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping"></span>
            </div>
            <p className="text-xs text-slate-600 leading-relaxed font-medium mb-4">
              可直接提取原招投标文件格式，或让 Agent 自主调用 Tools 查库填报并保留原下划线排版。
            </p>
          </div>

          <div className="space-y-2.5 pt-3 border-t border-emerald-100/60">
            {/* 核心功能1：提取全套投标文件格式 */}
            <button
              onClick={handleExtractBidFormat}
              disabled={!isAvailable || isRetrying || isExtractingFormat || isFillingFormat}
              className={`w-full py-3 px-5 font-extrabold text-sm rounded-xl shadow-md transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer ${
                isExtractingFormat 
                  ? 'bg-emerald-600 text-white cursor-wait animate-pulse ring-2 ring-emerald-300' 
                  : 'bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white shadow-emerald-200/60 hover:shadow-lg active:scale-98'
              }`}
              title="提取全套《投标文件格式/响应格式》为 Word (.docx)"
            >
              {isExtractingFormat ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span>正在精准切片提取全套格式...</span>
                </>
              ) : (
                <>
                  <span className="text-base">📋</span>
                  <span>提取全套《投标文件格式》(.docx)</span>
                </>
              )}
            </button>

            {/* 核心功能2：拟人化 Agent 自动填报 */}
            <button
              onClick={handleHumanFillBidFormat}
              disabled={!isAvailable || isRetrying || isExtractingFormat || isFillingFormat}
              className={`w-full py-3 px-5 font-extrabold text-sm rounded-xl shadow-md transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer ${
                isFillingFormat 
                  ? 'bg-indigo-600 text-white cursor-wait animate-pulse ring-2 ring-indigo-300' 
                  : 'bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white shadow-indigo-200/60 hover:shadow-lg active:scale-98'
              }`}
              title="拟人化 Agent 自动全文感知识别槽位、查库填报并保留排版"
            >
              {isFillingFormat ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  <span>拟人化 Agent 槽位感知与填报中...</span>
                </>
              ) : (
                <>
                  <span className="text-base">🧠</span>
                  <span>拟人化 Agent 自动填报 (.docx)</span>
                </>
              )}
            </button>

            <div className="text-[11px] text-slate-400 text-center font-medium pt-1">
              ✓ 物理 DOM 感知 + 大模型纯自主识别 + SQL 零幻觉查库填报
            </div>
          </div>
        </div>
      </div>

      {/* Agent 填报核查与对齐追溯 Modal 弹窗 */}
      {showAuditModal && (
        <div 
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowAuditModal(false);
          }}
          className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto"
        >
          <div className="bg-white rounded-3xl max-w-4xl w-full max-h-[85vh] overflow-hidden shadow-2xl border border-purple-100 flex flex-col animate-scale-up my-auto">
            
            {/* Modal Header */}
            <div className="p-5 bg-gradient-to-r from-purple-900 to-indigo-900 text-white flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <span className="p-2 bg-white/10 rounded-xl text-lg">🔍</span>
                <div>
                  <h3 className="font-bold text-base">Agent 标书填报对齐追溯核查报告 (Filling Audit Trail)</h3>
                  <p className="text-purple-200 text-xs mt-0.5">全流程展示 Agent 调用的 Tool 名字、数据库来源表/列及填报数值与样式</p>
                </div>
              </div>
              <button 
                type="button"
                onClick={() => setShowAuditModal(false)}
                className="w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 active:bg-white/30 text-white font-bold flex items-center justify-center transition-colors cursor-pointer text-base"
                title="关闭弹窗"
              >
                ✕
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto custom-scrollbar flex-1 bg-slate-50/50">
              {isLoadingAudit ? (
                <div className="py-16 text-center">
                  <div className="animate-spin w-8 h-8 border-4 border-purple-600 border-t-transparent rounded-full mx-auto mb-3"></div>
                  <p className="text-slate-600 text-sm font-semibold">正在生成与检索 Agent 填报对齐追溯明细...</p>
                </div>
              ) : auditReportData ? (
                <div className="space-y-4">
                  <div className="p-3 bg-purple-50 border border-purple-200 rounded-xl flex items-center justify-between text-xs text-purple-900 font-medium">
                    <span>{auditReportData.summary_note || '对齐任务处理完成'}</span>
                    <span className="font-bold bg-purple-200 text-purple-800 px-2.5 py-0.5 rounded-full">
                      已核查待填项: {auditReportData.total_fields_count || 0} 个
                    </span>
                  </div>

                  <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white shadow-xs">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="bg-slate-100/80 text-slate-700 font-bold border-b border-slate-200">
                          <th className="p-3">待填字段 / 位置</th>
                          <th className="p-3">Agent 调用的 Tool</th>
                          <th className="p-3">数据库来源表 & 字段</th>
                          <th className="p-3">数据库原始值</th>
                          <th className="p-3">填入 Word 的最终文本</th>
                          <th className="p-3">Agent 思考理由 (Thought)</th>
                          <th className="p-3 text-center">下划线</th>
                          <th className="p-3 text-center">状态</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 text-slate-700">
                        {auditReportData.audit_items && auditReportData.audit_items.length > 0 ? (
                          auditReportData.audit_items.map((item: any, idx: number) => (
                            <tr key={idx} className="hover:bg-purple-50/30 transition-colors">
                              <td className="p-3 font-semibold text-slate-900">{item.target_field}</td>
                              <td className="p-3 font-mono text-purple-700 bg-purple-50/50 px-2 py-0.5 rounded text-[11px] border border-purple-100">
                                {item.tool_called}
                              </td>
                              <td className="p-3 font-mono text-slate-600 text-[11px]">{item.data_source_table}</td>
                              <td className="p-3 text-slate-600">{item.db_raw_value}</td>
                              <td className="p-3 font-bold text-emerald-800 bg-emerald-50/40 px-2 py-1 rounded">
                                {item.final_filled_value}
                              </td>
                              <td className="p-3 text-slate-500 italic text-[11px] max-w-[180px] truncate" title={item.agent_reasoning}>
                                {item.agent_reasoning || "结合上下文自动推演"}
                              </td>
                              <td className="p-3 text-center">
                                {item.has_underline ? (
                                  <span className="px-2 py-0.5 bg-blue-50 text-blue-700 font-bold rounded text-[10px] border border-blue-200">
                                    保留下划线
                                  </span>
                                ) : (
                                  <span className="px-2 py-0.5 bg-slate-100 text-slate-500 rounded text-[10px]">
                                    无下划线
                                  </span>
                                )}
                              </td>
                              <td className="p-3 text-center">
                                <span className="px-2 py-0.5 bg-emerald-100 text-emerald-800 font-bold rounded-full text-[10px]">
                                  {item.alignment_status}
                                </span>
                              </td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td colSpan={8} className="p-6 text-center text-slate-400">
                              未检索到待填项对齐记录
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <div className="text-center py-10 text-slate-400 text-sm">暂无核查报告数据</div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="p-4 bg-slate-100 border-t border-slate-200 flex justify-end shrink-0">
              <button
                type="button"
                onClick={() => setShowAuditModal(false)}
                className="px-6 py-2.5 text-xs font-bold bg-slate-800 hover:bg-slate-900 active:bg-slate-950 text-white rounded-xl shadow-xs transition-all cursor-pointer"
              >
                关闭核查报告
              </button>
            </div>

          </div>
        </div>
      )}

    </div>
  );
};

