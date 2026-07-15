import React, { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';

// ==================== 类型定义 ====================

/** 单条引文来源 */
interface Source {
  section_title: string;
  text_preview: string;
}

/** 聊天消息 */
interface Message {
  role: 'user' | 'ai';
  content: string;
  /** AI 回复对应的 RAG 引文来源 */
  sources?: Source[];
  /** 是否正在流式输出中 */
  isStreaming?: boolean;
}

interface ChatPanelProps {
  /** 当前招标文件的数据库 ID，来自 AnalysisDashboard */
  documentId: string | null;
}

// ==================== 主组件 ====================

export function ChatPanel({ documentId }: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'ai',
      content: '您好！我是您的专属标书解析助手。我已深度阅读了当前的招标文件，您可以向我提问关于**资质要求、交货期、付款方式、评分标准**等任何深层细节。',
    },
  ]);
  const [input, setInput] = useState('');
  /** true: 正在流式接收 AI 回复，此时禁止再次发送 */
  const [isStreaming, setIsStreaming] = useState(false);
  /** 当前展示在侧抽屉中的引文来源（null 表示关闭抽屉） */
  const [activeSource, setActiveSource] = useState<Source | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  /** 自动滚动到底部 */
  const scrollToBottom = useCallback(() => {
    if (scrollContainerRef.current) {
      scrollContainerRef.current.scrollTo({
        top: scrollContainerRef.current.scrollHeight,
        behavior: 'smooth',
      });
    }
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // ==================== 核心发送逻辑 ====================

  const handleSend = useCallback(async () => {
    const trimmedInput = input.trim();
    if (!trimmedInput || isStreaming) return;

    // 检查 document_id
    if (!documentId) {
      setMessages(prev => [
        ...prev,
        { role: 'user', content: trimmedInput },
        {
          role: 'ai',
          content: '⚠️ 请先**上传并分析**一份招标文件，完成后我就可以基于文档内容回答您的问题了。',
        },
      ]);
      setInput('');
      return;
    }

    // 追加用户消息
    const userMessage: Message = { role: 'user', content: trimmedInput };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsStreaming(true);

    // 追加空 AI 消息占位（流式填充）
    const aiMessageIndex = messages.length + 1;
    setMessages(prev => [
      ...prev,
      { role: 'ai', content: '', isStreaming: true },
    ]);

    // 构建历史记录（排除刚加入的占位 AI 消息）
    const history = messages.map(m => ({ role: m.role, content: m.content }));

    // 发起 SSE 流式请求
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
    abortControllerRef.current = new AbortController();

    try {
      const response = await fetch(`${baseUrl}/api/v1/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          document_id: documentId,
          question: trimmedInput,
          history,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`请求失败: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let aiContent = '';
      let aiSources: Source[] = [];

      // 逐 chunk 解析 SSE 流
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        // SSE 格式：每行 "data: {...}\n\n"
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const rawJson = line.slice(6).trim();
          if (!rawJson) continue;

          try {
            const event = JSON.parse(rawJson);
            if (event.type === 'token') {
              aiContent += event.content;
              // 实时更新 AI 消息内容（打字机效果）
              setMessages(prev => {
                const updated = [...prev];
                const lastIdx = updated.length - 1;
                if (updated[lastIdx]?.role === 'ai') {
                  updated[lastIdx] = {
                    ...updated[lastIdx],
                    content: aiContent,
                    isStreaming: true,
                  };
                }
                return updated;
              });
            } else if (event.type === 'done') {
              aiSources = event.sources || [];
              // 流结束，更新最终消息（去掉 isStreaming 标志，附上引文来源）
              setMessages(prev => {
                const updated = [...prev];
                const lastIdx = updated.length - 1;
                if (updated[lastIdx]?.role === 'ai') {
                  updated[lastIdx] = {
                    role: 'ai',
                    content: aiContent,
                    sources: aiSources,
                    isStreaming: false,
                  };
                }
                return updated;
              });
            } else if (event.type === 'error') {
              aiContent = `❌ ${event.content}`;
              setMessages(prev => {
                const updated = [...prev];
                const lastIdx = updated.length - 1;
                if (updated[lastIdx]?.role === 'ai') {
                  updated[lastIdx] = {
                    role: 'ai',
                    content: aiContent,
                    isStreaming: false,
                  };
                }
                return updated;
              });
            }
          } catch {
            // 忽略非 JSON 行（如 keep-alive 空行）
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') return; // 用户主动中断
      setMessages(prev => {
        const updated = [...prev];
        const lastIdx = updated.length - 1;
        if (updated[lastIdx]?.role === 'ai') {
          updated[lastIdx] = {
            role: 'ai',
            content: '❌ 网络请求失败，请检查后端服务是否正常运行。',
            isStreaming: false,
          };
        }
        return updated;
      });
    } finally {
      setIsStreaming(false);
      abortControllerRef.current = null;
      // 聚焦回输入框
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [input, isStreaming, documentId, messages]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ==================== 引文 Badge 解析 ====================

  /**
   * 将 AI 回复中的 [来源: XXX] 标记解析为对应 Source 对象（用于点击弹窗）
   */
  const findSourceByTitle = (title: string, sources: Source[]): Source | undefined => {
    // 模糊匹配：比较章节名是否包含 title 关键词
    return sources.find(s =>
      s.section_title.includes(title) || title.includes(s.section_title)
    );
  };

  // ==================== 渲染 ====================

  return (
    <>
      {/* 主面板 */}
      <div className="bg-white/90 backdrop-blur-xl rounded-3xl shadow-lg border border-white flex flex-col h-full overflow-hidden transition-all">
        {/* 头部 (支持拖拽) */}
        <div className="chat-header cursor-move select-none p-4 border-b border-slate-100 bg-white/50 backdrop-blur-md flex items-center gap-3 relative z-10">
          <div className="relative">
            <div className="w-10 h-10 bg-gradient-to-tr from-indigo-500 to-purple-500 rounded-full flex items-center justify-center text-white text-lg shadow-md">
              🤖
            </div>
            <div
              className={`absolute bottom-0 right-0 w-3 h-3 border-2 border-white rounded-full transition-colors ${
                documentId ? 'bg-green-400' : 'bg-amber-400'
              }`}
            />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-extrabold text-slate-800">Copilot 助手</h3>
            <p className="text-xs text-slate-500 font-medium truncate">
              {documentId ? '✅ 文档已加载，RAG 检索就绪' : '⚠️ 请先上传招标文件'}
            </p>
          </div>
          {/* 快捷问题按钮 */}
          {documentId && (
            <button
              onClick={() => setInput('最高投标限价是多少？')}
              className="text-xs bg-indigo-50 text-indigo-600 px-2 py-1 rounded-lg hover:bg-indigo-100 transition-colors font-medium whitespace-nowrap"
            >
              试试看
            </button>
          )}
        </div>

        {/* 消息区 */}
        <div
          ref={scrollContainerRef}
          className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/50 scrollbar-hide relative"
        >
          {/* 背景装饰 */}
          <div className="absolute top-20 left-10 w-40 h-40 bg-purple-400/5 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute bottom-20 right-10 w-40 h-40 bg-blue-400/5 rounded-full blur-3xl pointer-events-none" />

          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in-up`}
            >
              {msg.role === 'ai' && (
                <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-100 to-purple-100 flex items-center justify-center text-sm mr-2 flex-shrink-0 mt-1">
                  🤖
                </div>
              )}
              <div className="max-w-[85%] flex flex-col gap-2">
                <div
                  className={`p-3 rounded-2xl shadow-sm text-sm leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-gradient-to-br from-blue-600 to-indigo-600 text-white rounded-tr-sm'
                      : 'bg-white border border-slate-100 text-slate-700 rounded-tl-sm'
                  }`}
                >
                  {msg.role === 'ai' ? (
                    <div className="prose prose-sm max-w-none prose-headings:text-slate-800 prose-strong:text-slate-800 prose-code:bg-slate-100 prose-code:px-1 prose-code:rounded">
                      <ReactMarkdown>{msg.content || (msg.isStreaming ? '▊' : '')}</ReactMarkdown>
                    </div>
                  ) : (
                    msg.content
                  )}
                </div>

                {/* 引文 Badge 区 */}
                {msg.role === 'ai' && !msg.isStreaming && msg.sources && msg.sources.length > 0 && (
                  <div className="flex flex-wrap gap-1 ml-1">
                    {msg.sources.map((src, sIdx) => (
                      <button
                        key={sIdx}
                        onClick={() => setActiveSource(src)}
                        className="inline-flex items-center gap-1 text-xs bg-amber-50 text-amber-700 border border-amber-200 px-2 py-0.5 rounded-full hover:bg-amber-100 hover:shadow-sm transition-all font-medium"
                      >
                        <span>📄</span>
                        <span className="max-w-[120px] truncate">{src.section_title}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}

          {/* 流式输出中的跳动指示（当最后一条 AI 消息正在流式但内容为空时显示） */}
          {isStreaming && messages[messages.length - 1]?.content === '' && (
            <div className="flex justify-start animate-fade-in">
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-100 to-purple-100 flex items-center justify-center text-sm mr-2 flex-shrink-0 mt-1">
                🤖
              </div>
              <div className="bg-white border border-slate-100 p-4 rounded-2xl rounded-tl-sm shadow-sm flex items-center space-x-1">
                <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          )}
        </div>

        {/* 输入区 */}
        <div className="p-4 bg-white border-t border-slate-100 relative z-10">
          <div className="relative group">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={documentId ? '询问标书细节... (Enter 发送)' : '请先上传招标文件...'}
              disabled={isStreaming}
              className="w-full pl-4 pr-14 py-3.5 bg-slate-50 border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 focus:bg-white transition-all shadow-inner font-medium text-slate-700 disabled:opacity-60 disabled:cursor-not-allowed text-sm"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isStreaming || !documentId}
              className="absolute right-2 top-1/2 -translate-y-1/2 bg-blue-600 disabled:bg-slate-300 hover:bg-blue-700 text-white p-2.5 rounded-xl transition-all shadow-md active:scale-95 disabled:cursor-not-allowed"
            >
              {isStreaming ? (
                <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              )}
            </button>
          </div>
          <p className="text-center text-[10px] text-slate-400 mt-2 font-medium">
            AI 可能会产生误导，最终决策请核对原文。
          </p>
        </div>
      </div>

      {/* 引文侧抽屉 */}
      {activeSource && (
        <div
          className="fixed inset-0 z-[60] flex items-end sm:items-center justify-center"
          onClick={() => setActiveSource(null)}
        >
          {/* 背景遮罩 */}
          <div className="absolute inset-0 bg-black/20 backdrop-blur-sm" />
          {/* 抽屉内容 */}
          <div
            className="relative z-10 bg-white rounded-3xl shadow-2xl p-6 mx-4 max-w-lg w-full animate-fade-in-up"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-start justify-between mb-4">
              <div>
                <span className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-600 bg-amber-50 border border-amber-200 px-3 py-1 rounded-full">
                  📄 原文来源
                </span>
                <h4 className="mt-2 font-extrabold text-slate-800 text-base leading-snug">
                  {activeSource.section_title}
                </h4>
              </div>
              <button
                onClick={() => setActiveSource(null)}
                className="text-slate-400 hover:text-slate-600 transition-colors p-1 rounded-xl hover:bg-slate-100 ml-3 flex-shrink-0"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="bg-amber-50/60 border border-amber-100 rounded-2xl p-4">
              <p className="text-sm text-slate-700 leading-relaxed whitespace-pre-wrap font-mono">
                {activeSource.text_preview}
                {activeSource.text_preview.length >= 200 && (
                  <span className="text-slate-400">……（片段截取）</span>
                )}
              </p>
            </div>
            <p className="text-xs text-slate-400 mt-3 text-center">
              此为 RAG 检索命中的文档片段，点击空白处关闭
            </p>
          </div>
        </div>
      )}
    </>
  );
}
