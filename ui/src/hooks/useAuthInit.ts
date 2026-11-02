import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { validateToken, refreshToken } from '../store/slices/authSlice';
import { AuthManager } from '../lib/auth';

/**
 * 认证初始化Hook
 * 在应用启动时检查和恢复认证状态
 */
export const useAuthInit = () => {
  const dispatch = useAppDispatch();
  const { isAuthenticated, isLoading } = useAppSelector((state) => state.auth);

  useEffect(() => {
    console.log('🔐 开始认证初始化...');
    
    // 如果已经认证，不需要再次初始化
    if (isAuthenticated) {
      console.log('✅ 已认证，跳过初始化');
      return;
    }

    // 检查是否有本地存储的认证信息
    const hasValidAuth = AuthManager.hasValidAuth();
    
    if (hasValidAuth) {
      console.log('🔄 发现有效的本地认证信息，验证token...');
      
      // 验证token是否仍然有效
      dispatch(validateToken())
        .unwrap()
        .then((user) => {
          console.log('✅ 初始化验证成功，用户已登录:', user.username);
        })
        .catch((error) => {
          console.log('❌ 初始化验证失败:', error.message);
          // 认证失败的处理已经在store中完成，不需要额外操作
        });
    } else {
      console.log('ℹ️ 没有有效的本地认证信息');
    }
  }, [dispatch, isAuthenticated]);

  return {
    isInitialized: !isLoading,
    isAuthenticated,
  };
};

/**
 * 路由变化时的token验证Hook
 * 在路由变化时检查token有效性，防止后端重启导致内存失效
 */
export const useRouteTokenValidation = () => {
  const location = useLocation();
  const dispatch = useAppDispatch();
  const { token, isLoading } = useAppSelector((state) => state.auth);
  const lastValidationTime = useRef<number>(0);
  const validationCooldown = 10000; // 10秒冷却时间，避免频繁验证

  useEffect(() => {
    // 只在有token的情况下验证
    if (!token) {
      console.log('🔍 路由变化但无token，跳过验证:', location.pathname);
      return;
    }

    // 如果正在加载中，跳过验证（避免与正在进行的认证流程冲突）
    if (isLoading) {
      console.log('🔍 正在加载中，跳过路由验证:', location.pathname);
      return;
    }

    // 冷却时间检查，避免频繁验证
    const now = Date.now();
    if (now - lastValidationTime.current < validationCooldown) {
      console.log('🔍 验证冷却中，跳过验证:', location.pathname);
      return;
    }

    console.log('🔍 路由变化，验证token有效性...', location.pathname);
    lastValidationTime.current = now;

    // 验证token是否仍然有效（防止后端重启导致内存失效）
    dispatch(validateToken())
      .unwrap()
      .then((user) => {
        console.log('✅ 路由验证：Token仍然有效，用户:', user.username, '继续访问:', location.pathname);
        // token有效，用户保持在当前页面或继续访问目标页面
      })
      .catch((error) => {
        console.log('❌ 路由验证：Token验证失败:', error.message);
        // 认证失败的处理（跳转到登录页）已经在store和ProtectedRoute中完成
        // 这里不需要额外操作
      });
  }, [location.pathname, dispatch, token, isLoading]);
};

/**
 * 自动token刷新Hook
 * 监控token过期状态，自动刷新即将过期的token
 */
export const useAutoTokenRefresh = () => {
  const dispatch = useAppDispatch();
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  useEffect(() => {
    if (!isAuthenticated) return;

    const checkTokenExpiry = () => {
      if (AuthManager.isTokenExpiringSoon()) {
        console.log('⏰ Token即将过期，尝试刷新...');
        dispatch(refreshToken())
          .unwrap()
          .then(() => {
            console.log('✅ Token刷新成功');
          })
          .catch((error) => {
            console.log('❌ Token刷新失败:', error.message);
          });
      }
    };

    // 每5分钟检查一次token状态
    const interval = setInterval(checkTokenExpiry, 5 * 60 * 1000);

    // 组件挂载时立即检查一次
    checkTokenExpiry();

    return () => clearInterval(interval);
  }, [dispatch, isAuthenticated]);
}; 