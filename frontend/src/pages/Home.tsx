import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { apiFetch } from '../utils/api';

interface DocumentRecord {
  id: string;
  filename: string;
  status: string;
  created_at: string | null;
}

export function Home() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchDocuments = async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
        const res = await apiFetch(`${baseUrl}/api/v1/documents/`);
        if (res.ok) {
          const json = await res.json();
          if (json.code === 200 && json.data) {
            setDocuments(json.data);
          }
        }
      } catch (err) {
        console.error('Failed to fetch documents', err);
      } finally {
        setIsLoading(false);
      }
    };
    fetchDocuments();
  }, []);

  const handleDelete = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation(); // 阻止点击卡片跳转
    if (!window.confirm('确定要删除这条解析记录吗？相关的分析数据和聊天历史都会被清除。')) {
      return;
    }

    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';
      const res = await apiFetch(`${baseUrl}/api/v1/documents/${docId}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        // 从状态中移除
        setDocuments(prev => prev.filter(d => d.id !== docId));
        // 清理本地聊天的缓存
        localStorage.removeItem(`chat_history_${docId}`);
        // 如果当前正好在看这个文档，可能需要处理，但因为在首页，无所谓
      } else {
        alert('删除失败，请稍后重试');
      }
    } catch (err) {
      console.error('Failed to delete document', err);
      alert('删除出错');
    }
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}
      className="max-w-7xl mx-auto space-y-10"
    >
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
        <motion.div whileHover={{ y: -8, scale: 1.02 }} className="glass p-8 rounded-2xl flex flex-col justify-center items-center group cursor-pointer transition-shadow hover:shadow-xl hover:shadow-blue-500/10">
          <motion.div whileHover={{ scale: 1.1 }} className="w-16 h-16 bg-blue-100 text-blue-600 rounded-full flex items-center justify-center text-2xl mb-4">📄</motion.div>
          <h3 className="font-bold text-slate-700 text-lg">智能标书解析</h3>
          <p className="text-slate-500 text-sm text-center mt-2">支持 PDF/Word，自动剥离五大核心维度数据。</p>
        </motion.div>
        <motion.div whileHover={{ y: -8, scale: 1.02 }} className="glass p-8 rounded-2xl flex flex-col justify-center items-center group cursor-pointer transition-shadow hover:shadow-xl hover:shadow-rose-500/10">
          <motion.div whileHover={{ scale: 1.1 }} className="w-16 h-16 bg-rose-100 text-rose-600 rounded-full flex items-center justify-center text-2xl mb-4">⚠️</motion.div>
          <h3 className="font-bold text-slate-700 text-lg">痛点与违约排雷</h3>
          <p className="text-slate-500 text-sm text-center mt-2">自动高亮特殊施工工况及严厉的违约扣款条款。</p>
        </motion.div>
        <motion.div whileHover={{ y: -8, scale: 1.02 }} className="glass p-8 rounded-2xl flex flex-col justify-center items-center group cursor-pointer transition-shadow hover:shadow-xl hover:shadow-emerald-500/10">
          <motion.div whileHover={{ scale: 1.1 }} className="w-16 h-16 bg-emerald-100 text-emerald-600 rounded-full flex items-center justify-center text-2xl mb-4">💰</motion.div>
          <h3 className="font-bold text-slate-700 text-lg">资金测算与排期</h3>
          <p className="text-slate-500 text-sm text-center mt-2">精准提取限价、预算及多阶段付款节点比例。</p>
        </motion.div>
      </div>

      {/* 历史记录列表区 */}
      <div className="mt-16 bg-white/60 backdrop-blur-md rounded-3xl p-8 border border-slate-200/50 shadow-sm">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-xl font-bold text-slate-800 flex items-center">
            <svg className="w-6 h-6 mr-2 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
            最近解析记录
          </h3>
        </div>
        
        {isLoading ? (
          <div className="flex justify-center items-center py-10 text-slate-400">
            <svg className="animate-spin h-6 w-6 mr-3" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            加载中...
          </div>
        ) : documents.length === 0 ? (
          <div className="text-center py-10 text-slate-500">
            暂无解析记录，快去上传您的第一份标书吧！
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {documents.map(doc => (
              <motion.div 
                key={doc.id}
                onClick={() => navigate(`/analysis/${doc.id}`)}
                whileHover={{ y: -5, scale: 1.01 }}
                className="group p-4 bg-white rounded-2xl border border-slate-100 shadow-sm hover:shadow-md hover:border-indigo-100 cursor-pointer transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center space-x-3 overflow-hidden">
                    <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-50 to-indigo-50 flex items-center justify-center flex-shrink-0 text-xl group-hover:scale-110 transition-transform">
                      {doc.filename.endsWith('.pdf') ? '📄' : '📝'}
                    </div>
                    <div className="overflow-hidden">
                      <p className="font-semibold text-slate-700 truncate text-sm" title={doc.filename}>
                        {doc.filename}
                      </p>
                      <p className="text-[11px] text-slate-400 mt-0.5">
                        {doc.created_at ? new Date(doc.created_at).toLocaleString() : '未知时间'}
                      </p>
                    </div>
                  </div>
                  {/* 删除按钮 */}
                  <button
                    onClick={(e) => handleDelete(e, doc.id)}
                    className="p-2 text-slate-300 hover:text-rose-500 hover:bg-rose-50 rounded-lg transition-colors opacity-0 group-hover:opacity-100 flex-shrink-0"
                    title="删除记录"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                  </button>
                </div>
                <div className="mt-4 flex items-center justify-between">
                  <span className={`text-[10px] font-bold px-2 py-1 rounded-full ${
                    doc.status === 'completed' ? 'bg-emerald-50 text-emerald-600' :
                    doc.status === 'pending' ? 'bg-amber-50 text-amber-600' :
                    'bg-rose-50 text-rose-600'
                  }`}>
                    {doc.status === 'completed' ? '解析完成' : doc.status === 'pending' ? '排队中/解析中' : '解析失败'}
                  </span>
                  <span className="text-indigo-500 text-xs font-medium opacity-0 group-hover:opacity-100 transition-opacity flex items-center">
                    查看看板
                    <svg className="w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5l7 7-7 7"></path></svg>
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}
