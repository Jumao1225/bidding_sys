import React, { useState } from 'react';
import { UploadBox } from '../components/UploadBox';
import { CostTable } from '../components/CostTable';
import { TimelineCard } from '../components/dashboard/TimelineCard';
import { EngineeringCard } from '../components/dashboard/EngineeringCard';
import { AgentTerminal } from '../components/dashboard/AgentTerminal';
import { EvaluationCard } from '../components/dashboard/EvaluationCard';

export function AnalysisDashboard() {
  const [terminalMessages, setTerminalMessages] = useState<any[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [result, setResult] = useState<any>(() => {
    try {
      const saved = localStorage.getItem('bidding_analysis_result');
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });

  const handleTerminalMessage = (msg: any) => {
    setTerminalMessages(prev => [...prev, msg]);
  };

  const handleAnalysisSuccess = (res: any) => {
    setResult(res);
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

  return (
    <div className="w-full space-y-10 animate-fade-in-up delay-100">
      
      {/* 上传区 (左侧文档预览，右侧解析分析) */}
      <UploadBox 
        onTerminalMessage={handleTerminalMessage}
        onAnalysisSuccess={handleAnalysisSuccess}
        onAnalyzingChange={handleAnalyzingChange}
      />
      
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
            <div className="text-5xl font-extrabold text-rose-600 mt-4">3<span className="text-xl text-rose-400 font-medium ml-2">处</span></div>
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-sm p-8 rounded-3xl shadow-sm border border-emerald-100 relative overflow-hidden group hover:shadow-md transition-all">
          <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-2xl -mr-10 -mt-10 group-hover:scale-110 transition-transform duration-500"></div>
          <div className="relative z-10">
            <div className="flex items-center gap-3 mb-2">
              <span className="p-2 bg-emerald-100 text-emerald-600 rounded-lg">✅</span>
              <div className="text-slate-500 font-bold tracking-wide">资质综合匹配度</div>
            </div>
            <div className="text-5xl font-extrabold text-emerald-500 mt-4">92<span className="text-3xl text-emerald-400 font-medium">%</span></div>
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
        <CostTable />
      </div>
    </div>
  );
}
