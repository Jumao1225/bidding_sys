import React from 'react';
import { Link, useLocation } from 'react-router-dom';

interface MainLayoutProps {
  children: React.ReactNode;
}

export default function MainLayout({ children }: MainLayoutProps) {
  const location = useLocation();
  
  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/';
    if (path === '/analysis') return location.pathname.startsWith('/analysis');
    return false;
  };

  const getLinkClass = (path: string) => 
    isActive(path) 
      ? "flex items-center px-4 py-3 bg-gradient-to-r from-blue-600/20 to-indigo-600/10 text-blue-400 rounded-xl font-bold border border-blue-500/20 transition-all shadow-[inset_2px_0_0_#3b82f6] group relative overflow-hidden"
      : "flex items-center px-4 py-3 text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-xl font-medium transition-all group";

  return (
    <div className="min-h-screen w-full flex text-slate-900 bg-transparent selection:bg-blue-200">
      {/* Sidebar - Premium Glass Dark */}
      <aside 
        style={{ height: 'calc(100vh - 32px)' }}
        className="sticky top-4 w-[280px] bg-slate-900/95 backdrop-blur-xl border-r border-white/10 shadow-[20px_0_40px_rgba(0,0,0,0.1)] text-white flex flex-col z-20 ml-4 my-4 mr-0 rounded-3xl overflow-hidden shrink-0 relative self-start"
      >
        {/* Subtle background gradients for depth */}
        <div className="absolute top-0 left-0 w-full h-64 bg-gradient-to-b from-blue-900/20 to-transparent pointer-events-none"></div>
        <div className="absolute bottom-0 right-0 w-64 h-64 bg-gradient-to-tl from-indigo-900/20 to-transparent blur-3xl pointer-events-none"></div>
        <div className="p-8 border-b border-white/5 relative overflow-hidden z-10">
          {/* Subtle light effect */}
          <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/20 rounded-full blur-3xl -mr-10 -mt-10 pointer-events-none animate-pulse-slow"></div>
          <h1 className="text-2xl font-extrabold bg-gradient-to-br from-white via-blue-100 to-blue-400 bg-clip-text text-transparent relative z-10 tracking-tight">
            AI Bidding<span className="text-blue-500">.</span>
          </h1>
          <p className="text-xs text-slate-400 mt-2 font-medium tracking-wide">ENTERPRISE EDITION</p>
        </div>
        
        <nav className="flex-1 p-5 space-y-2 relative z-10 overflow-y-auto custom-scrollbar">
          <p className="px-4 text-[10px] font-bold tracking-widest text-slate-500 mb-3 mt-2 uppercase">Core Engine</p>
          
          <Link to="/" className={getLinkClass('/')}>
            {isActive('/') && <div className="absolute inset-0 bg-blue-500/10 translate-y-full group-hover:translate-y-0 transition-transform duration-300"></div>}
            <svg className={`w-5 h-5 mr-3 ${isActive('/') ? 'text-blue-400' : 'opacity-60 group-hover:opacity-100 group-hover:scale-110 transition-all duration-300'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            <span className={isActive('/') ? "relative z-10" : "group-hover:translate-x-1 transition-transform duration-300"}>系统总览</span>
          </Link>
          
          <Link to="/analysis/new" className={getLinkClass('/analysis')}>
            {isActive('/analysis') && <div className="absolute inset-0 bg-blue-500/10 translate-y-full group-hover:translate-y-0 transition-transform duration-300"></div>}
            <svg className={`w-5 h-5 mr-3 ${isActive('/analysis') ? 'text-blue-400' : 'opacity-60 group-hover:opacity-100 group-hover:scale-110 transition-all duration-300'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
            </svg>
            <span className={isActive('/analysis') ? "relative z-10" : "group-hover:translate-x-1 transition-transform duration-300"}>智能解析</span>
          </Link>
          
          <a href="#" onClick={(e) => { e.preventDefault(); alert('成本测算功能开发中，敬请期待！'); }} className="flex items-center px-4 py-3 text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-xl font-medium transition-all group">
            <svg className="w-5 h-5 mr-3 opacity-60 group-hover:opacity-100 group-hover:scale-110 transition-all duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="group-hover:translate-x-1 transition-transform duration-300">成本测算</span>
          </a>

          <p className="px-4 text-[10px] font-bold tracking-widest text-slate-500 mb-3 mt-6 uppercase">Resources</p>

          <a href="#" className="flex items-center px-4 py-3 text-slate-400 hover:bg-white/5 hover:text-slate-200 rounded-xl font-medium transition-all group">
            <svg className="w-5 h-5 mr-3 opacity-60 group-hover:opacity-100 group-hover:scale-110 transition-all duration-300" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <span className="group-hover:translate-x-1 transition-transform duration-300">资质中心</span>
          </a>
        </nav>

        <div className="p-5 border-t border-white/5 mt-auto bg-black/10 relative z-10">
          <div className="flex items-center justify-between p-3 rounded-xl hover:bg-white/5 transition-colors cursor-pointer group">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-blue-600 to-indigo-500 flex items-center justify-center text-white font-bold shadow-lg ring-2 ring-white/10 group-hover:ring-blue-500/50 transition-all">
                OP
              </div>
              <div>
                <p className="text-sm font-bold text-slate-200 group-hover:text-white transition-colors">Operator</p>
                <p className="text-[11px] text-slate-500">admin@bidding.ai</p>
              </div>
            </div>
            <svg className="w-5 h-5 text-slate-500 group-hover:text-white transition-colors opacity-0 group-hover:opacity-100" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
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
        <main className="flex-1 px-10 pb-10">
          {children}
        </main>
      </div>
    </div>
  );
}
