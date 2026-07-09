import React, { useState, useEffect, useRef } from 'react';

export function ChatPanel() {
  const [messages, setMessages] = useState([
    { role: 'ai', content: '您好！我是您的专属标书解析大模型。我已经阅读了当前的招标文件，您可以向我提问关于项目资质、交货期、付款方式等任何深层细节。' }
  ]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSend = () => {
    if (!input.trim()) return;
    setMessages(prev => [...prev, { role: 'user', content: input }]);
    setInput('');
    setIsTyping(true);
    
    // 模拟 AI 回复
    setTimeout(() => {
      setIsTyping(false);
      setMessages(prev => [...prev, { role: 'ai', content: '根据招标文件第 15 页 3.2 条规定，本项目不接受联合体投标，且要求交货期为签订合同后的 30 个自然日内。建议在技术标中着重强调本地化交付团队优势。' }]);
    }, 1500);
  };

  return (
    <div className="bg-white/90 backdrop-blur-xl rounded-3xl shadow-lg border border-white flex flex-col h-full overflow-hidden transition-all">
      <div className="p-5 border-b border-slate-100 bg-white/50 backdrop-blur-md flex items-center gap-3 relative z-10">
        <div className="relative">
          <div className="w-10 h-10 bg-gradient-to-tr from-indigo-500 to-purple-500 rounded-full flex items-center justify-center text-white text-lg shadow-md">🤖</div>
          <div className="absolute bottom-0 right-0 w-3 h-3 bg-green-400 border-2 border-white rounded-full"></div>
        </div>
        <div>
          <h3 className="text-base font-extrabold text-slate-800">Copilot 助手</h3>
          <p className="text-xs text-slate-500 font-medium">Bidding GPT-4o Online</p>
        </div>
      </div>
      
      {/* 消息区 */}
      <div className="flex-1 overflow-y-auto p-5 space-y-6 bg-slate-50/50 custom-scrollbar relative">
        {/* 背景装饰 */}
        <div className="absolute top-20 left-10 w-40 h-40 bg-purple-400/5 rounded-full blur-3xl pointer-events-none"></div>
        <div className="absolute bottom-20 right-10 w-40 h-40 bg-blue-400/5 rounded-full blur-3xl pointer-events-none"></div>
        
        {messages.map((msg, idx) => (
          <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in-up`}>
            {msg.role === 'ai' && (
              <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-100 to-purple-100 flex items-center justify-center text-sm mr-2 flex-shrink-0 mt-1">🤖</div>
            )}
            <div className={`max-w-[85%] p-4 rounded-2xl shadow-sm text-sm leading-relaxed ${
              msg.role === 'user' 
                ? 'bg-gradient-to-br from-blue-600 to-indigo-600 text-white rounded-tr-sm' 
                : 'bg-white border border-slate-100 text-slate-700 rounded-tl-sm'
            }`}>
              {msg.content}
            </div>
          </div>
        ))}
        {isTyping && (
          <div className="flex justify-start animate-fade-in">
             <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-indigo-100 to-purple-100 flex items-center justify-center text-sm mr-2 flex-shrink-0 mt-1">🤖</div>
             <div className="bg-white border border-slate-100 p-4 rounded-2xl rounded-tl-sm shadow-sm flex items-center space-x-1">
                <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-2 h-2 bg-slate-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
             </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="p-5 bg-white border-t border-slate-100 relative z-10">
        <div className="relative group">
          <input 
            type="text" 
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="询问大模型标书细节..."
            className="w-full pl-5 pr-14 py-4 bg-slate-50 border border-slate-200 rounded-2xl focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 focus:bg-white transition-all shadow-inner font-medium text-slate-700"
          />
          <button 
            onClick={handleSend}
            disabled={!input.trim()}
            className="absolute right-2 top-1/2 -translate-y-1/2 bg-blue-600 disabled:bg-slate-300 hover:bg-blue-700 text-white p-2.5 rounded-xl transition-all shadow-md active:scale-95"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
          </button>
        </div>
        <p className="text-center text-[10px] text-slate-400 mt-3 font-medium">AI 可能会产生误导，最终决策请核对原文。</p>
      </div>
    </div>
  );
}
