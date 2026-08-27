import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Shield, 
  Building2, 
  Users, 
  Plus, 
  X, 
  Search, 
  KeyRound, 
  ArrowRightLeft, 
  Trash2, 
  Power, 
  Copy, 
  Check, 
  Crown, 
  ShieldCheck, 
  User as UserIcon,
  Sparkles,
  AlertTriangle
} from 'lucide-react';
import { apiFetch } from '../../utils/api';
import { useAuth } from '../../contexts/AuthContext';

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
  const { user } = useAuth();
  const isPlatformAdmin = user?.role === 'admin' || user?.role === 'platform_admin';
  const isTenantAdmin = user?.role === 'tenant_admin';
  const [activeTab, setActiveTab] = useState<'tenants' | 'users'>(isPlatformAdmin ? 'tenants' : 'users');
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  // Search & Filter
  const [searchTerm, setSearchTerm] = useState('');
  const [roleFilter, setRoleFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [copiedId, setCopiedId] = useState<string | null>(null);

  // Modals state
  const [showTenantModal, setShowTenantModal] = useState(false);
  const [showUserModal, setShowUserModal] = useState(false);
  const [newTenantName, setNewTenantName] = useState('');
  const [newUserEmail, setNewUserEmail] = useState('');
  const [newUserPassword, setNewUserPassword] = useState('');
  const [newUserTenantId, setNewUserTenantId] = useState('');
  const [newUserRole, setNewUserRole] = useState<'user' | 'tenant_admin'>('user');

  // Password reset modal
  const [showPasswordModal, setShowPasswordModal] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [resetPasswordValue, setResetPasswordValue] = useState('');

  // Tenant change modal
  const [showTenantChangeModal, setShowTenantChangeModal] = useState(false);
  const [resetTenantIdValue, setResetTenantIdValue] = useState('');
  const [resetUserRole, setResetUserRole] = useState<'user' | 'tenant_admin' | null>(null);

  const baseUrl = import.meta.env.VITE_API_BASE_URL || '';

  useEffect(() => {
    fetchData();
  }, [activeTab]);

  const fetchData = async () => {
    setIsLoading(true);
    setError('');
    try {
      // 并发请求用户与租户数据，确保顶部所有 KPI 统计指标实时准确
      const userPromise = apiFetch(`${baseUrl}/api/v1/admin/users?limit=1000`);
      const tenantPromise = isPlatformAdmin 
        ? apiFetch(`${baseUrl}/api/v1/admin/tenants?limit=1000`)
        : Promise.resolve(null);

      const [usersRes, tenantsRes] = await Promise.all([userPromise, tenantPromise]);

      if (usersRes && usersRes.ok) {
        const data = await usersRes.json();
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

      if (tenantsRes && tenantsRes.ok) {
        const data = await tenantsRes.json();
        data.sort((a: Tenant, b: Tenant) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
        setTenants(data);
      }
    } catch (err) {
      setError('网络错误，请稍后重试');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(text);
    setTimeout(() => setCopiedId(null), 2000);
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
        alert('🎉 企业租户创建成功！');
      } else {
        const errorData = await res.json().catch(() => ({}));
        let errMsg = '未知错误';
        if (typeof errorData.detail === 'string') {
          errMsg = errorData.detail;
        } else if (Array.isArray(errorData.detail)) {
          errMsg = errorData.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
        } else if (errorData.message) {
          errMsg = errorData.message;
        }
        alert(`开通租户失败: ${errMsg}`);
      }
    } catch (err: any) {
      alert(`网络或服务请求错误: ${err.message || err}`);
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const targetTenantId = isTenantAdmin ? (user?.tenant_id || '') : newUserTenantId;
      if (!targetTenantId) {
        alert('请选择要分配的目标企业租户！');
        return;
      }
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          email: newUserEmail.trim(), 
          password: newUserPassword, 
          tenant_id: targetTenantId,
          role: newUserRole,
          is_active: true
        })
      });
      if (res.ok) {
        setShowUserModal(false);
        setNewUserEmail('');
        setNewUserPassword('');
        setNewUserTenantId(isTenantAdmin ? (user?.tenant_id || '') : '');
        setNewUserRole('user');
        fetchData();
        alert('🎉 新账号分配成功！');
      } else {
        const errorData = await res.json().catch(() => ({}));
        let errMsg = '未知错误';
        if (typeof errorData.detail === 'string') {
          errMsg = errorData.detail;
        } else if (Array.isArray(errorData.detail)) {
          errMsg = errorData.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
        } else if (errorData.message) {
          errMsg = errorData.message;
        }
        alert(`创建账号失败: ${errMsg}`);
      }
    } catch (err: any) {
      alert(`网络或服务请求错误: ${err.message || err}`);
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
        const errorData = await res.json().catch(() => ({}));
        const errMsg = typeof errorData.detail === 'string' ? errorData.detail : (errorData.message || '未知错误');
        alert(`修改密码失败: ${errMsg}`);
      }
    } catch (err: any) {
      alert(`网络错误: ${err.message || err}`);
    }
  };

  const handleChangeTenant = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const updatePayload = {
        tenant_id: resetTenantIdValue,
        ...(resetUserRole ? { role: resetUserRole } : {}),
      };
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users/${selectedUserId}/tenant`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updatePayload)
      });
      if (res.ok) {
        setShowTenantChangeModal(false);
        setResetTenantIdValue('');
        setResetUserRole(null);
        setSelectedUserId('');
        fetchData();
        alert('租户变更成功');
      } else {
        const errorData = await res.json().catch(() => ({}));
        const errMsg = typeof errorData.detail === 'string' ? errorData.detail : (errorData.message || '未知错误');
        alert(`变更租户失败: ${errMsg}`);
      }
    } catch (err: any) {
      alert(`网络错误: ${err.message || err}`);
    }
  };

  const handleToggleStatus = async (targetUser: User) => {
    const nextStatus = !targetUser.is_active;
    const actionText = nextStatus ? '启用' : '停用';
    if (!window.confirm(`确定要${actionText}账号 "${targetUser.email}" 吗？`)) {
      return;
    }
    // 立即乐观更新本地状态
    setUsers(prev => prev.map(u => u.id === targetUser.id ? { ...u, is_active: nextStatus, updated_at: new Date().toISOString() } : u));
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users/${targetUser.id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: nextStatus })
      });
      if (res.ok) {
        const updated = await res.json();
        setUsers(prev => prev.map(u => u.id === targetUser.id ? { ...u, ...updated } : u));
      } else {
        // 回滚
        setUsers(prev => prev.map(u => u.id === targetUser.id ? { ...u, is_active: !nextStatus } : u));
        const data = await res.json().catch(() => ({}));
        alert(`操作失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      setUsers(prev => prev.map(u => u.id === targetUser.id ? { ...u, is_active: !nextStatus } : u));
      alert('网络错误');
    }
  };

  const handleDeleteUser = async (targetUser: User) => {
    if (!window.confirm(`⚠️ 警告：确定要彻底删除账号 "${targetUser.email}" 吗？此操作不可逆！`)) {
      return;
    }
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/users/${targetUser.id}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setUsers(prev => prev.filter(u => u.id !== targetUser.id));
      } else {
        const data = await res.json().catch(() => ({}));
        alert(`删除失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      alert('网络错误');
    }
  };

  const handleToggleTenantStatus = async (targetTenant: Tenant) => {
    const nextStatus = !targetTenant.is_active;
    const warningText = nextStatus 
      ? `确定要启用租户 "${targetTenant.name}" 吗？`
      : `⚠️ 警告：确定要停用租户 "${targetTenant.name}" 吗？停用后该租户下的所有普通用户和管理员将无法登录系统！`;
    if (!window.confirm(warningText)) {
      return;
    }
    // 立即乐观更新本地状态，防止重新拉取时的分页顺序变动或丢失
    setTenants(prev => prev.map(t => t.id === targetTenant.id ? { ...t, is_active: nextStatus, updated_at: new Date().toISOString() } : t));
    try {
      const res = await apiFetch(`${baseUrl}/api/v1/admin/tenants/${targetTenant.id}/status`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: nextStatus })
      });
      if (res.ok) {
        const updated = await res.json();
        setTenants(prev => prev.map(t => t.id === targetTenant.id ? { ...t, ...updated } : t));
      } else {
        // 回滚
        setTenants(prev => prev.map(t => t.id === targetTenant.id ? { ...t, is_active: !nextStatus } : t));
        const data = await res.json().catch(() => ({}));
        alert(`操作失败: ${data.detail || '未知错误'}`);
      }
    } catch (err) {
      setTenants(prev => prev.map(t => t.id === targetTenant.id ? { ...t, is_active: !nextStatus } : t));
      alert('网络错误');
    }
  };

  // Filtered Users
  const filteredUsers = useMemo(() => {
    return users.filter(u => {
      const tenantName = tenants.find(t => t.id === u.tenant_id)?.name || '';
      const matchSearch = 
        u.email.toLowerCase().includes(searchTerm.toLowerCase()) || 
        tenantName.toLowerCase().includes(searchTerm.toLowerCase()) ||
        u.tenant_id.toLowerCase().includes(searchTerm.toLowerCase());
      
      const matchRole = roleFilter === 'all' || 
        (roleFilter === 'admin' && (u.role === 'admin' || u.role === 'platform_admin')) ||
        u.role === roleFilter;

      const matchStatus = statusFilter === 'all' || 
        (statusFilter === 'active' && u.is_active) || 
        (statusFilter === 'inactive' && !u.is_active);

      return matchSearch && matchRole && matchStatus;
    });
  }, [users, tenants, searchTerm, roleFilter, statusFilter]);

  // Filtered Tenants
  const filteredTenants = useMemo(() => {
    return tenants.filter(t => {
      const matchSearch = 
        t.name.toLowerCase().includes(searchTerm.toLowerCase()) || 
        t.id.toLowerCase().includes(searchTerm.toLowerCase());
      
      const matchStatus = statusFilter === 'all' || 
        (statusFilter === 'active' && t.is_active) || 
        (statusFilter === 'inactive' && !t.is_active);

      return matchSearch && matchStatus;
    });
  }, [tenants, searchTerm, statusFilter]);

  // KPI Calculations
  const stats = useMemo(() => {
    const totalUsers = users.length;
    const activeUsers = users.filter(u => u.is_active).length;
    const totalTenants = tenants.length;
    const activeTenants = tenants.filter(t => t.is_active).length;
    const adminCount = users.filter(u => u.role === 'admin' || u.role === 'platform_admin' || u.role === 'tenant_admin').length;
    return { totalUsers, activeUsers, totalTenants, activeTenants, adminCount };
  }, [users, tenants]);

  // Helper for Role Render
  const renderRoleBadge = (role: string) => {
    if (role === 'admin' || role === 'platform_admin') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200/80 shadow-xs whitespace-nowrap">
          <Crown className="w-3.5 h-3.5 text-amber-600 shrink-0" />
          平台管理员
        </span>
      );
    }
    if (role === 'tenant_admin') {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-violet-50 text-violet-700 border border-violet-200/80 shadow-xs whitespace-nowrap">
          <ShieldCheck className="w-3.5 h-3.5 text-violet-600 shrink-0" />
          租户管理员
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-sky-50 text-sky-700 border border-sky-200/80 shadow-xs whitespace-nowrap">
        <UserIcon className="w-3.5 h-3.5 text-sky-600 shrink-0" />
        普通用户
      </span>
    );
  };

  // Helper for Status Render
  const renderStatusBadge = (isActive: boolean) => {
    if (isActive) {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200/80 shadow-xs whitespace-nowrap">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shrink-0"></span>
          正常运行
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200/80 shadow-xs whitespace-nowrap">
        <span className="w-1.5 h-1.5 rounded-full bg-rose-500 shrink-0"></span>
        已停用
      </span>
    );
  };

  return (
    <div className="h-full flex flex-col relative overflow-hidden bg-gradient-to-br from-slate-50 via-slate-100/50 to-indigo-50/20 rounded-3xl border border-slate-200/70 p-6 md:p-8 shadow-sm">
      {/* Background Decorative Glow */}
      <div className="absolute top-0 right-0 w-[550px] h-[550px] bg-indigo-500/10 rounded-full blur-[120px] pointer-events-none -translate-y-1/2 translate-x-1/3"></div>
      <div className="absolute bottom-0 left-0 w-[450px] h-[450px] bg-blue-500/10 rounded-full blur-[100px] pointer-events-none translate-y-1/3 -translate-x-1/4"></div>

      {/* Header Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6 relative z-10">
        <div>
          <h1 className="text-2xl md:text-3xl font-extrabold bg-gradient-to-r from-slate-900 via-indigo-950 to-indigo-800 bg-clip-text text-transparent flex items-center tracking-tight">
            <div className="w-10 h-10 rounded-2xl bg-indigo-600 flex items-center justify-center text-white shadow-lg shadow-indigo-500/30 mr-3.5 shrink-0">
              <Shield className="w-5 h-5" />
            </div>
            系统管理中心
          </h1>
          <p className="text-slate-500 text-sm mt-1.5 ml-0.5 font-medium">
            {isPlatformAdmin ? '全局多租户隔离调度、统一账号权限分配与系统级运维中台' : '本租户企业成员权限调度与账户生命周期管理'}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Tabs Pill Switcher */}
          <div className="flex bg-slate-200/70 p-1.5 rounded-2xl border border-slate-200/80 shadow-inner backdrop-blur-md">
            {isPlatformAdmin && (
              <button
                onClick={() => {
                  setActiveTab('tenants');
                  setSearchTerm('');
                }}
                className={`flex items-center px-5 py-2 rounded-xl text-sm font-semibold transition-all duration-200 ${
                  activeTab === 'tenants' 
                    ? 'bg-white text-indigo-700 shadow-md shadow-slate-300/50' 
                    : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                <Building2 className="w-4 h-4 mr-2" />
                租户管理
              </button>
            )}
            <button
              onClick={() => {
                setActiveTab('users');
                setSearchTerm('');
              }}
              className={`flex items-center px-5 py-2 rounded-xl text-sm font-semibold transition-all duration-200 ${
                activeTab === 'users' 
                  ? 'bg-white text-indigo-700 shadow-md shadow-slate-300/50' 
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Users className="w-4 h-4 mr-2" />
              {isTenantAdmin ? '本租户账号' : '全局用户'}
            </button>
          </div>

          {/* Action Button */}
          {activeTab === 'tenants' ? (
            <button 
              onClick={() => setShowTenantModal(true)}
              className="flex items-center px-4.5 py-2.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white text-sm font-bold rounded-2xl shadow-lg shadow-indigo-500/25 transition-all duration-200 active:scale-95 shrink-0"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              开通新租户
            </button>
          ) : (
            <button 
              onClick={() => {
                setNewUserEmail('');
                setNewUserPassword('');
                setNewUserTenantId(isTenantAdmin ? (user?.tenant_id || '') : '');
                setNewUserRole('user');
                setShowUserModal(true);
              }}
              className="flex items-center px-4.5 py-2.5 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white text-sm font-bold rounded-2xl shadow-lg shadow-indigo-500/25 transition-all duration-200 active:scale-95 shrink-0"
            >
              <Plus className="w-4 h-4 mr-1.5" />
              分配新账号
            </button>
          )}
        </div>
      </div>

      {/* KPI Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6 relative z-10">
        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/80 rounded-2xl p-4.5 shadow-sm hover:shadow-md transition-all flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              {isTenantAdmin ? '本租户成员' : '系统全局用户'}
            </span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-black text-slate-800 font-mono tracking-tight">{stats.totalUsers}</span>
              <span className="text-xs font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
                {stats.activeUsers} 位正常在用
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0">
            <Users className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/80 rounded-2xl p-4.5 shadow-sm hover:shadow-md transition-all flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              {isPlatformAdmin ? '已入驻企业租户' : '当前归属租户'}
            </span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-black text-slate-800 font-mono tracking-tight">
                {isPlatformAdmin ? stats.totalTenants : 1}
              </span>
              <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                {isPlatformAdmin ? `${stats.activeTenants} 家启用` : '独立隔离空间'}
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-2xl bg-blue-50 border border-blue-100 flex items-center justify-center text-blue-600 shrink-0">
            <Building2 className="w-5 h-5" />
          </div>
        </div>

        <div className="bg-white/80 backdrop-blur-xl border border-slate-200/80 rounded-2xl p-4.5 shadow-sm hover:shadow-md transition-all flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              管理员配置
            </span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-black text-slate-800 font-mono tracking-tight">{stats.adminCount}</span>
              <span className="text-xs font-medium text-violet-600 bg-violet-50 px-2 py-0.5 rounded-full">
                安全管控节点
              </span>
            </div>
          </div>
          <div className="w-11 h-11 rounded-2xl bg-violet-50 border border-violet-100 flex items-center justify-center text-violet-600 shrink-0">
            <Sparkles className="w-5 h-5" />
          </div>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="bg-white/90 backdrop-blur-xl border border-slate-200/80 rounded-2xl p-3 mb-4 flex flex-col md:flex-row items-center justify-between gap-3 shadow-xs relative z-10">
        <div className="relative w-full md:w-80">
          <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input 
            type="text"
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            placeholder={activeTab === 'users' ? '按邮箱、公司名或ID快速搜索...' : '按租户名称或ID快速搜索...'}
            className="w-full pl-10 pr-4 py-2 bg-slate-50/80 hover:bg-slate-50 focus:bg-white border border-slate-200/80 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl text-sm outline-none transition-all placeholder:text-slate-400 font-medium"
          />
        </div>

        <div className="flex items-center gap-2.5 w-full md:w-auto justify-end">
          {activeTab === 'users' && (
            <select
              value={roleFilter}
              onChange={e => setRoleFilter(e.target.value)}
              className="px-3.5 py-2 bg-slate-50 hover:bg-slate-100/80 border border-slate-200/80 rounded-xl text-xs font-semibold text-slate-600 outline-none transition-all cursor-pointer"
            >
              <option value="all">全部角色</option>
              {isPlatformAdmin && <option value="admin">平台管理员</option>}
              <option value="tenant_admin">租户管理员</option>
              <option value="user">普通用户</option>
            </select>
          )}

          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3.5 py-2 bg-slate-50 hover:bg-slate-100/80 border border-slate-200/80 rounded-xl text-xs font-semibold text-slate-600 outline-none transition-all cursor-pointer"
          >
            <option value="all">全部状态</option>
            <option value="active">正常运行</option>
            <option value="inactive">已停用</option>
          </select>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-4 bg-rose-50 border border-rose-200 text-rose-600 rounded-2xl relative z-10 flex items-center gap-2 text-sm font-medium">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Main Table Content */}
      <div className="flex-1 overflow-auto relative z-10 bg-white/90 backdrop-blur-xl border border-slate-200/80 rounded-2xl shadow-xl shadow-slate-200/30 flex flex-col">
        <AnimatePresence mode="wait">
          {activeTab === 'tenants' && (
            <motion.div
              key="tenants"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex-1 overflow-auto"
            >
              <table className="w-full text-left border-collapse min-w-[700px]">
                <thead>
                  <tr className="bg-slate-50/90 border-b border-slate-200/80 sticky top-0 z-20 backdrop-blur-md">
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">租户企业信息</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">租户唯一 ID</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">运行状态</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">入驻时间</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider text-right whitespace-nowrap">管理操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100/80">
                  {filteredTenants.map(tenant => {
                    const isOwnTenant = tenant.id === user?.tenant_id;
                    return (
                      <tr key={tenant.id} className="hover:bg-indigo-50/40 transition-colors group">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-3">
                            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-blue-600 flex items-center justify-center text-white font-bold text-sm shadow-sm shrink-0">
                              {tenant.name.substring(0, 1)}
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-slate-800 text-sm tracking-tight">{tenant.name}</span>
                              {isOwnTenant && (
                                <span className="text-[11px] font-bold bg-indigo-50 text-indigo-600 border border-indigo-100 px-2 py-0.5 rounded-full">
                                  当前租户
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="inline-flex items-center gap-1.5 bg-slate-100/70 hover:bg-slate-200/70 px-2.5 py-1 rounded-lg transition-colors border border-slate-200/50">
                            <span className="text-xs text-slate-600 font-mono tracking-tight">{tenant.id}</span>
                            <button 
                              onClick={() => handleCopy(tenant.id)} 
                              className="text-slate-400 hover:text-indigo-600 transition-colors"
                              title="复制租户ID"
                            >
                              {copiedId === tenant.id ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                            </button>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {renderStatusBadge(tenant.is_active)}
                        </td>
                        <td className="px-6 py-4 text-xs font-medium text-slate-500 whitespace-nowrap">
                          {new Date(tenant.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-6 py-4 text-right whitespace-nowrap">
                          {!isOwnTenant ? (
                            <button
                              onClick={() => handleToggleTenantStatus(tenant)}
                              className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-xs font-bold transition-all shadow-xs border ${
                                tenant.is_active 
                                  ? 'bg-amber-50 hover:bg-amber-100 text-amber-700 border-amber-200/80 active:scale-95' 
                                  : 'bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-200/80 active:scale-95'
                              }`}
                            >
                              <Power className="w-3.5 h-3.5" />
                              {tenant.is_active ? '停用租户' : '启用租户'}
                            </button>
                          ) : (
                            <span className="inline-flex items-center px-2.5 py-1 rounded-lg text-xs font-medium text-slate-400 bg-slate-50 border border-slate-200/60">
                              平台受保护
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {filteredTenants.length === 0 && !isLoading && (
                    <tr>
                      <td colSpan={5} className="px-6 py-16 text-center text-slate-400 text-sm">
                        未匹配到符合条件的租户数据
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </motion.div>
          )}

          {activeTab === 'users' && (
            <motion.div
              key="users"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="flex-1 overflow-auto"
            >
              <table className="w-full text-left border-collapse min-w-[850px]">
                <thead>
                  <tr className="bg-slate-50/90 border-b border-slate-200/80 sticky top-0 z-20 backdrop-blur-md">
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">账号邮箱 / 用户名</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">所属租户 (企业)</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">分配角色</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider whitespace-nowrap">账号状态</th>
                    <th className="px-6 py-3.5 text-xs font-bold text-slate-500 uppercase tracking-wider text-right whitespace-nowrap">操作管理</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100/80">
                  {filteredUsers.map(u => {
                    const isSelf = u.id === user?.id;
                    const isTargetPlatformAdmin = u.role === 'admin' || u.role === 'platform_admin';
                    const canManage = !isSelf && (!isTenantAdmin || !isTargetPlatformAdmin);
                    const tenantName = tenants.find(t => t.id === u.tenant_id)?.name;

                    return (
                      <tr key={u.id} className="hover:bg-indigo-50/40 transition-colors group">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-3">
                            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-slate-700 to-indigo-900 flex items-center justify-center text-white font-bold text-xs shadow-xs shrink-0">
                              {u.email.substring(0, 2).toUpperCase()}
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-slate-800 text-sm">{u.email}</span>
                              {isSelf && (
                                <span className="text-[11px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200/80 px-2 py-0.5 rounded-full">
                                  当前登录
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {tenantName ? (
                            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-slate-100/80 rounded-lg text-slate-700 text-xs font-medium border border-slate-200/60 max-w-[200px] truncate" title={tenantName}>
                              <Building2 className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                              <span className="truncate">{tenantName}</span>
                            </div>
                          ) : (
                            <span className="text-slate-400 font-mono text-xs bg-slate-50 px-2 py-1 rounded-md">{u.tenant_id}</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {renderRoleBadge(u.role)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          {renderStatusBadge(u.is_active)}
                        </td>
                        <td className="px-6 py-4 text-right whitespace-nowrap">
                          <div className="inline-flex items-center gap-1.5 justify-end">
                            {/* 变更租户 (仅平台管理员且非平台管理员目标) */}
                            {isPlatformAdmin && !isTargetPlatformAdmin && (
                              <button
                                onClick={() => {
                                  setSelectedUserId(u.id);
                                  setResetTenantIdValue(u.tenant_id);
                                  setResetUserRole(u.role === 'user' || u.role === 'tenant_admin' ? u.role : null);
                                  setShowTenantChangeModal(true);
                                }}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200/80 transition-all shadow-xs active:scale-95"
                                title="变更所属租户与权限"
                              >
                                <ArrowRightLeft className="w-3.5 h-3.5" />
                                变更租户
                              </button>
                            )}

                            {/* 修改密码 */}
                            <button
                              onClick={() => {
                                setSelectedUserId(u.id);
                                setResetPasswordValue('');
                                setShowPasswordModal(true);
                              }}
                              className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200/80 transition-all shadow-xs active:scale-95"
                              title="重置账户登录密码"
                            >
                              <KeyRound className="w-3.5 h-3.5" />
                              修改密码
                            </button>

                            {/* 停用 / 启用 */}
                            {canManage && (
                              <button
                                onClick={() => handleToggleStatus(u)}
                                className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold border transition-all shadow-xs active:scale-95 ${
                                  u.is_active 
                                    ? 'text-amber-700 bg-amber-50 hover:bg-amber-100 border-amber-200/80' 
                                    : 'text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border-emerald-200/80'
                                }`}
                                title={u.is_active ? '临时停用此账号' : '恢复启用此账号'}
                              >
                                <Power className="w-3.5 h-3.5" />
                                {u.is_active ? '停用' : '启用'}
                              </button>
                            )}

                            {/* 删除 */}
                            {canManage && (
                              <button
                                onClick={() => handleDeleteUser(u)}
                                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-bold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200/80 transition-all shadow-xs active:scale-95"
                                title="彻底删除此账号"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                                删除
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                  {filteredUsers.length === 0 && !isLoading && (
                    <tr>
                      <td colSpan={5} className="px-6 py-16 text-center text-slate-400 text-sm">
                        未匹配到符合条件的用户账号
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* 创建租户 Modal */}
      <AnimatePresence>
        {showTenantModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-md">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative border border-slate-100"
            >
              <button onClick={() => setShowTenantModal(false)} className="absolute top-5 right-5 text-slate-400 hover:text-slate-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0">
                  <Building2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">开通新租户</h3>
                  <p className="text-xs text-slate-500">为新入驻的企业创建独立的业务数据隔离空间</p>
                </div>
              </div>
              <form onSubmit={handleCreateTenant} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">公司/租户名称</label>
                  <input 
                    type="text" 
                    value={newTenantName}
                    onChange={e => setNewTenantName(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm transition-all font-medium"
                    placeholder="输入企业全称，例如：某某科技有限公司"
                    required
                  />
                </div>
                <button type="submit" className="w-full py-3 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-xl font-bold mt-6 shadow-lg shadow-indigo-500/25 transition-all active:scale-95 text-sm">
                  确认开通企业空间
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 创建账号 Modal */}
      <AnimatePresence>
        {showUserModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-md">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative border border-slate-100"
            >
              <button onClick={() => setShowUserModal(false)} className="absolute top-5 right-5 text-slate-400 hover:text-slate-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0">
                  <Users className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">分配新账号</h3>
                  <p className="text-xs text-slate-500">创建并分配新成员账号 (同一企业内不可重复，不同企业允许同名)</p>
                </div>
              </div>
              <form onSubmit={handleCreateUser} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">登录账号 (邮箱或用户名)</label>
                  <input 
                    type="text" 
                    value={newUserEmail}
                    onChange={e => setNewUserEmail(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm transition-all font-medium"
                    placeholder="输入登录邮箱或用户名，如 zhangsan 或 admin..."
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">初始密码</label>
                  <input 
                    type="password" 
                    value={newUserPassword}
                    onChange={e => setNewUserPassword(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm transition-all font-medium"
                    placeholder="设置初始密码..."
                    required
                  />
                </div>
                {isPlatformAdmin ? (
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">所属租户 (公司)</label>
                    <select 
                      value={newUserTenantId}
                      onChange={e => setNewUserTenantId(e.target.value)}
                      className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm font-medium transition-all"
                      required
                    >
                      <option value="" disabled>-- 请选择目标企业 --</option>
                      {tenants.map(t => (
                        <option key={t.id} value={t.id}>
                          {t.name === 'System Admin' ? '👑 System Admin (平台管理专属空间)' : `🏢 ${t.name}`}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">所属租户</label>
                    <div className="w-full px-4 py-2.5 bg-slate-100/80 border border-slate-200 text-slate-700 rounded-xl flex items-center justify-between text-xs font-semibold">
                      <span>当前租户 (本企业)</span>
                      <span className="text-[11px] bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full font-bold">本租户隔离</span>
                    </div>
                  </div>
                )}
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">账号权限角色</label>
                  <select
                    value={newUserRole}
                    onChange={e => setNewUserRole(e.target.value as 'user' | 'tenant_admin')}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm font-medium transition-all"
                  >
                    <option value="user">普通用户 (常规业务操作)</option>
                    <option value="tenant_admin">租户管理员 (管理本企业账号与配置)</option>
                  </select>
                </div>
                <button type="submit" className="w-full py-3 bg-gradient-to-r from-indigo-600 to-indigo-700 hover:from-indigo-700 hover:to-indigo-800 text-white rounded-xl font-bold mt-6 shadow-lg shadow-indigo-500/25 transition-all active:scale-95 text-sm">
                  确认分配新账号
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 修改密码 Modal */}
      <AnimatePresence>
        {showPasswordModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-md">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative border border-slate-100"
            >
              <button onClick={() => setShowPasswordModal(false)} className="absolute top-5 right-5 text-slate-400 hover:text-slate-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-2xl bg-amber-50 border border-amber-100 flex items-center justify-center text-amber-600 shrink-0">
                  <KeyRound className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">修改账户密码</h3>
                  <p className="text-xs text-slate-500">为该成员重新设定强密码</p>
                </div>
              </div>
              <form onSubmit={handleResetPassword} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">输入新密码</label>
                  <input 
                    type="password" 
                    value={resetPasswordValue}
                    onChange={e => setResetPasswordValue(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm transition-all font-medium"
                    placeholder="请输入新的安全密码..."
                    required
                  />
                </div>
                <button type="submit" className="w-full py-3 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-600 hover:to-amber-700 text-white rounded-xl font-bold mt-6 shadow-lg shadow-amber-500/25 transition-all active:scale-95 text-sm">
                  确认重置密码
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 变更租户 Modal */}
      <AnimatePresence>
        {showTenantChangeModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-md">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="bg-white rounded-3xl shadow-2xl p-6 w-full max-w-md relative border border-slate-100"
            >
              <button onClick={() => setShowTenantChangeModal(false)} className="absolute top-5 right-5 text-slate-400 hover:text-slate-600 transition-colors">
                <X className="w-5 h-5" />
              </button>
              <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-2xl bg-emerald-50 border border-emerald-100 flex items-center justify-center text-emerald-600 shrink-0">
                  <ArrowRightLeft className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">变更所属租户与权限</h3>
                  <p className="text-xs text-slate-500">将账号迁移调配至其他企业租户并调整角色</p>
                </div>
              </div>
              <form onSubmit={handleChangeTenant} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">选择目标新租户</label>
                  <select 
                    value={resetTenantIdValue}
                    onChange={e => setResetTenantIdValue(e.target.value)}
                    className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm font-medium transition-all"
                    required
                  >
                    <option value="" disabled>-- 请选择新租户 --</option>
                    {tenants.map(t => (
                      <option key={t.id} value={t.id}>{t.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-bold text-slate-700 uppercase tracking-wider mb-1.5">调整权限角色</label>
                  {resetUserRole ? (
                    <select
                      value={resetUserRole}
                      onChange={e => setResetUserRole(e.target.value as 'user' | 'tenant_admin')}
                      className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl outline-none text-sm font-medium transition-all"
                    >
                      <option value="user">普通用户</option>
                      <option value="tenant_admin">租户管理员</option>
                    </select>
                  ) : (
                    <p className="w-full px-4 py-2.5 bg-slate-100 border border-slate-200 text-slate-500 rounded-xl text-xs font-medium">
                      平台管理员权限不可在此调整
                    </p>
                  )}
                </div>
                <button type="submit" className="w-full py-3 bg-gradient-to-r from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 text-white rounded-xl font-bold mt-6 shadow-lg shadow-emerald-500/25 transition-all active:scale-95 text-sm">
                  确认变更租户与权限
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

    </div>
  );
}
