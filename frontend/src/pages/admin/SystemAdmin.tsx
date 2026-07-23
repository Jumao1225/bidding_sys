import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Shield, Building2, Users, Plus, CheckCircle2, X } from 'lucide-react';
import { apiFetch } from '../../utils/api';

interface Tenant {
  id: string;
  name: string;
  domain?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface User {
  id: string;
  email: string;
  full_name?: string;
  role: string;
  tenant_id: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export function SystemAdmin() {
  const [activeTab, setActiveTab] = useState<'tenants' | 'users'>('tenants');
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  // Modals state
  const [showTenantModal, setShowTenantModal] = useState(false);
  const [showUserModal, setShowUserModal] = useState(false);
  const [newTenantName, setNewTenantName] = useState('');
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserTenantId, setNewUserTenantId] = useState('');

  // Password reset modal
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [resetPasswordValue, setResetPasswordValue] = useState('');

  // Tenant change modal
  const [showTenantChangeModal, setShowTenantChangeModal] = useState(false);
  const [resetTenantIdValue, setResetTenantIdValue] = useState('');

  const baseUrl = import.meta.env.VITE_API_BASE_URL || '';

  useEffect(() => {
    fetchData();
  }, [activeTab]);

  const fetchData = async () => {
    setIsLoading(true);
    setError('');
    try {
      if (activeTab === 'tenants') {
        const res = await apiFetch(`${baseUrl}/api/v1/admin/tenants`);
        if (res.ok) {
          const data = await res.json();
          data.sort((a: Tenant, b: Tenant) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
          setTenants(data);
        } else {
          setError('获取租户列表失败');
        }
      } else {
        const res = await apiFetch(`${baseUrl}/api/v1/admin/users`);
        if (res.ok) {
          const data = await res.json();
          // Group by tenant and sort by updated_at
          const maxTenantUpdate = new Map<string, number>();
          data.forEach((u: User) => {
            const time = new Date(u.updated_at).getTime();
            if (!maxTenantUpdate.has(u.tenant_id) || time > maxTenantUpdate.get(u.tenant_id)!) {
              maxTenantUpdate.set(u.tenant_id, time);
            }
          });
          data.sort((a: User, b: User) => {
            const aMax = maxTenantUpdate.get(a.tenant_id)!;
            const bMax = maxTenantUpdate.get(b.tenant_id)!;
            if (aMax !== bMax) {
              return bMax - aMax; // groups with more recent updates first
            }
            if (a.tenant_id !== b.tenant_id) {
              return a.tenant_id.localeCompare(b.tenant_id); // stable group ordering
            }
            return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(); // newest first within group
          });
          setUsers(data);
        } else {
          setError('获取用户列表失败');
        }
        
        // Also fetch tenants for user creation dropdown if not already fetched
        if (tenants.length === 0) {
          const tRes = await apiFetch(`${baseUrl}/api/v1/admin/tenants`);
          if (tRes.ok) setTenants(await tRes.json());
        }
      }
    } catch (err) {
      setError('网络错误，请稍后重试');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCreateTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/tenants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newTenantName, is_active: true })
      });
      if (res.ok) {
        setShowTenantModal(false);
        setNewTenantName('');
        fetchData();
      } else {
        const data = await res.json().catch(() => ({}));
        alert(`创建失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      alert('网络错误');
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          email: newUserEmail, 
          password: newUserPassword, 
          tenant_id: newUserTenantId,
          role: 'user',
          is_active: true
        })
      });
      if (res.ok) {
        setShowUserModal(false);
        setNewUserEmail('');
        setNewUserPassword('');
        setNewUserTenantId('');
        fetchData();
      } else {
        const data = await res.json().catch(() => ({}));
        alert(`创建失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      alert('网络错误');
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users/${selectedUserId}/password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: resetPasswordValue })
      });
      if (res.ok) {
        setShowPasswordModal(false);
        setResetPasswordValue('');
        setSelectedUserId('');
        alert('密码修改成功');
      } else {
        const data = await res.json().catch(() => ({}));
        alert(`修改失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      alert('网络错误');
    }
  };

  const handleChangeTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users/${selectedUserId}/tenant`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tenant_id: resetTenantIdValue })
      });
      if (res.ok) {
        setShowTenantChangeModal(false);
        setResetTenantIdValue('');
        setSelectedUserId('');
        fetchData();
        alert('租户变更成功');
      } else {
        const data = await res.json().catch(() => ({}));
        alert(`修改失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      alert('网络错误');
    }
  };

  return (
    <div className="h-full flex flex-col relative overflow-hidden bg-slate-50/50 rounded-3xl border border-slate-200/60 p-6 md:p-8">
      <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-indigo-500/10 rounded-full blur-[100px] pointer-events-none -translate-y-1/2 translate-x-1/2"></div>
      
      <div className="flex items-center justify-between mb-8 relative z-10">
        <div>
          <h1 className="text-3xl font-extrabold bg-gradient-to-br from-slate-900 to-indigo-900 bg-clip-text text-transparent flex items-center">
            <Shield className="w-8 h-8 mr-3 text-indigo-600" />
            系统管理中心
          </h1>
          <p className="text-slate-500 mt-2">管理全局租户、用户分配与系统级配置</p>
        </div>
        <div className="flex bg-white/60 p-1.5 rounded-2xl border border-slate-200/60 shadow-sm backdrop-blur-sm">
          <button
            onClick={() => setActiveTab('tenants')}
            className={`flex items-center px-6 py-2.5 rounded-xl font-medium transition-all ${
              activeTab === 'tenants' 
                ? 'bg-white text-indigo-700 shadow-md shadow-slate-200/50' 
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <Building2 className="w-4 h-4 mr-2" />
            租户管理
          </button>
          <button
            onClick={() => setActiveTab('users')}
            className={`flex items-center px-6 py-2.5 rounded-xl font-medium transition-all ${
              activeTab === 'users' 
                ? 'bg-white text-indigo-700 shadow-md shadow-slate-200/50' 
                : 'text-slate-500 hover:text-slate-800'
            }`}
          >
            <Users className="w-4 h-4 mr-2" />
            全局用户
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 bg-rose-50 border border-rose-200 text-rose-600 rounded-2xl relative z-10">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-auto relative z-10">
        <AnimatePresence mode="wait">
          {activeTab === 'tenants' && (
            <motion.div
              key="tenants"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="space-y-6"
            >
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold text-slate-800">全部公司 / 租户</h2>
                <button 
                  onClick={() => setShowTenantModal(true)}
                  className="flex items-center px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-lg shadow-indigo-500/30 transition-all active:scale-95"
                >
                  <Plus className="w-4 h-4 mr-2" />
                  开通新租户
                </button>
              </div>

              <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-3xl overflow-hidden shadow-xl shadow-slate-200/20">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-slate-50/80 border-b border-slate-200/60">
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">租户名称</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">ID</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">状态</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">创建时间</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {tenants.map(tenant => (
                      <tr key={tenant.id} className="hover:bg-indigo-50/30 transition-colors">
                        <td className="px-6 py-4">
                          <div className="flex items-center">
                            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-100 to-blue-100 flex items-center justify-center text-indigo-600 font-bold mr-3">
                              {tenant.name.substring(0, 1)}
                            </div>
                            <span className="font-semibold text-slate-700">{tenant.name}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-sm text-slate-500 font-mono">{tenant.id}</td>
                        <td className="px-6 py-4">
                          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${tenant.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>
                            {tenant.is_active ? '启用中' : '已停用'}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm text-slate-500">
                          {new Date(tenant.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))}
                    {tenants.length === 0 && !isLoading && (
                      <tr>
                        <td colSpan={4} className="px-6 py-12 text-center text-slate-500">
                          暂无租户数据
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}

          {activeTab === 'users' && (
            <motion.div
              key="users"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="space-y-6"
            >
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-bold text-slate-800">全部账号</h2>
                <button 
                  onClick={() => setShowUserModal(true)}
                  className="flex items-center px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow-lg shadow-indigo-500/30 transition-all active:scale-95"
                >
                  <Plus className="w-4 h-4 mr-2" />
                  分配新账号
                </button>
              </div>

              <div className="bg-white/80 backdrop-blur-xl border border-slate-200/60 rounded-3xl overflow-hidden shadow-xl shadow-slate-200/20">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-slate-50/80 border-b border-slate-200/60">
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">账号邮箱</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">所属租户</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">角色</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider">状态</th>
                      <th className="px-6 py-4 text-sm font-semibold text-slate-500 uppercase tracking-wider text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {users.map(user => (
                      <tr key={user.id} className="hover:bg-indigo-50/30 transition-colors">
                        <td className="px-6 py-4">
                          <span className="font-semibold text-slate-700">{user.email}</span>
                        </td>
                        <td className="px-6 py-4 text-sm text-slate-600">
                          {tenants.find(t => t.id === user.tenant_id)?.name || <span className="text-slate-400 font-mono text-xs">{user.tenant_id}</span>}
                        </td>
                        <td className="px-6 py-4">
                          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${user.role === 'admin' ? 'bg-amber-100 text-amber-700' : 'bg-blue-100 text-blue-700'}`}>
                            {user.role}
                          </span>
                        </td>
                        <td className="px-6 py-4">
                          <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${user.is_active ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>
                            {user.is_active ? '正常' : '已停用'}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right space-x-3">
                          <button
                            onClick={() => {
                              setSelectedUserId(user.id);
                              setResetTenantIdValue(user.tenant_id);
                              setShowTenantChangeModal(true);
                            }}
                            className="text-emerald-600 hover:text-emerald-800 text-sm font-medium transition-colors"
                          >
                            变更租户
                          </button>
                          <button
                            onClick={() => {
                              setSelectedUserId(user.id);
                              setResetPasswordValue('');
                              setShowPasswordModal(true);
                            }}
                            className="text-indigo-600 hover:text-indigo-800 text-sm font-medium transition-colors"
                          >
                            修改密码
                          </button>
                        </td>
                      </tr>
                    ))}
                    {users.length === 0 && !isLoading && (
                      <tr>
                        <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                          暂无账号数据
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* 创建租户 Modal */}
      <AnimatePresence>
        {showTenantModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative"
            >
              <button onClick={() => setShowTenantModal(false)} className="absolute top-4 right-4 text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
              <h3 className="text-xl font-bold text-slate-800 mb-6">开通新租户</h3>
              <form onSubmit={handleCreateTenant} className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">公司/租户名称</label>
                  <input 
                    type="text" 
                    value={newTenantName}
                    onChange={e => setNewTenantName(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none"
                    placeholder="输入企业全称..."
                    required
                  />
                </div>
                <button type="submit" className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold mt-6">
                  确认开通
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 创建账号 Modal */}
      <AnimatePresence>
        {showUserModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative"
            >
              <button onClick={() => setShowUserModal(false)} className="absolute top-4 right-4 text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
              <h3 className="text-xl font-bold text-slate-800 mb-6">分配新账号</h3>
              <form onSubmit={handleCreateUser} className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">登录账号 (邮箱或用户名)</label>
                  <input 
                    type="text" 
                    value={newUserEmail}
                    onChange={e => setNewUserEmail(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">初始密码</label>
                  <input 
                    type="password" 
                    value={newUserPassword}
                    onChange={e => setNewUserPassword(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">所属租户 (公司)</label>
                  <select 
                    value={newUserTenantId}
                    onChange={e => setNewUserTenantId(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none"
                    required
                  >
                    <option value="" disabled>-- 请选择 --</option>
                    {tenants.map(t => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
                <button type="submit" className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-bold mt-6">
                  确认分配
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 修改密码 Modal */}
      <AnimatePresence>
        {showPasswordModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative"
            >
              <button onClick={() => setShowPasswordModal(false)} className="absolute top-4 right-4 text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
              <h3 className="text-xl font-bold text-slate-800 mb-6">修改账户密码</h3>
              <form onSubmit={handleResetPassword} className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">新密码</label>
                  <input 
                    type="password" 
                    value={resetPasswordValue}
                    onChange={e => setResetPasswordValue(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none"
                    placeholder="请输入新密码..."
                    required
                  />
                </div>
                <button type="submit" className="w-full py-3 bg-amber-500 hover:bg-amber-600 text-white rounded-xl font-bold mt-6">
                  确认修改
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 变更租户 Modal */}
      <AnimatePresence>
        {showTenantChangeModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative"
            >
              <button onClick={() => setShowTenantChangeModal(false)} className="absolute top-4 right-4 text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
              <h3 className="text-xl font-bold text-slate-800 mb-6">变更所属租户</h3>
              <form onSubmit={handleChangeTenant} className="space-y-4">
                <div>
                  <label className="block text-sm font-semibold text-slate-700 mb-1">选择新租户</label>
                  <select 
                    value={resetTenantIdValue}
                    onChange={e => setResetTenantIdValue(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none"
                    required
                  >
                    <option value="" disabled>-- 请选择 --</option>
                    {tenants.map(t => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
                <button type="submit" className="w-full py-3 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl font-bold mt-6">
                  确认变更
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

    </div>
  );
}
