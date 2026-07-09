import React from 'react';

interface MainLayoutProps {
  children: React.ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  return (
    <div className="min-h-screen flex text-slate-900 bg-transparent selection:bg-blue-200">
      {/* Sidebar - Premium Glass Dark */}
      <aside className="w-[280px] glass-dark text-white flex flex-col z-20 m-4 rounded-3xl overflow-hidden shrink-0">
        <div className="p-8 border-b border-white/10 relative overflow-hidden">
          {/* Subtle light effect */}
          <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/20 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none"></div>
          <h1 className="text-2xl font-extrabold bg-gradient-to-br from-white via-blue-100 to-blue-400 bg-clip-text text-transparent relative z-10 tracking-tight">
            AI Bidding<span className="text-blue-500">.</span>
          </h1>
          <p className="text-xs text-slate-400 mt-2 font-medium tracking-wide">ENTERPRISE EDITION</p>
        </div>
        
        <nav className="flex-1 p-5 space-y-3">
          <a href="#" className="flex items-center px-4 py-3.5 bg-blue-600/20 text-blue-400 rounded-xl font-bold border border-blue-500/20 transition-all hover:bg-blue-600/30 group">
            <span className="mr-3 text-lg opacity-80 group-hover:opacity-100 transition-opacity">✨</span>
            智能解析
          </a>
          <a href="#" className="flex items-center px-4 py-3.5 text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-xl font-medium transition-all group">
            <span className="mr-3 text-lg opacity-60 group-hover:opacity-100 transition-opacity">📊</span>
            投标看板
          </a>
          <a href="#" className="flex items-center px-4 py-3.5 text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-xl font-medium transition-all group">
            <span className="mr-3 text-lg opacity-60 group-hover:opacity-100 transition-opacity">💰</span>
            成本测算
          </a>
          <a href="#" className="flex items-center px-4 py-3.5 text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-xl font-medium transition-all group">
            <span className="mr-3 text-lg opacity-60 group-hover:opacity-100 transition-opacity">🏛️</span>
            资质中心
          </a>
        </nav>

        <div className="p-6 border-t border-white/10 mt-auto">
          <div className="flex items-center space-x-3 p-3 rounded-xl bg-white/5 border border-white/5 hover:bg-white/10 transition-colors cursor-pointer">
            <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white font-bold shadow-inner">
              OP
            </div>
            <div>
              <p className="text-sm font-bold text-white">Operator</p>
              <p className="text-xs text-slate-400">admin@bidding.ai</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content */}
      <div className="flex-1 flex flex-col relative z-10 min-w-0">
        {/* Header - Glassmorphism */}
        <header className="h-20 glass sticky top-0 z-30 flex items-center justify-between px-10 rounded-b-3xl mx-4 mb-4 mt-0 shadow-sm border-t-0">
          <div className="flex items-center">
            <div className="h-8 w-1 bg-blue-600 rounded-full mr-4"></div>
            <h2 className="text-xl font-bold text-slate-800 tracking-tight">文档解析引擎</h2>
          </div>
          <div className="flex items-center space-x-6">
            <button className="text-slate-400 hover:text-blue-600 transition-colors">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"></path></svg>
            </button>
            <div className="h-6 w-px bg-slate-200"></div>
            <span className="text-sm font-semibold text-slate-600 bg-slate-100 px-3 py-1.5 rounded-full border border-slate-200">v2.4 Agentic Flow</span>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 px-10 pb-10 overflow-x-hidden">
          {children}
        </main>
      </div>
    </div>
  );
}
