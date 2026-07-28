import React, { useState, useEffect } from 'react';
import { apiFetch } from '../utils/api';

export const CompanyProfilePage: React.FC = () => {
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const [formData, setFormData] = useState({
    company_name: '',
    legal_representative: '',
    authorized_delegate: '',
    credit_code: '',
    registered_address: '',
    contact_phone: '',
    email: '',
    bank_name: '',
    bank_account: ''
  });

  // 1. 组件加载时实时从 PostgreSQL 数据库读取企业基础档案
  useEffect(() => {
    fetchProfile();
  }, []);

  const fetchProfile = async () => {
    setIsLoading(true);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/company/profile`);
      if (res.ok) {
        const data = await res.json();
        setFormData({
          company_name: data.company_name || '',
          legal_representative: data.legal_representative || '',
          authorized_delegate: data.authorized_delegate || '',
          credit_code: data.credit_code || '',
          registered_address: data.registered_address || '',
          contact_phone: data.contact_phone || '',
          email: data.email || '',
          bank_name: data.bank_name || '',
          bank_account: data.bank_account || ''
        });
      }
    } catch (err) {
      console.error("读取企业基础档案失败", err);
    } finally {
      setIsLoading(false);
    }
  };

  // 2. 提交更新保存到 PostgreSQL 物理数据表 company_profiles
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSaving(true);
    setNotice(null);
    try {
      const baseUrl = import.meta.env.VITE_API_BASE_URL || '';
      const res = await apiFetch(`${baseUrl}/api/v1/company/profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (res.ok) {
        setNotice('✅ 企业基础档案已成功保存至 PostgreSQL 物理数据库！后续 Agent 自动填报将实时读取最新档案。');
        setTimeout(() => setNotice(null), 5000);
      } else {
        throw new Error(`保存失败 (HTTP ${res.status})`);
      }
    } catch (err: any) {
      setNotice(`❌ 保存企业档案失败: ${err.message || '网络通讯异常'}`);
      setTimeout(() => setNotice(null), 5000);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto animate-fade-in">
      {/* 页面 Header */}
      <div className="bg-gradient-to-r from-slate-900 via-indigo-950 to-blue-900 text-white p-8 rounded-3xl shadow-xl border border-white/10 relative overflow-hidden">
        <div className="absolute -right-10 -bottom-10 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl pointer-events-none"></div>
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="px-3 py-1 bg-blue-500/20 text-blue-300 rounded-full text-xs font-bold border border-blue-400/30">
                主数据管理 (Master Data)
              </span>
              <span className="text-xs text-slate-400 font-mono">PostgreSQL: company_profiles</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight">企业基础档案与主体配置</h1>
            <p className="text-slate-300 text-xs md:text-sm mt-1 max-w-2xl leading-relaxed">
              全局统一管理投标主体公司名称、法人代表、授权人、银行账号与信用代码。Agent 在智能装配标书初稿与开标一览表时将自动调用此处配置。
            </p>
          </div>

          <button
            onClick={fetchProfile}
            disabled={isLoading}
            className="px-4 py-2 bg-white/10 hover:bg-white/20 active:bg-white/30 text-white text-xs font-bold rounded-xl border border-white/20 transition-all flex items-center gap-2 shadow-xs cursor-pointer self-start md:self-auto"
          >
            <span className={isLoading ? "animate-spin" : ""}>🔄</span>
            <span>刷新数据</span>
          </button>
        </div>
      </div>

      {/* 提示 Alert */}
      {notice && (
        <div className={`p-4 rounded-2xl text-xs font-semibold flex items-center justify-between shadow-xs border animate-scale-up ${
          notice.startsWith('✅') 
            ? 'bg-emerald-50 text-emerald-900 border-emerald-200' 
            : 'bg-rose-50 text-rose-900 border-rose-200'
        }`}>
          <span>{notice}</span>
          <button onClick={() => setNotice(null)} className="text-slate-400 hover:text-slate-600 font-bold">✕</button>
        </div>
      )}

      {/* 表单卡片 */}
      <form onSubmit={handleSubmit} className="space-y-6">
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
                value={formData.company_name}
                onChange={(e) => setFormData({...formData, company_name: e.target.value})}
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1.5">统一社会信用代码</label>
              <input 
                type="text"
                placeholder="例如: 91510000MA6X12345X"
                value={formData.credit_code}
                onChange={(e) => setFormData({...formData, credit_code: e.target.value})}
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1.5">注册 / 通信地址</label>
              <input 
                type="text"
                placeholder="例如: 四川省成都市高新区天府大道北段128号"
                value={formData.registered_address}
                onChange={(e) => setFormData({...formData, registered_address: e.target.value})}
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
                  value={formData.legal_representative}
                  onChange={(e) => setFormData({...formData, legal_representative: e.target.value})}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">授权代理人姓名</label>
                <input 
                  type="text"
                  placeholder="例如: 李四"
                  value={formData.authorized_delegate}
                  onChange={(e) => setFormData({...formData, authorized_delegate: e.target.value})}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1.5">联系电话 / 手机</label>
              <input 
                type="text"
                placeholder="例如: 028-85123456"
                value={formData.contact_phone}
                onChange={(e) => setFormData({...formData, contact_phone: e.target.value})}
                className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1.5">电子邮箱</label>
              <input 
                type="email"
                placeholder="例如: bidding@shinan-construction.com"
                value={formData.email}
                onChange={(e) => setFormData({...formData, email: e.target.value})}
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
                  value={formData.bank_name}
                  onChange={(e) => setFormData({...formData, bank_name: e.target.value})}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-bold text-slate-700 mb-1.5">银行账号</label>
                <input 
                  type="text"
                  placeholder="例如: 4402 2410 1910 0123 456"
                  value={formData.bank_account}
                  onChange={(e) => setFormData({...formData, bank_account: e.target.value})}
                  className="w-full p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs font-mono text-slate-900 focus:bg-white focus:ring-2 focus:ring-blue-500 focus:outline-none transition-all"
                />
              </div>
            </div>
          </div>

        </div>

        {/* 底部保存提交 */}
        <div className="p-4 bg-slate-900 rounded-2xl flex items-center justify-between text-white shadow-lg">
          <div className="flex items-center gap-3 text-xs text-slate-300">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
            <span>修改后将直接写入 PostgreSQL 物理表，所有标书解析与装配模块实时生效</span>
          </div>

          <button
            type="submit"
            disabled={isSaving}
            className="px-8 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 active:scale-98 text-white font-extrabold text-xs rounded-xl shadow-lg transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
          >
            {isSaving ? (
              <>
                <div className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full"></div>
                <span>正在保存中...</span>
              </>
            ) : (
              <>
                <span>💾</span>
                <span>保存企业档案数据</span>
              </>
            )}
          </button>
        </div>

      </form>
    </div>
  );
};
