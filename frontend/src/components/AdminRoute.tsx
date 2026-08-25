import { Navigate, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useAuth } from '../contexts/AuthContext';

export function AdminRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    // Redirect to login if not authenticated
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (!['admin', 'platform_admin', 'tenant_admin'].includes(user?.role || '')) {
    // 只有平台管理员和租户管理员可以进入管理中心。
    return <Navigate to="/" replace />;
  }

  return children;
}
