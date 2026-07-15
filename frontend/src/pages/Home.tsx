import React from 'react';
import { useNavigate } from 'react-router-dom';

export function Home() {
  const navigate = useNavigate();

  return (
    <div className="max-w-7xl mx-auto space-y-10 animate-fade-in-up">
      {/* 顶部 Cinematic Banner */}
      <div className="relative overflow-hidden p-10 rounded-3xl shadow-xl bg-slate-900 border border-slate-700/50 flex items-center justify-between group">
        {/* Animated Background Elements */}
        <div className="absolute top-0 right-0 w-96 h-96 bg-blue-600/30 rounded-full blur-3xl -mr-20 -mt-20 pointer-events-none group-hover:bg-blue-500/40 transition-colors duration-1000"></div>
        <div className="absolute bottom-0 left-20 w-72 h-72 bg-indigo-600/20 rounded-full blur-3xl -mb-20 pointer-events-none group-hover:bg-indigo-500/30 transition-colors duration-1000"></div>
        
        {/* Geometric Pattern Overlay */}
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNDAiIGhlaWdodD0iNDAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGRlZnM+PHBhdHRlcm4gaWQ9ImEiIHdpZHRoPSI0MCIgaGVpZ2h0PSI0MCIgcGF0dGVyblVuaXRzPSJ1c2VyU3BhY2VPblVzZSI+PGNpcmNsZSBjeD0iMSIgY3k9IjEiIHI9IjEiIGZpbGw9InJnYmEoMjU1LDI1NSwyNTUsMC4wNSkiLz48L3BhdHRlcm4+PC9kZWZzPjxyZWN0IHdpZHRoPSIxMDAlIiBoZWlnaHQ9IjEwMCUiIGZpbGw9InVybCgjYSkiLz48L3N2Zz4=')] opacity-50"></div>

        <div className="relative z-10 max-w-2xl">
          <h2 className="text-4xl font-extrabold text-white mb-4 tracking-tight leading-tight">
            多智能体协作 <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-teal-300">重塑投标分析工作流</span>
          </h2>
          <p className="text-lg text-slate-300/90 font-medium">
            基于大模型驱动的审查引擎，三秒内完成数百页招标文件的资质拆解、成本测算与深层风险扫雷。
          </p>
        </div>
        
        <div className="relative z-10">
          <button 
            onClick={() => navigate('/analysis/new')}
            className="bg-white/10 backdrop-blur-md border border-white/20 hover:bg-white/20 text-white px-8 py-4 rounded-2xl font-bold shadow-2xl transition-all transform hover:scale-105 hover:-translate-y-1 flex items-center gap-3"
          >
            <span>进入解析工作台</span>
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M14 5l7 7m0 0l-7 7m7-7H3"></path></svg>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6 mt-10">
        <div className="glass p-8 rounded-2xl flex flex-col justify-center items-center group cursor-pointer hover:-translate-y-2 transition-transform">
          <div className="w-16 h-16 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-2xl mb-4 group-hover:scale-110 transition-transform">📄</div>
          <h3 className="font-bold text-slate-700 text-lg">智能标书解析</h3>
          <p className="text-slate-500 text-sm text-center mt-2">支持 PDF/Word，自动剥离五大核心维度数据。</p>
        </div>
        <div className="glass p-8 rounded-2xl flex flex-col justify-center items-center group cursor-pointer hover:-translate-y-2 transition-transform">
          <div className="w-16 h-16 bg-rose-100 text-rose-600 rounded-full flex items-center justify-center text-2xl mb-4 group-hover:scale-110 transition-transform">⚠️</div>
          <h3 className="font-bold text-slate-700 text-lg">痛点与违约排雷</h3>
          <p className="text-slate-500 text-sm text-center mt-2">自动高亮特殊施工工况及严厉的违约扣款条款。</p>
        </div>
        <div className="glass p-8 rounded-2xl flex flex-col justify-center items-center group cursor-pointer hover:-translate-y-2 transition-transform">
          <div className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center text-2xl mb-4 group-hover:scale-110 transition-transform">💰</div>
          <h3 className="font-bold text-slate-700 text-lg">资金测算与排期</h3>
          <p className="text-slate-500 text-sm text-center mt-2">精准提取限价、预算及多阶段付款节点比例。</p>
        </div>
      </div>
    </div>
  );
}
