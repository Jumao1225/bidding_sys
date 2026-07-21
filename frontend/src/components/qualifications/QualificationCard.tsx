import { motion } from 'framer-motion';

export interface Qualification {
  id: string;
  name: string;
  company_name?: string | null;
  level: string | null;
  expiry_date: string | null;
  file_url: string | null;
}

interface Props {
  qualification: Qualification;
  onDelete: (id: string) => void;
  onEdit: (qualification: Qualification) => void;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (id: string) => void;
}

export function QualificationCard({ qualification, onDelete, onEdit, selectable, selected, onToggleSelect }: Props) {
  // 计算是否过期
  const isExpired = qualification.expiry_date ? new Date(qualification.expiry_date) < new Date() : false;
  // 计算是否即将过期（30天内）
  const isExpiringSoon = qualification.expiry_date 
    ? new Date(qualification.expiry_date).getTime() - new Date().getTime() < 30 * 24 * 60 * 60 * 1000 && !isExpired
    : false;

  let statusColor = "bg-emerald-50 text-emerald-600 border-emerald-200";
  let statusText = "有效";
  let icon = "✅";
  let borderColor = "border-slate-100";
  
  if (isExpired) {
    statusColor = "bg-rose-50 text-rose-600 border-rose-200";
    statusText = "已过期";
    icon = "❌";
    borderColor = "border-rose-100";
  } else if (isExpiringSoon) {
    statusColor = "bg-amber-50 text-amber-600 border-amber-200";
    statusText = "即将过期";
    icon = "⚠️";
    borderColor = "border-amber-100";
  }

  return (
    <motion.div 
      whileHover={{ y: -4, boxShadow: '0 12px 24px -10px rgba(0,0,0,0.1)' }}
      onClick={() => { if (selectable && onToggleSelect) onToggleSelect(qualification.id); }}
      className={`group rounded-3xl p-6 border ${selected ? 'border-indigo-500 ring-2 ring-indigo-500/20' : borderColor} relative overflow-hidden transition-all bg-white shadow-sm ${selectable ? 'cursor-pointer' : ''}`}
    >
      {/* 装饰性背景 */}
      <div className="absolute -right-6 -top-6 w-32 h-32 bg-slate-50/50 rounded-full blur-2xl pointer-events-none"></div>

      {selectable ? (
        <div className="absolute top-4 right-4 z-20">
          <div className={`w-6 h-6 rounded-full border-2 flex items-center justify-center transition-colors ${selected ? 'bg-indigo-600 border-indigo-600 text-white' : 'border-slate-300 bg-white'}`}>
            {selected && <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="3" d="M5 13l4 4L19 7"></path></svg>}
          </div>
        </div>
      ) : (
        <div className="absolute top-4 right-4 z-20 flex space-x-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button onClick={(e) => { e.stopPropagation(); onEdit(qualification); }} className="p-1.5 bg-blue-50 text-blue-500 rounded-lg hover:bg-blue-100 transition-colors" title="编辑">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
          </button>
          <button onClick={(e) => { e.stopPropagation(); onDelete(qualification.id); }} className="p-1.5 bg-rose-50 text-rose-500 rounded-lg hover:bg-rose-100 transition-colors" title="删除">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
          </button>
        </div>
      )}

      <div className="flex justify-between items-start mb-4 relative z-10 pr-16">
        <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-2xl flex-shrink-0 ${statusColor}`}>
          {icon}
        </div>
        <div className="ml-4">
          <h3 className="text-lg font-bold text-slate-800 leading-tight mb-1">{qualification.name}</h3>
          {qualification.company_name && (
            <p className="text-sm text-slate-500 mb-1">{qualification.company_name}</p>
          )}
          <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold border ${statusColor}`}>
            {statusText}
          </span>
        </div>
      </div>

      <div className="space-y-3 mt-5">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-500">资质等级</span>
          <span className="text-sm font-bold text-slate-700 bg-slate-100 px-2 py-1 rounded-md">{qualification.level || '无'}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium text-slate-500">到期时间</span>
          <span className={`text-sm font-bold px-2 py-1 rounded-md ${isExpired ? 'text-rose-600 bg-rose-50' : 'text-slate-700 bg-slate-100'}`}>
            {qualification.expiry_date || '长期有效'}
          </span>
        </div>
      </div>

      {qualification.file_url && (
        <div className="mt-5 pt-4 border-t border-slate-100 flex space-x-2">
          <a href={qualification.file_url} target="_blank" rel="noreferrer" className="flex-1 flex items-center justify-center py-2 bg-indigo-50 hover:bg-indigo-100 text-indigo-600 rounded-xl text-sm font-bold transition-colors">
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
            原文件
          </a>
          <a href={qualification.file_url.replace(/\.[^/.]+$/, "") + ".md"} target="_blank" rel="noreferrer" className="flex-1 flex items-center justify-center py-2 bg-slate-50 hover:bg-slate-100 text-slate-600 rounded-xl text-sm font-bold transition-colors">
            <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
            OCR 文本
          </a>
        </div>
      )}
    </motion.div>
  );
}
