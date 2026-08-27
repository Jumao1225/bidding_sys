import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiFetch, API_BASE_URL } from '../utils/api';

interface WorkerItem {
  id: string;
  node_name: string;
  chapter_title: string;
  category: string;
  status: string;
  execution_time_ms: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  summary: string;
  proposals_count: number;
  proposals?: any[];
  tools_used?: string[];
  thought_steps?: Array<{
    step: number;
    type: 'thought' | 'tool_result';
    thought?: string;
    tool_calls?: any[];
    name?: string;
    output?: string;
  }>;
  created_at: string | null;
}

export const AgentAuditPage: React.FC = () => {
  const { documentId: paramDocId } = useParams<{ documentId: string }>();
  const navigate = useNavigate();

  const [activeDocId, setActiveDocId] = useState<string>(
    paramDocId || localStorage.getItem('bidding_document_id') || ''
  );
  const [docList, setDocList] = useState<any[]>([]);

  const [loading, setLoading] = useState(true);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [isDownloadingRaw, setIsDownloadingRaw] = useState(false);
  const [customInstruction, setCustomInstruction] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [workers, setWorkers] = useState<WorkerItem[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  // 审计日志每次刷新/微调都会生成新的 id，章节名才是稳定的选中键。
  const [selectedChapterTitle, setSelectedChapterTitle] = useState<string | null>(null);
  const selectedWorkerIdRef = useRef<string | null>(null);
  const selectedChapterTitleRef = useRef<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'details' | 'thought' | 'raw'>('details');
  const [showDocModal, setShowDocModal] = useState(false);
  const [docFilterText, setDocFilterText] = useState('');

  // 单章节重新生成与 Prompt 微调 State
  const [showRefineModal, setShowRefineModal] = useState(false);
  const [refinePrompt, setRefinePrompt] = useState('');
  const [isRefining, setIsRefining] = useState(false);

  const syncWorkerSelection = (items: WorkerItem[]) => {
    const sameWorker = selectedWorkerIdRef.current
      ? items.find(i => i.id === selectedWorkerIdRef.current)
      : undefined;
    const sameChapter = selectedChapterTitleRef.current
      ? items.find(i => i.chapter_title === selectedChapterTitleRef.current)
      : undefined;
    const nextWorker = sameWorker || sameChapter || items[0];

    if (nextWorker) {
      selectedWorkerIdRef.current = nextWorker.id;
      selectedChapterTitleRef.current = nextWorker.chapter_title;
      setSelectedWorkerId(nextWorker.id);
      setSelectedChapterTitle(nextWorker.chapter_title);
    } else {
      selectedWorkerIdRef.current = null;
      selectedChapterTitleRef.current = null;
      setSelectedWorkerId(null);
      setSelectedChapterTitle(null);
    }
  };

  // 同步 URL 参数变更
  useEffect(() => {
    if (paramDocId && paramDocId !== activeDocId) {
      setActiveDocId(paramDocId);
      localStorage.setItem('bidding_document_id', paramDocId);
    }
  }, [paramDocId]);

  // 拉取已上传的项目/招标文件列表
  const fetchDocList = async () => {
    try {
      const res = await apiFetch(`${API_BASE_URL}/api/v1/bidding/documents-list?doc_type=tender`);
      if (res.ok) {
        const data = await res.json();
        const docs = data || [];
        setDocList(docs);
        if (docs.length > 0) {
          const exists = docs.some((d: any) => d.id === activeDocId);
          if (!activeDocId || !exists) {
            const firstId = docs[0].id;
            setActiveDocId(firstId);
            localStorage.setItem('bidding_document_id', firstId);
            fetchWorkerLogs(firstId, true);
          }
        }
      }
    } catch (e) {
      console.warn('获取招标文件列表失败:', e);
    }
  };

  const [profileList, setProfileList] = useState<Array<{
    id: string;
    profile_name?: string;
    company_name?: string;
    is_default?: boolean;
  }>>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>('');

  const fetchProfileList = async () => {
    try {
      const res = await apiFetch(`${API_BASE_URL}/api/v1/company/profiles`);
      if (res.ok) {
        const data = await res.json();
        const list = data.profiles || [];
        setProfileList(list);
        if (list.length > 0) {
          const defaultItem = list.find((p: any) => p.is_default);
          setSelectedProfileId((prev) => prev || (defaultItem ? defaultItem.id : list[0].id));
        }
      }
    } catch (e) {
      console.warn('获取企业主体档案列表失败:', e);
    }
  };

  useEffect(() => {
    fetchDocList();
    fetchProfileList();
  }, []);

  const [isLivePolling, setIsLivePolling] = useState(false);

  // 真实物理端到端耗时与秒表计时器 State (支持 100ms 级别实时毫秒/秒级跳动计时与平滑冻结)
  const [liveTimerMs, setLiveTimerMs] = useState(0);
  const [serverWallTimeMs, setServerWallTimeMs] = useState(0);
  const [frozenDurationMs, setFrozenDurationMs] = useState(0);
  const timerStartRef = useRef<number | null>(null);

  useEffect(() => {
    let intervalId: any = null;
    if (isGenerating || isLivePolling) {
      if (!timerStartRef.current) {
        timerStartRef.current = Date.now();
      }
      intervalId = setInterval(() => {
        if (timerStartRef.current) {
          setLiveTimerMs(Date.now() - timerStartRef.current);
        }
      }, 100);
    } else {
      timerStartRef.current = null;
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }, [isGenerating, isLivePolling]);

  const fetchWorkerLogs = async (docIdToFetch?: string, showLoadingSpinner: boolean = true) => {
    const targetId = typeof docIdToFetch === 'string' ? docIdToFetch : activeDocId;
    if (!targetId) {
      setWorkers([]);
      setLoading(false);
      return;
    }

    if (showLoadingSpinner) {
      setLoading(true);
    }

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/fill-bid-format/${targetId}/worker-logs`);
      if (response.status === 404) {
        // 该文档尚未运行 Agent 填报，容错处理为空履历
        setWorkers([]);
        setError(null);
        return;
      }
      if (!response.ok) throw new Error('获取 Agent 运行日志失败');
      const data = await response.json();

      const items: WorkerItem[] = data.worker_items || [];
      setWorkers(items);
      if (typeof data.total_wall_time_ms === 'number' && data.total_wall_time_ms > 0) {
        setServerWallTimeMs(data.total_wall_time_ms);
      }
      syncWorkerSelection(items);
      setError(null);
    } catch (err: any) {
      console.warn('获取 Agent 履历数据出差/暂无履历:', err);
      setWorkers([]);
    } finally {
      setLoading(false);
    }
  };

  const eventSourceRef = useRef<EventSource | null>(null);

  // 使用 SSE (Server-Sent Events) 实时推流获取 Agent 履历与思维链
  const setupSSELogStream = (docId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const sseUrl = `${API_BASE_URL}/api/v1/bidding/fill-bid-format/${docId}/stream-logs`;
    const es = new EventSource(sseUrl);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.worker_items && Array.isArray(data.worker_items)) {
          setWorkers(data.worker_items);
          setLoading(false);
          syncWorkerSelection(data.worker_items as WorkerItem[]);
        }
        if (typeof data.total_wall_time_ms === 'number' && data.total_wall_time_ms > 0) {
          setServerWallTimeMs(data.total_wall_time_ms);
        }
        // 只有后端最终 Supervisor 终态才允许前端结束计时，Worker 完成不代表终审完成。
        if (data.is_completed && data.pipeline_status === 'completed') {
          setFrozenDurationMs(prev => (liveTimerMs > 0 ? liveTimerMs : prev));
          setIsLivePolling(false);
          setIsGenerating(false);
          setLoading(false);
          setNotice(`✨ ${data.pipeline_message || 'AI 团队自主撰写、终审与 Word 发布已完成。'}`);
          es.close();
        } else if (data.is_completed && data.pipeline_status === 'failed') {
          setFrozenDurationMs(prev => (liveTimerMs > 0 ? liveTimerMs : prev));
          setIsLivePolling(false);
          setIsGenerating(false);
          setLoading(false);
          setError(data.pipeline_message || '后台标书填报流程异常结束，请查看审计日志。');
          setNotice('⚠️ 后台流程已结束，但未成功完成最终发布。');
          es.close();
        }
      } catch (err) {
        console.warn('解析 SSE 消息失败:', err);
      }
    };

    es.onerror = () => {
      es.close();
      fetchWorkerLogs(docId, false);
    };
  };

  useEffect(() => {
    selectedWorkerIdRef.current = null;
    selectedChapterTitleRef.current = null;
    setSelectedWorkerId(null);
    setSelectedChapterTitle(null);

    if (activeDocId) {
      fetchWorkerLogs(activeDocId);
      setupSSELogStream(activeDocId);
    } else {
      setLoading(false);
    }

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [activeDocId]);

  // 触发 AI 全自主智能标书撰写
  const handleStartFilling = async () => {
    if (!activeDocId || isGenerating) return;

    setIsGenerating(true);
    setIsLivePolling(true);
    setNotice('⚡ 正在启动 AI 团队全自主标书撰写：正在清理上一轮履历并建立 0 延迟实时推流...');
    setError(null);

    // 清空历史旧履历，重置呈现最新一轮 Agent 思考与原位落盘弹增过程
    setWorkers([]);
    setSelectedWorkerId(null);
    setSelectedChapterTitle(null);
    selectedWorkerIdRef.current = null;
    selectedChapterTitleRef.current = null;
    setLoading(false);
    setLiveTimerMs(0);
    setFrozenDurationMs(0);
    setServerWallTimeMs(0);
    timerStartRef.current = Date.now();

    try {
      // 先发起 POST 请求，触发后端瞬间清理旧日志并写入初始 in_progress 记录
      const postPromise = apiFetch(`${API_BASE_URL}/api/v1/bidding/agent-fill-bid-format/${activeDocId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          custom_instructions: customInstruction || undefined,
          profile_id: selectedProfileId || undefined
        })
      });

      // 延迟 200ms 开启 SSE 0 延迟实时推流，确保能够精确捕获到最新的 in_progress 状态与实时卡片
      setTimeout(() => {
        setupSSELogStream(activeDocId);
      }, 200);

      const response = await postPromise;

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || '标书全自主撰写失败');
      }

      // POST 成功仅表示后台线程已启动，非撰写完成；SSE onmessage 中的 is_completed 逻辑会自动控制生命周期
      setNotice('⚡ Agent 团队后台全自主撰写已启动，正在通过 SSE 实时推流监听进度...');
    } catch (err: any) {
      setError(`撰写生成失败: ${err.message}`);
      // 仅在请求失败时才关闭 SSE 连接并重置状态，正常情况交由 SSE is_completed 回调自动关闭
      setIsGenerating(false);
      setIsLivePolling(false);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    }
  };

  // 下载标书 Word 文件 (.docx)
  const handleDownloadWord = async () => {
    if (!activeDocId || isDownloading) return;

    setIsDownloading(true);
    setNotice('📥 正在从服务器提取生成好的 Word 文档，准备下载...');

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/agent-fill-bid-format/${activeDocId}/download`);
      if (!response.ok) throw new Error('下载标书 Word 失败');

      const blob = await response.blob();
      const contentDisposition = response.headers.get('Content-Disposition') || '';
      let filename = '【已填报】投标文件格式.docx';
      const match = contentDisposition.match(/filename\*=UTF-8''(.+)/);
      if (match && match[1]) {
        filename = decodeURIComponent(match[1]);
      }

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setNotice('✅ 标书 Word 文档已成功下载！');
    } catch (err: any) {
      setError(`下载失败: ${err.message}`);
    } finally {
      setIsDownloading(false);
    }
  };

  // 下载原格式标书文件 (投标文件格式原始模板 .docx)
  const handleDownloadRawTemplate = async () => {
    if (!activeDocId || isDownloadingRaw) return;

    setIsDownloadingRaw(true);
    setNotice('📥 正在从服务器提取《投标文件格式》原格式标书模板，准备下载...');

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/extract-bid-format/${activeDocId}`);
      if (!response.ok) throw new Error('提取原格式标书文件失败');

      const blob = await response.blob();
      const contentDisposition = response.headers.get('Content-Disposition') || '';
      let filename = '【原格式】投标文件格式模板.docx';
      const match = contentDisposition.match(/filename\*=UTF-8''(.+)/);
      if (match && match[1]) {
        filename = decodeURIComponent(match[1]);
      }

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      const modeHeader = response.headers.get('X-Extraction-Mode');
      if (modeHeader === 'fallback_template') {
        setNotice('⚠️ 《投标文件格式》原标书章节未精准命中，已下载通用托底格式模板！');
      } else {
        setNotice('✅ 《投标文件格式》标书格式文件已成功下载！');
      }
    } catch (err: any) {
      setError(`下载原格式标书失败: ${err.message}`);
    } finally {
      setIsDownloadingRaw(false);
    }
  };

  // 单章节重新生成与 Prompt 微调处理
  const handleRegenerateChapter = async () => {
    if (!activeDocId || !selectedWorker || isRefining) return;
    setIsRefining(true);
    setNotice(`🔄 正在针对章节【${selectedWorker.chapter_title}】根据您的微调提示词重新生成与写盘...`);

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/fill-bid-format/${activeDocId}/regenerate-chapter`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          chapter_title: selectedWorker.chapter_title,
          custom_prompt: refinePrompt,
          category: selectedWorker.category,
        })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || '单章节重新生成失败');
      }

      const data = await response.json();
      setNotice(`✅ 章节【${selectedWorker.chapter_title}】微调重新生成成功！已原位更新 Word 文档。`);
      setShowRefineModal(false);
      setRefinePrompt('');

      // 更新本地 workers 列表并刷新履历
      if (data.worker_item) {
        setWorkers(prev => prev.map(w => w.chapter_title === data.chapter_title ? { ...w, ...data.worker_item } : w));
        // 微调会生成新的审计日志 id，必须同步更新选中项，不能让 selectedWorker 回退到第一张卡片。
        selectedWorkerIdRef.current = data.worker_item.id;
        selectedChapterTitleRef.current = data.chapter_title;
        setSelectedWorkerId(data.worker_item.id);
        setSelectedChapterTitle(data.chapter_title);
      } else {
        fetchWorkerLogs(activeDocId, false);
      }
    } catch (err: any) {
      setError(`单章节微调失败: ${err.message}`);
    } finally {
      setIsRefining(false);
    }
  };

  const filteredWorkers = workers.filter(
    (w) =>
      w.chapter_title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      w.node_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const selectedWorker =
    (selectedChapterTitle && workers.find((w) => w.chapter_title === selectedChapterTitle)) ||
    (selectedWorkerId && workers.find((w) => w.id === selectedWorkerId)) ||
    filteredWorkers[0];

  const totalTokens = workers.reduce((acc, w) => acc + (w.total_tokens || 0), 0);
  const totalPromptTokens = workers.reduce((acc, w) => acc + (w.prompt_tokens || 0), 0);
  const totalCompletionTokens = workers.reduce((acc, w) => acc + (w.completion_tokens || 0), 0);
  const totalWorkerComputeTimeMs = workers.reduce((acc, w) => acc + (w.execution_time_ms || 0), 0);

  const actualEffectiveWallTimeMs = (isGenerating || isLivePolling)
    ? liveTimerMs
    : (serverWallTimeMs > 0
      ? serverWallTimeMs
      : (frozenDurationMs > 0
        ? frozenDurationMs
        : Math.max(...workers.map(w => w.execution_time_ms || 0), 0)));

  const displayTimeSeconds = (actualEffectiveWallTimeMs / 1000).toFixed(1);

  const accelerationRatio = actualEffectiveWallTimeMs > 0 && totalWorkerComputeTimeMs > actualEffectiveWallTimeMs
    ? (totalWorkerComputeTimeMs / actualEffectiveWallTimeMs).toFixed(1)
    : '1.0';

  const successfulWorkers = workers.filter((w) => {
    const s = (w.status || '').toLowerCase();
    return s === 'success' || s === 'completed' || s === 'skipped' || s === 'master_completed';
  });

  const writeSuccessRateStr = workers.length > 0
    ? `${Math.round((successfulWorkers.length / workers.length) * 100)}%`
    : '100%';

  const currentDocObj = docList.find((d) => d.id === activeDocId);

  const filteredDocList = docList.filter(
    (doc) =>
      (doc.display_label || '').toLowerCase().includes(docFilterText.toLowerCase()) ||
      (doc.filename || '').toLowerCase().includes(docFilterText.toLowerCase()) ||
      (doc.project_name || '').toLowerCase().includes(docFilterText.toLowerCase()) ||
      (doc.project_code || '').toLowerCase().includes(docFilterText.toLowerCase())
  );

  // 格式化落盘扩写提案内嵌数据，智能解析二维表格数组与对象，避免原始 JSON 字符串挤爆表格或字符重叠
  const renderProposalValue = (val: any): React.ReactNode => {
    if (val === null || val === undefined) return <span className="text-slate-500 italic">空</span>;

    let parsed = val;
    if (typeof val === 'string') {
      const trimmed = val.trim();
      if ((trimmed.startsWith('[') && trimmed.endsWith(']')) || (trimmed.startsWith('{') && trimmed.endsWith('}'))) {
        try {
          parsed = JSON.parse(trimmed);
        } catch {
          parsed = val;
        }
      }
    }

    // 1. 如果是二维表格数据（行列表，如 [["我公司完全接受...", "无", "无"], ...]）
    if (Array.isArray(parsed)) {
      if (parsed.length === 0) return <span className="text-slate-500 italic">（空列表）</span>;

      // 二维表格行
      if (Array.isArray(parsed[0])) {
        return (
          <div className="space-y-2.5 max-h-72 overflow-y-auto dark-scrollbar pr-1">
            {parsed.map((row: any[], rIdx: number) => (
              <div key={rIdx} className="p-2.5 rounded-xl bg-slate-900/95 border border-slate-800 text-xs flex items-start gap-2.5 shadow-sm">
                <span className="px-2 py-0.5 rounded-md bg-purple-500/20 text-purple-300 font-mono text-[11px] font-bold shrink-0 mt-0.5 border border-purple-500/30">
                  行 {rIdx + 1}
                </span>
                <div className="flex-1 text-slate-200 leading-relaxed font-sans break-words space-y-1.5">
                  {row.map((colVal: any, cIdx: number) => {
                    const strCol = typeof colVal === 'object' ? JSON.stringify(colVal) : String(colVal ?? '');
                    return (
                      <div key={cIdx} className="flex items-start gap-1.5">
                        {row.length > 1 && (
                          <span className="px-1.5 py-0.2 rounded bg-slate-800 text-slate-400 font-mono text-[10px] shrink-0 select-none mt-0.5">
                            列{cIdx + 1}
                          </span>
                        )}
                        <span className={cIdx === 0 ? "text-emerald-300 font-medium leading-relaxed" : "text-slate-300 leading-relaxed"}>
                          {strCol}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        );
      }

      // 一维数组
      return (
        <ul className="space-y-1.5 max-h-56 overflow-y-auto dark-scrollbar pl-2 list-disc list-inside text-xs text-slate-200">
          {parsed.map((item: any, iIdx: number) => (
            <li key={iIdx} className="leading-relaxed font-sans break-words text-emerald-300">
              {typeof item === 'object' ? JSON.stringify(item) : String(item)}
            </li>
          ))}
        </ul>
      );
    }

    // 2. 如果是对象
    if (typeof parsed === 'object') {
      return (
        <div className="p-2.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs font-mono space-y-1.5 max-h-52 overflow-y-auto dark-scrollbar">
          {Object.entries(parsed).map(([k, v], oIdx) => (
            <div key={oIdx} className="flex items-start gap-2">
              <span className="text-purple-400 font-bold shrink-0">{k}:</span>
              <span className="text-slate-200 break-words">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
            </div>
          ))}
        </div>
      );
    }

    // 3. 普通长文本
    const strVal = String(parsed);
    return (
      <div className="text-xs text-emerald-300 font-medium leading-relaxed font-sans whitespace-pre-wrap break-words max-h-60 overflow-y-auto dark-scrollbar">
        {strVal}
      </div>
    );
  };

  // 格式化模板原文槽位
  const renderOriginalContext = (val: any): React.ReactNode => {
    if (!val) return <span className="text-slate-500 italic">模板空位</span>;
    const strVal = typeof val === 'object' ? JSON.stringify(val) : String(val);
    return (
      <div className="text-xs text-slate-400 font-mono leading-relaxed break-words max-h-48 overflow-y-auto dark-scrollbar">
        {strVal}
      </div>
    );
  };

  return (
    <div className="font-sans text-slate-100 selection:bg-purple-500 selection:text-white pb-12 animate-fade-in">
      {/* 统一一体化控制台 Mega-Container */}
      <div className="border border-slate-800/90 bg-slate-950 rounded-3xl shadow-2xl overflow-hidden backdrop-blur-xl divide-y divide-slate-800/80">
        
        {/* 1. 顶层编排与快速操作区 */}
        <div className="bg-slate-900/90 p-4">
          <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3.5">
            {/* 左侧: 双任务选择器 (目标文件 + 投标主体) */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 flex-1">
              {/* 目标招标文件选择 */}
              <div className="flex items-center gap-2.5 bg-slate-950/90 border border-purple-900/40 focus-within:border-purple-500/80 focus-within:ring-2 focus-within:ring-purple-500/20 rounded-xl px-3.5 py-2.5 shadow-inner transition-all">
                <span className="text-xs text-purple-300 font-bold shrink-0 flex items-center gap-1.5">
                  <span>📄</span>
                  <span>招标文件:</span>
                </span>
                <select
                  value={activeDocId}
                  onChange={(e) => {
                    const selectedId = e.target.value;
                    setActiveDocId(selectedId);
                    localStorage.setItem('bidding_document_id', selectedId);
                    navigate(`/agent-audit/${selectedId}`);
                  }}
                  className="min-w-0 flex-1 bg-transparent text-purple-100 font-semibold text-xs focus:outline-none cursor-pointer truncate"
                >
                  {docList.length > 0 ? (
                    docList.map((doc) => (
                      <option key={doc.id} value={doc.id} className="bg-slate-900 text-slate-100">
                        {doc.display_label || doc.filename}
                      </option>
                    ))
                  ) : (
                    <option value={activeDocId} className="bg-slate-900 text-slate-100">
                      {activeDocId ? `已定位文档 (${activeDocId.slice(0, 8)}...)` : '-- 暂无可用的招标文件 --'}
                    </option>
                  )}
                </select>

                <button
                  type="button"
                  onClick={() => setShowDocModal(true)}
                  className="px-2.5 py-1 rounded-lg bg-gradient-to-r from-purple-900/80 to-indigo-900/80 hover:from-purple-800 hover:to-indigo-800 text-purple-200 text-xs font-bold border border-purple-700/50 cursor-pointer transition-all shrink-0 whitespace-nowrap shadow-sm active:scale-95"
                  title="打开全景招标文件选择列表"
                >
                  📂 列表 ({docList.length})
                </button>
              </div>

              {/* 投标主体档案选择 */}
              <div className="flex items-center gap-2.5 bg-slate-950/90 border border-blue-900/40 focus-within:border-blue-500/80 focus-within:ring-2 focus-within:ring-blue-500/20 rounded-xl px-3.5 py-2.5 shadow-inner transition-all">
                <span className="text-xs text-blue-300 font-bold shrink-0 flex items-center gap-1.5">
                  <span>🏢</span>
                  <span>投标主体:</span>
                </span>
                <select
                  value={selectedProfileId}
                  onChange={(e) => setSelectedProfileId(e.target.value)}
                  className="min-w-0 flex-1 bg-transparent text-blue-100 font-semibold text-xs focus:outline-none cursor-pointer truncate"
                  title="指定生成此标书时使用的投标主体信息"
                >
                  {profileList.length > 0 ? (
                    profileList.map((p) => (
                      <option key={p.id} value={p.id} className="bg-slate-900 text-slate-100">
                        {p.is_default ? '⭐ [默认] ' : ''}{p.profile_name || '未命名主体'} {p.company_name ? `(${p.company_name})` : ''}
                      </option>
                    ))
                  ) : (
                    <option value="" className="bg-slate-900 text-slate-100">
                      -- 暂无主体档案 (使用系统默认) --
                    </option>
                  )}
                </select>

                <button
                  type="button"
                  onClick={() => navigate('/company-profile')}
                  className="px-2.5 py-1 rounded-lg bg-gradient-to-r from-blue-900/80 to-cyan-900/80 hover:from-blue-800 hover:to-cyan-800 text-blue-200 text-xs font-bold border border-blue-700/50 cursor-pointer transition-all shrink-0 whitespace-nowrap shadow-sm active:scale-95"
                  title="前往企业档案页管理各投标主体"
                >
                  ⚙️ 配置
                </button>
              </div>
            </div>

            {/* 右侧: 3 大操作按钮 */}
            <div className="flex flex-wrap items-center gap-2.5 shrink-0 xl:justify-end">
              <button
                type="button"
                onClick={handleDownloadRawTemplate}
                disabled={isDownloadingRaw || !activeDocId}
                className="px-3.5 py-2.5 rounded-xl bg-slate-800/90 hover:bg-slate-700 active:scale-98 text-slate-200 hover:text-white text-xs font-bold shadow-md border border-slate-700/70 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-40"
                title="提取并下载未经过 AI 扩写的原格式《投标文件格式》Word 模板"
              >
                {isDownloadingRaw ? (
                  <>
                    <span className="animate-spin w-3.5 h-3.5 border-2 border-slate-300 border-t-transparent rounded-full"></span>
                    <span>正在提取...</span>
                  </>
                ) : (
                  <>
                    <span>📄 原格式模板</span>
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={handleDownloadWord}
                disabled={isDownloading || !activeDocId}
                className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 active:scale-98 text-white text-xs font-bold shadow-lg shadow-emerald-950/50 border border-emerald-400/30 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-40"
              >
                {isDownloading ? (
                  <>
                    <span className="animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full"></span>
                    <span>正在下载...</span>
                  </>
                ) : (
                  <>
                    <span>📥 下载标书 Word</span>
                  </>
                )}
              </button>

              <button
                type="button"
                onClick={handleStartFilling}
                disabled={isGenerating || !activeDocId}
                className="px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 via-indigo-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 active:scale-98 text-white text-xs font-extrabold shadow-xl shadow-purple-900/60 transition-all flex items-center gap-2 cursor-pointer border border-purple-400/50 ring-1 ring-purple-400/30 disabled:opacity-50"
              >
                {isGenerating ? (
                  <>
                    <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
                    <span>AI 团队全自主撰写中...</span>
                  </>
                ) : (
                  <>
                    <span className="text-sm">✨</span>
                    <span>一键启动 Agent 全自主撰写</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* 2. 状态/通知栏 (条件渲染) */}
        {notice && (
          <div className="bg-purple-950/90 px-4 py-2.5 text-xs text-purple-200 flex items-center justify-between gap-3 font-medium shadow-inner animate-fade-in">
            <div className="min-w-0 flex items-center gap-2">
              <span className="text-sm">💡</span>
              <span>{notice}</span>
            </div>
            <button type="button" onClick={() => setNotice(null)} className="text-purple-400 hover:text-white font-bold px-1.5 py-0.5 rounded hover:bg-purple-900/50 transition-colors">
              ✕
            </button>
          </div>
        )}

        {error && (
          <div className="bg-rose-950/90 px-4 py-2.5 text-xs text-rose-200 flex items-center justify-between gap-3 font-medium shadow-inner animate-fade-in">
            <div className="min-w-0 flex items-center gap-2">
              <span className="text-sm">❌</span>
              <span>{error}</span>
            </div>
            <button type="button" onClick={() => setError(null)} className="text-rose-400 hover:text-white font-bold px-1.5 py-0.5 rounded hover:bg-rose-900/50 transition-colors">
              ✕
            </button>
          </div>
        )}

        {/* 3. 顶部指令配置 & 4 大指标统计区 */}
        <div className="bg-slate-900/60 p-4.5 space-y-3.5">
          {/* 自定义撰写指令控制条 */}
          <div className="space-y-2.5">
            <div className="bg-slate-950/95 border border-slate-800/90 focus-within:border-purple-500/80 focus-within:ring-2 focus-within:ring-purple-500/20 rounded-xl p-2.5 flex items-center gap-3 transition-all shadow-inner">
              <span className="text-sm p-1.5 bg-purple-500/15 text-purple-400 rounded-lg shrink-0 border border-purple-500/20">✍️</span>
              <input
                type="text"
                placeholder="自定义全局撰写指令（如：“商务偏离表统一填无偏离，付款节点填30%预付款，项目经理指定张三”）..."
                value={customInstruction}
                onChange={(e) => setCustomInstruction(e.target.value)}
                className="min-w-48 flex-1 bg-transparent text-xs text-slate-100 placeholder-slate-500 focus:outline-none font-medium"
              />
              <button
                type="button"
                onClick={handleStartFilling}
                disabled={isGenerating || !activeDocId}
                className="px-4 py-2 rounded-lg bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 active:scale-95 text-white text-xs font-bold transition-all shadow-md shadow-purple-950/50 cursor-pointer shrink-0 disabled:opacity-50 whitespace-nowrap border border-purple-400/30"
              >
                带指令生成
              </button>
            </div>

            {/* 快捷常用提示词标签 */}
            <div className="flex flex-wrap items-center gap-2 px-1">
              <span className="text-[11px] text-slate-400 font-bold flex items-center gap-1">
                <span>⚡</span>
                <span>快捷注入:</span>
              </span>
              {[
                '商务与技术条款严格填报无偏离',
                '付款节点填报为30%预付款与60%进度款',
                '工期统一按招标文件要求60日历天填报'
              ].map((tag, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setCustomInstruction(prev => prev ? `${prev}；${tag}` : tag)}
                  className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-purple-950/80 border border-slate-800 hover:border-purple-700/60 text-[11px] text-purple-300 font-medium transition-all cursor-pointer shadow-xs active:scale-95"
                >
                  + {tag}
                </button>
              ))}
            </div>
          </div>

          {/* 4 大核心统计指标 */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3.5">
            <div className="bg-slate-950/90 border border-slate-800/80 hover:border-purple-500/40 rounded-xl p-3.5 flex items-center gap-3.5 transition-all shadow-inner group">
              <div className="w-11 h-11 rounded-xl bg-purple-500/15 text-purple-400 border border-purple-500/25 flex items-center justify-center font-bold text-xl shrink-0 group-hover:scale-105 transition-transform">
                🤖
              </div>
              <div>
                <div className="text-[11px] text-slate-400 font-medium">子 Agent 节点数</div>
                <div className="text-base sm:text-lg font-black text-white font-mono mt-0.5">{workers.length} 个章节</div>
              </div>
            </div>

            <div className="bg-slate-950/90 border border-slate-800/80 hover:border-blue-500/40 rounded-xl p-3.5 flex items-center gap-3.5 transition-all shadow-inner group">
              <div className="w-11 h-11 rounded-xl bg-blue-500/15 text-blue-400 border border-blue-500/25 flex items-center justify-center font-bold text-xl shrink-0 group-hover:scale-105 transition-transform">
                ⏱️
              </div>
              <div>
                <div className="text-[11px] text-slate-400 font-medium flex items-center gap-1.5">
                  <span>累计撰写耗时</span>
                  {(isGenerating || isLivePolling) && (
                    <span className="w-2 h-2 rounded-full bg-blue-400 animate-ping inline-block" />
                  )}
                </div>
                <div className="text-base sm:text-lg font-black text-white font-mono mt-0.5">{displayTimeSeconds} 秒</div>
                {Number(accelerationRatio) > 1.1 && !isGenerating && !isLivePolling && (
                  <div className="text-[10px] text-blue-400/80 font-mono mt-0.5" title={`并发累计算力工时: ${(totalWorkerComputeTimeMs / 1000).toFixed(1)} 秒`}>
                    ⚡ 多Agent加速 {accelerationRatio}x
                  </div>
                )}
              </div>
            </div>

            <div className="bg-slate-950/90 border border-slate-800/80 hover:border-emerald-500/40 rounded-xl p-3.5 flex items-center gap-3.5 transition-all shadow-inner group">
              <div className="w-11 h-11 rounded-xl bg-emerald-500/15 text-emerald-400 border border-emerald-500/25 flex items-center justify-center font-bold text-xl shrink-0 group-hover:scale-105 transition-transform">
                ⚡
              </div>
              <div>
                <div className="text-[11px] text-slate-400 font-medium">Token 思考总消耗</div>
                <div className="text-base sm:text-lg font-black text-emerald-400 font-mono mt-0.5">{totalTokens.toLocaleString()}</div>
                {totalTokens > 0 && (
                  <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                    P: {totalPromptTokens.toLocaleString()} | C: {totalCompletionTokens.toLocaleString()}
                  </div>
                )}
              </div>
            </div>

            <div className="bg-slate-950/90 border border-slate-800/80 hover:border-amber-500/40 rounded-xl p-3.5 flex items-center gap-3.5 transition-all shadow-inner group">
              <div className="w-11 h-11 rounded-xl bg-amber-500/15 text-amber-400 border border-amber-500/25 flex items-center justify-center font-bold text-xl shrink-0 group-hover:scale-105 transition-transform">
                ✅
              </div>
              <div>
                <div className="text-[11px] text-slate-400 font-medium">写盘验证成功率</div>
                <div className="text-base sm:text-lg font-black text-amber-400 font-mono mt-0.5">
                  {writeSuccessRateStr}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* 4. 主工作台面板：左侧 Worker 列表 + 右侧思考与提案可视化 (固定对称高 720px) */}
        <div className="flex flex-col xl:flex-row h-[720px] bg-slate-950">
        {/* 左侧边栏 Worker 列表 */}
        <div className="w-full xl:w-84 border-b xl:border-b-0 xl:border-r border-slate-800/80 bg-slate-950/60 flex flex-col shrink-0 h-full">
          <div className="p-3.5 border-b border-slate-800/80 shrink-0 bg-slate-900/40">
            <div className="relative">
              <input
                type="text"
                placeholder="🔍 搜索章节名称或子 Agent..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800/90 focus:border-purple-500 focus:ring-1 focus:ring-purple-500/30 rounded-xl px-3.5 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none transition-all shadow-inner"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto dark-scrollbar p-2.5 space-y-2">
            {loading ? (
              <div className="py-16 text-center text-slate-500 text-xs">
                <div className="animate-spin w-7 h-7 border-2 border-purple-500 border-t-transparent rounded-full mx-auto mb-3"></div>
                加载 Agent 章节履历...
              </div>
            ) : filteredWorkers.length > 0 ? (
              filteredWorkers.map((w, idx) => {
                const isSelected = selectedWorker?.id === w.id;
                const isSupervisor = w.category === 'supervisor_master' || w.node_name.includes('Supervisor');
                return (
                  <div
                    key={w.id || idx}
                    onClick={() => {
                      selectedWorkerIdRef.current = w.id;
                      selectedChapterTitleRef.current = w.chapter_title;
                      setSelectedWorkerId(w.id);
                      setSelectedChapterTitle(w.chapter_title);
                    }}
                    className={`p-3.5 rounded-xl border transition-all cursor-pointer select-none ${isSelected
                      ? isSupervisor
                        ? 'bg-gradient-to-r from-purple-900/90 via-slate-900 to-amber-950/80 border-amber-400 text-white shadow-xl shadow-amber-950/40 ring-1 ring-amber-400/60 scale-[1.01]'
                        : 'bg-gradient-to-r from-purple-950/90 to-indigo-950/80 border-purple-500 text-white shadow-xl shadow-purple-950/50 ring-1 ring-purple-500/50 scale-[1.01]'
                      : isSupervisor
                        ? 'bg-slate-950/70 border-amber-500/30 text-amber-200 hover:bg-slate-900/80 hover:border-amber-400/50'
                        : 'bg-slate-950/60 border-slate-800/80 text-slate-300 hover:bg-slate-900/70 hover:border-slate-700'
                      }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="font-bold text-xs truncate max-w-[170px]" title={w.chapter_title}>
                        {isSupervisor ? `👑 ${w.chapter_title}` : w.chapter_title}
                      </span>
                      <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold ${w.status === 'in_progress'
                        ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30 animate-pulse'
                        : w.status === 'failed'
                          ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                          : isSupervisor
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 font-mono'
                            : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                        }`}>
                        {w.status === 'in_progress' ? '🤖 思考撰写中' : w.status === 'failed' ? '❌ 执行失败' : isSupervisor ? '👑 总控决策' : '✅ 已填报'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono mt-1.5 pt-1.5 border-t border-slate-800/50">
                      <span>⏱️ {(w.execution_time_ms / 1000).toFixed(1)}s</span>
                      <span>⚡ {w.total_tokens.toLocaleString()} tok</span>
                      <span className={isSupervisor ? "text-amber-300 font-semibold" : "text-purple-300 font-semibold"}>
                        {isSupervisor ? `章数: ${w.proposals_count}` : `提案: ${w.proposals_count} 项`}
                      </span>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="py-16 text-center text-slate-500 text-xs px-4">
                <span className="text-3xl block mb-2 opacity-60">📝</span>
                <span>暂未检索到填报履历，可点击右上角【一键启动 Agent 全自主撰写】</span>
              </div>
            )}
          </div>
        </div>

        {/* 右侧主内容区域 */}
        <div className="flex-1 min-w-0 bg-slate-950/70 flex flex-col h-full overflow-hidden">
          {selectedWorker ? (
            <>
              {/* Active Worker Header */}
              <div className="p-4 border-b border-slate-800/80 bg-slate-900/60 flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3 shrink-0 backdrop-blur-md">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <h2 className="font-extrabold text-sm sm:text-base text-white break-words tracking-tight">{selectedWorker.chapter_title}</h2>
                    <span className="px-2.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 text-xs font-mono font-bold border border-purple-500/30">
                      {selectedWorker.node_name}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-xs text-slate-400 mt-1 font-mono">
                    <span>类别: <strong className="text-slate-300">{selectedWorker.category}</strong></span>
                    <span>耗时: <strong className="text-slate-300">{(selectedWorker.execution_time_ms / 1000).toFixed(1)}s</strong></span>
                    <span>Token: <strong className="text-emerald-400">{selectedWorker.total_tokens.toLocaleString()} tok</strong></span>
                    <span>落盘提案: <strong className="text-purple-300">{selectedWorker.proposals_count} 项</strong></span>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2.5 xl:justify-end shrink-0">
                  {/* 单章节微调按钮 */}
                  {!selectedWorker.category?.includes('supervisor') && !selectedWorker.node_name.includes('Supervisor') && (
                    <button
                      type="button"
                      onClick={() => setShowRefineModal(true)}
                      disabled={isRefining || isGenerating}
                      className="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-purple-700/90 to-indigo-700/90 hover:from-purple-600 hover:to-indigo-600 active:scale-95 text-white text-xs font-bold shadow-md border border-purple-500/40 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                      title="针对当前章节输入自定义提示词重新生成与微调"
                    >
                      {isRefining ? (
                        <>
                          <span className="animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full"></span>
                          <span>单章微调中...</span>
                        </>
                      ) : (
                        <>
                          <span>✨ 重新生成 / Prompt 微调</span>
                        </>
                      )}
                    </button>
                  )}

                  {/* Tab Switcher */}
                  <div className="flex bg-slate-900/90 p-1 rounded-xl border border-slate-800 shadow-inner">
                    <button
                      type="button"
                      onClick={() => setActiveTab('details')}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${activeTab === 'details' ? 'bg-purple-600 text-white shadow-md shadow-purple-950/60' : 'text-slate-400 hover:text-white'
                        }`}
                    >
                      📌 结构化写盘
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveTab('thought')}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${activeTab === 'thought' ? 'bg-purple-600 text-white shadow-md shadow-purple-950/60' : 'text-slate-400 hover:text-white'
                        }`}
                    >
                      🧠 思维链 (CoT)
                    </button>
                    <button
                      type="button"
                      onClick={() => setActiveTab('raw')}
                      className={`px-3 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer ${activeTab === 'raw' ? 'bg-purple-600 text-white shadow-md shadow-purple-950/60' : 'text-slate-400 hover:text-white'
                        }`}
                    >
                      📄 原始 JSON
                    </button>
                  </div>
                </div>
              </div>

              {/* Main Log Area */}
              <div className="flex-1 p-5 overflow-y-auto dark-scrollbar bg-slate-950/90">
                {activeTab === 'details' ? (
                  <div className="space-y-5">
                    {/* 1. 调用的工具集 */}
                    <div className="bg-slate-900/90 border border-slate-800/90 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                      <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <span>🛠️</span>
                        <span>Agent 调用的技能工具集 (Tools Invoked)</span>
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                        <div className="bg-slate-950/90 border border-purple-900/40 rounded-xl p-3 flex items-start gap-3 shadow-sm hover:border-purple-700/60 transition-colors">
                          <div className="w-8 h-8 rounded-lg bg-purple-600/20 text-purple-400 flex items-center justify-center shrink-0 font-bold text-sm border border-purple-500/30">⚡</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">officecli_query_structure_tool</div>
                            <div className="text-[11px] text-slate-400 mt-0.5 leading-normal">探测 Word 模版 DOM 段落/表格节点与空位槽</div>
                          </div>
                        </div>
                        <div className="bg-slate-950/90 border border-blue-900/40 rounded-xl p-3 flex items-start gap-3 shadow-sm hover:border-blue-700/60 transition-colors">
                          <div className="w-8 h-8 rounded-lg bg-blue-600/20 text-blue-400 flex items-center justify-center shrink-0 font-bold text-sm border border-blue-500/30">🏢</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">query_company_profile_tool</div>
                            <div className="text-[11px] text-slate-400 mt-0.5 leading-normal">调取指定投标主体的工商与资质档案</div>
                          </div>
                        </div>
                        <div className="bg-slate-950/90 border border-emerald-900/40 rounded-xl p-3 flex items-start gap-3 shadow-sm hover:border-emerald-700/60 transition-colors">
                          <div className="w-8 h-8 rounded-lg bg-emerald-600/20 text-emerald-400 flex items-center justify-center shrink-0 font-bold text-sm border border-emerald-500/30">📖</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">get_full_chapter_text</div>
                            <div className="text-[11px] text-slate-400 mt-0.5 leading-normal">100% 全量检索招标文件原始章节要求与约束</div>
                          </div>
                        </div>
                        <div className="bg-slate-950/90 border border-amber-900/40 rounded-xl p-3 flex items-start gap-3 shadow-sm hover:border-amber-700/60 transition-colors">
                          <div className="w-8 h-8 rounded-lg bg-amber-600/20 text-amber-400 flex items-center justify-center shrink-0 font-bold text-sm border border-amber-500/30">💾</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">officecli_batch_fill_sentence_tool</div>
                            <div className="text-[11px] text-slate-400 mt-0.5 leading-normal">原子批处理多槽位长句原位写盘与 DOM 校验</div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* 2. 具体的原位修改与写盘明细表格 */}
                    <div className="bg-slate-900/90 border border-slate-800/90 rounded-2xl p-4 shadow-xl backdrop-blur-md">
                      <div className="flex items-center justify-between mb-3">
                        <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-2">
                          <span>✍️</span>
                          <span>原位修改与写盘落盘明细 (DOM Modifications & Write-Back)</span>
                        </h4>
                        <span className="text-xs font-mono text-purple-300 bg-purple-950/50 border border-purple-800/40 px-2.5 py-0.5 rounded-full font-bold">
                          写盘槽位: {selectedWorker.proposals_count} 处
                        </span>
                      </div>

                      <div className="bg-slate-950 border border-slate-800/90 rounded-xl overflow-hidden shadow-inner">
                        <div className="overflow-x-auto dark-scrollbar">
                          <table className="w-full text-left border-collapse text-xs min-w-[760px]">
                            <thead>
                              <tr className="bg-slate-900 text-slate-400 border-b border-slate-800 font-mono text-[11px]">
                                <th className="p-3.5 w-12 text-center whitespace-nowrap">#</th>
                                <th className="p-3.5 w-44 whitespace-nowrap">DOM 节点路径</th>
                                <th className="p-3.5 w-52 whitespace-nowrap">替换前模板原文</th>
                                <th className="p-3.5 min-w-[320px] whitespace-nowrap">实际填入 / 扩写结果</th>
                                <th className="p-3.5 w-28 text-center whitespace-nowrap">写盘状态</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/60">
                              {selectedWorker.proposals && selectedWorker.proposals.length > 0 ? (
                                selectedWorker.proposals.map((p: any, idx: number) => {
                                  const pathCell = p.path || p.node_path || p.chapter_title || `/body/p[${idx + 1}]`;
                                  const origCell = p.original_context || p.original_text || p.template_text;
                                  const propCell = p.proposed_text ?? p.value ?? p.text ?? p;
                                  return (
                                    <tr key={idx} className="hover:bg-slate-900/50 transition-colors">
                                      <td className="p-3.5 text-center text-slate-500 font-mono text-xs">{idx + 1}</td>
                                      <td className="p-3.5 align-top">
                                        <span className="font-mono text-[11px] text-purple-300 bg-purple-950/60 border border-purple-800/50 px-2.5 py-1 rounded-md inline-block max-w-[170px] truncate shadow-xs" title={pathCell}>
                                          {pathCell}
                                        </span>
                                      </td>
                                      <td className="p-3.5 align-top">
                                        {renderOriginalContext(origCell)}
                                      </td>
                                      <td className="p-3.5 align-top">
                                        {renderProposalValue(propCell)}
                                      </td>
                                      <td className="p-3.5 text-center align-top">
                                        <span className="px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-400 text-[10px] font-bold border border-emerald-500/40 whitespace-nowrap inline-flex items-center gap-1 shadow-xs">
                                          ✅ 已刷盘
                                        </span>
                                      </td>
                                    </tr>
                                  );
                                })
                              ) : (
                                <tr>
                                  <td colSpan={5} className="p-8 text-center text-slate-500 text-xs font-sans">
                                    此章节共完成 {selectedWorker.proposals_count} 项原位改写。切换至【🧠 思维链 (CoT)】可查看全量段落落盘总结。
                                  </td>
                                </tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : activeTab === 'thought' ? (
                  <div className="space-y-4">
                    {/* 实时 CoT 推导思考步骤明细 */}
                    <div className="bg-slate-900/90 border border-purple-900/40 rounded-2xl p-5 shadow-2xl backdrop-blur-md">
                      <div className="text-purple-400 font-bold mb-4 pb-3 border-b border-slate-800 flex items-center justify-between">
                        <span className="flex items-center gap-2 text-xs sm:text-sm">
                          <span>🧠</span>
                          <span>Agent 【{selectedWorker.chapter_title}】 ReAct 思维链轨迹 ({selectedWorker.thought_steps?.length || 0} 步交互)</span>
                        </span>
                        <span className="text-slate-500 font-mono text-xs">{selectedWorker.created_at || ''}</span>
                      </div>

                      {selectedWorker.thought_steps && selectedWorker.thought_steps.length > 0 ? (
                        <div className="space-y-3.5">
                          {selectedWorker.thought_steps.map((stepItem, idx) => {
                            if (stepItem.type === 'thought') {
                              return (
                                <div key={idx} className="bg-slate-950/90 border border-purple-800/40 rounded-xl p-4 shadow-md">
                                  <div className="flex items-center justify-between text-xs font-bold text-purple-300 mb-2.5">
                                    <div className="flex items-center gap-2">
                                      <span className="w-6 h-6 rounded-full bg-purple-600/30 text-purple-300 flex items-center justify-center font-mono text-[11px] font-bold border border-purple-500/40">
                                        {stepItem.step || idx + 1}
                                      </span>
                                      <span className="text-purple-200">🧠 [大模型 Reasoning / 思考推导独白]</span>
                                    </div>
                                    <span className="text-[10px] text-purple-400/80 font-mono bg-purple-950/50 px-2 py-0.5 rounded border border-purple-800/30">Thought Step</span>
                                  </div>
                                  {stepItem.thought && (
                                    <div className="text-xs text-slate-200 font-mono leading-relaxed pl-8 whitespace-pre-wrap selection:bg-purple-600 selection:text-white">
                                      {stepItem.thought}
                                    </div>
                                  )}
                                  {stepItem.tool_calls && stepItem.tool_calls.length > 0 && (
                                    <div className="mt-3 pl-8 space-y-2">
                                      {stepItem.tool_calls.map((tc: any, tcIdx: number) => (
                                        <div key={tcIdx} className="bg-purple-950/50 border border-purple-700/50 rounded-xl p-3 text-xs font-mono shadow-sm">
                                          <div className="flex items-center gap-2 text-purple-300 font-bold mb-1.5">
                                            <span>🛠️ 决定调用工具:</span>
                                            <code className="bg-purple-900/70 text-purple-200 px-2.5 py-0.5 rounded text-[11px] border border-purple-600/40">
                                              {tc.name || tc.function?.name || 'tool'}
                                            </code>
                                          </div>
                                          {tc.args && (
                                            <div className="text-[11px] text-slate-400 bg-slate-950 p-2.5 rounded-lg border border-slate-800/90 overflow-x-auto dark-scrollbar">
                                              <pre className="whitespace-pre-wrap">{typeof tc.args === 'string' ? tc.args : JSON.stringify(tc.args, null, 2)}</pre>
                                            </div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              );
                            } else {
                              return (
                                <div key={idx} className="bg-slate-950/90 border border-emerald-900/40 rounded-xl p-4 shadow-md ml-4">
                                  <div className="flex items-center justify-between text-xs font-bold text-emerald-300 mb-2">
                                    <div className="flex items-center gap-2">
                                      <span className="w-6 h-6 rounded-full bg-emerald-600/30 text-emerald-300 flex items-center justify-center font-mono text-xs border border-emerald-500/40">
                                        ⚡
                                      </span>
                                      <span className="text-emerald-200">⚡ [工具执行结果返回] — <code className="text-emerald-400">{stepItem.name}</code></span>
                                    </div>
                                    <span className="text-[10px] text-emerald-400/80 font-mono bg-emerald-950/50 px-2 py-0.5 rounded border border-emerald-800/30">Tool Output</span>
                                  </div>
                                  <div className="text-xs text-slate-300 font-mono leading-relaxed pl-8">
                                    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 overflow-x-auto max-h-60 dark-scrollbar text-[11px] text-emerald-200/90 shadow-inner">
                                      <pre className="whitespace-pre-wrap">{stepItem.output || '（执行完成）'}</pre>
                                    </div>
                                  </div>
                                </div>
                              );
                            }
                          })}
                        </div>
                      ) : (
                        <div className="text-slate-400 py-4 font-mono text-xs whitespace-pre-wrap leading-relaxed">
                          {selectedWorker.summary || '无独立思维链日志'}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 font-mono text-xs text-emerald-400 overflow-x-auto dark-scrollbar selection:bg-purple-600 selection:text-white shadow-xl">
                    <pre className="whitespace-pre-wrap">{JSON.stringify(selectedWorker, null, 2)}</pre>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-slate-950/60">
              <div className="max-w-xl w-full bg-slate-900/80 border border-purple-900/40 rounded-3xl p-8 shadow-2xl backdrop-blur-md">
                <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-purple-600 to-indigo-600 text-white flex items-center justify-center text-3xl mx-auto mb-4 shadow-lg shadow-purple-900/50">
                  📄
                </div>

                <h3 className="text-xl font-bold text-white mb-2">
                  {currentDocObj ? (currentDocObj.display_label || currentDocObj.filename) : '已定位招标文件'}
                </h3>

                <p className="text-xs text-slate-400 mb-6 leading-relaxed">
                  系统已载入目标招标文件与指定投标主体。点击下方【一键启动 Agent 全自主撰写标书】，多智能体专家团队将自动识别排版槽位、关联企业知识库与价格库，在后台原位扩写并刷盘生成标准 Word (.docx) 标书响应文档。
                </p>

                <div className="flex flex-wrap items-center justify-center gap-3">
                  <button
                    type="button"
                    onClick={handleStartFilling}
                    disabled={isGenerating || !activeDocId}
                    className="px-6 py-3 rounded-2xl bg-gradient-to-r from-purple-600 via-indigo-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 active:scale-98 text-white text-xs font-bold shadow-xl shadow-purple-900/50 transition-all flex items-center gap-2 cursor-pointer border border-purple-400/40 disabled:opacity-50"
                  >
                    {isGenerating ? (
                      <>
                        <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
                        <span>AI 专家团队撰写中...</span>
                      </>
                    ) : (
                      <>
                        <span className="text-base">✨</span>
                        <span>一键启动 Agent 全自主撰写标书</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={handleDownloadRawTemplate}
                    disabled={isDownloadingRaw || !activeDocId}
                    className="px-4 py-3 rounded-2xl bg-slate-800 hover:bg-slate-700 active:bg-slate-600 text-slate-200 text-xs font-bold border border-slate-700 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                    title="提取并下载未经过 AI 扩写的原格式《投标文件格式》Word 模板"
                  >
                    {isDownloadingRaw ? (
                      <>
                        <span className="animate-spin w-3.5 h-3.5 border-2 border-slate-300 border-t-transparent rounded-full"></span>
                        <span>正在提取...</span>
                      </>
                    ) : (
                      <>
                        <span>📄 下载原格式标书</span>
                      </>
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={handleDownloadWord}
                    disabled={isDownloading || !activeDocId}
                    className="px-4 py-3 rounded-2xl bg-emerald-700 hover:bg-emerald-600 active:bg-emerald-800 text-white text-xs font-bold shadow-md shadow-emerald-950/40 border border-emerald-500/30 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    <span>📥 下载标书 Word</span>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      </div>

      {/* 招标文件全景选择 Modal 弹窗 */}
      {showDocModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-6 animate-fade-in">
          <div className="bg-slate-900 border border-purple-800/60 rounded-3xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
            {/* Modal Header */}
            <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/40">
              <div className="flex items-center gap-3">
                <span className="p-2 bg-purple-500/20 text-purple-300 rounded-xl text-lg">📂</span>
                <div>
                  <h3 className="font-bold text-base text-white">选择目标招标文件 ({docList.length} 份可用)</h3>
                  <p className="text-xs text-slate-400 mt-0.5">请在下方卡片中点击指定招标文件，系统将自动载入并生成标书</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowDocModal(false)}
                className="w-8 h-8 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center justify-center font-bold cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Modal Search */}
            <div className="p-4 border-b border-slate-800 bg-slate-900/60">
              <input
                type="text"
                placeholder="🔍 输入项目名称、项目编号或原始文件名搜索..."
                value={docFilterText}
                onChange={(e) => setDocFilterText(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
              />
            </div>

            {/* Modal List Grid */}
            <div className="flex-1 p-5 overflow-y-auto custom-scrollbar grid grid-cols-1 2xl:grid-cols-2 gap-4">
              {filteredDocList.length > 0 ? (
                filteredDocList.map((doc) => {
                  const isCurrent = doc.id === activeDocId;
                  return (
                    <div
                      key={doc.id}
                      onClick={() => {
                        setActiveDocId(doc.id);
                        localStorage.setItem('bidding_document_id', doc.id);
                        navigate(`/agent-audit/${doc.id}`);
                        setShowDocModal(false);
                      }}
                      className={`p-4 rounded-2xl border transition-all cursor-pointer flex flex-col justify-between group ${isCurrent
                        ? 'bg-purple-950/60 border-purple-500 ring-2 ring-purple-500/30 shadow-lg shadow-purple-950/50'
                        : 'bg-slate-950/60 border-slate-800 hover:border-purple-600/60 hover:bg-slate-800/40'
                        }`}
                    >
                      <div>
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <span className="font-bold text-sm text-slate-100 group-hover:text-purple-300 transition-colors leading-snug line-clamp-2">
                            {doc.project_name || doc.filename}
                          </span>
                          {isCurrent && (
                            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-500 text-white shrink-0 shadow-xs">
                              当前选定
                            </span>
                          )}
                        </div>

                        <div className="space-y-1 text-xs text-slate-400 font-mono mb-3">
                          <div>📌 项目编号: <span className="text-slate-300">{doc.project_code || '--'}</span></div>
                          <div>📄 原始文件: <span className="text-slate-300 truncate inline-block max-w-[240px] align-bottom" title={doc.filename}>{doc.filename}</span></div>
                          <div>⏰ 上传时间: <span className="text-slate-400">{doc.created_at || '最近上传'}</span></div>
                        </div>
                      </div>

                      <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between">
                        <span className="text-[11px] text-emerald-400 font-bold bg-emerald-500/10 px-2 py-0.5 rounded-md border border-emerald-500/20">
                          {doc.parse_status === 'completed' ? '✅ 解析已就绪' : '⏳ 解析中'}
                        </span>
                        <button
                          type="button"
                          className="px-3 py-1 rounded-xl bg-purple-600 group-hover:bg-purple-500 text-white text-xs font-bold transition-all shadow-md cursor-pointer"
                        >
                          选择并生成标书 →
                        </button>
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="col-span-2 py-12 text-center text-slate-500 text-xs">
                  未查找到匹配的招标文件，请尝试其他关键词。
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 单章节 Prompt 微调与重新生成 Modal */}
      {showRefineModal && selectedWorker && (
        <div className="fixed inset-0 bg-black/75 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-fade-in">
          <div className="bg-slate-900 border border-purple-500/40 rounded-3xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col">
            {/* 弹窗 Header */}
            <div className="p-5 border-b border-slate-800 flex items-center justify-between bg-slate-950/60">
              <div className="flex items-center gap-3">
                <span className="w-10 h-10 rounded-2xl bg-purple-600/20 text-purple-300 border border-purple-500/30 flex items-center justify-center text-lg font-bold shadow-inner">
                  ✨
                </span>
                <div>
                  <h3 className="font-bold text-base text-white">针对章节【{selectedWorker.chapter_title}】微调重新生成</h3>
                  <p className="text-xs text-purple-300/80 mt-0.5">专属 Worker Agent 将根据您的提示词，重新检索上下文、重写内容并原位刷入 Word 文档</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setShowRefineModal(false)}
                disabled={isRefining}
                className="w-8 h-8 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center transition-colors cursor-pointer disabled:opacity-50"
              >
                ✕
              </button>
            </div>

            {/* 弹窗 Body */}
            <div className="p-6 space-y-4 bg-slate-950/40">
              {/* 推荐常用提示词快捷标签 */}
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-2 flex items-center gap-1.5">
                  <span>💡 常用微调提示词推荐（点击快速填入）：</span>
                </label>
                <div className="flex flex-wrap gap-2">
                  {[
                    "商务条款与技术要求全部严格填报无偏离",
                    "指定项目负责人为张三，具备一级建造师资格与高级工程师职称",
                  ].map((tag, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => setRefinePrompt(prev => prev ? `${prev}；${tag}` : tag)}
                      className="px-2.5 py-1 rounded-lg bg-slate-900 hover:bg-purple-900/60 border border-slate-800 hover:border-purple-600/60 text-[11px] text-purple-200 transition-all cursor-pointer text-left active:scale-95"
                    >
                      + {tag}
                    </button>
                  ))}
                </div>
              </div>

              {/* 用户提示词输入区域 */}
              <div>
                <label className="block text-xs font-bold text-slate-300 mb-2 flex items-center justify-between">
                  <span>✍️ 自定义微调指令 / 提示词 (Prompt)：</span>
                  <span className="text-[11px] text-slate-500 font-normal">支持输入任意具体的修正、补全或格式要求</span>
                </label>
                <textarea
                  rows={5}
                  value={refinePrompt}
                  onChange={(e) => setRefinePrompt(e.target.value)}
                  placeholder="例如：“将商务偏离全部设为无偏离；增加对项目工期20天的特别保证承诺；更新企业法定代表人身份信息为最新工商档案...”"
                  className="w-full bg-slate-950 border border-slate-800 focus:border-purple-500 rounded-2xl p-3.5 text-xs text-slate-100 placeholder-slate-500 focus:outline-none transition-colors resize-none leading-relaxed shadow-inner"
                  autoFocus
                />
              </div>

              {/* 提示信息 */}
              <div className="p-3 rounded-xl bg-purple-950/30 border border-purple-800/30 text-[11px] text-purple-300 flex items-start gap-2">
                <span className="text-sm shrink-0">ℹ️</span>
                <span>重新生成仅会重新调度该章节的专属 Worker Agent 进行推理与写盘，不会影响其他已生成章节的内容，写盘后可直接下载最新 Word 文档。</span>
              </div>
            </div>

            {/* 弹窗 Footer */}
            <div className="p-4 border-t border-slate-800 bg-slate-950/80 flex items-center justify-end gap-3">
              <button
                type="button"
                onClick={() => setShowRefineModal(false)}
                disabled={isRefining}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleRegenerateChapter}
                disabled={isRefining}
                className="px-5 py-2 rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 hover:from-purple-500 hover:to-indigo-500 active:scale-98 text-white text-xs font-bold transition-all shadow-lg shadow-purple-900/40 border border-purple-400/30 flex items-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {isRefining ? (
                  <>
                    <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
                    <span>正在针对性重新生成中...</span>
                  </>
                ) : (
                  <>
                    <span>🚀 确认微调并重新生成</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
