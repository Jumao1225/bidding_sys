import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export function ProtectedRoute({ children }: { children: JSX.Element }) {
  const { isAuthenticated } = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    // 未登录时重定向到登录页，并带上当前试图访问的路径
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}
