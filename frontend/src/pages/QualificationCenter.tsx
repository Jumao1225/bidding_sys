import { useEffect, useState } from 'react';
import { apiFetch } from '../utils/api';
import { motion } from 'framer-motion';
import { QualificationCard, type Qualification } from '../components/qualifications/QualificationCard';
import { QualificationUploadModal } from '../components/qualifications/QualificationUploadModal';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export function QualificationCenter() {
  const [qualifications, setQualifications] = useState<Qualification[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingQual, setEditingQual] = useState<Qualification | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [previewImageUrl, setPreviewImageUrl] = useState<string | null>(null);

  const fetchQualifications = async () => {
    setIsLoading(true);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/qualifications/`, {
        headers: { 'X-Tenant-ID': 'default-tenant' }
      });
      if (res.ok) {
        const json = await res.json();
        if (json.code === 200) {
          setQualifications(json.data);
        }
      }
    } catch (error) {
      console.error('Failed to fetch qualifications:', error);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchQualifications();
  }, []);

  const handleDelete = async (id: string) => {
    if (!window.confirm('确认删除此资质文件？')) return;
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/qualifications/${id}`, {
        method: 'DELETE',
        headers: { 'X-Tenant-ID': 'default-tenant' }
      });
      if (res.ok) {
        setQualifications(prev => prev.filter(q => q.id !== id));
        setSelectedIds(prev => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    } catch (error) {
      console.error('Delete failed:', error);
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`确认删除选中的 ${selectedIds.size} 个资质文件吗？`)) return;
    
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      // Implement batch deletion by calling individual DELETEs concurrently or a new batch endpoint
      // We'll use concurrent individual DELETEs for simplicity and avoiding new backend routes unless necessary
      const promises = Array.from(selectedIds).map(id => 
        apiFetch(`${baseUrl}/api/v1/qualifications/${id}`, {
          method: 'DELETE',
          headers: { 'X-Tenant-ID': 'default-tenant' }
        })
      );
      
      await Promise.all(promises);
      
      setQualifications(prev => prev.filter(q => !selectedIds.has(q.id)));
      setSelectedIds(new Set());
      setSelectionMode(false);
    } catch (error) {
      console.error('Batch delete failed:', error);
      alert('部分删除失败，请刷新页面后重试');
      fetchQualifications();
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleEdit = (qual: Qualification) => {
    setEditingQual(qual);
    setIsModalOpen(true);
  };

  const handleModalClose = () => {
    setIsModalOpen(false);
    setEditingQual(null);
  };

  const handleModalSuccess = () => {
    handleModalClose();
    // Refresh the list to reflect updates/new creations
    fetchQualifications();
  };

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }} 
      animate={{ opacity: 1, y: 0 }} 
      transition={{ duration: 0.5 }}
      className="max-w-7xl mx-auto"
    >
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-800 tracking-tight flex items-center">
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 mr-2">资质中心</span>
            🏆
          </h1>
          <p className="text-slate-500 mt-2 font-medium">集中管理企业资质、证照，支持 AI 扫描识别防超期。</p>
        </div>
        <div className="flex space-x-3">
          {selectionMode ? (
            <>
              <button 
                onClick={() => {
                  if (selectedIds.size === qualifications.length && qualifications.length > 0) {
                    setSelectedIds(new Set());
                  } else {
                    setSelectedIds(new Set(qualifications.map(q => q.id)));
                  }
                }}
                className="flex items-center px-5 py-3 bg-white text-indigo-600 font-bold rounded-xl shadow-sm border border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700 transition-all"
              >
                {selectedIds.size === qualifications.length && qualifications.length > 0 ? '取消全选' : '全选'}
              </button>
              <button 
                onClick={() => { setSelectionMode(false); setSelectedIds(new Set()); }}
                className="flex items-center px-5 py-3 bg-white text-slate-600 font-bold rounded-xl shadow-sm border border-slate-200 hover:bg-slate-50 hover:text-slate-800 transition-all"
              >
                取消选择
              </button>
              <button 
                onClick={handleBatchDelete}
                disabled={selectedIds.size === 0}
                className={`flex items-center px-5 py-3 font-bold rounded-xl shadow-lg transition-all ${selectedIds.size > 0 ? 'bg-rose-500 text-white hover:bg-rose-600 shadow-rose-500/30 hover:-translate-y-0.5' : 'bg-slate-100 text-slate-400 cursor-not-allowed shadow-none'}`}
              >
                <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                删除选中 ({selectedIds.size})
              </button>
            </>
          ) : (
            <>
              {qualifications.length > 0 && (
                <button 
                  onClick={() => setSelectionMode(true)}
                  className="flex items-center px-5 py-3 bg-white text-indigo-600 font-bold rounded-xl shadow-sm border border-indigo-100 hover:bg-indigo-50 hover:border-indigo-200 transition-all"
                >
                  <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path></svg>
                  批量管理
                </button>
              )}
              <button 
                onClick={() => { setEditingQual(null); setIsModalOpen(true); }}
                className="flex items-center px-5 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-bold rounded-xl shadow-lg hover:shadow-indigo-500/30 hover:-translate-y-0.5 transition-all"
              >
                <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 4v16m8-8H4"></path></svg>
                添加资质 (AI识别)
              </button>
            </>
          )}
        </div>
      </div>

      {isLoading ? (
        <div className="py-20 flex justify-center items-center">
          <svg className="animate-spin h-8 w-8 text-indigo-500" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        </div>
      ) : qualifications.length === 0 ? (
        <div className="bg-white/60 backdrop-blur-md rounded-3xl border border-dashed border-slate-300 p-20 flex flex-col items-center justify-center text-center">
          <div className="w-20 h-20 bg-slate-100 rounded-full flex items-center justify-center text-4xl mb-4">📜</div>
          <h3 className="text-xl font-bold text-slate-700 mb-2">资质库空空如也</h3>
          <p className="text-slate-500 max-w-md">点击右上角“添加资质”上传企业营业执照、施工资质等文件，AI将自动提取关键信息。</p>
        </div>
      ) : (
        <div className="bg-white rounded-3xl shadow-sm border border-slate-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-slate-50 border-b border-slate-200 text-slate-500 text-sm">
                  {selectionMode && (
                    <th className="py-4 px-6 font-bold w-12 text-center">
                      ✓
                    </th>
                  )}
                  <th className="py-4 px-6 font-bold">资质名称</th>
                  <th className="py-4 px-6 font-bold">等级</th>
                  <th className="py-4 px-6 font-bold">状态</th>
                  <th className="py-4 px-6 font-bold">到期时间</th>
                  <th className="py-4 px-6 font-bold text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {qualifications.map(qual => {
                  const isExpired = qual.expiry_date ? new Date(qual.expiry_date) < new Date() : false;
                  const isExpiringSoon = qual.expiry_date 
                    ? new Date(qual.expiry_date).getTime() - new Date().getTime() < 30 * 24 * 60 * 60 * 1000 && !isExpired
                    : false;

                  const fullFileUrl = qual.file_url ? (qual.file_url.startsWith('http') ? qual.file_url : `${API_BASE_URL}${qual.file_url}`) : null;

                  let statusColor = "bg-emerald-50 text-emerald-600 border-emerald-200";
                  let statusText = "有效";
                  if (isExpired) {
                    statusColor = "bg-rose-50 text-rose-600 border-rose-200";
                    statusText = "已过期";
                  } else if (isExpiringSoon) {
                    statusColor = "bg-amber-50 text-amber-600 border-amber-200";
                    statusText = "即将过期";
                  }

                  const selected = selectedIds.has(qual.id);

                  return (
                    <tr 
                      key={qual.id} 
                      className={`hover:bg-slate-50 transition-colors ${selectionMode ? 'cursor-pointer' : ''} ${selected ? 'bg-indigo-50/50' : ''}`}
                      onClick={() => { if (selectionMode) toggleSelect(qual.id); }}
                    >
                      {selectionMode && (
                        <td className="py-4 px-6">
                          <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors mx-auto ${selected ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-slate-300 bg-white'}`}>
                            {selected && <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>}
                          </div>
                        </td>
                      )}
                      <td className="py-4 px-6">
                        <div className="flex items-center">
                          <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-xl mr-4 flex-shrink-0 ${statusColor}`}>
                            {isExpired ? '❌' : (isExpiringSoon ? '⚠️' : '✅')}
                          </div>
                          <div>
                            <p className="font-bold text-slate-800">{qual.name}</p>
                            {qual.company_name && <p className="text-sm text-slate-500">{qual.company_name}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="py-4 px-6">
                        <span className="font-bold text-slate-700 bg-slate-100 px-2.5 py-1 rounded-lg text-sm">{qual.level || '无'}</span>
                      </td>
                      <td className="py-4 px-6">
                        <span className={`inline-flex px-2.5 py-1 rounded-full text-xs font-bold border ${statusColor}`}>
                          {statusText}
                        </span>
                      </td>
                      <td className="py-4 px-6">
                        <span className={`text-sm font-bold ${isExpired ? 'text-rose-600' : 'text-slate-700'}`}>
                          {qual.expiry_date || '长期有效'}
                        </span>
                      </td>
                      <td className="py-4 px-6">
                        <div className="flex items-center justify-end space-x-2">
                          {fullFileUrl && (
                            <>
                              {fullFileUrl.toLowerCase().endsWith('.pdf') ? (
                                <a href={fullFileUrl} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="p-2 text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors" title="原文件">
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                                </a>
                              ) : (
                                <button onClick={(e) => { e.stopPropagation(); setPreviewImageUrl(fullFileUrl); }} className="p-2 text-indigo-600 bg-indigo-50 hover:bg-indigo-100 rounded-lg transition-colors" title="预览图片">
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                                </button>
                              )}
                            </>
                          )}
                          {!selectionMode && (
                            <>
                              <button onClick={(e) => { e.stopPropagation(); handleEdit(qual); }} className="p-2 text-blue-500 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors" title="编辑">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
                              </button>
                              <button onClick={(e) => { e.stopPropagation(); handleDelete(qual.id); }} className="p-2 text-rose-500 bg-rose-50 hover:bg-rose-100 rounded-lg transition-colors" title="删除">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <QualificationUploadModal 
        isOpen={isModalOpen}
        onClose={handleModalClose}
        onSuccess={handleModalSuccess}
        editData={editingQual}
      />

      {/* 图片预览弹窗 */}
      {previewImageUrl && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm" onClick={() => setPreviewImageUrl(null)}>
          <motion.div 
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="relative w-full max-w-5xl max-h-[90vh] flex flex-col bg-white rounded-2xl shadow-2xl overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h3 className="font-bold text-slate-800">资质文件预览</h3>
              <button onClick={() => setPreviewImageUrl(null)} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4 flex items-center justify-center bg-slate-100/50">
              <img src={previewImageUrl} alt="资质文件预览" className="max-w-full max-h-[calc(90vh-100px)] object-contain shadow-sm rounded-lg" />
            </div>
          </motion.div>
        </div>
      )}
    </motion.div>
  );
}
