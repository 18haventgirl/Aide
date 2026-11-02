import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import type { AuthState, User, LoginCredentials, AuthToken } from '../../lib/types';
import { authAPI } from '../../services/apiService';
import { ApiError, isAuthenticationError, toApiError } from '../../lib/api-errors';
import { AuthManager } from '../../lib/auth';

// 从localStorage恢复初始状态
const initialAuthState = AuthManager.getAuthState();

// 初始状态
type SessionState = AuthState & { refreshRequestId: string | null };
const initialState: SessionState = {
  refreshRequestId: null,
  user: initialAuthState.user,
  token: initialAuthState.token,
  isAuthenticated: initialAuthState.isAuthenticated,
  isLoading: false,
  error: null,
};

// 异步actions
export const login = createAsyncThunk<AuthToken, LoginCredentials, { rejectValue: string }>(
  'auth/login',
  async (credentials, { rejectWithValue }) => {
    try {
      const response = await authAPI.login(credentials);
      if (response.success && response.data) {
        // 使用认证管理器保存token
        AuthManager.saveAuth(response.data);
        return response.data;
      }
      return rejectWithValue(response.message || '登录失败');
    } catch (error) {
      return rejectWithValue(toApiError(error).message);
    }
  }
);

export const logout = createAsyncThunk<void, void, { rejectValue: string }>(
  'auth/logout',
  async (_, { rejectWithValue }) => {
    try {
      await authAPI.logout();
      AuthManager.clearAuth();
    } catch (error) {
      // 即使登出API失败，也清除本地token
      AuthManager.clearAuth();
      return rejectWithValue(toApiError(error).message);
    }
  }
);

export const refreshToken = createAsyncThunk<AuthToken, void, {
  state: { auth: SessionState };
  rejectValue: { message: string; sessionEnded: boolean };
}>(
  'auth/refreshToken',
  async (_, { getState, requestId, rejectWithValue }) => {
    try {
      const response = await authAPI.refreshToken();
      if (!response.success || !response.data?.access_token || !response.data.user_info) {
        throw new ApiError(response.message || '刷新令牌失败', undefined, response.code);
      }
      if (getState().auth.refreshRequestId === requestId) AuthManager.saveAuth(response.data);
      return response.data;
    } catch (error) {
      const sessionEnded = isAuthenticationError(error) || AuthManager.isTokenExpired();
      if (sessionEnded && getState().auth.refreshRequestId === requestId) AuthManager.clearAuth();
      return rejectWithValue({ message: toApiError(error).message, sessionEnded });
    }
  },
  { condition: (_, { getState }) => {
    const { isAuthenticated, isLoading, refreshRequestId } = getState().auth;
    return isAuthenticated && !isLoading && refreshRequestId === null;
  } }
);

export const getCurrentUser = createAsyncThunk<User, void, { rejectValue: { message: string; isAuthError: boolean } }>(
  'auth/getCurrentUser',
  async (_, { rejectWithValue }) => {
    try {
      const response = await authAPI.getCurrentUser();

      // 后端实际返回的格式是 { success: true, message: "...", user_info: {...} }
      if (response.success) {
        // 检查是否有用户信息（兼容不同的返回格式）
        const userInfo = response.user_info || response.data;

        if (userInfo) {
          console.log('✅ getCurrentUser: 获取用户信息成功:', userInfo);
          return userInfo;
        } else {
          console.warn('⚠️ getCurrentUser: API成功但无用户数据:', response);
          return rejectWithValue({ message: response.message || '获取用户信息失败', isAuthError: false });
        }
      } else {
        return rejectWithValue({ message: response.message || '获取用户信息失败', isAuthError: false });
      }
    } catch (error) {
      console.error('❌ getCurrentUser: 获取失败:', error);

      // 检查是否是认证相关错误（401或特定业务错误码）
      const isAuthError = isAuthenticationError(error);

      if (isAuthError) {
        // 认证错误，静默处理
        console.log('🔇 getCurrentUser: 认证错误，静默处理');
        return rejectWithValue({
          message: toApiError(error, '认证失败').message,
          isAuthError: true
        });
      } else {
        // 其他错误（网络错误等）
        console.log('⚠️ getCurrentUser: 非认证错误');
        return rejectWithValue({
          message: toApiError(error, '获取用户信息失败').message,
          isAuthError: false
        });
      }
    }
  }
);

// 验证当前token有效性
export const validateToken = createAsyncThunk<User, void, { rejectValue: { message: string; isAuthError: boolean } }>(
  'auth/validateToken',
  async (_, { rejectWithValue }) => {
    try {
      // 检查本地token是否过期
      if (AuthManager.isTokenExpired()) {
        // 本地token过期，清除本地存储
        AuthManager.clearAuth();
        return rejectWithValue({ message: 'Token已过期', isAuthError: true });
      }

      // 验证token是否有效
      const response = await authAPI.getCurrentUser();

      // 后端实际返回的格式是 { success: true, message: "...", user_info: {...} }
      // 而不是标准的 { success: true, data: {...} }
      if (response.success) {
        // 检查是否有用户信息（兼容不同的返回格式）
        const userInfo = response.user_info || response.data;

        if (userInfo) {
          console.log('✅ validateToken: token验证成功，用户信息:', userInfo);
          return userInfo;
        } else {
          console.warn('⚠️ validateToken: API成功但无用户数据:', response);
          return rejectWithValue({ message: response.message || 'Token无效', isAuthError: true });
        }
      } else {
        return rejectWithValue({ message: response.message || 'Token无效', isAuthError: true });
      }

    } catch (error) {
      console.error('❌ validateToken: 验证失败:', error);

      // 检查是否是认证相关错误（401或特定业务错误码）
      const isAuthError = isAuthenticationError(error);

      if (isAuthError) {
        // 只有认证错误才清除本地存储
        console.log('🧹 validateToken: 认证错误，清除本地认证信息');
        AuthManager.clearAuth();
        return rejectWithValue({
          message: toApiError(error, 'Token无效').message,
          isAuthError: true
        });
      } else {
        // 其他错误（网络错误等）不清除认证状态
        console.log('⚠️ validateToken: 非认证错误，保持认证状态');
        return rejectWithValue({
          message: toApiError(error, '验证失败').message,
          isAuthError: false
        });
      }
    }
  }
);

// 认证slice
const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    clearError: (state) => {
      state.error = null;
    },
    setUser: (state, action: PayloadAction<User>) => {
      state.user = action.payload;
      state.isAuthenticated = true;
    },
    clearAuth: (state) => {
      state.refreshRequestId = null;
      state.user = null;
      state.token = null;
      state.isAuthenticated = false;
      state.error = null;
      AuthManager.clearAuth();
    },
    // 新增：恢复认证状态
    restoreAuth: (state) => {
      const authState = AuthManager.getAuthState();
      state.user = authState.user;
      state.token = authState.token;
      state.isAuthenticated = authState.isAuthenticated;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      // 登录
      .addCase(login.pending, (state) => {
        state.refreshRequestId = null;
        state.isLoading = true;
        state.error = null;
      })
      .addCase(login.fulfilled, (state, action) => {
        state.isLoading = false;
        state.error = null;
        if (action.payload.access_token && action.payload.user_info) {
          state.token = action.payload.access_token;
          state.user = action.payload.user_info;
          state.isAuthenticated = true;
        }
      })
      .addCase(login.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
        state.isAuthenticated = false;
      })
      // 登出
      .addCase(logout.pending, (state) => {
        state.refreshRequestId = null;
        state.isLoading = true;
      })
      .addCase(logout.fulfilled, (state) => {
        state.isLoading = false;
        state.user = null;
        state.token = null;
        state.isAuthenticated = false;
        state.error = null;
      })
      .addCase(logout.rejected, (state, action) => {
        state.isLoading = false;
        state.error = action.payload as string;
        // 即使登出失败，也清除本地状态
        state.user = null;
        state.token = null;
        state.isAuthenticated = false;
      })
      // 刷新token
      .addCase(refreshToken.pending, (state, action) => {
        state.refreshRequestId = action.meta.requestId;
      })
      .addCase(refreshToken.fulfilled, (state, action) => {
        if (state.refreshRequestId !== action.meta.requestId) return;
        state.refreshRequestId = null;
        state.error = null;
        if (action.payload.access_token && action.payload.user_info) {
          state.token = action.payload.access_token;
          state.user = action.payload.user_info;
          state.isAuthenticated = true;
        }
      })
      .addCase(refreshToken.rejected, (state, action) => {
        if (state.refreshRequestId !== action.meta.requestId) return;
        state.refreshRequestId = null;
        state.error = action.payload?.message || '刷新令牌失败';
        if (action.payload?.sessionEnded) {
          state.user = null;
          state.token = null;
          state.isAuthenticated = false;
        }
      })
      // 获取当前用户
      .addCase(getCurrentUser.pending, (state) => {
        state.isLoading = true;
      })
      .addCase(getCurrentUser.fulfilled, (state, action) => {
        state.isLoading = false;
        state.error = null;
        if (action.payload) {
          state.user = action.payload;
          state.isAuthenticated = true;
        }
      })
      .addCase(getCurrentUser.rejected, (state, action) => {
        state.isLoading = false;

        // 检查是否是认证错误
        const payload = action.payload as { message: string; isAuthError: boolean };

        if (payload?.isAuthError) {
          state.refreshRequestId = null;
          // 认证错误静默处理，不设置错误状态，避免显示弹窗
          console.log('🔇 getCurrentUser.rejected: 认证错误，静默清除认证状态');
          state.user = null;
          state.token = null;
          state.isAuthenticated = false;
          state.error = null; // 不设置错误，静默处理
        } else {
          // 非认证错误，清除认证状态并记录错误
          console.log('⚠️ getCurrentUser.rejected: 非认证错误，清除认证状态');
          state.user = null;
          state.token = null;
          state.isAuthenticated = false;
          state.error = payload?.message || '获取用户信息失败';
        }
      })
      // 验证token
      .addCase(validateToken.pending, (state) => {
        state.isLoading = true;
      })
      .addCase(validateToken.fulfilled, (state, action) => {
        state.isLoading = false;
        state.error = null;
        if (action.payload) {
          state.user = action.payload;
          state.isAuthenticated = true;
        }
      })
      .addCase(validateToken.rejected, (state, action) => {
        state.isLoading = false;

        // 检查是否是认证错误
        const payload = action.payload as { message: string; isAuthError: boolean };

        if (payload?.isAuthError) {
          state.refreshRequestId = null;
          // 认证错误静默处理，不设置错误状态，避免显示弹窗
          console.log('🔇 validateToken.rejected: 认证错误，静默清除认证状态');
          state.user = null;
          state.token = null;
          state.isAuthenticated = false;
          state.error = null; // 不设置错误，静默处理
        } else {
          // 非认证错误，保持认证状态，只记录错误
          console.log('⚠️ validateToken.rejected: 非认证错误，保持认证状态');
          state.error = payload?.message || '验证失败';
        }
      });
  },
});

export const { clearError, setUser, clearAuth, restoreAuth } = authSlice.actions;
export default authSlice.reducer;
