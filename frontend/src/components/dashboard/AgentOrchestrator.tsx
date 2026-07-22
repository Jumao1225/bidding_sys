import React, { useState, useEffect } from 'react';


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
}) => {
  const [typedDecision, setTypedDecision] = useState('');

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
    }, 30);
    
    return () => clearInterval(interval);
  }, [supervisorDecision?.currentDecision]);

  if (!isActive && workerStatuses.every(w => w.status === 'locked' || w.status === 'waiting')) {
    return null; // Don't show if not active and nothing has happened
  }

  return (
    <div className="mb-8 bg-white/60 backdrop-blur-xl rounded-3xl border border-indigo-100 shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden">
      {/* Header */}
      <div className="bg-gradient-to-r from-indigo-50/50 to-blue-50/50 p-5 border-b border-indigo-50 flex justify-between items-center">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-2xl bg-white shadow-sm flex items-center justify-center text-2xl border border-indigo-100">🧠</div>
          <div>
            <h3 className="font-bold text-slate-800 text-lg tracking-tight">Supervisor Agent</h3>
            <p className="text-xs font-medium text-indigo-400 uppercase tracking-wider">Dynamic Orchestration Engine</p>
          </div>
        </div>
        
        {isActive ? (
          <div className="flex items-center gap-2 text-indigo-600 text-sm font-bold bg-white px-4 py-1.5 rounded-full shadow-sm border border-indigo-100">
            <span className="relative flex h-3 w-3">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500"></span>
            </span>
            LIVE ORCHESTRATING
          </div>
        ) : (
          <div className="text-emerald-600 text-sm font-bold flex items-center gap-2 bg-white px-4 py-1.5 rounded-full shadow-sm border border-emerald-100">
            <span>✅</span> COMPLETED
          </div>
        )}
      </div>

      {/* Decision Bubble */}
      <div className="px-6 pt-6 pb-2">
        <div className={`transition-all duration-500 transform ${supervisorDecision?.currentDecision ? 'translate-y-0 opacity-100' : '-translate-y-4 opacity-0'}`}>
          <div className="flex gap-4 items-start max-w-4xl">
            <div className="mt-1 flex-shrink-0 w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm">
              ⚡
            </div>
            <div className="bg-white rounded-2xl rounded-tl-none p-5 border border-indigo-100 text-slate-700 min-h-[60px] text-sm leading-relaxed shadow-[0_4px_20px_rgb(0,0,0,0.03)]">
              {typedDecision || <span className="text-slate-400 italic">Waiting for next decision...</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Worker Grid */}
      <div className="p-6 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-5">
        {workerStatuses.map((worker) => {
          const style = statusConfig[worker.status];
          const isError = worker.status === 'failed';
          
          return (
            <div 
              key={worker.name} 
              className={`rounded-xl p-4 border transition-all duration-300 ${style.bg} ${style.border} ${isError ? 'animate-[shake_0.5s_ease-in-out]' : ''}`}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="text-2xl" title={worker.status}>{style.icon}</span>
                {worker.retryCount > 0 && (
                  <span className="text-xs bg-rose-500/20 text-rose-300 px-2 py-0.5 rounded-full border border-rose-500/30">
                    Retry {worker.retryCount}/2
                  </span>
                )}
              </div>
              
              <h4 className="font-bold text-slate-800 text-sm mb-1">{worker.label}</h4>
              <p className={`text-xs ${style.text} font-medium uppercase tracking-wider mb-2`}>
                {worker.status}
              </p>
              
              <div className="min-h-[40px]">
                {worker.status === 'running' && (
                  <div className="w-full bg-slate-700 h-1.5 rounded-full mt-3 overflow-hidden">
                    <div className="bg-blue-500 h-1.5 rounded-full animate-[progress_2s_ease-in-out_infinite]"></div>
                  </div>
                )}
                
                {worker.summary && (
                  <p className="text-xs text-slate-400 leading-tight mt-1 line-clamp-2" title={worker.summary}>
                    {worker.summary}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
      
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
