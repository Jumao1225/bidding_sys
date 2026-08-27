import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Building2, Shield, User, ArrowRight, X } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { getApiBaseUrl } from '../utils/api';

interface TenantOption {
  id: string;
  name: string;
  role?: string;
}

export function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  
  // 多租户选择弹窗状态
  const [candidateTenants, setCandidateTenants] = useState<TenantOption[]>([]);
  const [showTenantPicker, setShowTenantPicker] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = location.state?.from?.pathname || "/";

  const executeLogin = async (selectedTenantId?: string) => {
    setError('');
    setLoading(true);

    try {
      const baseUrl = getApiBaseUrl();
      const formData = new URLSearchParams();
      formData.append('username', email.trim());
      formData.append('password', password);
      if (selectedTenantId) {
        formData.append('tenant_id', selectedTenantId);
      }

      const res = await fetch(`${baseUrl}/api/v1/auth/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || '账号或密码错误，请重试。');
      }

      const data = await res.json();
      
      // 1. 如果后端检测到多个企业存在相同账号，弹出企业选择框
      if (data.require_tenant_selection && data.tenants && data.tenants.length > 0) {
        setCandidateTenants(data.tenants);
        setShowTenantPicker(true);
        setLoading(false);
        return;
      }

      // 2. 正常成功登录
      setShowTenantPicker(false);
      login(data.access_token, data.user);
      navigate(from, { replace: true });
    } catch (err: any) {
      setError(err.message || '登录失败，请检查网络后重试。');
      setShowTenantPicker(false);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await executeLogin();
  };

  return (
    <div className="min-h-screen w-full flex items-center justify-center relative overflow-hidden bg-slate-50/50">
      {/* 装饰性光效（匹配亮色极光主题） */}
      <div className="absolute top-0 left-0 w-full h-full pointer-events-none">
        <div className="absolute top-20 left-20 w-96 h-96 bg-blue-400/20 rounded-full blur-3xl animate-pulse-slow"></div>
        <div className="absolute bottom-20 right-20 w-96 h-96 bg-indigo-400/20 rounded-full blur-3xl animate-float"></div>
      </div>

      <motion.div 
        initial={{ opacity: 0, y: 30 }} 
        animate={{ opacity: 1, y: 0 }} 
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="glass p-10 rounded-3xl w-full max-w-md relative z-10 shadow-[0_8px_30px_rgb(0,0,0,0.04)] border border-white/60"
      >
        <div className="text-center mb-8">
          <motion.div 
            initial={{ scale: 0.5, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
            className="inline-flex w-16 h-16 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 items-center justify-center shadow-lg shadow-indigo-500/25 mb-4"
          >
            <span className="text-white font-extrabold text-2xl tracking-tighter">AI</span>
          </motion.div>
          <h1 className="text-3xl font-bold bg-gradient-to-br from-slate-900 via-blue-900 to-indigo-900 bg-clip-text text-transparent">
            欢迎登录
          </h1>
          <p className="text-slate-500 mt-2 text-sm">请输入您的登录账号和密码进入系统</p>
        </div>

        {error && (
          <motion.div 
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            className="bg-rose-50/80 text-rose-600 text-sm p-4 rounded-xl mb-6 border border-rose-100 backdrop-blur-sm font-medium"
          >
            {error}
          </motion.div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5" htmlFor="email">
              登录账号 / 邮箱
            </label>
            <input 
              id="email"
              type="text" 
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full px-4 py-3 bg-white/60 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl transition-all outline-none placeholder:text-slate-400 text-sm font-medium"
              placeholder="请输入账号 (支持 企业/账号 或 邮箱)"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-semibold text-slate-700 mb-1.5" htmlFor="password">
              密码
            </label>
            <input 
              id="password"
              type="password" 
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-4 py-3 bg-white/60 border border-slate-200 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10 rounded-xl transition-all outline-none placeholder:text-slate-400 text-sm font-medium"
              placeholder="••••••••"
              required
            />
          </div>
          
          <button 
            type="submit" 
            disabled={loading}
            className="w-full py-3.5 bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white rounded-xl font-bold shadow-lg shadow-indigo-500/25 transition-all transform hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-70 disabled:cursor-not-allowed disabled:transform-none mt-2 text-sm"
          >
            {loading ? (
              <span className="flex items-center justify-center">
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                正在验证...
              </span>
            ) : '登录系统'}
          </button>
        </form>
      </motion.div>

      {/* 跨企业同名选择弹窗 (Workspace Picker Modal) */}
      <AnimatePresence>
        {showTenantPicker && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-md">
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 15 }}
              className="bg-white rounded-3xl shadow-2xl p-6 md:p-8 w-full max-w-md relative border border-slate-100"
            >
              <button 
                onClick={() => setShowTenantPicker(false)}
                className="absolute top-5 right-5 text-slate-400 hover:text-slate-600 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>

              <div className="flex items-center gap-3 mb-6">
                <div className="w-12 h-12 rounded-2xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm shrink-0">
                  <Building2 className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-xl font-extrabold text-slate-800 tracking-tight">选择归属企业空间</h3>
                  <p className="text-xs text-slate-500 mt-0.5">检测到您的账号存在于多个企业，请选择要进入的空间</p>
                </div>
              </div>

              <div className="space-y-3 max-h-72 overflow-y-auto pr-1">
                {candidateTenants.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => executeLogin(t.id)}
                    disabled={loading}
                    className="w-full flex items-center justify-between p-4 rounded-2xl bg-slate-50 hover:bg-indigo-50/70 border border-slate-200/80 hover:border-indigo-300 transition-all text-left group shadow-xs active:scale-[0.98]"
                  >
                    <div className="flex items-center gap-3.5">
                      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-blue-600 flex items-center justify-center text-white font-bold text-sm shadow-xs shrink-0">
                        {t.name.substring(0, 1)}
                      </div>
                      <div>
                        <div className="font-bold text-slate-800 group-hover:text-indigo-900 transition-colors text-sm">
                          {t.name}
                        </div>
                        <div className="text-xs text-slate-400 font-mono mt-0.5">
                          {t.role === 'admin' || t.role === 'platform_admin' ? '👑 平台管理员' : t.role === 'tenant_admin' ? '🛡️ 租户管理员' : '👤 普通成员'}
                        </div>
                      </div>
                    </div>
                    <ArrowRight className="w-4 h-4 text-slate-400 group-hover:text-indigo-600 group-hover:translate-x-1 transition-all" />
                  </button>
                ))}
              </div>

              <div className="mt-6 text-center">
                <button
                  onClick={() => setShowTenantPicker(false)}
                  className="text-xs text-slate-400 hover:text-slate-600 font-medium transition-colors"
                >
                  返回重新输入账号
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
