import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { useAppDispatch, useAppSelector } from '../store/hooks';
import { login, clearError } from '../store/slices/authSlice';
import type { LoginCredentials } from '../lib/types';
import { AppLogo } from '../components/app-logo';
import { Button } from '../components/ui/button';
import { Eye, EyeOff, Lock, User, AlertCircle, Loader2, FileText, MessageCircle, CheckCircle2 } from 'lucide-react';

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
    <div className="app-shell grid overflow-y-auto lg:grid-cols-2">
      <aside className="hidden flex-col justify-between bg-[#141e30] p-12 text-white lg:flex xl:p-16">
        <AppLogo />
        <div className="max-w-md py-12">
          <p className="mb-5 text-xs font-medium tracking-[0.25em] text-blue-300">YOUR EVERYDAY ASSISTANT</p>
          <h1 className="text-4xl font-semibold leading-[1.5] tracking-tight">让日常井然有序，<br />让记录清晰可循。</h1>
          <p className="mt-6 text-sm leading-8 text-slate-400">从随手记下的想法，到每一次就诊的细节。<br />Aide 帮你把重要的信息，放在触手可及的地方。</p>
          <div className="mt-10 flex flex-wrap gap-3">{[[MessageCircle, '智能对话'], [FileText, '病历解析'], [CheckCircle2, '日常管理']].map(([Icon, label]) => {
            const FeatureIcon = Icon as typeof MessageCircle;
            return <span key={label as string} className="inline-flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300"><FeatureIcon className="h-4 w-4 text-blue-300" />{label as string}</span>;
          })}</div>
        </div>
        <p className="text-xs text-slate-500">Aide · 个人智能工作空间</p>
      </aside>
      <main className="flex items-center justify-center bg-card px-6 py-12 sm:px-12">
        <div className="w-full max-w-sm">
          <div className="mb-12 lg:hidden"><AppLogo /></div>
          <div className="mb-8"><h2 className="text-2xl font-semibold tracking-tight">欢迎回来</h2><p className="mt-3 text-sm text-muted-foreground">登录 Aide，继续你的个人工作空间。</p></div>
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
              <label htmlFor="login-username" className="block text-sm font-medium text-foreground">
                用户名
              </label>
              <div className="relative">
                <User className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/50" />
                <input
                  id="login-username"
                  {...register('username', {
                    required: '请输入用户名',
                    minLength: { value: 2, message: '用户名至少2个字符' },
                  })}
                  type="text"
                  className="field-control h-12 pl-10 pr-4"
                  placeholder="请输入用户名"
                  autoComplete="username"
                />
              </div>
              {errors.username && (
                <p className="text-destructive text-xs ml-1 animate-fade-in">{errors.username.message}</p>
              )}
            </div>

            <div className="space-y-1.5">
              <label htmlFor="login-password" className="block text-sm font-medium text-foreground">
                密码
              </label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/50" />
                <input
                  id="login-password"
                  {...register('password', {
                    required: '请输入密码',
                    minLength: { value: 6, message: '密码至少6个字符' },
                  })}
                  type={showPassword ? 'text' : 'password'}
                  className="field-control h-12 pl-10 pr-12"
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
              className="h-12 w-full"
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
            <div className="text-xs leading-6 text-muted-foreground">

              <span>测试账号：admin / 密码：admin123456</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

export default Login;
