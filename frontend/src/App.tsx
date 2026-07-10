import React, { useState, useRef, useEffect } from 'react';
import MainLayout from './layouts/MainLayout';
import { UploadBox } from './components/UploadBox';
import { ChatPanel } from './components/ChatPanel';
import { CostTable } from './components/CostTable';

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  
  // 对话框拖拽逻辑
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const draggingChatRef = useRef(false);
  const dragChatStartRef = useRef({ x: 0, y: 0 });

  // 悬浮球拖拽逻辑
  const [fabPosition, setFabPosition] = useState({ x: -40, y: -40 }); // 默认在右下角 (right-10, bottom-10)
  const [isFabSnapped, setIsFabSnapped] = useState(false);
  const draggingFabRef = useRef(false);
  const dragFabStartRef = useRef({ x: 0, y: 0 });
  const hasDraggedFab = useRef(false); // 用于区分点击和拖动

  useEffect(() => {
    // 初始设置FAB的绝对坐标（相对于页面左上角）
    // 为了更灵活的拖动，我们将原来 fixed bottom-10 right-10 的逻辑改为完全通过坐标控制
    setFabPosition({
      x: window.innerWidth - 100,
      y: window.innerHeight - 100
    });

    const handleMouseMove = (e: MouseEvent) => {
      if (draggingChatRef.current) {
        setPosition({
          x: e.clientX - dragChatStartRef.current.x,
          y: e.clientY - dragChatStartRef.current.y
        });
      } else if (draggingFabRef.current) {
        hasDraggedFab.current = true;
        setIsFabSnapped(false);
        setFabPosition({
          x: Math.max(-30, Math.min(e.clientX - dragFabStartRef.current.x, window.innerWidth - 34)),
          y: Math.max(0, Math.min(e.clientY - dragFabStartRef.current.y, window.innerHeight - 64))
        });
      }
    };

    const handleMouseUp = () => {
      draggingChatRef.current = false;
      
      if (draggingFabRef.current) {
        draggingFabRef.current = false;
        // 边缘吸附逻辑
        setFabPosition(prev => {
          const screenWidth = window.innerWidth;
          const isLeft = prev.x < screenWidth / 2;
          // 吸附并稍微隐藏（表现为缩进边栏），FAB宽64px
          const snappedX = isLeft ? -20 : screenWidth - 44; 
          setIsFabSnapped(true);
          return { ...prev, x: snappedX };
        });
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const handleChatMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.chat-header')) {
      draggingChatRef.current = true;
      dragChatStartRef.current = {
        x: e.clientX - position.x,
        y: e.clientY - position.y
      };
    }
  };

  const handleFabMouseDown = (e: React.MouseEvent) => {
    draggingFabRef.current = true;
    hasDraggedFab.current = false;
    dragFabStartRef.current = {
      x: e.clientX - fabPosition.x,
      y: e.clientY - fabPosition.y
    };
  };

  const handleFabClick = () => {
    if (!hasDraggedFab.current) {
      setIsChatOpen(!isChatOpen);
    }
  };

  // 计算弹窗展开方向和最佳坐标
  const isTop = fabPosition.y < window.innerHeight / 2;
  const isLeft = fabPosition.x < window.innerWidth / 2;
  
  let originClass = 'origin-bottom-right';
  if (isTop && isLeft) originClass = 'origin-top-left';
  else if (isTop && !isLeft) originClass = 'origin-top-right';
  else if (!isTop && isLeft) originClass = 'origin-bottom-left';
  else originClass = 'origin-bottom-right';

  // 计算并限制对话框的绝对位置，确保永远不会超出屏幕外
  const dialogWidth = 420;
  const dialogHeight = 650;
  const fabWidth = 64;
  
  let idealLeft = isLeft ? fabPosition.x : fabPosition.x - dialogWidth + fabWidth;
  let idealTop = isTop ? fabPosition.y + fabWidth + 10 : fabPosition.y - dialogHeight - 10;

  const clampedLeft = Math.max(20, Math.min(idealLeft, window.innerWidth - dialogWidth - 20));
  const clampedTop = Math.max(20, Math.min(idealTop, window.innerHeight - dialogHeight - 20));

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

        {/* 核心工作区：全宽展示 */}
        <div className="w-full space-y-10 animate-fade-in-up delay-100">
          
          {/* 上传 + 核价单 */}
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

      </div>

      {/* 展开的聊天窗口 (Fixed 独立层，确保不会超出屏幕) */}
      <div 
        className={`fixed z-[60] pointer-events-none ${originClass} transition-all duration-300 ${isChatOpen ? 'scale-100 opacity-100' : 'scale-0 opacity-0 h-0 w-0'}`}
        style={{ left: clampedLeft, top: clampedTop }}
      >
        <div 
          ref={chatRef} 
          onMouseDown={handleChatMouseDown}
          style={{ transform: `translate(${position.x}px, ${position.y}px)` }}
          className="pointer-events-auto w-[420px] h-[650px] min-w-[320px] min-h-[400px] max-w-[80vw] max-h-[85vh] shadow-2xl rounded-3xl overflow-hidden flex flex-col bg-white resize overflow-auto"
        >
          <ChatPanel />
        </div>
      </div>

      {/* 悬浮助手开关按钮 */}
      <div 
        className={`fixed z-50 pointer-events-none ${isFabSnapped ? 'transition-all duration-300' : ''}`}
        style={{ left: fabPosition.x, top: fabPosition.y }}
      >
        <button 
          onMouseDown={handleFabMouseDown}
          onClick={handleFabClick}
          className={`pointer-events-auto w-16 h-16 bg-gradient-to-tr from-blue-600 to-indigo-600 rounded-full flex items-center justify-center text-white shadow-2xl hover:scale-110 hover:shadow-indigo-500/50 transition-all duration-300 group ring-4 ring-white/50 cursor-move ${isFabSnapped ? 'opacity-60 hover:opacity-100' : ''}`}
        >
          {isChatOpen ? (
            <svg className="w-8 h-8 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
          ) : (
            <span className="text-3xl pointer-events-none group-hover:animate-bounce">🤖</span>
          )}
        </button>
      </div>
    </MainLayout>
  );
}

export default App;
