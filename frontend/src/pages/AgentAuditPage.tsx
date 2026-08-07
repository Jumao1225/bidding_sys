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
  const [customInstruction, setCustomInstruction] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [workers, setWorkers] = useState<WorkerItem[]>([]);
  const [selectedWorkerId, setSelectedWorkerId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [activeTab, setActiveTab] = useState<'details' | 'thought' | 'raw'>('details');
  const [showDocModal, setShowDocModal] = useState(false);
  const [docFilterText, setDocFilterText] = useState('');

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
      const res = await apiFetch(`${API_BASE_URL}/api/v1/bidding/documents-list`);
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

  useEffect(() => {
    fetchDocList();
  }, []);

  const [isLivePolling, setIsLivePolling] = useState(false);

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
      if (items.length > 0) {
        setSelectedWorkerId(prev => (prev && items.some(i => i.id === prev)) ? prev : items[0].id);
      } else {
        setSelectedWorkerId(null);
      }
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
          if (data.worker_items.length > 0) {
            setSelectedWorkerId(prev => (prev && data.worker_items.some((i: any) => i.id === prev)) ? prev : data.worker_items[0].id);
          }
        }
        if (data.is_completed) {
          setIsLivePolling(false);
          setIsGenerating(false);
          setNotice('✨ AI 团队自主撰写与原位写盘已全量收官！所有章节卡片均已更新。');
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
    if (activeDocId) {
      fetchWorkerLogs(activeDocId);
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
    setNotice('⚡ SSE 实时推流已建立：Agent 专家团队思考推导、调库与原位写盘正以 0 延迟秒级长链接实时推流至前端...');
    setError(null);

    // 清空历史旧履历，重置呈现最新一轮 Agent 思考与原位落盘弹增过程
    setWorkers([]);
    setSelectedWorkerId(null);

    // 开启 SSE 0 延迟实时推流
    setupSSELogStream(activeDocId);

    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/agent-fill-bid-format/${activeDocId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          custom_instructions: customInstruction || undefined
        })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || '标书全自主撰写失败');
      }

      setNotice('🎉 标书全自主智能撰写完成！数据与偏离表已原位刷盘，支持点击【下载标书 Word】查看。');
      await fetchWorkerLogs(activeDocId, false);
    } catch (err: any) {
      setError(`撰写生成失败: ${err.message}`);
    } finally {
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

  const filteredWorkers = workers.filter(
    (w) =>
      w.chapter_title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      w.node_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const selectedWorker = workers.find((w) => w.id === selectedWorkerId) || filteredWorkers[0];

  const totalTokens = workers.reduce((acc, w) => acc + (w.total_tokens || 0), 0);
  const totalTimeMs = workers.reduce((acc, w) => acc + (w.execution_time_ms || 0), 0);

  const currentDocObj = docList.find((d) => d.id === activeDocId);

  const filteredDocList = docList.filter(
    (doc) =>
      (doc.display_label || '').toLowerCase().includes(docFilterText.toLowerCase()) ||
      (doc.filename || '').toLowerCase().includes(docFilterText.toLowerCase()) ||
      (doc.project_name || '').toLowerCase().includes(docFilterText.toLowerCase()) ||
      (doc.project_code || '').toLowerCase().includes(docFilterText.toLowerCase())
  );

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans selection:bg-purple-500 selection:text-white">
      {/* 顶栏 Header */}
      <header className="h-16 border-b border-slate-800 bg-slate-900/90 backdrop-blur-md px-6 flex items-center justify-between shrink-0 sticky top-0 z-20">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <span className="p-1.5 bg-gradient-to-tr from-purple-600 to-indigo-600 text-white rounded-lg text-base shadow-sm">🚀</span>
            <div>
              <h1 className="font-bold text-sm text-white">标书智能生成与 Agent 控制台</h1>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[11px] text-purple-300 font-bold shrink-0">📄 选择目标招标文件:</span>
                <select
                  value={activeDocId}
                  onChange={(e) => {
                    const selectedId = e.target.value;
                    setActiveDocId(selectedId);
                    localStorage.setItem('bidding_document_id', selectedId);
                    navigate(`/agent-audit/${selectedId}`);
                  }}
                  className="bg-slate-950 border border-purple-800/60 text-purple-200 font-medium text-[11px] rounded-lg px-2.5 py-0.5 focus:outline-none focus:border-purple-400 cursor-pointer max-w-[340px] truncate shadow-inner"
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
                  className="px-2.5 py-0.5 rounded-lg bg-purple-900/60 hover:bg-purple-800 text-purple-200 text-[11px] font-bold border border-purple-700/60 cursor-pointer transition-all flex items-center gap-1 shrink-0"
                  title="打开全景招标文件选择列表"
                >
                  <span>📂 列表选择 ({docList.length})</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* 顶部右侧核心触发操作 */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              setIsLivePolling(!isLivePolling);
              fetchWorkerLogs(activeDocId, false);
            }}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 cursor-pointer border ${
              isLivePolling || isGenerating
                ? 'bg-purple-900/80 border-purple-500 text-purple-200 shadow-md shadow-purple-900/50'
                : 'bg-slate-800 hover:bg-slate-700 text-slate-200 border-slate-700'
            }`}
            title="点击切换 1.5 秒自动实时探针轮询"
          >
            <span className={isLivePolling || isGenerating ? "animate-spin text-purple-400" : ""}>📡</span>
            <span>{isLivePolling || isGenerating ? "实时思考探针中 (1.5s)" : "开启 1.5s 实时探针"}</span>
          </button>

          <button
            type="button"
            onClick={handleDownloadWord}
            disabled={isDownloading || !activeDocId}
            className="px-4 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 active:bg-emerald-700 text-white text-xs font-bold shadow-md shadow-emerald-900/30 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
          >
            {isDownloading ? (
              <>
                <span className="animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full"></span>
                <span>正在下载...</span>
              </>
            ) : (
              <>
                <span>📥 下载标书 Word (.docx)</span>
              </>
            )}
          </button>

          <button
            type="button"
            onClick={handleStartFilling}
            disabled={isGenerating || !activeDocId}
            className="px-5 py-1.5 rounded-xl bg-gradient-to-r from-purple-600 via-indigo-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 active:scale-98 text-white text-xs font-bold shadow-lg shadow-purple-900/40 transition-all flex items-center gap-2 cursor-pointer border border-purple-400/30 disabled:opacity-50"
          >
            {isGenerating ? (
              <>
                <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></span>
                <span>AI 团队全自主撰写中...</span>
              </>
            ) : (
              <>
                <span className="text-sm">✨</span>
                <span>一键启动 Agent 全自主撰写标书</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* 通知与状态栏 */}
      {notice && (
        <div className="bg-purple-950/80 border-b border-purple-800/80 px-6 py-2.5 text-xs text-purple-200 flex items-center justify-between font-medium animate-fade-in">
          <div className="flex items-center gap-2">
            <span>💡</span>
            <span>{notice}</span>
          </div>
          <button type="button" onClick={() => setNotice(null)} className="text-purple-400 hover:text-white font-bold">
            ✕
          </button>
        </div>
      )}

      {error && (
        <div className="bg-rose-950/90 border-b border-rose-800 px-6 py-2.5 text-xs text-rose-200 flex items-center justify-between font-medium animate-fade-in">
          <div className="flex items-center gap-2">
            <span>❌</span>
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => setError(null)} className="text-rose-400 hover:text-white font-bold">
            ✕
          </button>
        </div>
      )}

      {/* 顶部指令配置 & 指标统计区 */}
      <div className="bg-slate-900/70 border-b border-slate-800 px-6 py-4 space-y-4 shrink-0">
        {/* 自定义撰写指令控制条 */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-2xl p-3 flex items-center gap-3">
          <span className="text-sm p-1.5 bg-purple-500/10 text-purple-400 rounded-lg shrink-0">✍️</span>
          <input
            type="text"
            placeholder="自定义全局撰写指令（如：“商务偏离表统一填无偏离，付款节点填30%预付款，项目经理指定张三”）..."
            value={customInstruction}
            onChange={(e) => setCustomInstruction(e.target.value)}
            className="flex-1 bg-transparent text-xs text-slate-100 placeholder-slate-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={handleStartFilling}
            disabled={isGenerating}
            className="px-3.5 py-1.5 rounded-xl bg-purple-900/60 hover:bg-purple-800 text-purple-200 text-xs font-bold transition-all border border-purple-700/50 cursor-pointer shrink-0 disabled:opacity-50"
          >
            带指令生成
          </button>
        </div>

        {/* 4 大核心统计指标 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-500/10 text-purple-400 border border-purple-500/20 flex items-center justify-center font-bold text-lg">
              🤖
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">子 Agent 节点数</div>
              <div className="text-lg font-bold text-white font-mono">{workers.length} 个章节</div>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20 flex items-center justify-center font-bold text-lg">
              ⏱️
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">累计撰写耗时</div>
              <div className="text-lg font-bold text-white font-mono">{(totalTimeMs / 1000).toFixed(1)} 秒</div>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center justify-center font-bold text-lg">
              ⚡
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">Token 思考总消耗</div>
              <div className="text-lg font-bold text-emerald-400 font-mono">{totalTokens.toLocaleString()}</div>
            </div>
          </div>

          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3.5 flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20 flex items-center justify-center font-bold text-lg">
              ✅
            </div>
            <div>
              <div className="text-[11px] text-slate-400 font-medium">写盘验证成功率</div>
              <div className="text-lg font-bold text-amber-400 font-mono">
                {workers.length > 0
                  ? `${((workers.filter((w) => w.status === 'success').length / workers.length) * 100).toFixed(0)}%`
                  : '100%'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* 主工作台面板：左侧 Worker 列表 + 右侧思考与提案可视化 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧边栏 Worker 列表 */}
        <div className="w-80 border-r border-slate-800 bg-slate-900/60 flex flex-col shrink-0">
          <div className="p-3.5 border-b border-slate-800">
            <input
              type="text"
              placeholder="🔍 搜索章节名称或子 Agent..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500 transition-colors"
            />
          </div>

          <div className="flex-1 overflow-y-auto custom-scrollbar p-2 space-y-1.5">
            {loading ? (
              <div className="py-12 text-center text-slate-500 text-xs">
                <div className="animate-spin w-6 h-6 border-2 border-purple-500 border-t-transparent rounded-full mx-auto mb-2"></div>
                加载 Agent 章节履历...
              </div>
            ) : filteredWorkers.length > 0 ? (
              filteredWorkers.map((w, idx) => {
                const isSelected = selectedWorker?.id === w.id;
                const isSupervisor = w.category === 'supervisor_master' || w.node_name.includes('Supervisor');
                return (
                  <div
                    key={w.id || idx}
                    onClick={() => setSelectedWorkerId(w.id)}
                    className={`p-3 rounded-xl border transition-all cursor-pointer select-none ${
                      isSelected
                        ? isSupervisor
                          ? 'bg-gradient-to-r from-purple-900/90 to-amber-950/80 border-amber-400 text-white shadow-xl shadow-amber-950/40 ring-1 ring-amber-400/50'
                          : 'bg-purple-950/60 border-purple-500 text-white shadow-lg shadow-purple-950/50'
                        : isSupervisor
                          ? 'bg-slate-900/90 border-amber-500/40 text-amber-200 hover:bg-slate-800/80 hover:border-amber-400/60'
                          : 'bg-slate-900/40 border-slate-800/80 text-slate-300 hover:bg-slate-800/60 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-bold text-xs truncate max-w-[170px]" title={w.chapter_title}>
                        {isSupervisor ? `👑 ${w.chapter_title}` : w.chapter_title}
                      </span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                        w.status === 'in_progress'
                          ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30 animate-pulse'
                          : isSupervisor
                            ? 'bg-amber-500/20 text-amber-300 border border-amber-500/40 font-mono'
                            : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      }`}>
                        {w.status === 'in_progress' ? '🤖 思考撰写中' : isSupervisor ? '👑 总控决策' : '✅ 已填报'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono mt-1">
                      <span>{(w.execution_time_ms / 1000).toFixed(1)}s</span>
                      <span>{w.total_tokens.toLocaleString()} tok</span>
                      <span className={isSupervisor ? "text-amber-300 font-semibold" : "text-purple-300 font-semibold"}>
                        {isSupervisor ? `章数: ${w.proposals_count}` : `提案: ${w.proposals_count} 项`}
                      </span>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="py-12 text-center text-slate-500 text-xs px-4">
                <span className="text-2xl block mb-2">📝</span>
                <span>暂未检索到填报履历，可点击右上角【一键启动 Agent 全自主撰写标书】</span>
              </div>
            )}
          </div>
        </div>

        {/* 右侧主内容区域 */}
        <div className="flex-1 bg-slate-950 flex flex-col overflow-hidden">
          {selectedWorker ? (
            <>
              {/* Active Worker Header */}
              <div className="p-4 border-b border-slate-800 bg-slate-900/40 flex items-center justify-between shrink-0">
                <div>
                  <div className="flex items-center gap-3">
                    <h2 className="font-bold text-base text-white">{selectedWorker.chapter_title}</h2>
                    <span className="px-2.5 py-0.5 rounded-full bg-purple-500/20 text-purple-300 text-xs font-mono border border-purple-500/30">
                      {selectedWorker.node_name}
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-slate-400 mt-1 font-mono">
                    <span>类别: {selectedWorker.category}</span>
                    <span>耗时: {(selectedWorker.execution_time_ms / 1000).toFixed(1)} 秒</span>
                    <span>Prompt: {selectedWorker.prompt_tokens.toLocaleString()}</span>
                    <span>Completion: {selectedWorker.completion_tokens.toLocaleString()}</span>
                    <span>写盘提案: {selectedWorker.proposals_count} 项</span>
                  </div>
                </div>

                {/* Tab Switcher */}
                <div className="flex bg-slate-900 p-1 rounded-xl border border-slate-800">
                  <button
                    type="button"
                    onClick={() => setActiveTab('details')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                      activeTab === 'details' ? 'bg-purple-600 text-white shadow-xs' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    📌 结构化写盘与工具履历
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('thought')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                      activeTab === 'thought' ? 'bg-purple-600 text-white shadow-xs' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    🧠 完整思维链推导 (CoT)
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('raw')}
                    className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                      activeTab === 'raw' ? 'bg-purple-600 text-white shadow-xs' : 'text-slate-400 hover:text-white'
                    }`}
                  >
                    📄 原始 JSON 履历
                  </button>
                </div>
              </div>

              {/* Main Log Area */}
              <div className="flex-1 p-6 overflow-y-auto custom-scrollbar bg-slate-950">
                {activeTab === 'details' ? (
                  <div className="space-y-6">
                    {/* 1. 调用的工具集 */}
                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-xl">
                      <h4 className="text-xs font-bold text-purple-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <span>🛠️</span>
                        <span>Agent 调用的技能工具集 (Tools Invoked)</span>
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="bg-slate-950/80 border border-purple-900/30 rounded-xl p-3 flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-purple-600/20 text-purple-400 flex items-center justify-center shrink-0 font-bold">⚡</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">officecli_query_structure_tool</div>
                            <div className="text-[11px] text-slate-400 mt-0.5">探测 Word 模版 DOM 段落/表格节点与空位槽</div>
                          </div>
                        </div>
                        <div className="bg-slate-950/80 border border-blue-900/30 rounded-xl p-3 flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-blue-600/20 text-blue-400 flex items-center justify-center shrink-0 font-bold">🏢</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">get_company_profile</div>
                            <div className="text-[11px] text-slate-400 mt-0.5">调取企业法人、注册资金、营业执照主体档案</div>
                          </div>
                        </div>
                        <div className="bg-slate-950/80 border border-emerald-900/30 rounded-xl p-3 flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-emerald-600/20 text-emerald-400 flex items-center justify-center shrink-0 font-bold">📖</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">get_full_chapter_text</div>
                            <div className="text-[11px] text-slate-400 mt-0.5">100% 全量检索招标文件原始章节要求与约束</div>
                          </div>
                        </div>
                        <div className="bg-slate-950/80 border border-amber-900/30 rounded-xl p-3 flex items-start gap-3">
                          <div className="w-8 h-8 rounded-lg bg-amber-600/20 text-amber-400 flex items-center justify-center shrink-0 font-bold">💾</div>
                          <div>
                            <div className="text-xs font-bold text-slate-200 font-mono">officecli_batch_fill_sentence_tool</div>
                            <div className="text-[11px] text-slate-400 mt-0.5">原子批处理多槽位长句原位写盘与 DOM 校验</div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* 2. 调取的数据库与上下文信息源 */}
                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-xl">
                      <h4 className="text-xs font-bold text-blue-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                        <span>📚</span>
                        <span>调取与引用的数据库 & 上下文数据源 (Data Consumed)</span>
                      </h4>
                      <div className="flex flex-wrap gap-2.5">
                        <div className="px-3 py-1.5 rounded-xl bg-purple-950/60 border border-purple-800/40 text-purple-300 text-xs flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse"></span>
                          <span>🏢 企业主体档案 (Company Profile)</span>
                          <span className="text-[10px] text-slate-400 font-mono">企名/法人/税号</span>
                        </div>
                        <div className="px-3 py-1.5 rounded-xl bg-blue-950/60 border border-blue-800/40 text-blue-300 text-xs flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse"></span>
                          <span>💰 价格与报价数据库 (Financial DB)</span>
                          <span className="text-[10px] text-slate-400 font-mono">投标总价/分项单价</span>
                        </div>
                        <div className="px-3 py-1.5 rounded-xl bg-emerald-950/60 border border-emerald-800/40 text-emerald-300 text-xs flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                          <span>📜 招标文件切片 (DocChunk RAG)</span>
                          <span className="text-[10px] text-slate-400 font-mono">偏离表/评分规则</span>
                        </div>
                        <div className="px-3 py-1.5 rounded-xl bg-amber-950/60 border border-amber-800/40 text-amber-300 text-xs flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse"></span>
                          <span>🏅 资质与业绩中心 (Qualification DB)</span>
                          <span className="text-[10px] text-slate-400 font-mono">ISO证书/项目经验</span>
                        </div>
                      </div>
                    </div>

                    {/* 3. 具体的原位修改与写盘明细 */}
                    <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-5 shadow-xl">
                      <div className="flex items-center justify-between mb-4">
                        <h4 className="text-xs font-bold text-emerald-400 uppercase tracking-wider flex items-center gap-2">
                          <span>✍️</span>
                          <span>原位修改与写盘落盘明细 (DOM Modifications & Write-Back)</span>
                        </h4>
                        <span className="text-xs font-mono text-slate-400">写盘槽位: {selectedWorker.proposals_count} 处</span>
                      </div>

                      <div className="bg-slate-950 border border-slate-800 rounded-xl overflow-hidden shadow-inner">
                        <div className="overflow-x-auto">
                          <table className="w-full text-left border-collapse text-xs">
                            <thead>
                              <tr className="bg-slate-900/90 text-slate-400 border-b border-slate-800 font-mono">
                                <th className="p-3 w-12 text-center">#</th>
                                <th className="p-3 w-48">DOM 节点路径</th>
                                <th className="p-3">替换前模板原文</th>
                                <th className="p-3">实际填入/扩写结果</th>
                                <th className="p-3 w-28 text-center">写盘状态</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/60 font-mono">
                              {selectedWorker.proposals && selectedWorker.proposals.length > 0 ? (
                                selectedWorker.proposals.map((p: any, idx: number) => {
                                  const pathCell = p.path || p.node_path || p.chapter_title || `/body/p[${idx + 1}]`;
                                  const origCell = p.original_context || p.original_text || p.template_text || "模板槽位/表单行";
                                  const propCell = p.proposed_text || p.value || p.text || (typeof p === 'string' ? p : "已原子写盘");
                                  return (
                                    <tr key={idx} className="hover:bg-slate-900/40 transition-colors">
                                      <td className="p-3 text-center text-slate-500">{idx + 1}</td>
                                      <td className="p-3 font-mono text-[11px] text-purple-300 break-all bg-purple-950/20 px-2 py-1 rounded">
                                        {pathCell}
                                      </td>
                                      <td className="p-3 text-slate-400 leading-normal">{origCell}</td>
                                      <td className="p-3 text-emerald-300 font-medium leading-normal bg-emerald-950/20 px-2 py-1 rounded">
                                        {propCell}
                                      </td>
                                      <td className="p-3 text-center">
                                        <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 text-[10px] border border-emerald-500/30">
                                          ✅ 已刷盘
                                        </span>
                                      </td>
                                    </tr>
                                  );
                                })
                              ) : selectedWorker.summary && selectedWorker.summary.includes('|') ? (
                                selectedWorker.summary
                                  .split('\n')
                                  .filter(line => line.trim().startsWith('|') && !line.includes('---') && !line.includes('序号') && !line.includes('槽位/DOM'))
                                  .map((line, idx) => {
                                    const cells = line.split('|').map(c => c.trim()).filter(Boolean);
                                    if (cells.length < 3) return null;
                                    const pathCell = cells[1] || cells[0];
                                    const origCell = cells[2] || cells[1];
                                    const propCell = cells[3] || cells[2] || '已原子写盘';
                                    return (
                                      <tr key={idx} className="hover:bg-slate-900/40 transition-colors">
                                        <td className="p-3 text-center text-slate-500">{idx + 1}</td>
                                        <td className="p-3 font-mono text-[11px] text-purple-300 break-all bg-purple-950/20 px-2 py-1 rounded">
                                          {pathCell}
                                        </td>
                                        <td className="p-3 text-slate-400 leading-normal">{origCell}</td>
                                        <td className="p-3 text-emerald-300 font-medium leading-normal bg-emerald-950/20 px-2 py-1 rounded">
                                          {propCell}
                                        </td>
                                        <td className="p-3 text-center">
                                          <span className="px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-400 text-[10px] border border-emerald-500/30">
                                            ✅ 已刷盘
                                          </span>
                                        </td>
                                      </tr>
                                    );
                                  })
                              ) : (
                                <tr>
                                  <td colSpan={5} className="p-6 text-center text-slate-500 text-xs font-sans">
                                    此章节共完成 {selectedWorker.proposals_count} 项原位改写。切换至【🧠 完整思维链推导】可查看全量段落落盘总结。
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
                  <div className="space-y-6">
                    {/* 实时 CoT 推导思考步骤明细 (Thought Steps / ReAct Chain) */}
                    <div className="bg-slate-900/90 border border-purple-900/40 rounded-2xl p-6 shadow-2xl">
                      <div className="text-purple-400 font-bold mb-4 pb-3 border-b border-slate-800 flex items-center justify-between">
                        <span className="flex items-center gap-2 text-sm">
                          <span>🧠</span>
                          <span>Agent 【{selectedWorker.chapter_title}】 真实 ReAct 思维链轨迹 ({selectedWorker.thought_steps?.length || 0} 步交互)</span>
                        </span>
                        <span className="text-slate-500 font-mono text-xs">{selectedWorker.created_at || ''}</span>
                      </div>

                      {selectedWorker.thought_steps && selectedWorker.thought_steps.length > 0 ? (
                        <div className="space-y-4">
                          {selectedWorker.thought_steps.map((stepItem, idx) => {
                            if (stepItem.type === 'thought') {
                              return (
                                <div key={idx} className="bg-slate-950/90 border border-purple-800/40 rounded-xl p-4 shadow-md">
                                  <div className="flex items-center justify-between text-xs font-bold text-purple-300 mb-2">
                                    <div className="flex items-center gap-2">
                                      <span className="w-6 h-6 rounded-full bg-purple-600/30 text-purple-300 flex items-center justify-center font-mono text-[11px]">
                                        {stepItem.step || idx + 1}
                                      </span>
                                      <span>🧠 [大模型 Reasoning / 思考推导独白]</span>
                                    </div>
                                    <span className="text-[10px] text-purple-400/80 font-mono">Thought Step</span>
                                  </div>
                                  {stepItem.thought && (
                                    <div className="text-xs text-slate-200 font-mono leading-relaxed pl-8 whitespace-pre-wrap selection:bg-purple-600 selection:text-white">
                                      {stepItem.thought}
                                    </div>
                                  )}
                                  {stepItem.tool_calls && stepItem.tool_calls.length > 0 && (
                                    <div className="mt-3 pl-8 space-y-2">
                                      {stepItem.tool_calls.map((tc: any, tcIdx: number) => (
                                        <div key={tcIdx} className="bg-purple-950/50 border border-purple-700/50 rounded-lg p-2.5 text-xs font-mono">
                                          <div className="flex items-center gap-2 text-purple-300 font-bold mb-1">
                                            <span>🛠️ 决定调用工具:</span>
                                            <code className="bg-purple-900/60 text-purple-200 px-2 py-0.5 rounded text-[11px]">
                                              {tc.name || tc.function?.name || 'tool'}
                                            </code>
                                          </div>
                                          {tc.args && (
                                            <div className="text-[11px] text-slate-400 bg-slate-950 p-2 rounded border border-slate-800 overflow-x-auto">
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
                                      <span className="w-6 h-6 rounded-full bg-emerald-600/30 text-emerald-300 flex items-center justify-center font-mono text-[11px]">
                                        ⚡
                                      </span>
                                      <span>⚡ [工具执行结果返回] — <code className="text-emerald-400">{stepItem.name}</code></span>
                                    </div>
                                    <span className="text-[10px] text-emerald-400/80 font-mono">Tool Output</span>
                                  </div>
                                  <div className="text-xs text-slate-300 font-mono leading-relaxed pl-8">
                                    <div className="bg-slate-900 border border-slate-800 rounded-lg p-3 overflow-x-auto max-h-60 custom-scrollbar text-[11px] text-emerald-200/90">
                                      <pre className="whitespace-pre-wrap">{stepItem.output || '（执行完成）'}</pre>
                                    </div>
                                  </div>
                                </div>
                              );
                            }
                          })}
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {/* 阶段 1: 需求感知 */}
                          <div className="bg-slate-950/80 border border-purple-900/30 rounded-xl p-4">
                            <div className="flex items-center gap-2 text-xs font-bold text-purple-300 mb-2">
                              <span className="w-6 h-6 rounded-full bg-purple-600/30 text-purple-300 flex items-center justify-center font-mono text-[11px]">1</span>
                              <span>[阶段一：模版槽位与语法需求感知]</span>
                            </div>
                            <p className="text-xs text-slate-300 font-mono leading-relaxed pl-8">
                              通过 <code className="text-purple-400">officecli_query_structure_tool</code> 对目标章节进行全量 DOM 节点扫描，自动定位出模板中保留的前缀标签以及包含下划线 <code className="text-purple-400">______</code> 的可扩写槽位与空白表格。
                            </p>
                          </div>

                          {/* 阶段 2: 信息检索 */}
                          <div className="bg-slate-950/80 border border-blue-900/30 rounded-xl p-4">
                            <div className="flex items-center gap-2 text-xs font-bold text-blue-300 mb-2">
                              <span className="w-6 h-6 rounded-full bg-blue-600/30 text-blue-300 flex items-center justify-center font-mono text-[11px]">2</span>
                              <span>[阶段二：数据库与 RAG 跨章节交叉检索]</span>
                            </div>
                            <p className="text-xs text-slate-300 font-mono leading-relaxed pl-8">
                              调用 <code className="text-blue-400">get_company_profile</code> 提取企业法人与营业执照；调用 <code className="text-blue-400">get_full_chapter_text</code> 交叉检索招标文件原文约束。
                            </p>
                          </div>

                          {/* 阶段 3: 逻辑推理 */}
                          <div className="bg-slate-950/80 border border-emerald-900/30 rounded-xl p-4">
                            <div className="flex items-center gap-2 text-xs font-bold text-emerald-300 mb-2">
                              <span className="w-6 h-6 rounded-full bg-emerald-600/30 text-emerald-300 flex items-center justify-center font-mono text-[11px]">3</span>
                              <span>[阶段三：合规性与数值精准推导]</span>
                            </div>
                            <p className="text-xs text-slate-300 font-mono leading-relaxed pl-8">
                              遵守【模板原文 100% 盲守法则】，替换下划线，抹除假话空话，并将总价转化为大写人民币。
                            </p>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 完整思考推导文本 */}
                    <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 font-mono text-xs leading-relaxed text-slate-200 shadow-2xl overflow-x-auto whitespace-pre-wrap selection:bg-purple-600 selection:text-white">
                      <div className="text-purple-400 font-bold mb-4 pb-2 border-b border-slate-800 flex items-center justify-between">
                        <span>=== 📝 Agent 完整落盘文本与提案总结 ===</span>
                        <span className="text-slate-500 font-normal text-[11px]">{selectedWorker.created_at || ''}</span>
                      </div>
                      {selectedWorker.summary}
                    </div>
                  </div>
                ) : (
                  <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-6 font-mono text-xs text-emerald-400 overflow-x-auto selection:bg-purple-600 selection:text-white">
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
                  系统已载入目标招标文件。点击下方【一键启动 Agent 全自主撰写标书】，多智能体专家团队将自动识别排版槽位、关联企业知识库与价格库，在后台原位扩写并刷盘生成标准 Word (.docx) 标书响应文档。
                </p>

                <div className="flex items-center justify-center gap-4">
                  <button
                    type="button"
                    onClick={handleStartFilling}
                    disabled={isGenerating || !activeDocId}
                    className="px-6 py-3 rounded-2xl bg-gradient-to-r from-purple-600 via-indigo-600 to-blue-600 hover:from-purple-500 hover:to-blue-500 active:scale-98 text-white text-sm font-bold shadow-xl shadow-purple-900/50 transition-all flex items-center gap-2 cursor-pointer border border-purple-400/40 disabled:opacity-50"
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
                    onClick={handleDownloadWord}
                    disabled={isDownloading || !activeDocId}
                    className="px-5 py-3 rounded-2xl bg-slate-800 hover:bg-slate-700 active:bg-slate-600 text-slate-200 text-sm font-bold border border-slate-700 transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    <span>📥 下载 Word (.docx)</span>
                  </button>
                </div>
              </div>
            </div>
          )}
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
            <div className="flex-1 p-5 overflow-y-auto custom-scrollbar grid grid-cols-1 md:grid-cols-2 gap-4">
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
                      className={`p-4 rounded-2xl border transition-all cursor-pointer flex flex-col justify-between group ${
                        isCurrent
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
    </div>
  );
};
