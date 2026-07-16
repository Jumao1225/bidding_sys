import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { UploadBox } from '../components/UploadBox';
import { CostTable } from '../components/CostTable';
import { TimelineCard } from '../components/dashboard/TimelineCard';
import { EngineeringCard } from '../components/dashboard/EngineeringCard';
import { AgentTerminal } from '../components/dashboard/AgentTerminal';
import { EvaluationCard } from '../components/dashboard/EvaluationCard';

export function AnalysisDashboard() {
  const { id } = useParams<{ id: string }>();
  const [terminalMessages, setTerminalMessages] = useState<any[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  
  const [result, setResult] = useState<any>(null);

  // 处理历史记录加载
  useEffect(() => {
    if (id && id !== 'new') {
      // 告诉全局 ChatPanel 当前活动的文档 ID
      localStorage.setItem('bidding_document_id', id);
      // 分发事件让 App.tsx 或 ChatPanel 能够立刻响应
      window.dispatchEvent(new Event('bidding_document_changed'));
      
      const loadHistory = async () => {
        setIsLoadingHistory(true);
        try {
          const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
          const res = await fetch(`${baseUrl}/api/v1/documents/${id}/result`);
          if (res.ok) {
            const json = await res.json();
            if (json.code === 200 && json.data) {
              setResult(json.data);
              setTerminalMessages([
                { id: Date.now().toString(), type: 'success', content: '✅ 历史数据加载完毕。' }
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
      setTerminalMessages([{ id: Date.now().toString(), type: 'info', content: '等待主控 Agent 调度...' }]);
    }
  };

  // Safe fallback extractors
  const tl = result?.metadata?.timeline || {};
  const eng = result?.metadata?.engineering || {};
  const ev = result?.metadata?.evaluation || {};
  const qual = result?.metadata?.qualification || {};

  // Calculate dynamic metrics for KPI Cards based on dedicated LangGraph nodes output
  const risks = result?.risks_analysis || [];
  const highRiskCount = risks.filter((r: any) => r.severity === '高').length;
  
  const qualItems = result?.qualifications_analysis?.items || [];
  let matchScore = 100;
  if (qualItems.length > 0) {
    const totalScore = qualItems.reduce((acc: number, curr: any) => {
      if (curr.status === '可以做到') return acc + 100;
      if (curr.status === '努力可做到' || curr.status === '中') return acc + 50;
      return acc + 0; // '做不到' or others
    }, 0);
    matchScore = Math.round(totalScore / qualItems.length);
  } else if (!result) {
    matchScore = 0;
  }

  return (
    <div className="w-full space-y-10 animate-fade-in-up delay-100">
      
      {/* 文本阅读与履约盘点/风险提示区域 */}
      <UploadBox 
        onTerminalMessage={handleTerminalMessage}
        onAnalysisSuccess={handleAnalysisSuccess}
        onAnalyzingChange={handleAnalyzingChange}
        initialResult={result}
        initialTaskId={id === 'new' ? null : id}
      />
      
      {isLoadingHistory && (
        <div className="bg-white/80 backdrop-blur-md p-10 rounded-3xl shadow-sm border border-slate-100 flex flex-col items-center justify-center min-h-[300px]">
          <svg className="animate-spin h-10 w-10 text-indigo-500 mb-4" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          <p className="text-slate-600 font-medium">正在从数据库恢复历史解析结果...</p>
        </div>
      )}
      
      {/* 实时智能体思考终端 */}
      <AgentTerminal isAnalyzing={isAnalyzing} messages={terminalMessages} />
        
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
      
      {/* 专项提取维度面板矩阵 */}
      <div className="grid grid-cols-2 gap-8">
        <TimelineCard 
          biddingDeadline={tl.bid_deadline}
          qaDeadline={tl.qa_deadline}
          projectDuration={tl.construction_period_days}
        />
        <EngineeringCard 
          painPoints={eng.special_working_conditions ? Object.values(eng.special_working_conditions).map(String) : []}
          equipment={eng.main_equipment_quantities ? Object.keys(eng.main_equipment_quantities) : []}
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <EvaluationCard 
          weights={{ 
            price: Number(ev.price_weight?.replace('%', '')) || 50, 
            tech: Number(ev.tech_weight?.replace('%', '')) || 30, 
            business: 100 - (Number(ev.price_weight?.replace('%', '')) || 50) - (Number(ev.tech_weight?.replace('%', '')) || 30) 
          }}
          penalties={ev.penalty_clauses ? Object.values(ev.penalty_clauses).map(String) : []}
        />
        <CostTable equipment={eng.main_equipment_quantities || {}} />
      </div>
    </div>
  );
}
