import React, { useState, useMemo, useRef, useEffect } from 'react';
import { apiFetch } from '../utils/api';
import { Upload, X, FileText, CheckCircle2, ChevronRight, Loader2 } from 'lucide-react';
import { SmartDocViewer } from './SmartDocViewer';
import { motion, AnimatePresence } from 'framer-motion';
import { Group, Panel, Separator } from 'react-resizable-panels';
import { Virtuoso } from 'react-virtuoso';

export interface UploadBoxProps {
  onTerminalMessage?: (msg: { id: string, type: 'info' | 'tool_call' | 'success' | 'error', content: string }) => void;
  onAnalysisSuccess?: (result: any) => void;
  onAnalyzingChange?: (isAnalyzing: boolean) => void;
  initialResult?: any;
  initialTaskId?: string | null;
  onSupervisorUpdate?: (decision: any) => void;
  onWorkerStatusChange?: (worker: string, status: string, summary?: string, documentId?: string) => void;
}

interface AnalysisDocumentReference {
  document_id?: string;
  id?: string;
}

/**
 * 优先使用持久化文档 ID，避免任务临时 ID 在原文件预览接口中无法定位文件。
 */
export function get_original_file_preview_id(
  task_id: string | null | undefined,
  result: AnalysisDocumentReference | null | undefined,
  initial_task_id: string | null | undefined,
): string | null {
  return result?.document_id || result?.id || task_id || initial_task_id || null;
}

// 高亮组件
const HighlightText = React.memo(({ text, resultData, targetQuote }: { text: string, resultData: any, targetQuote?: string | null }) => {
  const virtuosoRef = useRef<any>(null);
  const paragraphs = useMemo(() => text.split('\n'), [text]);

  const highlightList = useMemo(() => {
    const list: any[] = [];
    if (resultData?.qualifications_analysis?.items) {
      resultData.qualifications_analysis.items.forEach((item: any) => {
        if (item.exact_quote) list.push({ quote: item.exact_quote, type: item.status, obj: item });
      });
    }
    if (resultData?.risks_analysis) {
      resultData.risks_analysis.forEach((risk: any) => {
        if (risk.exact_quote) list.push({ quote: risk.exact_quote, type: risk.severity, obj: risk });
      });
    }
    return list;
  }, [resultData]);

  // 监听 targetQuote 变动，自动计算目标段落索引并平滑滚动定位
  useEffect(() => {
    if (!targetQuote || !text || paragraphs.length === 0) return;
    const cleanQuote = targetQuote.trim();
    if (!cleanQuote) return;

    let targetIdx = paragraphs.findIndex(p => p.includes(cleanQuote));
    if (targetIdx === -1 && cleanQuote.length > 5) {
      const subQuote = cleanQuote.slice(0, 8);
      targetIdx = paragraphs.findIndex(p => p.includes(subQuote));
    }

    if (targetIdx !== -1 && virtuosoRef.current) {
      virtuosoRef.current.scrollToIndex({
        index: targetIdx,
        align: 'center',
        behavior: 'smooth'
      });
    }
  }, [targetQuote, paragraphs, text]);

  const renderParagraph = (index: number, pText: string) => {
    if (!pText.trim()) return <div className="h-4" />;
    
    const indices: any[] = [];
    highlightList.forEach(h => {
      if (!h.quote) return;
      let idx = pText.indexOf(h.quote);
      while (idx !== -1) {
        indices.push({ start: idx, end: idx + h.quote.length, ...h });
        idx = pText.indexOf(h.quote, idx + h.quote.length);
      }
    });
    indices.sort((a, b) => a.start - b.start);

    const nodes = [];
    let lastIndex = 0;

    indices.forEach((h, i) => {
      if (h.start < lastIndex) return; // skip overlaps

      nodes.push(<span key={`text-${i}`} className="transition-colors duration-300">{pText.substring(lastIndex, h.start)}</span>);

      let colorClass = 'bg-gray-200';
      if (h.type === '做不到' || h.type === '高') colorClass = 'bg-red-200 text-red-900 border-b-2 border-red-500 shadow-sm';
      else if (h.type === '努力可做到' || h.type === '中') colorClass = 'bg-orange-200 text-orange-900 border-b-2 border-orange-500 shadow-sm';
      else if (h.type === '可以做到' || h.type === '低') colorClass = 'bg-green-200 text-green-900 border-b-2 border-green-500 shadow-sm';

      const isSelected = targetQuote && h.quote && (h.quote.includes(targetQuote) || targetQuote.includes(h.quote));
      const activeClass = isSelected ? 'ring-4 ring-blue-500 ring-offset-2 scale-105 shadow-xl font-extrabold animate-pulse' : '';

      nodes.push(
        <mark key={`mark-${i}`} className={`${colorClass} ${activeClass} px-1.5 py-0.5 rounded cursor-help hover:ring-2 hover:ring-offset-1 transition-all duration-300`} title={h.obj.reason || h.obj.description}>
          {pText.substring(h.start, h.end)}
        </mark>
      );
      lastIndex = h.end;
    });

    nodes.push(<span key="text-end" className="transition-colors duration-300">{pText.substring(lastIndex)}</span>);

    return <div className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-700 mb-2">{nodes}</div>;
  };

  return (
    <Virtuoso 
      ref={virtuosoRef}
      style={{ height: '100%', width: '100%' }}
      data={paragraphs}
      itemContent={renderParagraph}
      className="custom-scrollbar"
    />
  );
});

export function UploadBox({ onTerminalMessage, onAnalysisSuccess, onAnalyzingChange, initialResult = null, initialTaskId = null, onSupervisorUpdate, onWorkerStatusChange }: UploadBoxProps = {}) {
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [isAnalyzing, setIsAnalyzingInternal] = useState(false);

  const setIsAnalyzing = (val: boolean) => {
    setIsAnalyzingInternal(val);
    if (onAnalyzingChange) onAnalyzingChange(val);
  };
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [embeddingInfo, setEmbeddingInfo] = useState<{
    percent: number;
    processed_count: number;
    total_texts: number;
    current_batch: number;
    total_batches: number;
  } | null>(null);
  
  const [result, setResult] = useState<any>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  
  // 视图与布局状态 (从 localStorage 初始化)
  const [viewMode, setViewMode] = useState<'text' | 'original'>(() => 
    (localStorage.getItem('bidding_view_mode') as 'text'|'original') || 'original'
  );
  const [activeTab, setActiveTab] = useState<'qual' | 'risk'>(() => 
    (localStorage.getItem('bidding_active_tab') as 'qual'|'risk') || 'qual'
  );
  const [splitRatio, setSplitRatio] = useState(() => 
    Number(localStorage.getItem('bidding_split_ratio')) || 60
  ); 
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [targetQuote, setTargetQuote] = useState<string | null>(null);
  const [zoomLevel, setZoomLevel] = useState<number>(100);

  const handleZoomIn = () => setZoomLevel(prev => Math.min(prev + 15, 200));
  const handleZoomOut = () => setZoomLevel(prev => Math.max(prev - 15, 50));
  const handleZoomReset = () => setZoomLevel(100);

  const handleCardClick = (exactQuote?: string, fallbackText?: string) => {
    const quoteToUse = exactQuote || fallbackText;
    if (!quoteToUse) return;
    
    setTargetQuote(quoteToUse);

    // 针对 原文件预览 模式：采用多词切片重合度打分算法（Keyword Overlap Scoring），完美匹配“联合投标”与“联合体投标”等微小文字差异
    if (viewMode === 'original') {
      setTimeout(() => {
        const cleanQuote = quoteToUse.trim();
        if (!cleanQuote) return;
        
        // 1. 获取所有精细的段落 <p> 与文本 <span> 节点
        const candidates = Array.from(document.querySelectorAll(
          '.smart-doc-container .docx-wrapper p, .smart-doc-container p, .react-pdf__Page__textContent span'
        )) as HTMLElement[];

        // 2. 提取目标句中的核心关键词列表（按 2-3 字滑窗切词）
        const rawKeywords = cleanQuote.replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, '');
        const keywords: string[] = [];
        for (let i = 0; i < rawKeywords.length - 1; i += 2) {
          keywords.push(rawKeywords.slice(i, i + 3));
        }

        // 3. 计算每个 DOM 节点的重合度得分
        let bestScore = 0;
        let bestElem: HTMLElement | null = null;

        candidates.forEach(el => {
          const txt = (el.textContent || '').trim();
          if (!txt || txt.length > 500) return; // 排除包围大容器

          let score = 0;

          // 字符串完全包含加高分
          if (txt.includes(cleanQuote)) {
            score += 100;
          }

          // 核心关键词匹配累加得分
          keywords.forEach(kw => {
            if (kw && txt.includes(kw)) {
              score += 20;
            }
          });

          // 业务核心词汇（如“联合”、“投标”、“不允许”）加权，完美支持“联合投标”对齐“联合体投标”
          if (cleanQuote.includes("联合") && txt.includes("联合")) score += 40;
          if (cleanQuote.includes("不允许") && (txt.includes("不允许") || txt.includes("不接受") || txt.includes("不得"))) score += 30;

          if (score > bestScore) {
            bestScore = score;
            bestElem = el;
          }
        });

        if (bestElem && bestScore >= 20) {
          bestElem.scrollIntoView({ behavior: 'smooth', block: 'center' });
          bestElem.classList.add('ring-4', 'ring-blue-500', 'ring-offset-4', 'bg-amber-200/90', 'text-slate-900', 'rounded-lg', 'p-1', 'transition-all', 'duration-500', 'animate-pulse', 'z-20', 'relative');
          setTimeout(() => {
            bestElem?.classList.remove('ring-4', 'ring-blue-500', 'ring-offset-4', 'bg-amber-200/90', 'text-slate-900', 'rounded-lg', 'p-1', 'animate-pulse', 'z-20', 'relative');
          }, 4000);
        }
      }, 150);
    }
  };

  // 不再将 result, taskId, fileName 写入 localStorage，一切依赖历史记录或单次会话
  
  // 同步外部传入的历史数据
  useEffect(() => {
    if (initialResult) {
      setResult(initialResult);
    }
    if (initialTaskId) {
      setTaskId(initialTaskId);
    }
  }, [initialResult, initialTaskId]);

  useEffect(() => {
    localStorage.setItem('bidding_view_mode', viewMode);
    localStorage.setItem('bidding_active_tab', activeTab);
    localStorage.setItem('bidding_split_ratio', splitRatio.toString());
  }, [viewMode, activeTab, splitRatio]);

  // manual split resizing logic replaced by react-resizable-panels

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
      setResult(null); // 上传新文件清空结果
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
      setResult(null);
    }
  };

  const handleAnalyze = async () => {
    if (!file) return;

    setIsAnalyzing(true);
    if (onAnalyzingChange) onAnalyzingChange(true);
    setProgress(0);
    setStatusText("准备上传...");
    setResult(null);

    const baseUrl = import.meta.env.VITE_API_BASE_URL || "";

    // 获取真实公司资质数据（无资质时保持为空，严禁使用虚假硬编码数据以防幻觉）
    let realCompanyQuals = "";
    try {
      const qualRes = await apiFetch(`${baseUrl}/api/v1/qualifications/`, {
        headers: { 'X-Tenant-ID': 'default-tenant' }
      });
      if (qualRes.ok) {
        const qualJson = await qualRes.json();
        if (qualJson.code === 200 && qualJson.data && qualJson.data.length > 0) {
          const qualsStr = qualJson.data.map((q: any) => {
            let s = q.name;
            if (q.level && q.level !== '无') s += `(${q.level})`;
            if (q.expiry_date) s += `[有效期至:${q.expiry_date}]`;
            return s;
          }).join("、");
          realCompanyQuals = `本公司已具备以下资质证书：${qualsStr}。`;
          const companyName = qualJson.data.find((q:any) => q.company_name)?.company_name;
          if (companyName) {
             realCompanyQuals = `公司名称：${companyName}。` + realCompanyQuals;
          }
        }
      }
    } catch (err) {
      console.error("Failed to fetch qualifications", err);
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("company_quals", realCompanyQuals);

    try {
      const response = await apiFetch(`${baseUrl}/api/v1/analysis/upload-and-analyze`, {
        method: "POST",
        body: formData,
      });

      const data = await response.json();
      if (data.code === 200 && data.data.task_id) {
        const taskId = data.data.task_id;
        setTaskId(taskId);
        setFileName(file.name);
        setStatusText("任务已提交，排队中...");

        // 立刻持久化最新解析的 document_id，保证切换页面再切回时能恢复解析状态与结果
        localStorage.setItem('bidding_document_id', taskId);
        window.dispatchEvent(new Event('bidding_document_changed'));
        
        // 开启 SSE 监听
        const eventSource = new EventSource(`${baseUrl}/api/v1/sse/progress/${taskId}`);
        
        eventSource.onmessage = (event) => {
          try {
            const msgData = JSON.parse(event.data);
            if (msgData.status) setStatusText(msgData.status);
            if (msgData.progress) setProgress(msgData.progress);
            
            if (msgData.agent_log) {
              const log = msgData.agent_log;
              if (log.document_id) {
                localStorage.setItem('bidding_document_id', log.document_id);
              }
              if (log.type === 'embedding_progress') {
                setEmbeddingInfo({
                  percent: log.percent,
                  processed_count: log.processed_count,
                  total_texts: log.total_texts,
                  current_batch: log.current_batch,
                  total_batches: log.total_batches
                });
                setStatusText(`🧮 BGE-M3 向量化计算中 (${log.percent}%)`);
              }

              if (onTerminalMessage) {
                onTerminalMessage({
                  id: Date.now().toString() + Math.random().toString(),
                  ...log
                });
              }
              
              if (log.type === 'supervisor_decision' && onSupervisorUpdate) {
                onSupervisorUpdate({
                  currentDecision: log.reasoning,
                  nextWorker: log.worker,
                  completedSteps: log.completed_steps,
                  retryCounts: log.retry_counts,
                });
              }
              
              if (log.type === 'worker_start' && onWorkerStatusChange) {
                if (Array.isArray(log.worker)) {
                  log.worker.forEach((w: string) => onWorkerStatusChange(w, 'running'));
                } else {
                  onWorkerStatusChange(log.worker, 'running');
                }
              }
              
              if (log.type === 'worker_complete' && onWorkerStatusChange) {
                onWorkerStatusChange(log.worker, log.status === 'success' ? 'success' : 'failed', log.summary, log.document_id);
              }
            }
            if (msgData.progress === 100) {
              if (msgData.result && !msgData.result.error) {
                setResult(msgData.result);
                // 持久化 document_id，供 ChatPanel 聊天接口使用
                if (msgData.result.document_id) {
                  localStorage.setItem('bidding_document_id', msgData.result.document_id);
                }
                if (onAnalysisSuccess) onAnalysisSuccess(msgData.result);
              } else if (msgData.result && msgData.result.error) {
                alert("解析出错: " + msgData.result.error);
              }
              eventSource.close();
              setTimeout(() => setIsAnalyzing(false), 500); // 延迟关闭以展示 100% 状态
            }
          } catch (e) {
            console.error("SSE parsing error", e);
          }
        };

        eventSource.onerror = (error) => {
          console.error("EventSource failed:", error);
          eventSource.close();
          setIsAnalyzing(false);
          alert("进度连接中断，请重试。");
        };

      } else {
        alert("解析失败: " + data.message);
        setIsAnalyzing(false);
      }
    } catch (error) {
      console.error("解析失败:", error);
      alert("解析请求失败，请检查后端服务及跨域设置。");
      setIsAnalyzing(false);
    }
  };


  const handleClear = () => {
    setResult(null);
    setFile(null);
    setTaskId(null);
    setFileName(null);
    localStorage.removeItem('bidding_analysis_result');
    localStorage.removeItem('bidding_task_id');
    localStorage.removeItem('bidding_file_name');
    localStorage.removeItem('bidding_document_id');
    // 触发全局事件通知 ChatPanel 刷新状态
    window.dispatchEvent(new Event('bidding_document_changed'));
    if (onAnalysisSuccess) onAnalysisSuccess(null);
  };

  const activeDocOrTaskId = get_original_file_preview_id(taskId, result, initialTaskId);

  const viewerDocuments = useMemo(() => {
    if (!activeDocOrTaskId) return [];
    
    // 如果是上传成功后的单次会话，fileName 有值
    // 如果是恢复的历史记录，result 中会带回 filename
    const rawFileName = fileName || (result && result.filename) || "document.docx";
    let actualFileName = rawFileName;
    let fileType = rawFileName.split('.').pop()?.toLowerCase() || "docx";

    // 旧版 .doc 格式由后端接口自动交付转换为 .docx 的二进制流，此处前端归一化为 docx 以便使用 docx-preview 本地渲染
    if (fileType === "doc") {
      fileType = "docx";
      if (actualFileName.toLowerCase().endsWith(".doc")) {
        actualFileName = actualFileName.slice(0, -4) + ".docx";
      }
    }

    return [{ 
      id: activeDocOrTaskId,
      uri: `${import.meta.env.VITE_API_BASE_URL || ""}/api/v1/analysis/download/${activeDocOrTaskId}`,
      fileName: actualFileName,
      fileType: fileType
    }];
  }, [activeDocOrTaskId, fileName, result]);

  const leftPanelContent = useMemo(() => {
    return (
      <div className="flex flex-col h-full border border-slate-200 rounded-2xl overflow-hidden bg-slate-50 shadow-sm transition-all duration-300 hover:shadow-md">
        <div className="bg-white px-5 py-4 border-b border-slate-200 font-bold text-slate-800 flex justify-between items-center">
          <div className="flex items-center gap-4">
            <span className="text-blue-500">🔍</span>
            <span>原文对照区</span>
            {/* 切换按钮 */}
            <div className="flex bg-slate-100 p-1 rounded-lg">
              <button onClick={() => setViewMode('text')} className={viewMode === 'text' ? 'bg-white shadow-sm px-3 py-1 rounded text-blue-600 text-sm transition-all' : 'px-3 py-1 text-slate-500 text-sm hover:text-slate-700 transition-all'}>提取文本</button>
              <button onClick={() => setViewMode('original')} className={viewMode === 'original' ? 'bg-white shadow-sm px-3 py-1 rounded text-blue-600 text-sm transition-all' : 'px-3 py-1 text-slate-500 text-sm hover:text-slate-700 transition-all'}>原文件预览</button>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* 原文件预览 专属 缩放比例控制工具 */}
            {viewMode === 'original' && (
              <div className="flex items-center bg-slate-100 p-1 rounded-lg gap-1 border border-slate-200 shadow-2xs">
                <button 
                  onClick={handleZoomOut}
                  className="px-2 py-0.5 text-xs font-bold text-slate-600 hover:bg-white hover:text-blue-600 rounded transition-all shadow-2xs cursor-pointer select-none"
                  title="缩小原文件 (Zoom Out)"
                >
                  -
                </button>
                <span 
                  onClick={handleZoomReset}
                  className="px-2 py-0.5 text-xs font-semibold text-slate-600 hover:text-blue-600 cursor-pointer min-w-[42px] text-center select-none"
                  title="点击重置为 100% 原始大小"
                >
                  {zoomLevel}%
                </span>
                <button 
                  onClick={handleZoomIn}
                  className="px-2 py-0.5 text-xs font-bold text-slate-600 hover:bg-white hover:text-blue-600 rounded transition-all shadow-2xs cursor-pointer select-none"
                  title="放大原文件 (Zoom In)"
                >
                  +
                </button>
              </div>
            )}

            <span className="text-xs text-slate-400 font-medium bg-slate-100 px-2 py-1 rounded-md">悬浮高亮查看说明</span>
            
            {/* 全屏切换按钮 */}
            <button 
              onClick={() => setIsFullscreen(!isFullscreen)}
              className="p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
              title={isFullscreen ? "退出沉浸模式" : "沉浸阅读模式"}
            >
              {isFullscreen ? (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"></path></svg>
              )}
            </button>
          </div>
        </div>
        <div className={`flex-1 flex flex-col gpu-layer ${viewMode === 'text' ? 'overflow-y-auto custom-scrollbar p-6' : 'overflow-hidden'}`}>
          {viewMode === 'text' ? (
            <HighlightText text={result?.extracted_text || ""} resultData={result} targetQuote={targetQuote} />
          ) : (
            activeDocOrTaskId ? (
              <div className="flex-1 w-full bg-[#f3f4f6] h-full">
                <SmartDocViewer documents={viewerDocuments} zoomLevel={zoomLevel} />
              </div>
            ) : (
              <div className="flex items-center justify-center h-full text-slate-400">正在加载原文件...</div>
            )
          )}
        </div>
      </div>
    );
  }, [viewMode, activeDocOrTaskId, viewerDocuments, result, isFullscreen, targetQuote, zoomLevel]);

  return (
    <motion.div 
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="bg-white/80 backdrop-blur-sm p-8 rounded-3xl shadow-sm border border-emerald-100 relative overflow-hidden group hover:shadow-md transition-all h-full flex flex-col"
    >
      <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:scale-110 transition-transform duration-500"></div>
      
      {/* Header section with optional Clear button */}
      <div className="relative z-10 flex justify-between items-start">
        <div className="flex items-center gap-3 mb-2">
          <div className="w-12 h-12 bg-blue-100 rounded-2xl flex items-center justify-center shadow-inner group-hover:scale-110 transition-transform">
            <span className="text-2xl">🤖</span>
          </div>
          <div>
            <h2 className="text-xl font-bold text-slate-800 tracking-tight">招标文件智能解析</h2>
            <p className="text-sm text-slate-500">v2.4 Agentic Flow</p>
          </div>
        </div>
        
        {/* 重新上传按钮 */}
        {result && !isAnalyzing && (
          <button 
            onClick={handleClear}
            className="flex items-center gap-2 px-4 py-2 bg-slate-100 hover:bg-rose-50 text-slate-600 hover:text-rose-600 rounded-xl transition-all text-sm font-bold shadow-sm"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            重新解析新文档
          </button>
        )}
      </div>

      <div className="mt-8 relative z-10 flex-shrink-0">
        
        {!result && !isAnalyzing && (
          <div
            className={`border-2 border-dashed rounded-xl p-8 text-center transition-all duration-300 transform ${
              isDragging ? 'border-blue-500 bg-blue-50 scale-[1.02]' : 'border-slate-300 hover:border-blue-400 hover:bg-slate-50'
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="flex flex-col items-center justify-center space-y-4">
              <div className={`w-16 h-16 rounded-full flex items-center justify-center text-3xl transition-transform duration-500 ${isDragging ? 'bg-blue-200 scale-110' : 'bg-blue-100'}`}>
                📄
              </div>
              <div>
                <p className="text-slate-700 font-medium">拖拽 Word/PDF 文件到此处，或</p>
                <label className="text-blue-600 hover:text-blue-800 font-bold cursor-pointer mt-1 block transition-colors">
                  点击浏览文件
                  <input type="file" className="hidden" accept=".pdf,.doc,.docx" onChange={handleFileSelect} />
                </label>
              </div>
              <p className="text-sm text-slate-400">支持 50MB 以内的文档</p>
            </div>
          </div>
        )}

        {file && !isAnalyzing && (
          <div className="mt-4 p-4 bg-slate-50 rounded-xl flex items-center justify-between border border-slate-200 hover:border-blue-300 transition-colors animate-fade-in-up">
            <div className="flex items-center space-x-4">
              <div className="p-3 bg-white rounded-lg shadow-sm text-2xl">📑</div>
              <div>
                <p className="font-bold text-slate-800">{file.name}</p>
                <p className="text-sm text-slate-500 font-medium">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
              </div>
            </div>
            <button
              onClick={handleAnalyze}
              className="px-6 py-2.5 rounded-xl font-bold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 shadow-lg shadow-blue-200 transform transition-all hover:-translate-y-0.5 hover:shadow-xl active:scale-95"
            >
              开始 AI 解析
            </button>
          </div>
        )}

        {/* 流式进度条 UI */}
        {isAnalyzing && (
          <div className="mt-6 p-8 bg-slate-50 rounded-2xl border border-blue-100 shadow-inner overflow-hidden relative animate-fade-in">
            <div className="absolute top-0 left-0 h-1.5 bg-gradient-to-r from-blue-400 via-indigo-500 to-purple-500 transition-all duration-700 ease-out" style={{ width: `${progress}%` }}></div>
            <div className="flex flex-col items-center justify-center space-y-4 relative z-10">
              <div className="relative">
                <div className="animate-spin rounded-full h-12 w-12 border-4 border-blue-100 border-t-blue-600"></div>
                <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-blue-600">
                  {progress}%
                </div>
              </div>
              <p className="text-slate-700 font-bold text-lg animate-pulse">{statusText}</p>
              <p className="text-slate-400 text-sm">正在调度多智能体网络进行深度分析...</p>

              {/* Embedding 专属生成进度卡片 */}
              {embeddingInfo && (
                <div className="w-full max-w-md bg-white border border-indigo-100 rounded-xl p-4 shadow-sm mt-3 animate-fade-in-up">
                  <div className="flex items-center justify-between text-xs font-bold mb-2">
                    <span className="text-indigo-600 flex items-center gap-1.5">
                      <span className="animate-spin text-sm">🧮</span>
                      <span>BGE-M3 向量化矩阵生成进度</span>
                    </span>
                    <span className="text-indigo-600 font-mono font-extrabold">{embeddingInfo.percent}%</span>
                  </div>
                  <div className="w-full bg-indigo-50 h-2.5 rounded-full overflow-hidden mb-2 border border-indigo-100/60">
                    <div 
                      className="bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500 h-full transition-all duration-500 ease-out shadow-sm"
                      style={{ width: `${embeddingInfo.percent}%` }}
                    ></div>
                  </div>
                  <div className="flex justify-between text-[11px] text-slate-500 font-mono">
                    <span>切片已向量化: {embeddingInfo.processed_count} / {embeddingInfo.total_texts}</span>
                    <span>批次: {embeddingInfo.current_batch} / {embeddingInfo.total_batches}</span>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 结果分屏区域 */}
      {result && !isAnalyzing && (
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 } as any} transition={{ duration: 0.5 } as any} className="mt-8 h-[calc(100vh-200px)] min-h-[800px] relative">
          {(() => {
            if (isFullscreen) {
              return (
                <div className="w-full h-full">
                  {leftPanelContent}
                </div>
              );
            }

            return (
              <Group orientation="horizontal" onLayoutChange={(layout) => setSplitRatio(layout['left-panel'] || 50)}>
                <Panel id="left-panel" defaultSize={splitRatio} minSize={30}>
                  {leftPanelContent}
                </Panel>
                
                <Separator className="w-4 flex flex-shrink-0 items-center justify-center cursor-col-resize group z-10 mx-1 outline-none">
                  <div className="w-1 h-12 bg-slate-200 rounded-full group-hover:bg-blue-400 group-hover:shadow-[0_0_8px_rgba(96,165,250,0.5)] transition-all duration-300"></div>
                </Separator>

                {/* 右侧分析结论区 */}
                <Panel defaultSize={100 - splitRatio} minSize={20}>
                  <div className="flex flex-col h-full border border-slate-200 rounded-2xl overflow-hidden bg-white shadow-sm transition-all hover:shadow-md">
            <div className="bg-slate-50 flex border-b border-slate-200 p-1 gap-1">
              <button 
                className={`flex-1 py-3 px-4 font-bold text-sm transition-all rounded-xl ${activeTab === 'qual' ? 'text-blue-700 bg-white shadow-sm' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}
                onClick={() => setActiveTab('qual')}
              >
                🎯 履约盘点 <span className="ml-1 px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full text-xs">{result.qualifications_analysis?.match_score || 0}分</span>
              </button>
              <button 
                className={`flex-1 py-3 px-4 font-bold text-sm transition-all rounded-xl ${activeTab === 'risk' ? 'text-blue-700 bg-white shadow-sm' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}
                onClick={() => setActiveTab('risk')}
              >
                ⚠️ 风险提示 <span className="ml-1 px-2 py-0.5 bg-rose-100 text-rose-700 rounded-full text-xs">{result.risks_analysis?.length || 0}</span>
              </button>
            </div>
            
            <div className="p-6 overflow-y-auto flex-1 bg-slate-50/50 custom-scrollbar">
              {activeTab === 'qual' && (
                <div className="space-y-4 animate-fade-in">
                  {result.qualifications_analysis?.items?.map((item: any, idx: number) => (
                    <div 
                      key={idx} 
                      onClick={() => handleCardClick(item.exact_quote, item.requirement)}
                      className="p-5 rounded-xl border border-slate-200 bg-white shadow-sm hover:shadow-md hover:border-blue-405 hover:bg-blue-50/20 cursor-pointer transition-all active:scale-[0.99] group/card"
                      title="点击跳转左侧原文出处定位"
                    >
                      <div className="flex justify-between items-start mb-3">
                        <h4 className="font-bold text-slate-800 leading-tight pr-4 flex-1">{item.requirement}</h4>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="text-[10px] text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full font-bold opacity-0 group-hover/card:opacity-100 transition-opacity shadow-xs">🎯 定位原文</span>
                          <span className={`px-3 py-1 text-xs rounded-full font-bold shadow-sm ${
                            item.status === '做不到' ? 'bg-red-100 text-red-700 border border-red-200' :
                            item.status === '努力可做到' ? 'bg-orange-100 text-orange-700 border border-orange-200' :
                            'bg-green-100 text-green-700 border border-green-200'
                          }`}>
                            {item.status}
                          </span>
                        </div>
                      </div>
                      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                        <p className="text-sm text-slate-600"><span className="font-bold text-slate-700 mr-2">🤖 AI 分析:</span>{item.reason}</p>
                      </div>
                    </div>
                  ))}
                  {(!result.qualifications_analysis?.items || result.qualifications_analysis.items.length === 0) && (
                    <div className="flex flex-col items-center justify-center h-48 text-slate-400">
                      <span className="text-4xl mb-3">✨</span>
                      <p>未发现明确资质要求</p>
                    </div>
                  )}
                </div>
              )}

              {activeTab === 'risk' && (
                <div className="space-y-4 animate-fade-in">
                  {[...(result.risks_analysis || [])].sort((a: any, b: any) => {
                    const order: Record<string, number> = { '高': 0, '中': 1, '低': 2 };
                    return (order[a.severity] ?? 3) - (order[b.severity] ?? 3);
                  }).map((risk: any, idx: number) => (
                    <div 
                      key={idx} 
                      onClick={() => handleCardClick(risk.exact_quote, risk.description)}
                      className="p-5 rounded-xl border border-rose-100 bg-white shadow-sm hover:shadow-md hover:border-rose-400 hover:bg-rose-50/20 cursor-pointer transition-all active:scale-[0.99] group/card relative overflow-hidden"
                      title="点击跳转左侧原文出处定位"
                    >
                      <div className={`absolute left-0 top-0 bottom-0 w-1 ${
                          risk.severity === '高' ? 'bg-rose-500' :
                          risk.severity === '中' ? 'bg-orange-400' :
                          'bg-blue-400'
                        }`}></div>
                      <div className="flex justify-between items-start mb-3 pl-2">
                        <div className="flex items-center space-x-2">
                          <span className="font-bold text-slate-800">{risk.risk_type}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full font-bold opacity-0 group-hover/card:opacity-100 transition-opacity shadow-xs">📍 定位原文</span>
                          <span className={`px-3 py-1 text-xs rounded-full font-bold shadow-sm ${
                            risk.severity === '高' ? 'bg-rose-100 text-rose-700 border border-rose-200' :
                            risk.severity === '中' ? 'bg-orange-100 text-orange-700 border border-orange-200' :
                            'bg-blue-100 text-blue-700 border border-blue-200'
                          }`}>
                            {risk.severity}风险
                          </span>
                        </div>
                      </div>
                      <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 ml-2">
                        <p className="text-sm text-slate-600"><span className="font-bold text-slate-700 mr-2">⚠️ 描述:</span>{risk.description}</p>
                      </div>
                    </div>
                  ))}
                  {(!result.risks_analysis || result.risks_analysis.length === 0) && (
                    <div className="flex flex-col items-center justify-center h-48 text-slate-400">
                      <span className="text-4xl mb-3">🛡️</span>
                      <p>未发现明显风险条款</p>
                    </div>
                  )}
                </div>
              )}
            </div>
            </div>
              </Panel>
            </Group>
            );
          })()}
        </motion.div>
      )}
    </motion.div>
  );
}
