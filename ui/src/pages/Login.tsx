import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { login, clearError } from '../store/slices/authSlice';
import type { LoginCredentials } from '../lib/types';
import { Button } from '../components/ui/button';
import { Eye, EyeOff, Lock, User, AlertCircle, Loader2, Bot, Zap } from 'lucide-react';

const Login: React.FC = () => {
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();
  const dispatch = useAppDispatch();
  const { isLoading, error, isAuthenticated } = useAppSelector((state) => state.auth);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginCredentials>({ mode: 'onBlur' });

  useEffect(() => {
    return () => { dispatch(clearError()); };
  }, [dispatch]);

  useEffect(() => {
    if (isAuthenticated) {
      navigate('/', { replace: true });
    }
  }, [isAuthenticated, navigate]);

  const onSubmit = async (data: LoginCredentials) => {
    dispatch(clearError());
    try {
      await dispatch(login(data)).unwrap();
    } catch {
      // handled in store
    }
  };

  return (
    <div className="min-h-screen relative flex items-center justify-center p-4 overflow-hidden">
      {/* Decorative background */}
      <div className="absolute inset-0 bg-gradient-to-br from-blue-50 via-white to-indigo-50" />
      <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-gradient-to-bl from-blue-200/30 to-primary/10 rounded-full translate-x-1/3 -translate-y-1/3 blur-3xl" />
      <div className="absolute bottom-0 left-0 w-[500px] h-[500px] bg-gradient-to-tr from-indigo-200/20 to-blue-100/30 rounded-full -translate-x-1/4 translate-y-1/4 blur-3xl" />

      {/* Card */}
      <div className="relative w-full max-w-md">
        <div className="bg-white/75 backdrop-blur-[16px] rounded-2xl p-8 shadow-xl animate-fade-in" style={{ WebkitBackdropFilter: 'blur(16px)', border: '1px solid rgba(37,99,235,0.15)' }}>
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-primary to-blue-600 shadow-lg shadow-primary/25 mb-5">
              <Bot className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-2xl font-heading font-bold text-foreground">
              Aide
            </h1>
            <p className="text-muted-foreground mt-1.5">
              智能个人日常助手
            </p>
          </div>

          {/* Error */}
          {error && (
            <div className="mb-6 p-3.5 bg-destructive/10 border border-destructive/20 rounded-xl flex items-center gap-3 animate-fade-in">
              <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0" />
              <span className="text-sm text-destructive/90">{error}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-foreground/80 ml-1">
                用户名
              </label>
              <div className="relative">
                <User className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-muted-foreground/50" />
                <input
                  {...register('username', {
                    required: '请输入用户名',
                    minLength: { value: 2, message: '用户名至少2个字符' },
                  })}
                  type="text"
                  className="w-full pl-10 pr-4 py-3 bg-muted/50 border border-border rounded-xl focus:ring-2 focus:ring-ring focus:border-transparent outline-none transition-all text-sm placeholder:text-muted-foreground/50"
                  placeholder="请输入用户名"
                  autoComplete="username"
                />
              </div>
              {errors.username && (
                <p className="text-destructive text-xs ml-1 animate-fade-in">{errors.username.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <label className="block text-sm font-medium text-foreground/80 ml-1">
                密码
              </label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-muted-foreground/50" />
                <input
                  {...register('password', {
                    required: '请输入密码',
                    minLength: { value: 6, message: '密码至少6个字符' },
                  })}
                  type={showPassword ? 'text' : 'password'}
                  className="w-full pl-10 pr-12 py-3 bg-muted/50 border border-border rounded-xl focus:ring-2 focus:ring-ring focus:border-transparent outline-none transition-all text-sm placeholder:text-muted-foreground/50"
                  placeholder="请输入密码"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 p-2 rounded-lg hover:bg-muted transition-colors"
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4 text-muted-foreground/60" />
                  ) : (
                    <Eye className="h-4 w-4 text-muted-foreground/60" />
                  )}
                </button>
              </div>
              {errors.password && (
                <p className="text-destructive text-xs ml-1 animate-fade-in">{errors.password.message}</p>
              )}
            </div>

            <Button
              type="submit"
              className="w-full bg-gradient-to-r from-primary to-blue-600 hover:from-primary/90 hover:to-blue-600/90 text-white font-semibold py-3 rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/20 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-none disabled:active:scale-100"
              disabled={isLoading}
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin" />
                  登录中...
                </span>
              ) : (
                '登录'
              )}
            </Button>
          </form>

          {/* Footer */}
          <div className="mt-6 pt-5 border-t border-border/50 text-center">
            <div className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-muted/50 rounded-full text-xs text-muted-foreground">
              <Zap className="w-3 h-3 text-warning" />
              <span>测试密码：admin123456</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Login;