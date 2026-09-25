import axios from 'axios';
import type { AxiosInstance, AxiosError, AxiosResponse } from 'axios';
import { API_BASE_URL, API_ENDPOINTS, REQUEST_TIMEOUT } from '../lib/config';
import type { LoginCredentials, RegisterCredentials, AuthToken, User } from '../lib/types';
import { AuthManager } from '../lib/auth';

// 通用API响应类型
export interface ApiResponse<T = any> {
  success: boolean;
  data: T;
  message?: string;
  error?: string;
  code?: number;
}

// 分页响应类型
export interface PaginatedResponse<T = any> {
  data: T[];
  total: number;
  page: number;
  size: number;
  has_more: boolean;
}

// 错误处理回调类型
export type ErrorCallback = (error: string, details?: any) => void;

// 全局错误处理回调
let globalErrorHandler: ErrorCallback | null = null;
// 认证失败回调
let authFailureHandler: (() => void) | null = null;

// 设置全局错误处理
export function setGlobalErrorHandler(handler: ErrorCallback) {
  globalErrorHandler = handler;
}

// 设置认证失败处理
export function setAuthFailureHandler(handler: () => void) {
  authFailureHandler = handler;
}

// 创建axios实例
const apiClient: AxiosInstance = axios.create({
  baseURL: '', // 始终使用相对路径，因为前端现在通过后端服务器提供
  timeout: REQUEST_TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
  },
});

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    // 使用认证管理器获取token
    const token = AuthManager.getToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    
    // 添加请求日志
    console.log(`🚀 API Request: ${config.method?.toUpperCase()} ${config.url}`, {
      hasToken: !!token,
      tokenExpired: AuthManager.isTokenExpired(),
    });
    
    return config;
  },
  (error) => {
    console.error('❌ Request Error:', error);
    return Promise.reject(error);
  }
);

// 响应拦截器
apiClient.interceptors.response.use(
  (response: AxiosResponse) => {
    console.log(`✅ API Response: ${response.status} ${response.config.url}`);
    
    // 检查统一API响应格式中的success字段
    if (response.data && typeof response.data === 'object' && 'success' in response.data) {
      if (!response.data.success) {
        // API业务层面的错误，但HTTP状态码可能是200
        console.warn('API业务错误:', response.data);
        
        // 检查业务错误码
        const errorCode = response.data.code;
        
        // 对于登录失败(1002)，不触发路由守卫，只显示错误信息
        if (errorCode === 1002) { // INVALID_CREDENTIALS
          if (globalErrorHandler) {
            const errorMessage = response.data.message || '用户名或密码错误';
            globalErrorHandler(errorMessage, response.data);
          }
        }
        // 对于其他认证相关错误，静默处理
        else if (errorCode >= 1001 && errorCode <= 1004) {
          console.log('🔇 认证相关错误，静默处理:', response.data.message);
          
          // 对于令牌过期等情况，调用认证失败处理器
          if (authFailureHandler && (
            errorCode === 1003 || // TOKEN_EXPIRED
            errorCode === 1004    // TOKEN_INVALID
          )) {
            authFailureHandler();
          }
          
          // 不显示认证错误的弹窗，让用户体验更平滑
        }
        // 其他业务错误
        else {
          if (globalErrorHandler) {
            const errorMessage = response.data.message || '操作失败';
            globalErrorHandler(errorMessage, response.data);
          }
        }
      }
    }
    
    return response;
  },
  (error: AxiosError) => {
    console.error(`❌ API Error: ${error.response?.status} ${error.config?.url}`, error.response?.data);
    
    // 处理HTTP级别的认证失败 (401)
    const responseData = error.response?.data as any;
    const isAuthError = error.response?.status === 401 || 
      (responseData && 
       typeof responseData.code === 'number' &&
       responseData.code >= 1001 && 
       responseData.code <= 1004);
    
    if (isAuthError) {
      console.log('🔇 HTTP认证错误，静默处理:', error.response?.status, responseData?.message);
      
      // 对于令牌过期等情况，调用认证失败处理器
      if (authFailureHandler && (
        error.response?.status === 401 || // HTTP 401
        responseData?.code === 1003 || // TOKEN_EXPIRED
        responseData?.code === 1004    // TOKEN_INVALID
      )) {
        authFailureHandler();
      }
      
      // 不显示认证错误的弹窗，直接跳转到登录页，让用户体验更平滑
      return Promise.reject(error);
    }
    
    // 处理其他错误（非认证错误才显示弹窗）
    if (globalErrorHandler) {
      const errorMessage = getErrorMessage(error);
      globalErrorHandler(errorMessage, error.response?.data);
    }
    
    return Promise.reject(error);
  }
);

// 获取错误消息
function getErrorMessage(error: AxiosError): string {
  if (error.response?.data) {
    const data = error.response.data as any;
    // 优先使用统一API响应格式中的message
    if (data.message) return data.message;
    if (data.error) return data.error;
    if (data.detail) return data.detail;
  }
  
  switch (error.response?.status) {
    case 400:
      return '请求参数错误';
    case 401:
      return '认证失败';
    case 403:
      return '权限不足';
    case 404:
      return '请求的资源不存在';
    case 409:
      return '资源冲突';
    case 422:
      return '数据验证失败';
    case 500:
      return '服务器内部错误';
    case 502:
      return '网关错误';
    case 503:
      return '服务暂时不可用';
    default:
      return error.message || '网络连接失败';
  }
}

// 基础API服务类
class ApiService {
  // 通用GET请求
  async get<T>(url: string, params?: any): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.get(url, { params });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // 通用POST请求
  async post<T>(url: string, data?: any): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.post(url, data);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // 通用PUT请求
  async put<T>(url: string, data?: any): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.put(url, data);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // 通用DELETE请求
  async delete<T>(url: string): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.delete(url);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // 错误处理
  private handleError(error: any): Error {
    if (error.response) {
      const message = getErrorMessage(error);
      return new Error(message);
    }
    return error;
  }
}

// 创建API服务实例
export const apiService = new ApiService();

// 会话相关API
export const conversationAPI = {
  // 获取会话列表 - 修复返回类型
  async getConversations(userId: string, limit: number = 10, offset: number = 0): Promise<ApiResponse<any[]>> {
    return apiService.get(API_ENDPOINTS.CONVERSATION.LIST(userId), { limit, offset });
  },

  // 获取会话详情
  async getConversation(conversationId: string): Promise<ApiResponse<any>> {
    return apiService.get(API_ENDPOINTS.CONVERSATION.DETAIL(conversationId));
  },
};

// 消息相关API
export const messageAPI = {
  // 获取消息列表 - 修复返回类型
  async getMessages(conversationId: string, limit: number = 10, offset: number = 0): Promise<ApiResponse<any[]>> {
    return apiService.get(API_ENDPOINTS.MESSAGE.LIST(conversationId), { limit, offset });
  },
};

// 笔记相关API
export const noteAPI = {
  // 获取笔记列表 - 修正：后端返回包含data字段的结构
  async getNotes(userId: string, params?: any): Promise<ApiResponse<{data: any[], total: number, user_id: number}>> {
    return apiService.get(API_ENDPOINTS.NOTE.LIST(userId), params);
  },

  // 创建笔记
  async createNote(userId: string, data: any): Promise<ApiResponse<any>> {
    return apiService.post(API_ENDPOINTS.NOTE.CREATE(userId), data);
  },

  // 更新笔记
  async updateNote(userId: string, noteId: string, data: any): Promise<ApiResponse<any>> {
    return apiService.put(API_ENDPOINTS.NOTE.UPDATE(userId, noteId), data);
  },

  // 删除笔记
  async deleteNote(userId: string, noteId: string): Promise<ApiResponse<any>> {
    return apiService.delete(API_ENDPOINTS.NOTE.DELETE(userId, noteId));
  },

  // 搜索笔记 - 修正：后端返回包含data字段的结构
  async searchNotes(userId: string, searchData: any): Promise<ApiResponse<{data: any[], total: number, user_id: number}>> {
    return apiService.post(API_ENDPOINTS.NOTE.SEARCH(userId), searchData);
  },

  // 获取笔记标签 - 修正：后端返回包含data字段的结构
  async getTags(userId: string): Promise<ApiResponse<{data: any[], total: number, user_id: number}>> {
    return apiService.get(API_ENDPOINTS.NOTE.TAGS(userId));
  },
};

// 待办事项相关API
export const todoAPI = {
  // 获取待办事项列表 - 修正：后端直接返回Todo数组，不是分页结构
  async getTodos(userId: string, params?: any): Promise<ApiResponse<any[]>> {
    return apiService.get(API_ENDPOINTS.TODO.LIST(userId), params);
  },

  // 创建待办事项
  async createTodo(userId: string, data: any): Promise<ApiResponse<any>> {
    return apiService.post(API_ENDPOINTS.TODO.CREATE(userId), data);
  },

  // 更新待办事项
  async updateTodo(userId: string, todoId: string, data: any): Promise<ApiResponse<any>> {
    return apiService.put(API_ENDPOINTS.TODO.UPDATE(userId, todoId), data);
  },

  // 删除待办事项
  async deleteTodo(userId: string, todoId: string): Promise<ApiResponse<any>> {
    return apiService.delete(API_ENDPOINTS.TODO.DELETE(userId, todoId));
  },

  // 完成待办事项
  async completeTodo(userId: string, todoId: string): Promise<ApiResponse<any>> {
    return apiService.post(API_ENDPOINTS.TODO.COMPLETE(userId, todoId));
  },

  // 取消完成待办事项
  async uncompleteTodo(userId: string, todoId: string): Promise<ApiResponse<any>> {
    return apiService.post(API_ENDPOINTS.TODO.UNCOMPLETE(userId, todoId));
  },

  // 获取待办事项统计 - 后端返回包含data字段的结构
  async getStats(userId: string): Promise<ApiResponse<{data: any}>> {
    return apiService.get(API_ENDPOINTS.TODO.STATS(userId));
  },
};

// 认证相关API
export const authAPI = {
  async login(credentials: LoginCredentials): Promise<ApiResponse<AuthToken>> {
    return apiService.post(API_ENDPOINTS.AUTH.LOGIN, credentials);
  },

  async register(credentials: RegisterCredentials): Promise<ApiResponse<AuthToken>> {
    return apiService.post(API_ENDPOINTS.AUTH.REGISTER, credentials);
  },

  async logout(): Promise<ApiResponse<any>> {
    return apiService.post(API_ENDPOINTS.AUTH.LOGOUT);
  },

  async refreshToken(): Promise<ApiResponse<AuthToken>> {
    return apiService.post(API_ENDPOINTS.AUTH.REFRESH);
  },

  async getCurrentUser(): Promise<ApiResponse<User>> {
    return apiService.get(API_ENDPOINTS.USER.PROFILE);
  },
};

// 导出axios实例供特殊需求使用
export { apiClient }; 