import { useEffect, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  FileCog,
  Info,
  KeyRound,
  ScanText,
  Save,
  Server,
} from 'lucide-react';
import { apiFetch, API_BASE_URL } from '../../utils/api';

const DRAFT_STORAGE_KEY = 'bidding_model_env_draft';

interface ModelConfig {
  provider: string;
  description: string;
  accent: string;
  icon: typeof Server;
  fields: ModelFieldConfig[];
}

interface ModelFieldConfig {
  label: string;
  envKey: string;
  placeholder: string;
  secret?: boolean;
}

interface StoredUser {
  id?: string | number;
  email?: string;
  username?: string;
  tenant_id?: string;
  role?: string;
}

interface TenantOption {
  id: string;
  name: string;
}

const MODEL_CONFIGS: ModelConfig[] = [
  {
    provider: '招投标文件处理语言模型',
    description: '负责招投标文件的结构化提取、评标分析与标书生成。',
    accent: 'from-blue-500 to-cyan-400',
    icon: Server,
    fields: [
      { label: 'API Key', envKey: 'OPENAI_API_KEY', placeholder: '请输入 API Key', secret: true },
      { label: 'API 地址', envKey: 'OPENAI_API_BASE', placeholder: '请输入 API 地址' },
      { label: '模型名称', envKey: 'LLM_MODEL_NAME', placeholder: '请输入模型名称' },
    ],
  },
  {
    provider: '文档 OCR 模型（MinerU）',
    description: '负责 PDF、扫描件和复杂版面的 OCR 与文档结构解析。',
    accent: 'from-amber-500 to-orange-400',
    icon: ScanText,
    fields: [
      { label: 'API Token', envKey: 'MINERU_API_TOKEN', placeholder: '请输入 MinerU API Token', secret: true },
      { label: 'API 地址', envKey: 'MINERU_API_BASE_URL', placeholder: '请输入 MinerU API 地址' },
    ],
  },
  {
    provider: '视觉模型',
    description: '负责图片、图纸和其他视觉内容的理解与信息提取。',
    accent: 'from-indigo-500 to-violet-400',
    icon: KeyRound,
    fields: [
      { label: 'API Key', envKey: 'ALI_VLM_API_KEY', placeholder: '请输入视觉模型 API Key', secret: true },
      { label: 'API 地址', envKey: 'ALI_VLM_API_BASE', placeholder: '请输入视觉模型 API 地址' },
      { label: '模型名称', envKey: 'ALI_VLM_MODEL_NAME', placeholder: '请输入视觉模型名称' },
    ],
  },
];

const MODEL_KEYS = MODEL_CONFIGS.flatMap((config) => config.fields.map((field) => field.envKey));

const DEFAULT_VALUES: Record<string, string> = {
  LLM_MODEL_NAME: 'gpt-4o',
  MINERU_API_BASE_URL: 'https://mineru.net/api/v4',
  ALI_VLM_API_BASE: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  ALI_VLM_MODEL_NAME: 'qwen-vl-plus',
  LOCAL_VLM_API_BASE: 'http://127.0.0.1:8083/v1',
  LOCAL_VLM_MODEL_NAME: 'minimax-m3-mxfp8',
};

function readStoredUser(): StoredUser | null {
  try {
    const savedUser = localStorage.getItem('bidding_user');
    return savedUser ? JSON.parse(savedUser) as StoredUser : null;
  } catch (error) {
    console.warn('[模型配置] 读取当前用户信息失败。', error);
    return null;
  }
}

export function getDraftStorageKey(tenantId?: string): string {
  let identity = 'anonymous';
  try {
    const user = readStoredUser();
    identity = String(tenantId || user?.id || user?.email || user?.username || identity);
  } catch (error) {
    console.warn('[模型配置] 读取当前用户身份失败，将使用匿名草稿空间。', error);
  }
  return `${DRAFT_STORAGE_KEY}:${encodeURIComponent(identity)}`;
}

function readDraft(): Record<string, string> {
  try {
    const savedDraft = localStorage.getItem(getDraftStorageKey());
    if (!savedDraft) return { ...DEFAULT_VALUES };
    const parsedDraft = JSON.parse(savedDraft) as unknown;
    if (!parsedDraft || typeof parsedDraft !== 'object' || Array.isArray(parsedDraft)) return { ...DEFAULT_VALUES };
    return { ...DEFAULT_VALUES, ...(parsedDraft as Record<string, string>) };
  } catch (error) {
    console.warn('[模型配置] 读取本地草稿失败，将使用默认配置。', error);
    return { ...DEFAULT_VALUES };
  }
}

export function EnvConfigPage() {
  const storedUser = readStoredUser();
  const isPlatformAdmin = storedUser?.role === 'admin' || storedUser?.role === 'platform_admin';
  const [values, setValues] = useState<Record<string, string>>(readDraft);
  const [lastSavedValues, setLastSavedValues] = useState<Record<string, string>>(readDraft);
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [tenants, setTenants] = useState<TenantOption[]>([]);
  const [targetTenantId, setTargetTenantId] = useState(isPlatformAdmin ? '' : (storedUser?.tenant_id ?? ''));
  const changedCount = MODEL_KEYS.filter((key) => values[key] !== lastSavedValues[key]).length;

  useEffect(() => {
    if (!isPlatformAdmin) return;
    let isMounted = true;

    const loadTenants = async () => {
      try {
        const response = await apiFetch(`${API_BASE_URL}/api/v1/admin/tenants`);
        if (!response.ok) throw new Error(`租户列表请求失败: ${response.status}`);
        const tenantValues = await response.json() as TenantOption[];
        if (!isMounted) return;
        setTenants(tenantValues);
        setTargetTenantId((currentTenantId) => currentTenantId || tenantValues[0]?.id || '');
      } catch (loadError) {
        if (isMounted) setError('读取租户列表失败，无法选择模型配置租户');
        console.error('[模型配置] 租户列表读取失败。', loadError);
      }
    };

    void loadTenants();
    return () => {
      isMounted = false;
    };
  }, [isPlatformAdmin]);

  useEffect(() => {
    if (!targetTenantId) return;
    let isMounted = true;

    const loadBackendConfig = async () => {
      try {
        const query = `?tenant_id=${encodeURIComponent(targetTenantId)}`;
        const response = await apiFetch(`${API_BASE_URL}/api/v1/admin/model-config${query}`);
        if (!response.ok) {
          if (isMounted && response.status === 403) {
            setError('只有平台管理员可以读取和修改后端模型配置');
          }
          return;
        }

        const payload = await response.json() as { data?: { values?: Record<string, string> } };
        const backendValues = payload.data?.values;
        if (!isMounted || !backendValues) return;

        setValues((currentValues) => ({ ...currentValues, ...backendValues }));
        setLastSavedValues((currentValues) => ({ ...currentValues, ...backendValues }));
        console.info('[模型配置] 已加载后端当前生效配置。');
      } catch (loadError) {
        if (isMounted) {
          setError('读取后端模型配置失败，请确认后端服务已启动');
        }
        console.error('[模型配置] 后端配置读取失败。', loadError);
      }
    };

    void loadBackendConfig();
    return () => {
      isMounted = false;
    };
  }, [targetTenantId]);

  const updateValue = (key: string, value: string) => {
    setValues((currentValues) => ({ ...currentValues, [key]: value }));
    setNotice('');
    setError('');
  };

  const handleSaveBackend = async () => {
    setIsSaving(true);
    setNotice('');
    setError('');

    try {
      const query = `?tenant_id=${encodeURIComponent(targetTenantId)}`;
      const response = await apiFetch(`${API_BASE_URL}/api/v1/admin/model-config${query}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        // 只提交当前页面管理的八个键，避免把本地缓存中的其他变量提交给后端。
        body: JSON.stringify(Object.fromEntries(MODEL_KEYS.map((key) => [key, values[key] ?? '']))),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => ({})) as { detail?: string };
        setError(errorPayload.detail || '模型配置保存到后端失败');
        return;
      }

      const payload = await response.json() as { data?: { values?: Record<string, string> } };
      const savedValues = payload.data?.values ?? values;
      setValues((currentValues) => ({ ...currentValues, ...savedValues }));
      setLastSavedValues((currentValues) => ({ ...currentValues, ...savedValues }));
      localStorage.setItem(getDraftStorageKey(targetTenantId), JSON.stringify(savedValues));
      setNotice('模型配置已保存到后端并立即生效');
      console.info('[模型配置] 后端模型配置保存成功。');
    } catch (saveError) {
      setError('模型配置保存到后端失败，请检查网络连接');
      console.error('[模型配置] 后端模型配置保存失败。', saveError);
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    setValues({ ...DEFAULT_VALUES });
    setNotice('已恢复为示例模型配置，尚未保存到后端');
    setError('');
    console.info('[模型配置] 已恢复示例配置。');
  };

  return (
    <div className="relative min-h-[calc(100vh-6rem)] overflow-hidden rounded-3xl border border-slate-200/60 bg-slate-50/50 p-6 md:p-8">
      <div className="pointer-events-none absolute -right-32 -top-48 h-[520px] w-[520px] rounded-full bg-indigo-500/10 blur-[100px]" />
      <div className="pointer-events-none absolute -bottom-48 -left-32 h-[420px] w-[420px] rounded-full bg-blue-500/10 blur-[100px]" />

      <div className="relative z-10">
        <div className="flex flex-col justify-between gap-5 xl:flex-row xl:items-start">
          <div>
            <div className="mb-3 flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-600 to-blue-500 text-white shadow-lg shadow-indigo-500/25">
                <FileCog className="h-6 w-6" />
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-[0.22em] text-indigo-500">Model Runtime</p>
                <h1 className="bg-gradient-to-br from-slate-900 to-indigo-900 bg-clip-text text-3xl font-extrabold text-transparent">模型配置中心</h1>
              </div>
            </div>
            {isPlatformAdmin && (
              <div className="mt-4 flex items-center gap-3">
                <label htmlFor="model-config-tenant" className="text-sm font-semibold text-slate-700">配置租户</label>
                <select id="model-config-tenant" value={targetTenantId} onChange={(event) => setTargetTenantId(event.target.value)} className="min-w-56 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-indigo-400 focus:ring-4 focus:ring-indigo-500/10">
                  <option value="" disabled>请选择租户</option>
                  {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
                </select>
              </div>
            )}
            <p className="max-w-2xl text-sm leading-6 text-slate-500">只需填写模型 API Key、模型名称和 API 地址，即可完成当前系统的模型接入配置。</p>
          </div>

        </div>

        {(notice || error) && (
          <div className={`mb-6 flex items-center gap-3 rounded-2xl border px-4 py-3 text-sm ${error ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
            {error ? <AlertTriangle className="h-4 w-4 shrink-0" /> : <Check className="h-4 w-4 shrink-0" />}
            <span>{error || notice}</span>
          </div>
        )}

        <div className="grid gap-6 xl:grid-cols-3">
          {MODEL_CONFIGS.map((config) => (
            <ModelConfigCard key={config.provider} config={config} values={values} visibleSecrets={visibleSecrets} onChange={updateValue} onToggleSecret={(key) => setVisibleSecrets((current) => ({ ...current, [key]: !current[key] }))} />
          ))}
        </div>

        <div className="mt-6 flex flex-col justify-between gap-4 rounded-3xl border border-slate-200/60 bg-white/75 p-5 shadow-xl shadow-slate-200/20 backdrop-blur-xl sm:flex-row sm:items-center md:p-6">
          <div className="flex items-start gap-3 text-xs leading-5 text-slate-400">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-indigo-500" />
            <span>{changedCount > 0 ? `有 ${changedCount} 项修改尚未保存。` : '当前模型配置已同步到后端。'} 点击“保存到后端”后，配置才会写入后端并立即生效。</span>
          </div>
          <div className="flex shrink-0 flex-wrap gap-3">
            <button type="button" onClick={handleReset} className="inline-flex items-center rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700">恢复示例</button>
            <button type="button" onClick={handleSaveBackend} disabled={isSaving} className="inline-flex items-center rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-slate-900/15 transition-all hover:-translate-y-0.5 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60"><Save className="mr-2 h-4 w-4" />{isSaving ? '正在保存…' : '保存到后端'}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

interface ModelConfigCardProps {
  config: ModelConfig;
  values: Record<string, string>;
  visibleSecrets: Record<string, boolean>;
  onChange: (key: string, value: string) => void;
  onToggleSecret: (key: string) => void;
}

function ModelConfigCard({ config, values, visibleSecrets, onChange, onToggleSecret }: ModelConfigCardProps) {
  const Icon = config.icon;
  return (
    <section className="rounded-3xl border border-slate-200/60 bg-white/75 p-5 shadow-xl shadow-slate-200/20 backdrop-blur-xl transition-all hover:-translate-y-1 hover:shadow-indigo-100/50 md:p-6">
      <div className="mb-6 flex items-start gap-3 border-b border-slate-100 pb-5">
        <div className={`flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br ${config.accent} text-white shadow-md`}><Icon className="h-5 w-5" /></div>
        <div>
          <h2 className="text-lg font-bold text-slate-800">{config.provider}</h2>
          <p className="mt-1 text-xs leading-5 text-slate-400">{config.description}</p>
        </div>
      </div>
      <div className="space-y-4">
        {config.fields.map((field) => (
          <ModelField
            key={field.envKey}
            label={field.label}
            envKey={field.envKey}
            value={values[field.envKey] ?? ''}
            placeholder={field.placeholder}
            secret={field.secret}
            isVisible={visibleSecrets[field.envKey] ?? false}
            onToggleVisibility={() => onToggleSecret(field.envKey)}
            onChange={(value) => onChange(field.envKey, value)}
          />
        ))}
      </div>
    </section>
  );
}

interface ModelFieldProps {
  label: string;
  envKey: string;
  value: string;
  placeholder: string;
  secret?: boolean;
  isVisible?: boolean;
  onToggleVisibility?: () => void;
  onChange: (value: string) => void;
}

function ModelField({ label, envKey, value, placeholder, secret = false, isVisible = false, onToggleVisibility, onChange }: ModelFieldProps) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <label htmlFor={`env-${envKey}`} className="text-sm font-semibold text-slate-700">{label}</label>
        {secret && onToggleVisibility && <button type="button" onClick={onToggleVisibility} className="rounded-lg p-1 text-slate-400 transition-colors hover:bg-indigo-50 hover:text-indigo-600" aria-label={isVisible ? `隐藏 ${envKey}` : `显示 ${envKey}`}>{isVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button>}
      </div>
      <code className="mb-2 block text-[11px] font-medium text-indigo-500">{envKey}</code>
      <input id={`env-${envKey}`} type={secret && !isVisible ? 'password' : 'text'} value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="w-full rounded-xl border border-slate-200 bg-slate-50/80 px-3.5 py-3 font-mono text-sm text-slate-700 outline-none transition-all placeholder:text-slate-300 focus:border-indigo-400 focus:bg-white focus:ring-4 focus:ring-indigo-500/10" />
    </div>
  );
}
