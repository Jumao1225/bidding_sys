import React, { useState, useEffect, useRef } from 'react';

interface TerminalMessage {
  id: string;
  type: 'info' | 'tool_call' | 'success' | 'error';
  content: string;
}

interface AgentTerminalProps {
  isAnalyzing: boolean;
  messages: TerminalMessage[];
}

export function AgentTerminal({ isAnalyzing, messages }: AgentTerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [messages]);

  return (
    <div className="bg-slate-900 rounded-3xl overflow-hidden shadow-2xl border border-slate-700 font-mono flex flex-col group transition-all h-[350px]">
      {/* Terminal Header */}
      <div className="bg-slate-800/80 px-4 py-3 flex items-center gap-3 border-b border-slate-700/50">
        <div className="flex gap-2">
          <div className="w-3 h-3 rounded-full bg-rose-500"></div>
          <div className="w-3 h-3 rounded-full bg-amber-500"></div>
          <div className="w-3 h-3 rounded-full bg-emerald-500"></div>
        </div>
        <div className="text-slate-400 text-xs font-semibold tracking-wider flex-1 text-center">
          Master Agent - ReAct Tool Calling
        </div>
        {isAnalyzing && (
          <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
        )}
      </div>

      {/* Terminal Body */}
      <div ref={terminalRef} className="p-5 flex-1 overflow-y-auto custom-scrollbar text-sm space-y-3">
        {messages.length === 0 ? (
          <div className="text-slate-500 flex items-center h-full justify-center">
            等待上传文档触发解析...
          </div>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className="animate-fade-in-up">
              {msg.type === 'info' && (
                <span className="text-slate-400">
                  <span className="text-blue-400 mr-2">❯</span>
                  {msg.content}
                </span>
              )}
              {msg.type === 'tool_call' && (
                <span className="text-amber-400/90 font-semibold">
                  <span className="animate-pulse mr-2">⚙️</span>
                  {msg.content}
                </span>
              )}
              {msg.type === 'success' && (
                <span className="text-emerald-400">
                  <span className="mr-2">✔</span>
                  {msg.content}
                </span>
              )}
              {msg.type === 'error' && (
                <span className="text-rose-400">
                  <span className="mr-2">✖</span>
                  {msg.content}
                </span>
              )}
            </div>
          ))
        )}
        
        {isAnalyzing && (
          <div className="flex items-center text-slate-500 mt-2">
            <span className="text-blue-400 mr-2">❯</span>
            <span className="animate-pulse">_</span>
          </div>
        )}
      </div>
    </div>
  );
}
