import React, { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { apiFetch } from '../utils/api';
import { useDialog } from '../components/DialogProvider';
import { UploadBox } from '../components/UploadBox';
import { CostTable } from '../components/CostTable';
import { TimelineCard } from '../components/dashboard/TimelineCard';
import { EngineeringCard } from '../components/dashboard/EngineeringCard';
import { AgentOrchestrator } from '../components/dashboard/AgentOrchestrator';
import type { WorkerStatus, SupervisorDecision, TerminalMessage } from '../components/dashboard/AgentOrchestrator';
import { EvaluationCard } from '../components/dashboard/EvaluationCard';
import { QualificationCard } from '../components/dashboard/QualificationCard';
import { FinancialCard } from '../components/dashboard/FinancialCard';
import {
  clear_active_document_id,
  set_active_document_id,
} from '../utils/documentIdentity';

export function AnalysisDashboard() {
  const { alert } = useDialog();
  const { id } = useParams<{ id: string }>();
  const [terminalMessages, setTerminalMessages] = useState<any[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [retryingDomain, setRetryingDomain] = useState<string | null>(null);
  // 设备清单重新提取后，先以原始清单渲染，避免旧成本结果遮盖最新提取结果。
  const [isEquipmentOnly, setIsEquipmentOnly] = useState(false);
  const hasAutoDownloadedRef = useRef(false);

  const [result, setResult] = useState<any>(null);

  const initialWorkerStatuses: WorkerStatus[] = [
    { name: 'master_agent', label: '元数据提取', status: 'waiting', retryCount: 0 },
    { name: 'strategy_qual', label: '资质盘点', status: 'locked', retryCount: 0 },
    { name: 'strategy_risk', label: '风险排查', status: 'locked', retryCount: 0 },
    { name: 'cost_estimation', label: '成本核算', status: 'locked', retryCount: 0 },
  ];
  const [supervisorDecision, setSupervisorDecision] = useState<SupervisorDecision | undefined>(undefined);
  const [workerStatuses, setWorkerStatuses] = useState<WorkerStatus[]>(initialWorkerStatuses);

  useEffect(() => {
    // 1. 如果 URL 中包含明确的文档 ID，优先同步并广播
    if (id && id !== 'new') {
      set_active_document_id(id);
    } else if (id === 'new') {
      clear_active_document_id();
    }

    const targetDocId = (id && id !== 'new') ? id : localStorage.getItem('bidding_document_id');
    if (!targetDocId) return;

    setIsEquipmentOnly(false);
    setIsLoadingHistory(true);
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';

    apiFetch(`${baseUrl}/api/v1/documents/${targetDocId}/result`)
      .then(async res => {
        const resJson = await res.json();
        if (!res.ok) {
          if (res.status === 403 || res.status === 404) {
            // 任务 ID、旧租户文档或已删除文档不能继续作为当前文档使用。
            clear_active_document_id(targetDocId);
          }
          throw new Error(`恢复历史数据失败：HTTP ${res.status}`);
        }
        return resJson;
      })
      .then(resJson => {
        const docData = resJson?.data || resJson;
        if (docData && (docData.document_id || docData.id)) {
          setResult(docData);
          const realDocId = docData.document_id || docData.id;
          set_active_document_id(realDocId);
        }
      })
      .catch(err => {
        console.error("恢复历史数据失败:", err);
      })
      .finally(() => {
        setIsLoadingHistory(false);
      });
  }, [id]);


  const handleTerminalMessage = (msg: any) => {
    setTerminalMessages(prev => [...prev, { ...msg, id: Date.now().toString() }]);
  };

  const autoDownloadDraft = async (targetDocId: string) => {
    if (hasAutoDownloadedRef.current) return;
    hasAutoDownloadedRef.current = true;

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const response = await apiFetch(`${baseUrl}/api/v1/analysis/draft/download/${targetDocId}`);
      if (!response.ok) return;

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `投标书草稿_${targetDocId.slice(0, 8)}.docx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);

      setTerminalMessages(prev => [
        ...prev,
        { id: Date.now().toString() + "_dl", type: 'success', content: '🎉 标书起草完成！已自动触发浏览器下载 Word 投标书草稿。' }
      ]);
    } catch (err) {
      console.error("自动下载标书草稿失败:", err);
    }
  };

  const handleAnalysisSuccess = (res: any) => {
    setIsEquipmentOnly(false);
    setResult(res);
    if (res?.document_id) {
      set_active_document_id(res.document_id);
      autoDownloadDraft(res.document_id);
    }
    setTerminalMessages(prev => [
      ...prev,
      { id: Date.now().toString(), type: 'success', content: '🎉 所有领域数据已提取并落盘完毕，智能面板已更新。' }
    ]);
  };

  const handleAnalyzingChange = (analyzing: boolean) => {
    setIsAnalyzing(analyzing);
    if (analyzing) {
      hasAutoDownloadedRef.current = false;
      setWorkerStatuses(initialWorkerStatuses);
      setSupervisorDecision(undefined);
      setTerminalMessages([{ id: Date.now().toString(), type: 'info', content: '等待主控 Agent 调度...' }]);
    }
  };

  const handleSupervisorUpdate = (decision: any) => {
    setSupervisorDecision(decision);
    if (decision.nextWorker && decision.nextWorker !== 'FINISH') {
      setWorkerStatuses(prev => prev.map(w =>
        w.name === decision.nextWorker ? { ...w, status: 'waiting', retryCount: decision.retryCounts?.[w.name] || 0 } : w
      ));
    }
  };

  const fetchLatestResult = (targetDocId: string) => {
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    apiFetch(`${baseUrl}/api/v1/documents/${targetDocId}/result`)
      .then(res => res.json())
      .then(resJson => {
        const docData = resJson?.data || resJson;
        if (docData && (docData.document_id || docData.id)) {
          setResult(docData);
        }
      })
      .catch(err => {
        console.error("增量获取最新结果失败:", err);
      });
  };

  const handleWorkerStatusChange = (workerName: string, status: string, summary?: string, docId?: string) => {
    setWorkerStatuses(prev => prev.map(w =>
      w.name === workerName ? { ...w, status: status as any, summary: summary || w.summary } : w
    ));
    if (status === 'success') {
      const targetDocId = docId || activeDocId || localStorage.getItem('bidding_document_id');
      if (targetDocId) {
        fetchLatestResult(targetDocId);
        if (workerName === 'writer_agent' || workerName === 'writer' || workerName === 'draft') {
          autoDownloadDraft(targetDocId);
        }
      }
    }
  };

  const activeDocId = result?.document_id || result?.id || (id && id !== 'new' ? id : null) || localStorage.getItem('bidding_document_id') || undefined;

  const handleReextract = async (domain: string): Promise<boolean> => {
    const targetDocId = activeDocId || (id && id !== 'new' ? id : null) || localStorage.getItem('bidding_document_id');
    if (!targetDocId) {
      setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: '❌ 重新提取失败: 未找到有效文档，请先上传并解析标书文件。' }]);
      await alert('未找到有效文档ID，请先上传并解析标书文件。', {
        title: '无法重新提取',
        intent: 'warning',
      });
      return false;
    }

    setRetryingDomain(domain);
    // 成本核算专项接口的实际用途是重新匹配 BOM 清单，避免继续使用“重新提取”造成误解。
    const operationLabel = domain === 'cost_estimation' || domain === 'cost'
      ? '重新匹配 BOM 清单'
      : domain.includes('qual')
        ? '重新分析履约资质盘点'
        : domain.includes('risk')
          ? '重新分析风险提示'
          : `重新提取专项领域: ${domain}`;

    // 同步更新 Supervisor 拓扑图 Worker 状态，激活齿轮旋转与呼吸蓝光动效
    const matchedWorkerName = domain.includes('qual') ? 'strategy_qual'
      : domain.includes('risk') ? 'strategy_risk'
      : (domain.includes('cost') || domain === 'engineering') ? 'cost_estimation'
      : domain === 'master_agent' ? 'master_agent'
      : null;

    if (matchedWorkerName) {
      setWorkerStatuses(prev => prev.map(w =>
        w.name === matchedWorkerName ? { ...w, status: 'running', summary: `正在${operationLabel}...` } : w
      ));
    }

    setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'info', content: `正在${operationLabel} ...` }]);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/analysis/${targetDocId}/reextract/${domain}`, {
        method: 'POST'
      });
      if (res.ok) {
        const json = await res.json();
        if (json.code === 200 && json.data && !json.data.error) {
          if (domain === 'cost_estimation' || domain === 'cost') {
            setIsEquipmentOnly(false);
            setResult((prev: any) => ({
              ...prev,
              cost_analysis: json.data
            }));
          } else if (domain === 'writer' || domain === 'draft' || domain === 'writer_agent') {
            setResult((prev: any) => ({
              ...prev,
              parsed_metadata: {
                ...(prev?.parsed_metadata || {}),
                draft_path: json.data?.draft_path,
                bid_doc_outline: json.data?.bid_doc_outline || prev?.parsed_metadata?.bid_doc_outline
              }
            }));
          } else if (domain === 'strategy_qual' || domain === 'qualifications_analysis' || domain === 'qual_analysis') {
            setResult((prev: any) => ({
              ...prev,
              qualifications_analysis: json.data?.qualifications_analysis || json.data,
              analysis_status: json.data?.analysis_status || prev?.analysis_status,
              overall_status: 'completed'
            }));
          } else if (domain === 'strategy_risk' || domain === 'risks_analysis' || domain === 'risk_analysis') {
            setResult((prev: any) => ({
              ...prev,
              risks_analysis: json.data?.risks_analysis || json.data,
              analysis_status: json.data?.analysis_status || prev?.analysis_status,
              overall_status: 'completed'
            }));
          } else {
            if (domain === 'engineering') {
              setIsEquipmentOnly(true);
            }
            setResult((prev: any) => ({
              ...prev,
              metadata: {
                ...(prev?.metadata || {}),
                [domain]: json.data
              }
            }));
          }
          const successLabel = domain === 'cost_estimation' || domain === 'cost'
            ? 'BOM 清单重新匹配'
            : domain === 'writer'
              ? '标书起草'
              : domain;
          setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'success', content: `✅ ${successLabel}${domain === 'cost_estimation' || domain === 'cost' ? '成功！' : '领域重新提取/计算成功！'}` }]);
          
          if (matchedWorkerName) {
            setWorkerStatuses(prev => prev.map(w =>
              w.name === matchedWorkerName ? { ...w, status: 'success', summary: `${operationLabel}完成` } : w
            ));
          }
          return true;
        } else {
          const errMsg = json.data?.error || json.message || '系统错误';
          setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取失败: ${errMsg}` }]);
          if (matchedWorkerName) {
            setWorkerStatuses(prev => prev.map(w =>
              w.name === matchedWorkerName ? { ...w, status: 'failed', summary: `${operationLabel}失败: ${errMsg}` } : w
            ));
          }
          return false;
        }
      } else if (res.status === 409) {
        const json = await res.json().catch(() => ({ detail: '专项分析任务正在执行中，请勿重复提交' }));
        const tipMsg = json.detail || '专项分析任务正在执行中，请稍候查看结果';
        setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'info', content: `⏳ 提示: ${tipMsg}` }]);
        await alert(tipMsg, {
          title: '任务正在执行',
          intent: 'info',
        });
        return false;
      } else {
        const json = await res.json().catch(() => ({ detail: `网络服务异常 (${res.status})` }));
        const errMsg = json.detail || json.message || `网络服务异常 (${res.status})`;
        setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取失败: ${errMsg}` }]);
        if (matchedWorkerName) {
          setWorkerStatuses(prev => prev.map(w =>
            w.name === matchedWorkerName ? { ...w, status: 'failed', summary: `${operationLabel}失败` } : w
          ));
        }
        return false;
      }
    } catch (err: any) {
      setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取网络错误: ${err.message}` }]);
      if (matchedWorkerName) {
        setWorkerStatuses(prev => prev.map(w =>
          w.name === matchedWorkerName ? { ...w, status: 'failed', summary: `${operationLabel}网络异常` } : w
        ));
      }
      return false;
    } finally {
      setRetryingDomain(null);
    }
  };

  const handleReextractEquipmentOnly = async () => {
    // 设备清单提取与价格匹配解耦：此按钮只读取原文并刷新工程清单。
    await handleReextract('engineering');
  };


  const tl = result?.metadata?.timeline || {};
  const eng = result?.metadata?.engineering || {};
  const ev = result?.metadata?.evaluation || {};
  const qual = result?.metadata?.qualification || {};
  const fin = result?.metadata?.financial || {};

  const [dashboardActiveTab, setDashboardActiveTab] = useState<'qual' | 'risk'>('qual');
  const uploadBoxSectionRef = useRef<HTMLDivElement>(null);

  const risks = result?.risks_analysis || [];
  const highRiskCount = risks.filter((r: any) => r.severity === '高').length;
  const midRiskCount = risks.filter((r: any) => r.severity === '中').length;
  const lowRiskCount = risks.filter((r: any) => r.severity === '低' || (!r.severity && r.severity !== '高' && r.severity !== '中')).length;
  const isRiskRetrying = retryingDomain === 'strategy_risk' || retryingDomain === 'risks_analysis' || retryingDomain === 'risk_analysis';
  const isQualRetrying = retryingDomain === 'strategy_qual' || retryingDomain === 'qualifications_analysis' || retryingDomain === 'qual_analysis';

  const qualItems = result?.qualifications_analysis?.items || [];
  let matchScore = 100;
  if (qualItems.length > 0) {
    const totalScore = qualItems.reduce((acc: number, curr: any) => {
      if (curr.status === '可以做到') return acc + 100;
      if (curr.status === '努力可做到' || curr.status === '中') return acc + 50;
      return acc + 0;
    }, 0);
    matchScore = Math.round(totalScore / qualItems.length);
  } else if (!result) {
    matchScore = 0;
  }

  const documentId = activeDocId;
  const outline = result?.metadata?.bid_doc_outline || result?.parsed_metadata?.bid_doc_outline;
  const draftPath = result?.metadata?.draft_path || result?.parsed_metadata?.draft_path;

  return (
    <div className="w-full space-y-10 animate-fade-in-up delay-100 pb-20">

      {/* 文本阅读与履约盘点/风险提示区域 */}
      <div ref={uploadBoxSectionRef}>
        <UploadBox
          onTerminalMessage={handleTerminalMessage}
          onAnalysisSuccess={handleAnalysisSuccess}
          onAnalyzingChange={handleAnalyzingChange}
          initialResult={result}
          initialTaskId={id === 'new' ? null : id}
          onSupervisorUpdate={handleSupervisorUpdate}
          onWorkerStatusChange={handleWorkerStatusChange}
          onReextract={handleReextract}
          retryingDomain={retryingDomain}
          activeTab={dashboardActiveTab}
          onTabChange={setDashboardActiveTab}
        />
      </div>

      {isLoadingHistory && (
        <div className="bg-white/80 backdrop-blur-md p-10 rounded-3xl shadow-sm border border-slate-100 flex flex-col items-center justify-center min-h-[300px]">
          <svg className="animate-spin h-10 w-10 text-indigo-500 mb-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <p className="text-slate-600 font-medium">正在从数据库恢复历史解析结果...</p>
        </div>
      )}

      <AgentOrchestrator
        isActive={isAnalyzing}
        supervisorDecision={supervisorDecision}
        workerStatuses={workerStatuses}
        terminalMessages={terminalMessages}
      />

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div 
          onClick={() => {
            setDashboardActiveTab('risk');
            uploadBoxSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }}
          className={`bg-white/80 backdrop-blur-sm p-8 rounded-3xl shadow-sm border border-rose-100 relative overflow-hidden group hover:shadow-md hover:border-rose-300 transition-all cursor-pointer ${
            isRiskRetrying ? 'ring-2 ring-rose-400 ring-offset-2' : ''
          }`}
          title="点击定位并查看详细风险条款"
        >
          <div className="absolute top-0 right-0 w-32 h-32 bg-rose-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:scale-110 transition-transform duration-500"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <span className="p-2 bg-rose-100 text-rose-600 rounded-lg">⚠️</span>
                <div className="text-slate-500 font-bold tracking-wide">发现高危风险项</div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleReextract('strategy_risk');
                  }}
                  disabled={isRiskRetrying}
                  className="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed group/btn"
                  title="重新分析风险提示"
                >
                  <svg 
                    className={`w-4 h-4 ${isRiskRetrying ? 'animate-spin text-rose-600' : 'group-hover/btn:rotate-180 transition-transform duration-500'}`} 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </button>
                <span className="text-[10px] text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full font-bold opacity-0 group-hover:opacity-100 transition-opacity">
                  查看列表 ↗
                </span>
              </div>
            </div>

            <div className="flex items-baseline gap-3 mt-4">
              {isRiskRetrying ? (
                <div className="flex items-center gap-2 text-rose-600 text-2xl font-black animate-pulse py-2">
                  <span className="animate-spin text-xl">⚙️</span>
                  <span>风控深度排查中...</span>
                </div>
              ) : (
                <>
                  <div className="text-5xl font-extrabold text-rose-600">
                    {result ? highRiskCount : '-'}
                    <span className="text-xl text-rose-400 font-medium ml-2">处</span>
                  </div>
                  {result && (
                    <div className="text-xs text-slate-400 font-medium ml-auto flex items-center gap-2">
                      <span className="bg-rose-50 text-rose-700 px-2 py-0.5 rounded-full font-bold">高危 {highRiskCount}</span>
                      <span className="bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full font-bold">中度 {midRiskCount}</span>
                      <span className="bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full font-bold">轻度 {lowRiskCount}</span>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>

        <div 
          onClick={() => {
            setDashboardActiveTab('qual');
            uploadBoxSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
          }}
          className={`bg-white/80 backdrop-blur-sm p-8 rounded-3xl shadow-sm border border-emerald-100 relative overflow-hidden group hover:shadow-md hover:border-emerald-300 transition-all cursor-pointer ${
            isQualRetrying ? 'ring-2 ring-emerald-400 ring-offset-2' : ''
          }`}
          title="点击定位并查看详细履约盘点"
        >
          <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:scale-110 transition-transform duration-500"></div>
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <span className="p-2 bg-emerald-100 text-emerald-600 rounded-lg">✅</span>
                <div className="text-slate-500 font-bold tracking-wide">资质综合匹配度 (预估)</div>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleReextract('strategy_qual');
                  }}
                  disabled={isQualRetrying}
                  className="p-1.5 text-slate-400 hover:text-emerald-600 hover:bg-emerald-50 rounded-lg transition-all disabled:opacity-40 disabled:cursor-not-allowed group/btn"
                  title="重新分析履约资质盘点"
                >
                  <svg 
                    className={`w-4 h-4 ${isQualRetrying ? 'animate-spin text-emerald-600' : 'group-hover/btn:rotate-180 transition-transform duration-500'}`} 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                </button>
                <span className="text-[10px] text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full font-bold opacity-0 group-hover:opacity-100 transition-opacity">
                  查看盘点 ↗
                </span>
              </div>
            </div>

            <div className="mt-4">
              {isQualRetrying ? (
                <div className="flex items-center gap-2 text-emerald-600 text-2xl font-black animate-pulse py-2">
                  <span className="animate-spin text-xl">⚙️</span>
                  <span>资质模型深度核算中...</span>
                </div>
              ) : (
                <div className="text-5xl font-extrabold text-emerald-500">
                  {result ? matchScore : '-'}
                  <span className="text-3xl text-emerald-400 font-medium">%</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 专项提取维度面板矩阵 - 5 大维度 Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* 核心财务防线卡片 */}
        <FinancialCard financial={fin} onReextract={() => handleReextract('financial')} isRetrying={retryingDomain === 'financial'} />

        {/* 资质综合准入卡片 */}
        <QualificationCard qualification={qual} onReextract={() => handleReextract('qualification')} isRetrying={retryingDomain === 'qualification'} />

        {/* 商务时限排期卡片 */}
        <TimelineCard timeline={tl} onReextract={() => handleReextract('timeline')} isRetrying={retryingDomain === 'timeline'} />

        {/* 施工技术防线卡片 */}
        <EngineeringCard engineering={eng} onReextract={() => handleReextract('engineering')} isRetrying={retryingDomain === 'engineering'} />

        {/* 评标办法与售后硬性约束 - 全宽横幅强化展示 */}
        <div className="md:col-span-2">
          <EvaluationCard evaluation={ev} onReextract={() => handleReextract('evaluation')} isRetrying={retryingDomain === 'evaluation'} />
        </div>
      </div>

      {/* BOM 成本核算表 */}
      <div className="w-full">
        <CostTable
          documentId={activeDocId}
          documentFilename={result?.filename}
          equipmentList={eng.main_equipment_list || []}
          financial={fin}
          costAnalysis={result?.cost_analysis || {}}
          onReextract={() => handleReextract('cost_estimation')}
          onReextractEquipment={handleReextractEquipmentOnly}
          isEquipmentOnly={isEquipmentOnly}
          onCostUpdated={(updatedCost) => {
            if (result) {
              setIsEquipmentOnly(false);
              setResult({
                ...result,
                cost_analysis: updatedCost
              });
            }
          }}
          isRetrying={retryingDomain === 'cost_estimation'}
          isExtractingEquipment={retryingDomain === 'engineering'}
        />
      </div>
    </div>
  );
}
