import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { apiFetch } from '../utils/api';
import { UploadBox } from '../components/UploadBox';
import { CostTable } from '../components/CostTable';
import { TimelineCard } from '../components/dashboard/TimelineCard';
import { EngineeringCard } from '../components/dashboard/EngineeringCard';
import { AgentOrchestrator } from '../components/dashboard/AgentOrchestrator';
import type { WorkerStatus, SupervisorDecision, TerminalMessage } from '../components/dashboard/AgentOrchestrator';
import { EvaluationCard } from '../components/dashboard/EvaluationCard';
import { QualificationCard } from '../components/dashboard/QualificationCard';
import { FinancialCard } from '../components/dashboard/FinancialCard';
import { DraftCard } from '../components/DraftCard';

export function AnalysisDashboard() {
  const { id } = useParams<{ id: string }>();
  const [terminalMessages, setTerminalMessages] = useState<any[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [retryingDomain, setRetryingDomain] = useState<string | null>(null);
  
  const [result, setResult] = useState<any>(null);

  const initialWorkerStatuses: WorkerStatus[] = [
    { name: 'master_agent', label: '元数据提取', status: 'waiting', retryCount: 0 },
    { name: 'strategy_qual', label: '资质盘点', status: 'locked', retryCount: 0 },
    { name: 'strategy_risk', label: '风险排查', status: 'locked', retryCount: 0 },
    { name: 'cost_estimation', label: '成本核算', status: 'locked', retryCount: 0 },
    { name: 'writer_agent', label: '标书起草', status: 'locked', retryCount: 0 },
  ];
  const [supervisorDecision, setSupervisorDecision] = useState<SupervisorDecision | undefined>(undefined);
  const [workerStatuses, setWorkerStatuses] = useState<WorkerStatus[]>(initialWorkerStatuses);

  useEffect(() => {
    // 1. 如果 URL 中包含明确的文档 ID，优先同步并广播
    if (id && id !== 'new') {
      localStorage.setItem('bidding_document_id', id);
      window.dispatchEvent(new Event('bidding_document_changed'));
    } else if (id === 'new') {
      localStorage.removeItem('bidding_document_id');
      window.dispatchEvent(new Event('bidding_document_changed'));
    }

    const targetDocId = (id && id !== 'new') ? id : localStorage.getItem('bidding_document_id');
    if (!targetDocId) return;

    setIsLoadingHistory(true);
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';

    apiFetch(`${baseUrl}/api/v1/documents/${targetDocId}/result`)
      .then(res => res.json())
      .then(resJson => {
        const docData = resJson?.data || resJson;
        if (docData && (docData.document_id || docData.id)) {
          setResult(docData);
          const realDocId = docData.document_id || docData.id;
          if (realDocId && realDocId !== localStorage.getItem('bidding_document_id')) {
            localStorage.setItem('bidding_document_id', realDocId);
            window.dispatchEvent(new Event('bidding_document_changed'));
          }
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

  const handleAnalysisSuccess = (res: any) => {
    setResult(res);
    if (res.document_id) {
      localStorage.setItem('bidding_document_id', res.document_id);
      window.dispatchEvent(new Event('bidding_document_changed'));
    }
    setTerminalMessages(prev => [
      ...prev,
      { id: Date.now().toString(), type: 'success', content: '🎉 所有领域数据已提取并落盘完毕，智能面板已更新。' }
    ]);
  };

  const handleAnalyzingChange = (analyzing: boolean) => {
    setIsAnalyzing(analyzing);
    if (analyzing) {
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

  const handleWorkerStatusChange = (workerName: string, status: string, summary?: string) => {
    setWorkerStatuses(prev => prev.map(w => 
      w.name === workerName ? { ...w, status: status as any, summary: summary || w.summary } : w
    ));
  };

  const activeDocId = result?.document_id || result?.id || (id && id !== 'new' ? id : null) || localStorage.getItem('bidding_document_id') || undefined;

  const handleReextract = async (domain: string) => {
    const targetDocId = activeDocId || (id && id !== 'new' ? id : null) || localStorage.getItem('bidding_document_id');
    if (!targetDocId) {
      setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: '❌ 重新提取失败: 未找到有效文档，请先上传并解析标书文件。' }]);
      alert("未找到有效文档ID，请先上传并解析标书文件。");
      return;
    }

    setRetryingDomain(domain);
    setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'info', content: `正在重新提取专项领域: ${domain} ...` }]);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/analysis/${targetDocId}/reextract/${domain}`, {
        method: 'POST'
      });
      if (res.ok) {
        const json = await res.json();
        if (json.code === 200 && json.data && !json.data.error) {
          if (domain === 'cost_estimation' || domain === 'cost') {
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
          } else {
            setResult((prev: any) => ({
              ...prev,
              metadata: {
                ...(prev?.metadata || {}),
                [domain]: json.data
              }
            }));
          }
          const domainLabel = domain === 'cost_estimation' ? 'BOM 成本测算' : domain === 'writer' ? '标书起草' : domain;
          setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'success', content: `✅ ${domainLabel} 领域重新提取/计算成功！` }]);
        } else {
          const errMsg = json.data?.error || json.message || '系统错误';
          setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取失败: ${errMsg}` }]);
        }
      } else {
        const json = await res.json().catch(() => ({ detail: `网络服务异常 (${res.status})` }));
        const errMsg = json.detail || json.message || `网络服务异常 (${res.status})`;
        setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取失败: ${errMsg}` }]);
      }
    } catch (err: any) {
      setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取网络错误: ${err.message}` }]);
    } finally {
      setRetryingDomain(null);
    }
  };


  const tl = result?.metadata?.timeline || {};
  const eng = result?.metadata?.engineering || {};
  const ev = result?.metadata?.evaluation || {};
  const qual = result?.metadata?.qualification || {};
  const fin = result?.metadata?.financial || {};

  const risks = result?.risks_analysis || [];
  const highRiskCount = risks.filter((r: any) => r.severity === '高').length;
  
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
      <UploadBox 
        onTerminalMessage={handleTerminalMessage}
        onAnalysisSuccess={handleAnalysisSuccess}
        onAnalyzingChange={handleAnalyzingChange}
        initialResult={result}
        initialTaskId={id === 'new' ? null : id}
        onSupervisorUpdate={handleSupervisorUpdate}
        onWorkerStatusChange={handleWorkerStatusChange}
      />
      
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
      <div className="grid grid-cols-2 gap-8">
        <div className="bg-white/80 backdrop-blur-sm p-8 rounded-3xl shadow-sm border border-rose-100 relative overflow-hidden group hover:shadow-md transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-rose-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:scale-110 transition-transform duration-500"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-2">
              <span className="p-2 bg-rose-100 text-rose-600 rounded-lg">⚠️</span>
              <div className="text-slate-500 font-bold tracking-wide">发现高危风险项</div>
            </div>
            <div className="text-5xl font-extrabold text-rose-600 mt-4">{result ? highRiskCount : '-'}<span className="text-xl text-rose-400 font-medium ml-2">处</span></div>
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm p-8 rounded-3xl shadow-sm border border-emerald-100 relative overflow-hidden group hover:shadow-md transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:scale-110 transition-transform duration-500"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-2">
              <span className="p-2 bg-emerald-100 text-emerald-600 rounded-lg">✅</span>
              <div className="text-slate-500 font-bold tracking-wide">资质综合匹配度 (预估)</div>
            </div>
            <div className="text-5xl font-extrabold text-emerald-500 mt-4">{result ? matchScore : '-'}<span className="text-3xl text-emerald-400 font-medium">%</span></div>
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
          equipmentList={eng.main_equipment_list || []} 
          costAnalysis={result?.cost_analysis || {}} 
          onReextract={() => handleReextract('cost_estimation')}
          isRetrying={retryingDomain === 'cost_estimation'}
        />
      </div>

      {/* 投标书草稿生成与终极交付 - 全宽横幅 */}
      <div className="w-full">
        <DraftCard 
          documentId={activeDocId}
          outline={outline}
          draftPath={draftPath}
          onReextract={() => handleReextract('writer')}
          isRetrying={retryingDomain === 'writer'}
        />
      </div>
    </div>
  );
}
