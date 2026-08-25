import { useRef, useState } from 'react';
import type { ChangeEvent } from 'react';
import {
  AlertTriangle,
  Check,
  Download,
  Eye,
  EyeOff,
  FileCog,
  Info,
  KeyRound,
  ScanText,
  Save,
  Server,
  Upload,
} from 'lucide-react';

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

export function getDraftStorageKey(): string {
  let identity = 'anonymous';
  try {
    const savedUser = localStorage.getItem('bidding_user');
    if (savedUser) {
      const user = JSON.parse(savedUser) as { id?: string | number; email?: string; username?: string };
      identity = String(user.id ?? user.email ?? user.username ?? identity);
    }
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

export function parseEnvContent(content: string): Record<string, string> {
  const values: Record<string, string> = {};
  content.split(/\r?\n/).forEach((line) => {
    const trimmedLine = line.trim();
    if (!trimmedLine || trimmedLine.startsWith('#')) return;
    const separatorIndex = trimmedLine.indexOf('=');
    if (separatorIndex <= 0) return;

    const key = trimmedLine.slice(0, separatorIndex).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) return;
    let value = trimmedLine.slice(separatorIndex + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1).replaceAll('\\"', '"').replaceAll("\\'", "'");
    }
    values[key] = value;
  });
  return values;
}

export function serializeEnvContent(values: Record<string, string>): string {
  const orderedKeys = [...MODEL_KEYS, ...Object.keys(values).filter((key) => !MODEL_KEYS.includes(key)).sort()];
  return orderedKeys
    .filter((key, index, keys) => keys.indexOf(key) === index && values[key] !== undefined)
    .map((key) => `${key}=${formatEnvValue(values[key])}`)
    .join('\n') + '\n';
}

function formatEnvValue(value: string): string {
  if (!/[\s#"']/.test(value)) return value;
  return `"${value.replaceAll('"', '\\"')}"`;
}

export function EnvConfigPage() {
  const [values, setValues] = useState<Record<string, string>>(readDraft);
  const [lastSavedValues, setLastSavedValues] = useState<Record<string, string>>(readDraft);
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({});
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);
  const changedCount = MODEL_KEYS.filter((key) => values[key] !== lastSavedValues[key]).length;

  const updateValue = (key: string, value: string) => {
    setValues((currentValues) => ({ ...currentValues, [key]: value }));
    setNotice('');
    setError('');
  };

  const handleSaveDraft = () => {
    try {
      localStorage.setItem(getDraftStorageKey(), JSON.stringify(values));
      setLastSavedValues({ ...values });
      setNotice('模型配置草稿已保存到当前浏览器');
      console.info('[模型配置] 草稿保存成功。');
    } catch (saveError) {
      setError('草稿保存失败，请检查浏览器存储权限');
      console.error('[模型配置] 草稿保存失败。', saveError);
    }
  };

  const handleExport = () => {
    const file = new Blob([serializeEnvContent(values)], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = '.env';
    link.click();
    URL.revokeObjectURL(url);
    setNotice('已导出 .env，请将文件放置到项目根目录');
    console.info('[模型配置] .env 文件导出成功。');
  };

  const handleFileChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    try {
      const importedValues = parseEnvContent(await file.text());
      const importedModelValues = Object.fromEntries(MODEL_KEYS.filter((key) => importedValues[key] !== undefined).map((key) => [key, importedValues[key]]));
      if (Object.keys(importedModelValues).length === 0) {
        setError('文件中未找到模型 API、名称或地址配置');
        return;
      }
      setValues((currentValues) => ({ ...currentValues, ...importedValues }));
      setNotice(`已导入 ${Object.keys(importedModelValues).length} 项模型配置，请检查后保存或导出`);
      setError('');
      console.info('[模型配置] .env 文件导入成功。', { count: Object.keys(importedModelValues).length });
    } catch (importError) {
      setError('文件读取失败，请重新选择 .env 文件');
      console.error('[模型配置] .env 文件读取失败。', importError);
    }
  };

  const handleReset = () => {
    setValues({ ...DEFAULT_VALUES });
    setNotice('已恢复为示例模型配置，尚未写入本地草稿');
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
            <p className="max-w-2xl text-sm leading-6 text-slate-500">只需填写模型 API Key、模型名称和 API 地址，即可完成当前系统的模型接入配置。</p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <input ref={fileInputRef} type="file" accept=".env,text/plain" aria-label="导入 .env 文件" onChange={handleFileChange} className="hidden" />
            <button type="button" onClick={() => fileInputRef.current?.click()} className="inline-flex items-center rounded-xl border border-slate-200 bg-white/80 px-4 py-2.5 text-sm font-semibold text-slate-600 shadow-sm transition-all hover:-translate-y-0.5 hover:border-indigo-200 hover:text-indigo-700">
              <Upload className="mr-2 h-4 w-4" />导入 .env
            </button>
            <button type="button" onClick={handleExport} className="inline-flex items-center rounded-xl bg-indigo-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-indigo-500/25 transition-all hover:-translate-y-0.5 hover:bg-indigo-700">
              <Download className="mr-2 h-4 w-4" />导出 .env
            </button>
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
            <span>{changedCount > 0 ? `有 ${changedCount} 项修改尚未保存。` : '当前模型配置已保存。'} 导入原始 `.env` 后再导出，可以保留其他未展示的环境变量。</span>
          </div>
          <div className="flex shrink-0 flex-wrap gap-3">
            <button type="button" onClick={handleReset} className="inline-flex items-center rounded-xl px-4 py-2.5 text-sm font-semibold text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700">恢复示例</button>
            <button type="button" onClick={handleSaveDraft} className="inline-flex items-center rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-slate-900/15 transition-all hover:-translate-y-0.5 hover:bg-slate-800"><Save className="mr-2 h-4 w-4" />保存草稿</button>
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
