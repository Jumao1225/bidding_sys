import { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

interface User {
  id: string;
  email: string;
  tenant_id: string;
  role: string;
}

interface AuthContextType {
  token: string | null;
  user: User | null;
  login: (token: string, user: User) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('bidding_token'));
  const [user, setUser] = useState<User | null>(() => {
    const savedUser = localStorage.getItem('bidding_user');
    if (savedUser && savedUser !== 'undefined') {
      try {
        return JSON.parse(savedUser);
      } catch (e) {
        console.error("Failed to parse user from local storage", e);
        return null;
      }
    }
    return null;
  });
  const navigate = useNavigate();
  const location = useLocation();

  const login = (newToken: string, newUser: User) => {
    setToken(newToken);
    setUser(newUser);
    localStorage.setItem('bidding_token', newToken);
    localStorage.setItem('bidding_user', JSON.stringify(newUser));
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('bidding_token');
    localStorage.removeItem('bidding_user');
    // 切换用户时清空之前用户的标书解析状态
    localStorage.removeItem('bidding_document_id');
    localStorage.removeItem('bidding_analysis_result');
    localStorage.removeItem('bidding_task_id');
    localStorage.removeItem('bidding_file_name');
    // 触发全局事件通知 ChatPanel 和 App 刷新状态
    window.dispatchEvent(new Event('bidding_document_changed'));
    navigate('/login', { state: { from: location }, replace: true });
  };

  // 监听由于 token 过期导致的登出事件 (由 api.ts 触发)
  useEffect(() => {
    const handleUnauthorized = () => {
      logout();
    };
    window.addEventListener('unauthorized_access', handleUnauthorized);
    return () => window.removeEventListener('unauthorized_access', handleUnauthorized);
  }, [navigate, location]);

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
