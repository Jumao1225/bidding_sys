import React, { useState, useEffect } from 'react';
import { AgentTerminal } from './AgentTerminal';
import type { TerminalMessage } from './AgentTerminal';
export type { TerminalMessage };

export interface WorkerStatus {
  name: string;
  label: string;
  status: 'waiting' | 'running' | 'success' | 'failed' | 'skipped' | 'locked';
  retryCount: number;
  summary?: string;
  durationMs?: number;
}

export interface SupervisorDecision {
  currentDecision?: string;
  nextWorker?: string | string[];
  completedSteps: string[];
  retryCounts: Record<string, number>;
}

interface AgentOrchestratorProps {
  isActive: boolean;
  supervisorDecision?: SupervisorDecision;
  workerStatuses: WorkerStatus[];
  terminalMessages?: TerminalMessage[];
}

const statusConfig = {
  waiting: { bg: 'bg-slate-50/80', border: 'border-slate-200 border-dashed', icon: '⏳', text: 'text-slate-500' },
  running: { bg: 'bg-blue-50', border: 'border-blue-400 shadow-[0_0_20px_rgba(59,130,246,0.2)]', icon: '⚙️', text: 'text-blue-600 animate-pulse' },
  success: { bg: 'bg-emerald-50/80', border: 'border-emerald-300', icon: '✅', text: 'text-emerald-600' },
  failed: { bg: 'bg-rose-50/80', border: 'border-rose-300', icon: '❌', text: 'text-rose-600' },
  skipped: { bg: 'bg-amber-50/80', border: 'border-amber-300 border-dashed', icon: '⏭️', text: 'text-amber-600' },
  locked: { bg: 'bg-white', border: 'border-slate-100', icon: '🔒', text: 'text-slate-300' },
};

export const AgentOrchestrator: React.FC<AgentOrchestratorProps> = ({
  isActive,
  supervisorDecision,
  workerStatuses,
  terminalMessages = []
}) => {
  const [typedDecision, setTypedDecision] = useState('');
  const [activeTab, setActiveTab] = useState<'combined' | 'topology' | 'terminal'>('combined');
  const [isTerminalExpanded, setIsTerminalExpanded] = useState(true);

  // Typewriter effect for supervisor decisions
  useEffect(() => {
    if (!supervisorDecision?.currentDecision) {
      setTypedDecision('');
      return;
    }
    
    let i = 0;
    const txt = supervisorDecision.currentDecision;
    setTypedDecision('');
    
    const interval = setInterval(() => {
      if (i < txt.length) {
        setTypedDecision((prev) => prev + txt.charAt(i));
        i++;
      } else {
        clearInterval(interval);
      }
    }, 25);
    
    return () => clearInterval(interval);
  }, [supervisorDecision?.currentDecision]);

  const hasWorkerContent = workerStatuses.some(w => w.status !== 'locked' && w.status !== 'waiting');
  const hasMessages = terminalMessages.length > 0;

  if (!isActive && !hasWorkerContent && !hasMessages) {
    return null; // 静默隐藏空全空初始状态
  }

  return (
    <div className="mb-10 bg-white/70 backdrop-blur-xl rounded-3xl border border-indigo-100 shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden transition-all">
      {/* Header Bar */}
      <div className="bg-gradient-to-r from-indigo-50/80 via-blue-50/60 to-slate-50/80 p-5 border-b border-indigo-100 flex flex-wrap justify-between items-center gap-4">
        <div className="flex items-center gap-4">
          <div className="w-11 h-11 rounded-2xl bg-white shadow-sm flex items-center justify-center text-2xl border border-indigo-100/80">
            🧠
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-bold text-slate-800 text-lg tracking-tight">Supervisor Agent 智能协同控制中心</h3>
              <span className="text-[10px] bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-bold">
                Multi-Agent Hub
              </span>
            </div>
            <p className="text-xs font-medium text-slate-400 mt-0.5">主控决策路由 ✕ 动态 Task 拓扑 ✕ 实时全网控制日志</p>
          </div>
        </div>

        {/* Tab & Live Status Toggle */}
        <div className="flex items-center gap-3">
          <div className="bg-white/80 p-1 rounded-xl border border-indigo-100 shadow-inner flex items-center gap-1 text-xs font-medium">
            <button
              onClick={() => setActiveTab('combined')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'combined'
                  ? 'bg-indigo-600 text-white font-bold shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              ⚡ 双显全景
            </button>
            <button
              onClick={() => setActiveTab('topology')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'topology'
                  ? 'bg-indigo-600 text-white font-bold shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              🧠 指挥拓扑
            </button>
            <button
              onClick={() => setActiveTab('terminal')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'terminal'
                  ? 'bg-indigo-600 text-white font-bold shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100'
              }`}
            >
              💻 交互日志 ({terminalMessages.length})
            </button>
          </div>

          {isActive ? (
            <div className="flex items-center gap-2 text-indigo-600 text-xs font-bold bg-white px-3.5 py-2 rounded-xl shadow-sm border border-indigo-100">
              <span className="relative flex h-2.5 w-2.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-indigo-500"></span>
              </span>
              实时调度中
            </div>
          ) : (
            <div className="text-emerald-600 text-xs font-bold flex items-center gap-1.5 bg-white px-3.5 py-2 rounded-xl shadow-sm border border-emerald-100">
              <span>✅</span> 执行完毕
            </div>
          )}
        </div>
      </div>

      {/* Decision Bubble Section */}
      {(activeTab === 'combined' || activeTab === 'topology') && (
        <div className="px-6 pt-5 pb-2 border-b border-slate-100/60 bg-slate-50/40">
          <div className={`transition-all duration-500 transform ${supervisorDecision?.currentDecision ? 'translate-y-0 opacity-100' : 'opacity-80'}`}>
            <div className="flex gap-3.5 items-start max-w-5xl">
              <div className="mt-0.5 flex-shrink-0 w-8 h-8 rounded-xl bg-indigo-100/80 text-indigo-600 flex items-center justify-center font-bold text-sm shadow-sm border border-indigo-200/50">
                ⚡
              </div>
              <div className="bg-white rounded-2xl rounded-tl-none p-4 border border-indigo-100/80 text-slate-700 min-h-[50px] text-xs leading-relaxed shadow-sm flex-1">
                <span className="font-bold text-indigo-900 mr-2 block mb-1 text-[11px] uppercase tracking-wider">
                  🎯 Supervisor 核心决策思考 (Chain of Thought):
                </span>
                {typedDecision || supervisorDecision?.currentDecision || <span className="text-slate-400 italic">等待主控 Agent 下达最新路由决策...</span>}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Worker Grid (Topology View) */}
      {(activeTab === 'combined' || activeTab === 'topology') && (
        <div className="p-6">
          <div className="flex items-center justify-between mb-3 text-xs font-bold text-slate-500">
            <span>全网 Worker 节点调度图</span>
            <span>已完成项: {workerStatuses.filter(w => w.status === 'success').length} / {workerStatuses.length}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {workerStatuses.map((worker) => {
              const style = statusConfig[worker.status];
              const isError = worker.status === 'failed';
              
              return (
                <div 
                  key={worker.name} 
                  className={`rounded-2xl p-4 border transition-all duration-300 ${style.bg} ${style.border} ${isError ? 'animate-[shake_0.5s_ease-in-out]' : ''}`}
                >
                  <div className="flex justify-between items-start mb-2">
                    <span className="text-xl" title={worker.status}>{style.icon}</span>
                    {worker.retryCount > 0 && (
                      <span className="text-[10px] bg-rose-500/20 text-rose-600 px-2 py-0.5 rounded-full font-bold border border-rose-300">
                        Retry {worker.retryCount}/2
                      </span>
                    )}
                  </div>
                  
                  <h4 className="font-bold text-slate-800 text-xs mb-0.5">{worker.label}</h4>
                  <p className={`text-[10px] ${style.text} font-bold uppercase tracking-wider mb-2`}>
                    {worker.status}
                  </p>
                  
                  <div className="min-h-[30px]">
                    {worker.status === 'running' && (
                      <div className="w-full bg-slate-200 h-1.5 rounded-full mt-2 overflow-hidden">
                        <div className="bg-blue-500 h-1.5 rounded-full animate-[progress_2s_ease-in-out_infinite]"></div>
                      </div>
                    )}
                    
                    {worker.summary && (
                      <p className="text-[11px] text-slate-400 leading-tight mt-1 line-clamp-2" title={worker.summary}>
                        {worker.summary}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Embedded Terminal Section */}
      {(activeTab === 'combined' || activeTab === 'terminal') && (
        <div className="border-t border-slate-200/80">
          <div className="bg-slate-900 text-slate-400 px-6 py-2.5 flex items-center justify-between text-xs font-mono">
            <div className="flex items-center gap-2 font-bold text-slate-300">
              <span className="text-emerald-400">💻</span>
              <span>Agent 实时交互日志与全量 Command Log</span>
            </div>
            <button
              onClick={() => setIsTerminalExpanded(!isTerminalExpanded)}
              className="text-slate-400 hover:text-white transition-colors text-[11px]"
            >
              {isTerminalExpanded ? '折叠日志 [-]' : '展开日志 [+]'}
            </button>
          </div>

          {isTerminalExpanded && (
            <div className="p-2 bg-[#080d1a]">
              <AgentTerminal 
                isAnalyzing={isActive} 
                messages={terminalMessages} 
              />
            </div>
          )}
        </div>
      )}
      
      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          25% { transform: translateX(-4px); }
          50% { transform: translateX(4px); }
          75% { transform: translateX(-4px); }
        }
        @keyframes progress {
          0% { width: 0%; transform: translateX(-100%); }
          100% { width: 100%; transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
};
