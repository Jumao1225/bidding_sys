import React, { useState, useRef, useEffect } from 'react';
import { Routes, Route } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import { ChatPanel } from './components/ChatPanel';
import { Home } from './pages/Home';
import { AnalysisDashboard } from './pages/AnalysisDashboard';
import { QualificationCenter } from './pages/QualificationCenter';
import { PriceBookCenter } from './pages/PriceBookCenter';
import { Login } from './pages/Login';
import { SystemAdmin } from './pages/admin/SystemAdmin';
import { ProtectedRoute } from './components/ProtectedRoute';
import { AdminRoute } from './components/AdminRoute';

function App() {
  const [isChatOpen, setIsChatOpen] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const chatRef = useRef<HTMLDivElement>(null);
  const fabRef = useRef<HTMLDivElement>(null);
  // 从 localStorage 读取 document_id，供 ChatPanel RAG 接口使用
  // 每次打开对话框时重新读取，确保拿到最新分析结果的 ID
  const [documentId, setDocumentId] = useState<string | null>(
    () => localStorage.getItem('bidding_document_id')
  );

  // 对话框拖拽逻辑
  useEffect(() => {
    // 监听历史记录加载或新分析成功导致的文档 ID 变更
    const handleDocChange = () => {
      setDocumentId(localStorage.getItem('bidding_document_id'));
    };

    window.addEventListener('bidding_document_changed', handleDocChange);
    return () => {
      window.removeEventListener('bidding_document_changed', handleDocChange);
    };
  }, []);

  const [position, setPosition] = useState({ x: 0, y: 0 });

  // 悬浮球拖拽逻辑
  const [fabPosition, setFabPosition] = useState({ x: -40, y: -40 }); // 默认在右下角 (right-10, bottom-10)
  const hasDraggedFab = useRef(false); // 用于区分点击和拖动
  const fabSnapTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    // 初始设置FAB的绝对坐标（相对于页面左上角）
    setFabPosition({
      x: window.innerWidth - 100,
      y: window.innerHeight - 100
    });
  }, []);

  const handleChatMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('.chat-header')) {
      const startX = e.clientX - position.x;
      const startY = e.clientY - position.y;
      let newX = position.x;
      let newY = position.y;

      if (chatRef.current) {
        chatRef.current.style.transition = 'none';
      }
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'move';

      const handleMouseMove = (moveEvent: MouseEvent) => {
        newX = moveEvent.clientX - startX;
        newY = moveEvent.clientY - startY;

        if (chatRef.current) {
          chatRef.current.style.transform = `translate(${newX}px, ${newY}px)`;
        }
      };

      const handleMouseUp = () => {
        setPosition({ x: newX, y: newY });
        if (chatRef.current) {
          chatRef.current.style.transition = '';
        }
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', handleMouseUp);
      };

      document.addEventListener('mousemove', handleMouseMove, { passive: true });
      document.addEventListener('mouseup', handleMouseUp);
    }
  };

  const handleFabMouseDown = (e: React.MouseEvent) => {
    hasDraggedFab.current = false;

    // 如果在回弹动画过程中又抓起了它，立刻打断动画并清空定时器
    if (fabSnapTimeout.current) {
      clearTimeout(fabSnapTimeout.current);
      fabSnapTimeout.current = null;
    }
    if (fabRef.current) {
      fabRef.current.style.transition = 'none';
      // 获取子 button 并锁定它的样式，防止拖拽期间鼠标脱离导致 hover 动画高频闪烁（这在视觉上会造成严重的“卡顿感”）
      const button = fabRef.current.querySelector('button');
      if (button) {
        button.style.transition = 'none';
        button.style.transform = 'scale(1.1)';
      }
    }
    
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'move';

    const startX = e.clientX;
    const startY = e.clientY;
    let newX = fabPosition.x;
    let newY = fabPosition.y;
    let deltaX = 0;
    let deltaY = 0;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      hasDraggedFab.current = true;
      newX = Math.max(-10, Math.min(fabPosition.x + (moveEvent.clientX - startX), window.innerWidth - 54));
      newY = Math.max(0, Math.min(fabPosition.y + (moveEvent.clientY - startY), window.innerHeight - 64));

      deltaX = newX - fabPosition.x;
      deltaY = newY - fabPosition.y;

      if (fabRef.current) {
        fabRef.current.style.transform = `translate(${deltaX}px, ${deltaY}px)`;
      }
    };

    const handleMouseUp = () => {
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      
      if (fabRef.current) {
        const button = fabRef.current.querySelector('button');
        if (button) {
          button.style.transition = '';
          button.style.transform = '';
        }
      }

      if (hasDraggedFab.current) {
        // 智能吸附到屏幕边缘
        const snapToLeft = newX + 28 < window.innerWidth / 2;
        const snappedX = snapToLeft ? 20 : window.innerWidth - 76; // 76 = 56(宽) + 20(边距)
        const snappedY = newY;

        // 计算动画滑行的目标终点
        const finalDeltaX = snappedX - fabPosition.x;
        const finalDeltaY = snappedY - fabPosition.y;

        if (fabRef.current) {
          // 添加回弹过渡动画
          fabRef.current.style.transition = 'transform 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.1)';
          fabRef.current.style.transform = `translate(${finalDeltaX}px, ${finalDeltaY}px)`;

          fabSnapTimeout.current = setTimeout(() => {
            if (fabRef.current) {
              fabRef.current.style.transition = '';
              fabRef.current.style.transform = 'none';
            }
            setFabPosition({ x: snappedX, y: snappedY });
            setPosition({ x: 0, y: 0 }); // 重置面板拖拽偏移
            fabSnapTimeout.current = null;
          }, 350);
        } else {
          setFabPosition({ x: snappedX, y: snappedY });
          setPosition({ x: 0, y: 0 });
        }
      }
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove, { passive: true });
    document.addEventListener('mouseup', handleMouseUp);
  };

  const handleFabClick = () => {
    if (!hasDraggedFab.current) {
      // 打开时重新读取最新的 document_id（用户可能刚完成分析）
      setDocumentId(localStorage.getItem('bidding_document_id'));
      setIsChatOpen(!isChatOpen);
    }
  };

  const hasDraggedChat = position.x !== 0 || position.y !== 0;

  // 计算弹窗展开方向和最佳坐标
  const isTop = fabPosition.y < window.innerHeight / 2;
  const isLeft = fabPosition.x < window.innerWidth / 2;
  // 动态计算实际面板尺寸，匹配 CSS 的 max-w 和 max-h 限制
  const dialogWidth = Math.min(420, window.innerWidth * 0.8);
  const dialogHeight = Math.min(650, window.innerHeight * 0.85);
  const fabWidth = 56;

  // 采用“侧边停靠”策略，彻底解决上下空间不足导致的重叠问题
  // 如果悬浮球在左侧，面板向右展开；如果在右侧，面板向左展开
  let idealLeft = isLeft ? fabPosition.x + fabWidth + 10 : fabPosition.x - dialogWidth - 10;
  // 垂直方向尽量与悬浮球居中对齐
  let idealTop = fabPosition.y + (fabWidth / 2) - (dialogHeight / 2);

  // 完美边缘滑动：确保任何情况下面板都在屏幕内
  const clampedLeft = Math.max(20, Math.min(idealLeft, window.innerWidth - dialogWidth - 20));
  const clampedTop = Math.max(20, Math.min(idealTop, window.innerHeight - dialogHeight - 20));

  let chatStyle: React.CSSProperties = {};
  if (isFullscreen) {
    chatStyle = { top: '16px', bottom: '16px', right: '16px', left: '316px' };
  } else {
    chatStyle = { left: clampedLeft, top: clampedTop };
  }

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="*" element={
        <ProtectedRoute>
          <>
            <MainLayout>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/analysis/:id" element={<AnalysisDashboard />} />
                <Route path="/qualifications" element={<QualificationCenter />} />
                <Route path="/price-book" element={<PriceBookCenter />} />
                <Route path="/admin/*" element={
                  <AdminRoute>
                    <SystemAdmin />
                  </AdminRoute>
                } />
              </Routes>
            </MainLayout>

            {/* 展开的聊天窗口 (Fixed 独立层，确保不会超出屏幕) */}
            <div
              className={`fixed z-[60] pointer-events-none origin-center transition-all duration-100 ease-out ${isChatOpen ? 'scale-100 opacity-100' : 'scale-[0.85] opacity-0'}`}
              style={chatStyle}
            >
              <div
                ref={chatRef}
                onMouseDown={!isFullscreen ? handleChatMouseDown : undefined}
                onDragStart={(e) => e.preventDefault()}
                style={!isFullscreen
                  ? { transform: `translate(${position.x}px, ${position.y}px)`, willChange: 'transform' }
                  : { transform: 'none', width: '100%', height: '100%' }}
                className={`${isChatOpen ? 'pointer-events-auto' : 'pointer-events-none'} shadow-2xl rounded-3xl overflow-hidden flex flex-col bg-white ${isFullscreen
                  ? 'w-full h-full transition-[width,height]'
                  : 'w-[420px] h-[650px] min-w-[320px] min-h-[400px] max-w-[80vw] max-h-[85vh] resize transition-[width,height]'
                  }`}
              >
                <ChatPanel
                  documentId={documentId}
                  isFullscreen={isFullscreen}
                  onToggleFullscreen={() => setIsFullscreen(!isFullscreen)}
                  onClose={() => setIsChatOpen(false)}
                />
              </div>
            </div>

            {/* 悬浮助手开关按钮 */}
            <div
              ref={fabRef}
              className="fixed z-50 pointer-events-none"
              style={{ left: fabPosition.x, top: fabPosition.y, willChange: 'transform, left, top' }}
            >
              <button
                onMouseDown={handleFabMouseDown}
                onClick={handleFabClick}
                onDragStart={(e) => e.preventDefault()}
                className="pointer-events-auto w-14 h-14 bg-gradient-to-tr from-blue-600 to-indigo-600 rounded-full flex items-center justify-center text-white shadow-2xl hover:scale-110 hover:shadow-indigo-500/50 transition-all duration-300 group ring-4 ring-white/50 cursor-move"
              >
                {isChatOpen ? (
                  <svg className="w-6 h-6 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
                ) : (
                  <span className="text-2xl pointer-events-none group-hover:animate-bounce">🤖</span>
                )}
              </button>
            </div>
          </>
        </ProtectedRoute>
      } />
    </Routes>
  );
}

export default App;
