import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { apiFetch } from '../../utils/api';
import type { Qualification } from './QualificationCard';
import { useDialog } from '../DialogProvider';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
  // 编辑现有资质时传入该记录。
  editData: Qualification | null;
}

type ParseErrorKind = 'service' | 'file' | 'network' | 'unknown';

interface ParseErrorState {
  kind: ParseErrorKind;
  title: string;
  message: string;
  suggestion: string;
}

interface ApiErrorPayload {
  code?: number;
  message?: string;
  detail?: string;
}

const IMAGE_OCR_MODEL_NAME = import.meta.env.VITE_ALI_VLM_MODEL_NAME || 'Qwen3.8-27B';

/** 从接口响应中提取后端返回的可读错误信息。 */
function getApiErrorMessage(payload: unknown): string | undefined {
  if (!payload || typeof payload !== 'object') return undefined;

  const data = payload as ApiErrorPayload;
  if (typeof data.detail === 'string' && data.detail.trim()) return data.detail.trim();
  if (typeof data.message === 'string' && data.message.trim()) return data.message.trim();
  return undefined;
}

/** 将后端错误或网络异常转换成面向用户的资质解析提示。 */
function createParseError(status?: number, backendMessage?: string, error?: unknown): ParseErrorState {
  const rawMessage = backendMessage || (error instanceof Error ? error.message : '');
  const normalizedMessage = rawMessage.toLowerCase();
  const isNetworkError = !status && (
    normalizedMessage.includes('failed to fetch') ||
    normalizedMessage.includes('network') ||
    normalizedMessage.includes('connection')
  );
  const isServiceError = Boolean(status && status >= 500) || /vlm|模型|ai|服务|连接/.test(normalizedMessage);

  if (isNetworkError) {
    return {
      kind: 'network',
      title: '暂时无法连接 AI 识别服务',
      message: '当前网络或识别服务连接异常，资质文件尚未完成解析。',
      suggestion: '请确认模型服务已启动且网络正常，然后点击“重试当前文件”。',
    };
  }

  if (isServiceError) {
    return {
      kind: 'service',
      title: 'AI 识别服务暂时不可用',
      message: '文件已上传，但当前模型服务没有正常返回结果，未生成资质记录。',
      suggestion: '请检查模型配置或服务状态，确认恢复后再重试；原文件不会丢失。',
    };
  }

  if (status && status >= 400 && status < 500) {
    return {
      kind: 'file',
      title: '文件暂时无法解析',
      message: rawMessage || '未能从文件中识别到有效的资质信息。',
      suggestion: '请确认文件清晰、完整且格式受支持（PDF、PNG、JPG），然后重新上传。',
    };
  }

  return {
    kind: 'unknown',
    title: '资质解析失败',
    message: '本次解析没有完成，系统未保存任何资质记录。',
    suggestion: '请稍后重试；如果连续失败，请联系管理员检查识别服务。',
  };
}

export function QualificationUploadModal({ isOpen, onClose, onSuccess, editData }: Props) {
  const { alert } = useDialog();
  const [isDragging, setIsDragging] = useState(false);
  const [isParsing, setIsParsing] = useState(false);
  const [parseError, setParseError] = useState<ParseErrorState | null>(null);
  const [lastFile, setLastFile] = useState<File | null>(null);
  
  // 保存解析结果或正在编辑的资质列表。
  const [parsedDataList, setParsedDataList] = useState<Qualification[] | null>(null);
  const [processingTitle, setProcessingTitle] = useState('正在识别资质文件...');
  const [processingDescription, setProcessingDescription] = useState('正在调用 AI 识别服务提取资质名称、等级与到期时间');

  const fileInputRef = useRef<HTMLInputElement>(null);

  // 模态框打开编辑模式时，将编辑记录同步到本地状态。
  useEffect(() => {
    if (!isOpen) {
      setParseError(null);
      setLastFile(null);
      setIsDragging(false);
      return;
    }

    if (editData) {
      setParsedDataList([editData]);
    } else {
      setParsedDataList(null);
      setParseError(null);
      setLastFile(null);
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
    // 保存最近一次文件，便于模型服务恢复后直接重试，避免用户重复选择文件。
    setLastFile(file);
    setParseError(null);
    const isImageFile = /\.(jpg|jpeg|png|webp|bmp)$/i.test(file.name);
    if (isImageFile) {
      setProcessingTitle(`正在调用 ${IMAGE_OCR_MODEL_NAME} 视觉模型进行 OCR 识别...`);
      setProcessingDescription('图片将由视觉模型直接识别并提取资质名称、等级与到期时间');
    } else {
      setProcessingTitle('正在调用 MinerU 云端 OCR 引擎进行深度识别...');
      setProcessingDescription('PDF 将先由 MinerU 解析文档结构，再提取资质名称、等级与到期时间');
    }
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
      
      const payload: unknown = await res.json().catch(() => null);

      if (!res.ok) {
        const backendMessage = getApiErrorMessage(payload);
        const friendlyError = createParseError(res.status, backendMessage);
        console.error('[资质解析失败]', {
          fileName: file.name,
          status: res.status,
          backendMessage,
          errorKind: friendlyError.kind,
        });
        setParseError(friendlyError);
        return;
      }

      const json = payload as { code?: number; data?: Qualification[]; message?: string };
      
      if (json.code === 200 && Array.isArray(json.data) && json.data.length > 0) {
        // 接口返回资质列表。
        setParsedDataList(json.data as Qualification[]);
      } else {
        const friendlyError = createParseError(res.status, json.message);
        console.error('[资质解析失败] 接口返回空结果', {
          fileName: file.name,
          status: res.status,
          backendMessage: json.message,
          errorKind: friendlyError.kind,
        });
        setParseError(friendlyError);
      }
    } catch (error) {
      const friendlyError = createParseError(undefined, undefined, error);
      console.error('[资质解析失败] 请求异常', {
        fileName: file.name,
        error,
        errorKind: friendlyError.kind,
      });
      setParseError(friendlyError);
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
        await alert('删除失败', { title: '删除资质失败', intent: 'danger' });
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
      await alert('保存出错', { title: '保存资质失败', intent: 'danger' });
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
                className="space-y-4"
              >
                {parseError && (
                  <div
                    role="alert"
                    className={`rounded-2xl border px-5 py-4 ${parseError.kind === 'file' ? 'border-amber-200 bg-amber-50' : 'border-rose-200 bg-rose-50'}`}
                  >
                    <div className="flex items-start">
                      <div className={`mt-0.5 mr-3 flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-lg ${parseError.kind === 'file' ? 'bg-amber-100 text-amber-600' : 'bg-rose-100 text-rose-600'}`}>
                        {parseError.kind === 'file' ? '⚠️' : '!'}</div>
                      <div className="min-w-0 flex-1">
                        <h3 className={`font-bold ${parseError.kind === 'file' ? 'text-amber-800' : 'text-rose-800'}`}>
                          {parseError.title}
                        </h3>
                        <p className={`mt-1 text-sm ${parseError.kind === 'file' ? 'text-amber-700' : 'text-rose-700'}`}>
                          {parseError.message}
                        </p>
                        <p className={`mt-2 text-xs ${parseError.kind === 'file' ? 'text-amber-600' : 'text-rose-600'}`}>
                          {parseError.suggestion}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {lastFile && (
                            <button
                              type="button"
                              onClick={() => handleUpload(lastFile)}
                              className="rounded-lg bg-rose-600 px-3 py-2 text-xs font-bold text-white transition-colors hover:bg-rose-700"
                            >
                              重试当前文件
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 transition-colors hover:bg-slate-50"
                          >
                            重新选择文件
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                <div
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
                  <p className="text-sm text-slate-500">支持 PDF、PNG、JPG，AI 将自动识别文件中包含的所有独立资质信息</p>
                </div>
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
                <h3 className="text-lg font-bold text-slate-800 mb-2">{processingTitle}</h3>
                <p className="text-sm text-slate-500 animate-pulse">{processingDescription}</p>
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
