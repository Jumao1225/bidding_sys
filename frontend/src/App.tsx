import React, { useState, useRef, useEffect } from 'react';
import { Routes, Route } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import { ChatPanel } from './components/ChatPanel';
import { Home } from './pages/Home';
import { AnalysisDashboard } from './pages/AnalysisDashboard';

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  // 从 localStorage 读取 document_id，供 ChatPanel RAG 接口使用
  // 每次打开对话框时重新读取，确保拿到最新分析结果的 ID
  const [documentId, setDocumentId] = useState<string | null>(
    () => localStorage.getItem('bidding_document_id')
  );
  
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
      // 打开时重新读取最新的 document_id（用户可能刚完成分析）
      setDocumentId(localStorage.getItem('bidding_document_id'));
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
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/analysis/:id" element={<AnalysisDashboard />} />
      </Routes>

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
          <ChatPanel documentId={documentId} />
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
