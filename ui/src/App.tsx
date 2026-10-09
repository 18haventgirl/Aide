import React, { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import ErrorBoundary from './components/ErrorBoundary';
import { setGlobalErrorHandler, setAuthFailureHandler } from './services/apiService';
import { useToast } from './components/ui/toast';
import { useAppDispatch } from './store/hooks';
import { logout } from './store/slices/authSlice';
import { useAuthInit, useAutoTokenRefresh, useRouteTokenValidation } from './hooks/useAuthInit';
import { AppLogo } from './components/app-logo';

function App() {
  const { error: showError } = useToast();
  const dispatch = useAppDispatch();
  
  // 初始化认证状态
  const { isInitialized, isAuthenticated } = useAuthInit();
  
  // 自动token刷新
  useAutoTokenRefresh();
  
  // 路由变化时验证token（防止后端重启导致内存失效）
  useRouteTokenValidation();

  useEffect(() => {
    // 设置全局API错误处理
    setGlobalErrorHandler((error: string, details?: any) => {
      showError(error, details?.message || '请稍后重试');
    });

    // 设置认证失败处理
    setAuthFailureHandler(() => {
      dispatch(logout());
    });
  }, [showError, dispatch]);

  // 认证初始化中，显示加载页面
  if (!isInitialized) {
    return (
      <div className="app-shell flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-5" role="status">
          <AppLogo />
          <p className="text-muted-foreground text-sm">正在加载工作空间…</p>
        </div>
      </div>
    );
  }

  return (
    <ErrorBoundary>
      <Routes>
        {/* 公开路由 */}
        <Route 
          path="/login" 
          element={
            <ProtectedRoute requireAuth={false}>
              <Login />
            </ProtectedRoute>
          } 
        />
        
        {/* 受保护路由 */}
        <Route 
          path="/" 
          element={
            <ProtectedRoute requireAuth={true}>
              <Dashboard />
            </ProtectedRoute>
          } 
        />
        
        {/* 默认重定向到主页 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ErrorBoundary>
  );
}

export default App;
