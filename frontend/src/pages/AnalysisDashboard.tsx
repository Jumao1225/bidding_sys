import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { apiFetch } from '../utils/api';
import { UploadBox } from '../components/UploadBox';
import { CostTable } from '../components/CostTable';
import { TimelineCard } from '../components/dashboard/TimelineCard';
import { EngineeringCard } from '../components/dashboard/EngineeringCard';
import { AgentTerminal } from '../components/dashboard/AgentTerminal';
import { AgentOrchestrator } from '../components/dashboard/AgentOrchestrator';
import type { WorkerStatus, SupervisorDecision } from '../components/dashboard/AgentOrchestrator';
import { EvaluationCard } from '../components/dashboard/EvaluationCard';
import { QualificationCard } from '../components/dashboard/QualificationCard';
import { FinancialCard } from '../components/dashboard/FinancialCard';

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
    const targetDocId = (id && id !== 'new') ? id : localStorage.getItem('bidding_document_id');
    if (targetDocId && targetDocId !== 'new') {
      localStorage.setItem('bidding_document_id', targetDocId);
      window.dispatchEvent(new Event('bidding_document_changed'));
      
      const loadHistory = async () => {
        setIsLoadingHistory(true);
        try {
          const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
          const res = await apiFetch(`${baseUrl}/api/v1/documents/${targetDocId}/result`);
          if (res.ok) {
            const json = await res.json();
            if (json.code === 200 && json.data) {
              setResult(json.data);
              setTerminalMessages([
                { id: Date.now().toString(), type: 'success', content: '✅ 历史解析数据加载完毕。' }
              ]);
              // 为历史任务填充成功的 Worker 状态，以便显示调度大盘
              setWorkerStatuses([
                { name: 'master_agent', label: '元数据提取', status: 'success', retryCount: 0, summary: '已完成' },
                { name: 'strategy_qual', label: '资质盘点', status: 'success', retryCount: 0, summary: '已完成' },
                { name: 'strategy_risk', label: '风险排查', status: 'success', retryCount: 0, summary: '已完成' },
                { name: 'cost_estimation', label: '成本核算', status: 'success', retryCount: 0, summary: '已完成' },
                { name: 'writer_agent', label: '标书起草', status: 'success', retryCount: 0, summary: '已完成' },
              ]);
            }
          }
        } catch (err) {
          console.error("Failed to load history", err);
          setTerminalMessages([
            { id: Date.now().toString(), type: 'error', content: '❌ 加载历史数据失败。' }
          ]);
        } finally {
          setIsLoadingHistory(false);
        }
      };
      
      loadHistory();
    }
  }, [id]);


  const handleTerminalMessage = (msg: any) => {
    setTerminalMessages(prev => [...prev, msg]);
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

  const handleReextract = async (domain: string) => {
    const targetDocId = (id && id !== 'new') ? id : (result?.document_id || localStorage.getItem('bidding_document_id'));
    if (!targetDocId) {
      setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: '❌ 重新提取失败: 未找到有效文档，请先上传并解析标书文件。' }]);
      alert("未找到有效文档ID，请先上传并解析标书文件。");
      return;
    }

    setRetryingDomain(domain);
    setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'info', content: `正在重新提取专项领域: ${domain} ...` }]);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
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
          } else {
            setResult((prev: any) => ({
              ...prev,
              metadata: {
                ...(prev?.metadata || {}),
                [domain]: json.data
              }
            }));
          }
          const domainLabel = domain === 'cost_estimation' ? 'BOM 成本测算' : domain;
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
      console.error(`Re-extract ${domain} failed`, err);
      setTerminalMessages(prev => [...prev, { id: Date.now().toString(), type: 'error', content: `❌ ${domain} 提取异常: ${err?.message || '服务器未响应'}` }]);
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
      />
      
      <details className="bg-white/80 backdrop-blur-sm rounded-2xl shadow-sm border border-slate-200 overflow-hidden group">
        <summary className="px-6 py-4 font-bold text-slate-700 cursor-pointer hover:bg-slate-50 transition-colors list-none flex justify-between items-center">
          <div className="flex items-center gap-3">
            <span className="text-slate-400">👨‍💻</span>
            查看底层 Agent 详细交互日志
          </div>
          <span className="text-slate-400 group-open:rotate-180 transition-transform">▼</span>
        </summary>
        <div className="border-t border-slate-100">
          <AgentTerminal isAnalyzing={isAnalyzing} messages={terminalMessages} />
        </div>
      </details>
        
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
        {/* 新增的财务防线卡片 */}
        <FinancialCard financial={fin} onReextract={() => handleReextract('financial')} isRetrying={retryingDomain === 'financial'} />
        
        {/* 资质综合门槛卡片 */}
        <QualificationCard qualification={qual} onReextract={() => handleReextract('qualification')} isRetrying={retryingDomain === 'qualification'} />
        
        <TimelineCard timeline={tl} onReextract={() => handleReextract('timeline')} isRetrying={retryingDomain === 'timeline'} />
        
        <EngineeringCard engineering={eng} onReextract={() => handleReextract('engineering')} isRetrying={retryingDomain === 'engineering'} />
        
        <EvaluationCard evaluation={ev} onReextract={() => handleReextract('evaluation')} isRetrying={retryingDomain === 'evaluation'} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <CostTable 
          equipmentList={eng.main_equipment_list || []} 
          costAnalysis={result?.cost_analysis || {}} 
          onReextract={() => handleReextract('cost_estimation')}
          isRetrying={retryingDomain === 'cost_estimation'}
        />
      </div>
    </div>
  );
}
