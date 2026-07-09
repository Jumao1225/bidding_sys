import React from 'react';
import MainLayout from './layouts/MainLayout';
import { UploadBox } from './components/UploadBox';
import { ChatPanel } from './components/ChatPanel';
import { CostTable } from './components/CostTable';

function App() {
  return (
    <MainLayout>
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
            <button className="bg-white/10 backdrop-blur-md border border-white/20 hover:bg-white/20 text-white px-8 py-4 rounded-2xl font-bold shadow-2xl transition-all transform hover:scale-105 hover:-translate-y-1 flex items-center gap-3">
              <span>导出标书草案</span>
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
            </button>
          </div>
        </div>

        {/* 核心工作区：左右分栏 */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-10">
          
          {/* 左侧区域：上传 + 核价单 */}
          <div className="lg:col-span-2 space-y-10 animate-fade-in-up delay-100">
            <UploadBox />
            
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

            <CostTable />
          </div>

          {/* 右侧区域：AI 问答面板 */}
          <div className="lg:col-span-1 h-full animate-fade-in-up delay-200">
            <div className="sticky top-28 h-[calc(100vh-140px)]">
              <ChatPanel />
            </div>
          </div>

        </div>

      </div>
    </MainLayout>
  );
}

export default App;
