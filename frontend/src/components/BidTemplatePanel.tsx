import React, { useEffect, useRef, useState } from 'react';
import { apiFetch, API_BASE_URL } from '../utils/api';
import { useDialog } from './DialogProvider';

interface BidTemplate {
  id: string;
  filename: string;
  file_size: number;
  file_sha256: string;
  content_type?: string | null;
  template_type: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface BidTemplateBinding {
  id: string;
  document_id: string;
  template_id: string;
  status: string;
  note?: string | null;
  created_at: string;
  updated_at: string;
}

interface BidTemplatePanelProps {
  documentId: string;
}

interface ApiPayload<T> {
  data?: T;
  detail?: string;
  message?: string;
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function getApiError(payload: ApiPayload<unknown>, fallback: string): string {
  return payload.detail || payload.message || fallback;
}

function readTemplateList(payload: ApiPayload<BidTemplate[]> | BidTemplate[]): BidTemplate[] {
  if (Array.isArray(payload)) return payload;
  return Array.isArray(payload.data) ? payload.data : [];
}

export const BidTemplatePanel: React.FC<BidTemplatePanelProps> = ({ documentId }) => {
  const { confirm } = useDialog();
  const [templates, setTemplates] = useState<BidTemplate[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [boundTemplateId, setBoundTemplateId] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isBinding, setIsBinding] = useState(false);
  const [isUnbinding, setIsUnbinding] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const loadTemplates = async () => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/templates`);
      if (!response.ok) throw new Error('获取外部模板列表失败');
      const payload = await response.json() as ApiPayload<BidTemplate[]> | BidTemplate[];
      const nextTemplates = readTemplateList(payload);
      setTemplates(nextTemplates);
      setSelectedTemplateId((previous) => previous || nextTemplates[0]?.id || '');
    } catch (loadError) {
      console.warn('获取外部投标模板列表失败:', loadError);
      setError(loadError instanceof Error ? loadError.message : '获取外部模板列表失败');
    }
  };

  const loadBinding = async () => {
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/template-bindings/${documentId}`);
      if (!response.ok) throw new Error('获取当前模板绑定失败');
      const payload = await response.json() as ApiPayload<BidTemplateBinding | null>;
      const binding = payload.data;
      const nextBoundTemplateId = binding?.template_id || '';
      setBoundTemplateId(nextBoundTemplateId);
      if (nextBoundTemplateId) setSelectedTemplateId(nextBoundTemplateId);
    } catch (loadError) {
      console.warn('获取外部投标模板绑定失败:', loadError);
      setError(loadError instanceof Error ? loadError.message : '获取当前模板绑定失败');
    }
  };

  useEffect(() => {
    if (!documentId) return;
    setTemplates([]);
    setSelectedTemplateId('');
    setBoundTemplateId('');
    setNotice(null);
    setError(null);
    setIsLoading(true);
    Promise.all([loadTemplates(), loadBinding()]).finally(() => setIsLoading(false));
  }, [documentId]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.docx')) {
      setError('只能上传 .docx 格式的 Word 空白模板');
      return;
    }

    setIsUploading(true);
    setError(null);
    setNotice(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/templates/upload`, {
        method: 'POST',
        body: formData,
      });
      const payload = await response.json() as ApiPayload<BidTemplate>;
      if (!response.ok || !payload.data) throw new Error(getApiError(payload, '模板上传失败'));

      setTemplates((previous) => [
        payload.data as BidTemplate,
        ...previous.filter((item) => item.id !== payload.data?.id),
      ]);
      setSelectedTemplateId(payload.data.id);
      setNotice('模板上传成功，请点击“绑定到当前文档”后再启动 Agent。');
    } catch (uploadError) {
      console.warn('上传外部投标模板失败:', uploadError);
      setError(uploadError instanceof Error ? uploadError.message : '模板上传失败');
    } finally {
      setIsUploading(false);
    }
  };

  const handleBind = async () => {
    if (!selectedTemplateId || isBinding) return;

    setIsBinding(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/template-bindings/${documentId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: selectedTemplateId }),
      });
      const payload = await response.json() as ApiPayload<BidTemplateBinding>;
      if (!response.ok || !payload.data) throw new Error(getApiError(payload, '模板绑定失败'));

      setBoundTemplateId(payload.data.template_id);
      setNotice('模板绑定成功，后续自动填报将直接使用这份空白 Word 模板。');
    } catch (bindError) {
      console.warn('绑定外部投标模板失败:', bindError);
      setError(bindError instanceof Error ? bindError.message : '模板绑定失败');
    } finally {
      setIsBinding(false);
    }
  };

  const handleUnbind = async () => {
    if (!boundTemplateId || isUnbinding) return;
    const confirmed = await confirm('解除绑定后，后续提取和 Agent 填报将使用招标文件原格式。确定解除吗？', {
      title: '确认解除模板绑定',
      intent: 'warning',
      confirmText: '解除绑定',
    });
    if (!confirmed) return;

    setIsUnbinding(true);
    setError(null);
    setNotice(null);
    try {
      const response = await apiFetch(`${API_BASE_URL}/api/v1/bidding/template-bindings/${documentId}`, {
        method: 'DELETE',
      });
      const payload = await response.json() as ApiPayload<BidTemplateBinding | null>;
      if (!response.ok) throw new Error(getApiError(payload, '解除模板绑定失败'));

      setBoundTemplateId('');
      setNotice('模板已解除绑定，后续将使用招标文件原格式。');
    } catch (unbindError) {
      console.warn('解除外部投标模板绑定失败:', unbindError);
      setError(unbindError instanceof Error ? unbindError.message : '解除模板绑定失败');
    } finally {
      setIsUnbinding(false);
    }
  };

  const boundTemplate = templates.find((template) => template.id === boundTemplateId);

  return (
    <section
      data-testid="bid-template-panel"
      className="border-t border-slate-800/80 bg-slate-950/75 px-4 py-3.5"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-extrabold text-slate-100">📎 外部空白 Word 模板</span>
            <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
              不需要增加标识
            </span>
          </div>
          <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
            上传你们自己的空白 .docx，系统按文档结构和表格布局使用；不绑定时继续沿用招标文件原格式。
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            onChange={handleUpload}
            className="hidden"
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || isLoading}
            className="rounded-lg border border-purple-500/40 bg-purple-900/40 px-3 py-2 text-xs font-bold text-purple-200 transition hover:bg-purple-800/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isUploading ? '上传中...' : '上传 .docx 模板'}
          </button>

          <select
            aria-label="选择外部空白 Word 模板"
            value={selectedTemplateId}
            onChange={(event) => setSelectedTemplateId(event.target.value)}
            disabled={isLoading || templates.length === 0}
            className="min-w-56 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-2 text-xs text-slate-200 outline-none focus:border-purple-500 disabled:opacity-50"
          >
            {templates.length > 0 ? (
              templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.filename}（{formatFileSize(template.file_size)}）
                </option>
              ))
            ) : (
              <option value="">暂无已上传模板</option>
            )}
          </select>

          <button
            type="button"
            onClick={handleBind}
            disabled={!selectedTemplateId || isBinding || isLoading}
            className="rounded-lg border border-blue-500/40 bg-blue-900/40 px-3 py-2 text-xs font-bold text-blue-200 transition hover:bg-blue-800/60 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isBinding ? '绑定中...' : '绑定到当前文档'}
          </button>

          {boundTemplateId && (
            <button
              type="button"
              onClick={handleUnbind}
              disabled={isUnbinding || isLoading}
              className="rounded-lg border border-amber-500/40 bg-amber-900/40 px-3 py-2 text-xs font-bold text-amber-200 transition hover:bg-amber-800/60 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isUnbinding ? '解除中...' : '解除绑定'}
            </button>
          )}
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
        <span className={boundTemplateId ? 'font-bold text-emerald-300' : 'text-slate-500'}>
          {boundTemplateId
            ? `当前绑定：${boundTemplate?.filename || '外部 Word 模板'}`
            : '当前绑定：未绑定，使用招标文件原格式'}
        </span>
        {notice && <span className="text-purple-300">💡 {notice}</span>}
        {error && <span className="text-rose-300">❌ {error}</span>}
      </div>
    </section>
  );
};
