import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { apiFetch } from '../../utils/api';
import type { Qualification } from './QualificationCard';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  // If editing an existing one, pass it in
  editData: Qualification | null;
}

export function QualificationUploadModal({ isOpen, onClose, onSuccess, editData }: Props) {
  const [isDragging, setIsDragging] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  
  // Array of parsed (or editing) qualifications
  const [parsedDataList, setParsedDataList] = useState<Qualification[] | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Sync editData to local state when modal opens for editing
  useEffect(() => {
    if (editData) {
      setParsedDataList([editData]);
    } else {
      setParsedDataList(null);
    }
  }, [editData, isOpen]);

  if (!isOpen) return null;

  const handleDragOver = (e: any) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: any) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleUpload(e.dataTransfer.files[0]);
    }
  };

  const handleFileSelect = (e: any) => {
    if (e.target.files && e.target.files[0]) {
      handleUpload(e.target.files[0]);
    }
  };

  const handleUpload = async (file: File) => {
    setIsParsing(true);
    const formData = new FormData();
    formData.append('file', file);
    
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/qualifications/upload`, {
        method: 'POST',
        body: formData,
        headers: {
          'X-Tenant-ID': 'default-tenant'
        }
      });
      
      if (!res.ok) throw new Error('Upload failed');
      const json = await res.json();
      
      if (json.code === 200 && json.data) {
        // Now returns an array
        setParsedDataList(json.data as Qualification[]);
      } else {
        alert(json.message || '解析失败');
      }
    } catch (error) {
      console.error(error);
      alert('解析过程发生错误');
    } finally {
      setIsParsing(false);
    }
  };

  const handleFieldChange = (index: number, field: keyof Qualification, value: string) => {
    if (!parsedDataList) return;
    const newList = [...parsedDataList];
    newList[index] = { ...newList[index], [field]: value };
    setParsedDataList(newList);
  };

  const handleDeleteItem = async (index: number, qualId: string) => {
    if (!parsedDataList) return;
    
    // 如果是处于编辑现有记录的模式，才调用后端删除接口
    if (editData) {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      try {
        if (qualId) {
          await apiFetch(`${baseUrl}/api/v1/qualifications/${qualId}`, {
            method: 'DELETE',
            headers: { 'X-Tenant-ID': 'default-tenant' }
          });
        }
      } catch (error) {
        console.error(error);
        alert('删除失败');
        return;
      }
    }
    
    // 更新本地状态
    const newList = parsedDataList.filter((_, i) => i !== index);
    if (newList.length > 0) {
      setParsedDataList(newList);
    } else {
      setParsedDataList(null);
      onClose();
    }
  };

  const handleSaveAll = async () => {
    if (!parsedDataList) return;
    
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    
    try {
      if (editData) {
        // 单个编辑模式，调用 PUT
        const qual = parsedDataList[0];
        await apiFetch(`${baseUrl}/api/v1/qualifications/${qual.id}`, {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            'X-Tenant-ID': 'default-tenant'
          },
          body: JSON.stringify({
            name: qual.name,
            company_name: qual.company_name || null,
            level: qual.level,
            expiry_date: qual.expiry_date || null
          })
        });
      } else {
        // 新上传模式，批量调用 POST
        await Promise.all(parsedDataList.map(qual => {
          return apiFetch(`${baseUrl}/api/v1/qualifications/`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-Tenant-ID': 'default-tenant'
            },
            body: JSON.stringify({
              name: qual.name,
              company_name: qual.company_name || null,
              level: qual.level,
              expiry_date: qual.expiry_date || null,
              file_url: qual.file_url || null
            })
          });
        }));
      }
      
      onSuccess();
    } catch (error) {
      console.error(error);
      alert('保存出错');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm overflow-y-auto">
      <motion.div 
        initial={{ opacity: 0, scale: 0.95 }} 
        animate={{ opacity: 1, scale: 1 }} 
        exit={{ opacity: 0, scale: 0.95 }}
        className="bg-white rounded-3xl shadow-2xl w-full max-w-2xl overflow-hidden border border-slate-100 my-8 flex flex-col max-h-[90vh]"
      >
        <div className="p-6 border-b border-slate-100 flex items-center justify-between bg-slate-50/50 shrink-0">
          <h2 className="text-xl font-bold text-slate-800 flex items-center">
            {editData ? '修改资质信息' : '添加新资质 (AI 智能解析)'}
          </h2>
          <button onClick={onClose} className="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M6 18L18 6M6 6l12 12"></path></svg>
          </button>
        </div>

        <div className="p-8 overflow-y-auto custom-scrollbar flex-1">
          <AnimatePresence mode="wait">
            {!parsedDataList && !isParsing && (
              <motion.div 
                key="upload"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className={`border-2 border-dashed rounded-2xl p-10 flex flex-col items-center justify-center text-center cursor-pointer transition-colors ${isDragging ? 'border-indigo-500 bg-indigo-50/50' : 'border-slate-200 hover:border-indigo-300 hover:bg-slate-50'}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <input type="file" className="hidden" ref={fileInputRef} onChange={handleFileSelect} accept=".pdf,.png,.jpg,.jpeg" />
                <div className="w-16 h-16 bg-indigo-100 text-indigo-600 rounded-full flex items-center justify-center mb-4">
                  <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path></svg>
                </div>
                <h3 className="text-lg font-bold text-slate-700 mb-1">点击或拖拽文件到此处上传</h3>
                <p className="text-sm text-slate-500">支持多合一 PDF，AI 将自动识别文件中包含的所有独立资质信息</p>
              </motion.div>
            )}

            {isParsing && (
              <motion.div 
                key="parsing"
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                className="py-12 flex flex-col items-center justify-center"
              >
                <div className="relative w-20 h-20 mb-6">
                  <div className="absolute inset-0 border-4 border-indigo-100 rounded-full"></div>
                  <div className="absolute inset-0 border-4 border-indigo-600 rounded-full border-t-transparent animate-spin"></div>
                  <div className="absolute inset-0 flex items-center justify-center text-2xl animate-pulse">🤖</div>
                </div>
                <h3 className="text-lg font-bold text-slate-800 mb-2">正在进行 MinerU 深度 OCR 识别...</h3>
                <p className="text-sm text-slate-500 animate-pulse">正在利用大模型提取所有资质的名称、等级与到期时间</p>
              </motion.div>
            )}

            {parsedDataList && !isParsing && (
              <motion.div 
                key="form"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                className="space-y-6"
              >
                {!editData && (
                  <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 px-4 py-3 rounded-xl text-sm flex items-center mb-6">
                    <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                    AI 提取成功！共识别出 {parsedDataList.length} 个资质记录，请核对信息。
                  </div>
                )}
                
                {parsedDataList.map((qual, index) => (
                  <div key={qual.id || index} className="p-5 border border-slate-200 rounded-2xl bg-slate-50 relative">
                    <div className="absolute top-0 right-0 flex items-center">
                      {parsedDataList.length > 1 && (
                        <div className="bg-blue-100 text-blue-700 text-xs font-bold px-3 py-1 rounded-bl-xl">
                          资质 #{index + 1}
                        </div>
                      )}
                      {!editData && (
                        <button 
                          onClick={() => handleDeleteItem(index, qual.id)}
                          className="bg-rose-100 hover:bg-rose-200 text-rose-600 p-1.5 rounded-bl-xl rounded-tr-xl ml-px transition-colors"
                          title="删除此项"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                        </button>
                      )}
                    </div>
                    
                    <div className="mb-4">
                      <label className="block text-sm font-bold text-slate-700 mb-2">资质名称</label>
                      <input 
                        type="text" 
                        value={qual.name} 
                        onChange={e => handleFieldChange(index, 'name', e.target.value)}
                        className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all outline-none text-slate-800 font-medium bg-white"
                        placeholder="如：安全生产许可证、营业执照"
                      />
                    </div>
                    
                    <div className="mb-4">
                      <label className="block text-sm font-bold text-slate-700 mb-2">所属公司名称 (可选)</label>
                      <input 
                        type="text" 
                        value={qual.company_name || ''} 
                        onChange={e => handleFieldChange(index, 'company_name', e.target.value)}
                        className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all outline-none text-slate-800 bg-white"
                        placeholder="如：某某建筑工程有限公司"
                      />
                    </div>
                    
                    <div className="grid grid-cols-2 gap-5">
                      <div>
                        <label className="block text-sm font-bold text-slate-700 mb-2">资质等级 (可选)</label>
                        <input 
                          type="text" 
                          value={qual.level || ''} 
                          onChange={e => handleFieldChange(index, 'level', e.target.value)}
                          className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all outline-none text-slate-800 bg-white"
                          placeholder="如：一级、特级"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-bold text-slate-700 mb-2">到期时间 (可选)</label>
                        <input 
                          type="date" 
                          value={qual.expiry_date || ''} 
                          onChange={e => handleFieldChange(index, 'expiry_date', e.target.value)}
                          className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-200 transition-all outline-none text-slate-800 bg-white"
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
        
        {parsedDataList && !isParsing && (
          <div className="p-6 border-t border-slate-100 bg-slate-50/50 flex space-x-3 justify-end shrink-0">
            <button onClick={onClose} className="px-6 py-2.5 rounded-xl font-bold text-slate-600 bg-slate-200 hover:bg-slate-300 transition-colors">
              关闭 / 稍后处理
            </button>
            <button onClick={handleSaveAll} className="px-6 py-2.5 rounded-xl font-bold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:shadow-lg hover:shadow-indigo-500/30 transition-all">
              {parsedDataList.length > 1 ? '批量保存全部确认' : '确认保存'}
            </button>
          </div>
        )}
      </motion.div>
    </div>
  );
}
