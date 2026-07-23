import React, { useEffect, useRef } from 'react';
import { Terminal, Settings, CheckCircle2, XCircle, ChevronRight, Activity } from 'lucide-react';

export interface TerminalMessage {
  id: string;
  type: 'info' | 'tool_call' | 'success' | 'error' | 'supervisor_decision' | 'worker_start' | 'worker_complete' | 'chapter_execution' | 'planner_tasks' | string;
  content: string;
  extra?: Record<string, any>;
}

export interface AgentTerminalProps {
  isAnalyzing: boolean;
  messages: TerminalMessage[];
}

// 提取并高亮 JSON 字符串与关键字
const HighlightedText = ({ text }: { text: string }) => {
  // 简单的正则匹配 JSON/Object 结构的内容
  const parts = text.split(/(\{.*?\})/g);
  
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith('{') && part.endsWith('}')) {
          return (
            <span key={i} className="text-blue-300 bg-blue-900/40 px-1.5 py-0.5 rounded text-xs break-all mx-1 font-mono border border-blue-700/50 shadow-inner inline-block">
              {part}
            </span>
          );
        }
        // 高亮可能包含下划线的特殊 Agent 关键字
        const words = part.split(/(\b[a-zA-Z_][a-zA-Z0-9_]*\b)/g);
        return (
          <span key={i}>
            {words.map((w, j) => {
              if (w.includes('_') && w.length > 4) {
                return <span key={j} className="text-purple-400 font-medium">{w}</span>;
              }
              return w;
            })}
          </span>
        );
      })}
    </>
  );
};

export function AgentTerminal({ isAnalyzing, messages }: AgentTerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="bg-[#0b1121] rounded-2xl overflow-hidden shadow-2xl shadow-blue-900/20 border border-slate-700/60 font-mono flex flex-col transition-all min-h-[140px] max-h-[360px] relative">
      {/* 扫光效果 */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none rounded-2xl z-0">
        {isAnalyzing && (
          <div className="w-full h-1/3 bg-gradient-to-b from-transparent via-blue-500/10 to-transparent absolute animate-[scan_3s_ease-in-out_infinite]"></div>
        )}
      </div>

      {/* Terminal Header */}
      <div className="bg-slate-900/90 px-4 py-3 flex items-center justify-between border-b border-slate-700/50 relative z-10 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-rose-500/90 shadow-[0_0_5px_rgba(244,63,94,0.5)]"></div>
            <div className="w-3 h-3 rounded-full bg-amber-500/90 shadow-[0_0_5px_rgba(245,158,11,0.5)]"></div>
            <div className="w-3 h-3 rounded-full bg-emerald-500/90 shadow-[0_0_5px_rgba(16,185,129,0.5)]"></div>
          </div>
          <div className="text-slate-300 text-xs font-semibold tracking-wider flex items-center gap-1.5 ml-2">
            <Terminal size={14} className="text-blue-400" />
            Agent Trace Terminal
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-sans tracking-widest font-bold">
            {isAnalyzing ? 'LIVE TRACING' : 'STANDBY'}
          </span>
          <div className={`w-2 h-2 rounded-full ${isAnalyzing ? 'bg-emerald-400 animate-pulse shadow-[0_0_8px_rgba(52,211,153,0.8)]' : 'bg-slate-600'}`}></div>
        </div>
      </div>

      {/* Terminal Body */}
      <div ref={terminalRef} className="p-5 flex-1 overflow-y-auto custom-scrollbar text-[13px] space-y-3 relative z-10">
        {messages.length === 0 ? (
          <div className="text-slate-500 flex flex-col items-center h-full justify-center gap-3 opacity-60">
            <Activity size={32} className="text-slate-600" />
            <span>Waiting for Agent Initialization...</span>
          </div>
        ) : (
          messages.map((msg, index) => (
            <div key={msg.id} className="animate-fade-in-up flex items-start gap-2.5 group">
              {msg.type === 'tool_call' && (
                <>
                  <Settings size={14} className="text-amber-400 mt-0.5 shrink-0 animate-[spin_4s_linear_infinite] opacity-90" />
                  <span className="text-amber-200/90 font-medium leading-relaxed break-all">
                    <HighlightedText text={msg.content} />
                  </span>
                </>
              )}
              {(msg.type === 'success' || msg.type === 'worker_complete') && (
                <>
                  <CheckCircle2 size={14} className="text-emerald-400 mt-0.5 shrink-0 drop-shadow-[0_0_3px_rgba(52,211,153,0.5)]" />
                  <span className="text-emerald-400/90 leading-relaxed break-all">
                    <HighlightedText text={msg.content} />
                  </span>
                </>
              )}
              {msg.type === 'error' && (
                <>
                  <XCircle size={14} className="text-rose-400 mt-0.5 shrink-0 drop-shadow-[0_0_3px_rgba(244,63,94,0.5)]" />
                  <span className="text-rose-400/90 leading-relaxed break-all">
                    <HighlightedText text={msg.content} />
                  </span>
                </>
              )}
              {/* 所有其他/默认信息类型全量安全渲染 */}
              {!['tool_call', 'success', 'worker_complete', 'error'].includes(msg.type) && (
                <>
                  <ChevronRight size={15} className="text-blue-400 mt-0.5 shrink-0 opacity-80 group-hover:opacity-100 transition-opacity" />
                  <span className="text-slate-300 leading-relaxed break-all">
                    <HighlightedText text={msg.content} />
                  </span>
                </>
              )}
              <span className="ml-auto text-[10px] text-slate-600/50 opacity-0 group-hover:opacity-100 transition-opacity shrink-0 select-none">
                {String(index + 1).padStart(3, '0')}
              </span>
            </div>
          ))
        )}
        
        {isAnalyzing && (
          <div className="flex items-center text-slate-500 mt-4 pl-1">
            <ChevronRight size={16} className="text-blue-500 mr-1 opacity-70" />
            <span className="animate-pulse font-bold text-blue-500 text-lg leading-none mb-1">_</span>
          </div>
        )}
      </div>
    </div>
  );
}
