import React, { useState, useEffect } from 'react';
import { 
  Building2, 
  UserCheck, 
  Landmark, 
  Star, 
  Plus, 
  Trash2, 
  Copy, 
  CheckCircle2, 
  AlertCircle, 
  RefreshCw, 
  Check, 
  ShieldAlert, 
  FileText
} from 'lucide-react';
import { apiFetch } from '../utils/api';

export interface CompanyProfileItem {
  id?: string;
  profile_name?: string;
  is_default?: boolean;
  company_name?: string;
  legal_representative?: string;
  authorized_delegate?: string;
  credit_code?: string;
  registered_address?: string;
  contact_phone?: string;
  email?: string;
  bank_name?: string;
  bank_account?: string;
  created_at?: string;
  updated_at?: string;
}

const emptyProfileForm: CompanyProfileItem = {
  profile_name: '',
  company_name: '',
  legal_representative: '',
  authorized_delegate: '',
  credit_code: '',
  registered_address: '',
  contact_phone: '',
  email: '',
  bank_name: '',
  bank_account: ''
};

export const CompanyProfilePage: React.FC = () => {
  const [profiles, setProfiles] = useState<CompanyProfileItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState<boolean>(false);
  const [formData, setFormData] = useState<CompanyProfileItem>(emptyProfileForm);

  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [isSettingDefault, setIsSettingDefault] = useState<boolean>(false);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [notice, setNotice] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // 1. 初始化拉取企业档案列表
  useEffect(() => {
    fetchProfilesList();
  }, []);

  const showNotice = (message: string, type: 'success' | 'error' = 'success') => {
    setNotice({ message, type });
    setTimeout(() => setNotice(null), 5000);
  };

  const fetchProfilesList = async (targetSelectId?: string) => {
    setIsLoading(true);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/company/profiles`);
      if (res.ok) {
        const data = await res.json();
        const list: CompanyProfileItem[] = data.profiles || [];
        setProfiles(list);

        if (list.length > 0) {
          // 如果传入了目标 ID 则选中它，否则保留当前选中或默认选第一项（默认档案）
          let nextSelected = list[0];
          if (targetSelectId) {
            const found = list.find(p => p.id === targetSelectId);
            if (found) nextSelected = found;
          } else if (selectedId && !isCreating) {
            const found = list.find(p => p.id === selectedId);
            if (found) nextSelected = found;
          }
          setSelectedId(nextSelected.id || null);
          setFormData({ ...nextSelected });
          setIsCreating(false);
        } else {
          // 若暂无记录，进入新建模式
          setSelectedId(null);
          setFormData({ ...emptyProfileForm, profile_name: '默认企业档案' });
          setIsCreating(true);
        }
      }
    } catch (err: any) {
      console.error('获取企业档案列表失败', err);
      showNotice(`获取企业档案列表失败: ${err.message || '网络异常'}`, 'error');
    } finally {
      setIsLoading(false);
    }
  };

  // 选中某条档案
  const handleSelectProfile = (item: CompanyProfileItem) => {
    setIsCreating(false);
    setSelectedId(item.id || null);
    setFormData({
      profile_name: item.profile_name || '',
      company_name: item.company_name || '',
      legal_representative: item.legal_representative || '',
      authorized_delegate: item.authorized_delegate || '',
      credit_code: item.credit_code || '',
      registered_address: item.registered_address || '',
      contact_phone: item.contact_phone || '',
      email: item.email || '',
      bank_name: item.bank_name || '',
      bank_account: item.bank_account || ''
    });
  };

  // 点击新建档案
  const handleStartCreate = () => {
    setIsCreating(true);
    setSelectedId(null);
    setFormData({
      ...emptyProfileForm,
      profile_name: `企业档案-${profiles.length + 1}`
    });
  };

  // 复制当前档案快速新建
  const handleCloneProfile = () => {
    setIsCreating(true);
    setSelectedId(null);
    setFormData({
      ...formData,
      profile_name: `${formData.profile_name || '企业档案'} (副本)`
    });
    showNotice('已复制当前档案内容，请修改名称与字段后保存。', 'success');
  };

  // 提交保存（新建或更新）
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.profile_name?.trim()) {
      showNotice('请输入档案显示名称', 'error');
      return;
    }
    if (!formData.company_name?.trim()) {
      showNotice('请输入投标人公司全称', 'error');
      return;
    }

    setIsSaving(true);
    const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
    try {
      if (isCreating) {
        // POST 创建
        const res = await apiFetch(`${baseUrl}/api/v1/company/profiles`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData)
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `创建失败 (HTTP ${res.status})`);
        }
        const created = await res.json();
        showNotice(`✅ 成功创建企业档案「${created.profile_name}」！`);
        await fetchProfilesList(created.id);
      } else if (selectedId) {
        // PUT 更新
        const res = await apiFetch(`${baseUrl}/api/v1/company/profiles/${selectedId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(formData)
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || `保存失败 (HTTP ${res.status})`);
        }
        const updated = await res.json();
        showNotice(`✅ 企业档案「${updated.profile_name}」已成功更新！`);
        await fetchProfilesList(selectedId);
      }
    } catch (err: any) {
      showNotice(`❌ 操作失败: ${err.message || '网络通讯异常'}`, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  // 设为默认档案
  const handleSetDefault = async () => {
    if (!selectedId) return;
    setIsSettingDefault(true);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/company/profiles/${selectedId}/set-default`, {
        method: 'PATCH'
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `设置失败 (HTTP ${res.status})`);
      }
      showNotice('⭐ 已成功将该档案设为系统默认主体！');
      await fetchProfilesList(selectedId);
    } catch (err: any) {
      showNotice(`❌ 设为默认失败: ${err.message}`, 'error');
    } finally {
      setIsSettingDefault(false);
    }
  };

  // 删除当前档案
  const handleDelete = async () => {
    if (!selectedId) return;
    const current = profiles.find(p => p.id === selectedId);
    if (current?.is_default) {
      showNotice('默认档案不允许直接删除，请先将其他档案设为默认。', 'error');
      return;
    }

    if (!window.confirm(`确定要删除企业档案「${current?.profile_name || '当前档案'}」吗？`)) {
      return;
    }

    setIsDeleting(true);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/company/profiles/${selectedId}`, {
        method: 'DELETE'
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `删除失败 (HTTP ${res.status})`);
      }
      showNotice('🗑️ 企业档案已删除');
      await fetchProfilesList();
    } catch (err: any) {
      showNotice(`❌ 删除失败: ${err.message}`, 'error');
    } finally {
      setIsDeleting(false);
    }
  };

  const activeProfile = profiles.find(p => p.id === selectedId);

  return (
    <div className="space-y-6 max-w-7xl mx-auto animate-fade-in pb-12">
      {/* 页面 Header */}
      <div className="bg-gradient-to-r from-slate-900 via-indigo-950 to-blue-900 text-white p-8 rounded-3xl shadow-xl border border-white/10 relative overflow-hidden">
        <div className="absolute -right-10 -bottom-10 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="px-3 py-1 bg-blue-500/20 text-blue-300 rounded-full text-xs font-bold border border-blue-400/30">
                主数据管理 (Master Data)
              </span>
              <span className="text-xs text-slate-400 font-mono">多主体企业档案池 ({profiles.length} 个主体)</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">企业基础档案与主体配置</h1>
            <p className="text-slate-300 text-xs md:text-sm mt-1 max-w-2xl leading-relaxed">
              集中管理母公司、子公司、分公司及联合体成员的投标档案。在标书撰写控制台可直接下拉选择指定主体生成标书，告别反复修改覆盖。
            </p>
          </div>

          <div className="flex items-center gap-3 self-start md:self-auto">
            <button
              onClick={handleStartCreate}
              className="px-4 py-2.5 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-bold rounded-xl border border-blue-400/30 transition-all flex items-center gap-2 shadow-lg cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              <span>新建主体档案</span>
            </button>
            <button
              onClick={() => fetchProfilesList()}
              disabled={isLoading}
              className="px-3.5 py-2.5 bg-white/10 hover:bg-white/20 active:bg-white/30 text-white text-xs font-bold rounded-xl border border-white/20 transition-all flex items-center gap-1.5 shadow-xs cursor-pointer"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
              <span>刷新</span>
            </button>
          </div>
        </div>
      </div>

      {/* 提示 Alert */}
      {notice && (
        <div
          className={`p-4 rounded-2xl text-xs font-semibold flex items-center justify-between shadow-xs border animate-scale-up ${
            notice.type === 'success'
              ? 'bg-emerald-50 text-emerald-900 border-emerald-200'
              : 'bg-rose-50 text-rose-900 border-rose-200'
          }`}
        >
          <div className="flex items-center gap-2">
            {notice.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-600 flex-shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
            )}
            <span>{notice.message}</span>
          </div>
          <button
            onClick={() => setNotice(null)}
            className="text-slate-400 hover:text-slate-600 font-bold px-2 py-0.5"
          >
            ✕
          </button>
        </div>
      )}

      {/* 主布局：左侧主体列表 + 右侧详情编辑 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* ==================== 左侧：主体档案列表 (4 列) ==================== */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between px-2">
            <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <Building2 className="w-4 h-4 text-blue-600" />
              <span>投标主体列表</span>
              <span className="text-xs font-normal text-slate-400 font-mono">({profiles.length})</span>
            </h2>
            <span className="text-[11px] text-slate-400">点击切换编辑</span>
          </div>

          <div className="space-y-2.5 max-h-[720px] overflow-y-auto pr-1">
            {profiles.length === 0 && !isLoading && (
              <div className="p-8 text-center bg-white rounded-2xl border border-dashed border-slate-200">
                <FileText className="w-8 h-8 text-slate-300 mx-auto mb-2" />
                <p className="text-xs text-slate-500 font-medium">暂无企业档案</p>
                <button
                  onClick={handleStartCreate}
                  className="mt-3 px-3 py-1.5 bg-blue-50 text-blue-600 rounded-lg text-xs font-bold hover:bg-blue-100"
                >
                  立即新建
                </button>
              </div>
            )}

            {profiles.map((item) => {
              const isSelected = !isCreating && item.id === selectedId;
              return (
                <div
                  key={item.id}
                  onClick={() => handleSelectProfile(item)}
                  className={`p-4 rounded-2xl border transition-all cursor-pointer relative overflow-hidden group ${
                    isSelected
                      ? 'bg-gradient-to-br from-blue-50/90 to-indigo-50/70 border-blue-500 shadow-md ring-2 ring-blue-500/20'
                      : 'bg-white border-slate-200 hover:border-blue-300 hover:shadow-xs'
                  }`}
                >
                  {/* 默认档案角标 */}
                  {item.is_default && (
                    <div className="absolute top-0 right-0">
                      <div className="bg-gradient-to-r from-emerald-500 to-teal-500 text-white text-[10px] font-bold px-2.5 py-0.5 rounded-bl-xl shadow-xs flex items-center gap-1">
                        <Star className="w-3 h-3 fill-current text-amber-200" />
                        <span>默认主体</span>
                      </div>
                    </div>
                  )}

                  <div className="pr-16">
                    <h3 className={`text-sm font-extrabold truncate ${isSelected ? 'text-blue-950' : 'text-slate-800'}`}>
                      {item.profile_name || '未命名主体'}
                    </h3>
                    <p className="text-xs text-slate-500 truncate mt-1">
                      {item.company_name || '尚未填写公司全称'}
                    </p>
                  </div>

                  <div className="mt-3 pt-2.5 border-t border-slate-100/80 flex items-center justify-between text-[11px] text-slate-400">
                    <span className="truncate max-w-[140px]">
                      法人: {item.legal_representative || '--'}
                    </span>
                    <span className="font-mono text-[10px]">
                      {item.credit_code ? `${item.credit_code.slice(0, 8)}...` : '无税号'}
                    </span>
                  </div>
                </div>
              );
            })}

            {/* 新建卡片占位（处于创建态时高亮） */}
            {isCreating && (
              <div className="p-4 rounded-2xl border-2 border-dashed border-blue-400 bg-blue-50/50 shadow-xs">
                <div className="flex items-center gap-2 text-blue-700 font-bold text-xs">
                  <Plus className="w-4 h-4" />
                  <span>正在新建档案草稿...</span>
                </div>
                <p className="text-[11px] text-blue-600/80 mt-1">请在右侧表单中填写并点击保存</p>
              </div>
            )}
          </div>
        </div>

        {/* ==================== 右侧：表单编辑 / 新建区 (8 列) ==================== */}
        <div className="lg:col-span-8">
          <form onSubmit={handleSubmit} className="space-y-6">
            
            {/* 顶部状态栏与工具栏 */}
            <div className="bg-white p-5 rounded-3xl border border-slate-200 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-extrabold px-2.5 py-0.5 rounded-full bg-slate-100 text-slate-700">
                    {isCreating ? '新建档案' : '编辑档案'}
                  </span>
                  <h2 className="text-base font-extrabold text-slate-900 truncate max-w-md">
                    {isCreating ? '录入新投标主体' : formData.profile_name || '编辑企业档案'}
                  </h2>
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  {isCreating
                    ? '填写完成后保存，该主体即可在标书撰写控制台被直接调用'
                    : `主体唯一标识: ${selectedId || '--'}`}
                </p>
              </div>

              {/* 顶部快捷操作 */}
              <div className="flex items-center gap-2 flex-wrap">
                {!isCreating && (
                  <>
                    {!activeProfile?.is_default && (
                      <button
                        type="button"
                        onClick={handleSetDefault}
                        disabled={isSettingDefault}
                        className="px-3 py-1.5 bg-amber-50 hover:bg-amber-100 text-amber-800 text-xs font-bold rounded-xl border border-amber-200 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                      >
                        <Star className="w-3.5 h-3.5 text-amber-600" />
                        <span>设为默认</span>
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleCloneProfile}
                      className="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-xl border border-slate-200 transition-all flex items-center gap-1.5 cursor-pointer"
                    >
                      <Copy className="w-3.5 h-3.5" />
                      <span>复制此档案</span>
                    </button>
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={isDeleting || activeProfile?.is_default}
                      title={activeProfile?.is_default ? '默认档案不可删除' : '删除档案'}
                      className="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-bold rounded-xl border border-rose-200 transition-all flex items-center gap-1.5 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>删除</span>
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* 档案核心标识：显示名称 */}
            <div className="bg-gradient-to-r from-blue-50/80 via-indigo-50/60 to-white p-5 rounded-3xl border border-blue-200/80 shadow-xs">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex-1">
                  <label className="block text-xs font-extrabold text-blue-950 mb-1.5">
                    档案显示名称 <span className="text-rose-500">*</span>
                    <span className="text-slate-400 font-normal ml-2 text-[11px]">(用于在标书撰写下拉菜单中标识，如："四川石楠-成都分公司"、"联合体主体-A公司")</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="例如: 四川石楠建设-总部"
                    value={formData.profile_name || ''}
                    onChange={(e) => setFormData({ ...formData, profile_name: e.target.value })}
                    className="w-full p-3 bg-white border border-blue-300 rounded-xl text-xs font-extrabold text-slate-900 focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all shadow-inner"
                  />
                </div>
              </div>
            </div>

            {/* 字段输入卡片网格 */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              
              {/* 卡片 1: 基础身份标识 */}
              <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4 hover:shadow-md transition-shadow">
                <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
                  <span className="p-2 bg-blue-50 text-blue-600 rounded-xl font-bold text-base">🏢</span>
                  <div>
                    <h3 className="font-bold text-slate-800 text-sm">企业主体身份标识</h3>
                    <p className="text-slate-400 text-xs">对应标书封面、致函落款与营业执照对齐字段</p>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1.5">
                    投标人公司全称 <span className="text-rose-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="例如: 四川石楠建设工程有限公司"
                    value={formData.company_name || ''}
                    onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1.5">统一社会信用代码</label>
                  <input
                    type="text"
                    placeholder="例如: 91510000MA6X12345X"
                    value={formData.credit_code || ''}
                    onChange={(e) => setFormData({ ...formData, credit_code: e.target.value })}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1.5">注册 / 通信地址</label>
                  <input
                    type="text"
                    placeholder="例如: 四川省成都市高新区天府大道北段128号"
                    value={formData.registered_address || ''}
                    onChange={(e) => setFormData({ ...formData, registered_address: e.target.value })}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                  />
                </div>
              </div>

              {/* 卡片 2: 人员与联系方式 */}
              <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4 hover:shadow-md transition-shadow">
                <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
                  <span className="p-2 bg-purple-50 text-purple-600 rounded-xl font-bold text-base">👤</span>
                  <div>
                    <h3 className="font-bold text-slate-800 text-sm">法定代表人与授权代理人</h3>
                    <p className="text-slate-400 text-xs">对应授权委托书、承诺函及联系人落款</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1.5">法定代表人姓名</label>
                    <input
                      type="text"
                      placeholder="例如: 张三"
                      value={formData.legal_representative || ''}
                      onChange={(e) => setFormData({ ...formData, legal_representative: e.target.value })}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1.5">授权代理人姓名</label>
                    <input
                      type="text"
                      placeholder="例如: 李四"
                      value={formData.authorized_delegate || ''}
                      onChange={(e) => setFormData({ ...formData, authorized_delegate: e.target.value })}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1.5">联系电话 / 手机</label>
                  <input
                    type="text"
                    placeholder="例如: 028-85123456"
                    value={formData.contact_phone || ''}
                    onChange={(e) => setFormData({ ...formData, contact_phone: e.target.value })}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-slate-700 mb-1.5">电子邮箱</label>
                  <input
                    type="email"
                    placeholder="例如: bidding@shinan-construction.com"
                    value={formData.email || ''}
                    onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                    className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                  />
                </div>
              </div>

              {/* 卡片 3: 银行财务账号 */}
              <div className="bg-white p-6 rounded-3xl border border-slate-200 shadow-sm space-y-4 md:col-span-2 hover:shadow-md transition-shadow">
                <div className="flex items-center gap-2 pb-3 border-b border-slate-100">
                  <span className="p-2 bg-emerald-50 text-emerald-600 rounded-xl font-bold text-base">🏦</span>
                  <div>
                    <h3 className="font-bold text-slate-800 text-sm">银行开户与财务结算信息</h3>
                    <p className="text-slate-400 text-xs">对应《开标一览表》、保证金退还与结算开户行条款</p>
                  </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1.5">开户银行名称</label>
                    <input
                      type="text"
                      placeholder="例如: 中国工商银行股份有限公司成都高新支行"
                      value={formData.bank_name || ''}
                      onChange={(e) => setFormData({ ...formData, bank_name: e.target.value })}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-slate-700 mb-1.5">银行账号</label>
                    <input
                      type="text"
                      placeholder="例如: 4402 2410 1910 0123 456"
                      value={formData.bank_account || ''}
                      onChange={(e) => setFormData({ ...formData, bank_account: e.target.value })}
                      className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                    />
                  </div>
                </div>
              </div>

            </div>

            {/* 底部保存提交栏 */}
            <div className="p-4 bg-slate-900 rounded-2xl flex items-center justify-between text-white shadow-lg">
              <div className="flex items-center gap-3 text-xs text-slate-300">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
                <span>
                  {isCreating ? '新建主体将直接保存至数据库主体池' : '修改将实时更新对应主体档案'}
                </span>
              </div>

              <div className="flex items-center gap-3">
                {isCreating && (
                  <button
                    type="button"
                    onClick={() => {
                      if (profiles.length > 0) {
                        handleSelectProfile(profiles[0]);
                      }
                    }}
                    className="px-4 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl transition-all cursor-pointer"
                  >
                    取消新建
                  </button>
                )}
                <button
                  type="submit"
                  disabled={isSaving}
                  className="px-8 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 active:scale-98 text-white font-extrabold text-xs rounded-xl shadow-lg transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
                >
                  {isSaving ? (
                    <>
                      <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                      <span>正在保存中...</span>
                    </>
                  ) : (
                    <>
                      <span>💾</span>
                      <span>{isCreating ? '确认创建主体档案' : '保存主体档案修改'}</span>
                    </>
                  )}
                </button>
              </div>
            </div>

          </form>
        </div>

      </div>
    </div>
  );
};
