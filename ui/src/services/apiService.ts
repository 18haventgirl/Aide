import axios from 'axios';
import type { AxiosInstance, AxiosError, AxiosResponse } from 'axios';
import { API_ENDPOINTS, REQUEST_TIMEOUT } from '../lib/config';
import type { LoginCredentials, AuthToken, HealthRecord, HealthRecordCreateRequest } from '../lib/types';
import type { Note, NoteCreateRequest, NoteUpdateRequest, Todo, TodoCreateRequest, TodoUpdateRequest, TodoStatsResponse } from '../lib/types';
import type { StoredConversation, StoredMessage, UserList, SearchNote, NoteSearchRequest, ListParams, CurrentUserResponse } from '../lib/api-contracts';
import type { ChatResponse } from '../lib/websocket';
import { isRecord, responseErrorMessage, toApiError } from '../lib/api-errors';
import { AuthManager } from '../lib/auth';

// 通用API响应类型
export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  message?: string;
  error?: string;
  code?: number;
}

// 分页响应类型
export interface PaginatedResponse<T = unknown> {
  data: T[];
  total: number;
  page: number;
  size: number;
  has_more: boolean;
}

// 错误处理回调类型
export type ErrorCallback = (error: string, details?: unknown) => void;

// 全局错误处理回调
let globalErrorHandler: ErrorCallback | null = null;
// 认证失败回调
let authFailureHandler: (() => void) | null = null;

// 设置全局错误处理
export function setGlobalErrorHandler(handler: ErrorCallback | null) {
  globalErrorHandler = handler;
}

// 设置认证失败处理
export function setAuthFailureHandler(handler: (() => void) | null) {
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
  (response: AxiosResponse<unknown>) => {
    console.log(`✅ API Response: ${response.status} ${response.config.url}`);
    
    // 检查统一API响应格式中的success字段
    if (isRecord(response.data) && 'success' in response.data) {
      if (!response.data.success) {
        // API业务层面的错误，但HTTP状态码可能是200
        console.warn('API业务错误:', response.data);
        
        // 检查业务错误码
        const errorCode = response.data.code;
        
        // 对于登录失败(1002)，不触发路由守卫，只显示错误信息
        if (errorCode === 1002) { // INVALID_CREDENTIALS
          if (globalErrorHandler) {
            const errorMessage = responseErrorMessage(response.data) || '用户名或密码错误';
            globalErrorHandler(errorMessage, response.data);
          }
        }
        // 对于其他认证相关错误，静默处理
        else if (typeof errorCode === 'number' && errorCode >= 1001 && errorCode <= 1004) {
          console.log('🔇 认证相关错误，静默处理:', response.data.message);
          
          // 对于令牌过期等情况，调用认证失败处理器
          if (response.config.url !== API_ENDPOINTS.AUTH.REFRESH && authFailureHandler && (
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
            const errorMessage = responseErrorMessage(response.data) || '操作失败';
            globalErrorHandler(errorMessage, response.data);
          }
        }
      }
    }
    
    return response;
  },
  (error: AxiosError) => {
    if (error.code === 'ERR_CANCELED') return Promise.reject(error);
    console.error(`❌ API Error: ${error.response?.status} ${error.config?.url}`, error.response?.data);
    
    // 处理HTTP级别的认证失败 (401)
    const responseData = isRecord(error.response?.data) ? error.response.data : undefined;
    const isAuthError = error.response?.status === 401 || 
      (responseData && 
       typeof responseData.code === 'number' &&
       responseData.code >= 1001 && 
       responseData.code <= 1004);
    
    if (isAuthError) {
      console.log('🔇 HTTP认证错误，静默处理:', error.response?.status, responseData?.message);
      
      // 对于令牌过期等情况，调用认证失败处理器
      if (error.config?.url !== API_ENDPOINTS.AUTH.REFRESH && authFailureHandler && (
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
function getErrorMessage(error: unknown): string {
  return toApiError(error).message;
}

// 基础API服务类
class ApiService {
  // 通用GET请求
  async get<T>(url: string, params?: ListParams): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.get(url, { params });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // 通用POST请求
  async post<T>(url: string, data?: unknown): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.post(url, data);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // 通用PUT请求
  async put<T>(url: string, data?: unknown): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.put(url, data);
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  async patch<T>(url: string, data?: unknown): Promise<ApiResponse<T>> {
    try {
      const response = await apiClient.patch(url, data);
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
  private handleError(error: unknown): Error {
    // Preserve status/code so authentication failures remain distinguishable.
    return toApiError(error);
  }
}

// 创建API服务实例
export const apiService = new ApiService();

// 会话相关API
export const conversationAPI = {
  // 获取会话列表 - 修复返回类型
  async getConversations(userId: string, limit: number = 10, offset: number = 0): Promise<ApiResponse<StoredConversation[]>> {
    return apiService.get(API_ENDPOINTS.CONVERSATION.LIST(userId), { limit, offset });
  },

  // 获取会话详情
  async getConversation(conversationId: string): Promise<ApiResponse<unknown>> {
    return apiService.get(API_ENDPOINTS.CONVERSATION.DETAIL(conversationId));
  },

  // 创建会话
  async createConversation(data: unknown): Promise<ApiResponse<unknown>> {
    return apiService.post(API_ENDPOINTS.CONVERSATION.CREATE, data);
  },

  // 更新会话
  async updateConversation(conversationId: string, data: unknown): Promise<ApiResponse<unknown>> {
    return apiService.put(API_ENDPOINTS.CONVERSATION.UPDATE(conversationId), data);
  },

  // 删除会话
  async deleteConversation(conversationId: string): Promise<ApiResponse<unknown>> {
    return apiService.delete(API_ENDPOINTS.CONVERSATION.DELETE(conversationId));
  },
};

// 消息相关API
export const messageAPI = {
  // 获取消息列表 - 修复返回类型
  async getMessages(conversationId: string, limit: number = 10, offset: number = 0): Promise<ApiResponse<StoredMessage[]>> {
    return apiService.get(API_ENDPOINTS.MESSAGE.LIST(conversationId), { limit, offset });
  },

  // 发送消息
  async sendMessage(data: unknown): Promise<ApiResponse<unknown>> {
    return apiService.post(API_ENDPOINTS.MESSAGE.CREATE, data);
  },
};

// 聊天相关API
export const chatAPI = {
  // 发送聊天消息
  async sendChatMessage(data: { conversation_id: string; message: string }): Promise<ApiResponse<ChatResponse>> {
    return apiService.post(API_ENDPOINTS.CHAT.SEND, data);
  },
};

// 笔记相关API
export const noteAPI = {
  // 获取笔记列表 - 修正：后端返回包含data字段的结构
  async getNotes(userId: string, params?: ListParams): Promise<ApiResponse<UserList<Note>>> {
    return apiService.get(API_ENDPOINTS.NOTE.LIST(userId), params);
  },

  async getNote(userId: string, noteId: string): Promise<ApiResponse<Note>> {
    return apiService.get(API_ENDPOINTS.NOTE.UPDATE(userId, noteId));
  },

  // 创建笔记
  async createNote(userId: string, data: NoteCreateRequest): Promise<ApiResponse<Note>> {
    return apiService.post(API_ENDPOINTS.NOTE.CREATE(userId), data);
  },

  // 更新笔记
  async updateNote(userId: string, noteId: string, data: NoteUpdateRequest): Promise<ApiResponse<Note>> {
    return apiService.put(API_ENDPOINTS.NOTE.UPDATE(userId, noteId), data);
  },

  // 删除笔记
  async deleteNote(userId: string, noteId: string): Promise<ApiResponse<unknown>> {
    return apiService.delete(API_ENDPOINTS.NOTE.DELETE(userId, noteId));
  },

  // 搜索笔记 - 修正：后端返回包含data字段的结构
  async searchNotes(userId: string, searchData: NoteSearchRequest, signal?: AbortSignal): Promise<ApiResponse<UserList<SearchNote>>> {
    if (signal) {
      const response = await apiClient.post(API_ENDPOINTS.NOTE.SEARCH(userId), searchData, { signal });
      if (response.data?.success === false) throw new Error(response.data.message || '搜索失败');
      return response.data;
    }
    try {
      const response = await apiService.post<UserList<Note>>(API_ENDPOINTS.NOTE.SEARCH(userId), searchData);
      if (response.success === false || !Array.isArray(response.data?.data)) {
        return apiService.get<UserList<Note>>(API_ENDPOINTS.NOTE.LIST(userId), { search: searchData.query, tag: searchData.tag, status: searchData.status, limit: searchData.limit });
      }
      return response;
    } catch {
      // Keep keyword search usable when vector dependencies are unavailable.
      return apiService.get<UserList<Note>>(API_ENDPOINTS.NOTE.LIST(userId), { search: searchData.query, tag: searchData.tag, status: searchData.status, limit: searchData.limit });
    }
  },

  // 获取笔记标签 - 修正：后端返回包含data字段的结构
  async getTags(userId: string): Promise<ApiResponse<UserList<string>>> {
    return apiService.get(API_ENDPOINTS.NOTE.TAGS(userId));
  },
};

// 待办事项相关API
export const todoAPI = {
  // 获取待办事项列表 - 修正：后端直接返回Todo数组，不是分页结构
  async getTodos(userId: string, params?: ListParams): Promise<ApiResponse<Todo[]>> {
    return apiService.get(API_ENDPOINTS.TODO.LIST(userId), params);
  },

  async getTodo(userId: string, todoId: string): Promise<ApiResponse<Todo>> {
    return apiService.get(API_ENDPOINTS.TODO.UPDATE(userId, todoId));
  },

  // 创建待办事项
  async createTodo(userId: string, data: TodoCreateRequest): Promise<ApiResponse<Todo>> {
    return apiService.post(API_ENDPOINTS.TODO.CREATE(userId), data);
  },

  // 更新待办事项
  async updateTodo(userId: string, todoId: string, data: TodoUpdateRequest): Promise<ApiResponse<Todo>> {
    return apiService.put(API_ENDPOINTS.TODO.UPDATE(userId, todoId), data);
  },

  // 删除待办事项
  async deleteTodo(userId: string, todoId: string): Promise<ApiResponse<unknown>> {
    return apiService.delete(API_ENDPOINTS.TODO.DELETE(userId, todoId));
  },

  // 完成待办事项
  async completeTodo(userId: string, todoId: string): Promise<ApiResponse<unknown>> {
    return apiService.post(API_ENDPOINTS.TODO.COMPLETE(userId, todoId));
  },

  // 取消完成待办事项
  async uncompleteTodo(userId: string, todoId: string): Promise<ApiResponse<unknown>> {
    return apiService.post(API_ENDPOINTS.TODO.UNCOMPLETE(userId, todoId));
  },

  // 获取待办事项统计 - 后端返回包含data字段的结构
  async getStats(userId: string): Promise<ApiResponse<{data: TodoStatsResponse['data']}>> {
    return apiService.get(API_ENDPOINTS.TODO.STATS(userId));
  },

  // 获取关联笔记的待办事项 - 后端返回包含data字段的结构
  async getTodosByNote(userId: string, noteId: string): Promise<ApiResponse<{data: Todo[], total: number}>> {
    return apiService.get(API_ENDPOINTS.TODO.BY_NOTE(userId, noteId));
  },
};

export const healthRecordAPI = {
  async getRecords(userId: string, params?: { start_date?: string; end_date?: string; limit?: number }): Promise<ApiResponse<{ records: HealthRecord[]; daily_counts: Record<string, number>; total: number; user_id: number }>> {
    return apiService.get(API_ENDPOINTS.HEALTH_RECORD.LIST(userId), params);
  },
  async getRecord(userId: string, recordId: string): Promise<ApiResponse<HealthRecord>> {
    return apiService.get(API_ENDPOINTS.HEALTH_RECORD.DETAIL(userId, recordId));
  },
  async createRecord(userId: string, data: HealthRecordCreateRequest): Promise<ApiResponse<HealthRecord>> {
    return apiService.post(API_ENDPOINTS.HEALTH_RECORD.CREATE(userId), data);
  },
  async updateRecord(userId: string, recordId: string, data: Partial<HealthRecordCreateRequest>): Promise<ApiResponse<HealthRecord>> {
    return apiService.patch(API_ENDPOINTS.HEALTH_RECORD.UPDATE(userId, recordId), data);
  },
  async deleteRecord(userId: string, recordId: string): Promise<ApiResponse<{ id: number }>> {
    return apiService.delete(API_ENDPOINTS.HEALTH_RECORD.DELETE(userId, recordId));
  },
};

// 用户相关API
export const userAPI = {
  // 获取用户信息
  async getProfile(): Promise<ApiResponse<unknown>> {
    return apiService.get(API_ENDPOINTS.USER.PROFILE);
  },

  // 获取用户偏好设置
  async getPreferences(): Promise<ApiResponse<unknown>> {
    return apiService.get(API_ENDPOINTS.USER.PREFERENCES);
  },

  // 更新用户偏好设置
  async updatePreferences(data: unknown): Promise<ApiResponse<unknown>> {
    return apiService.put(API_ENDPOINTS.USER.PREFERENCES, data);
  },
};

// 认证相关API
export const authAPI = {
  async login(credentials: LoginCredentials): Promise<ApiResponse<AuthToken>> {
    return apiService.post(API_ENDPOINTS.AUTH.LOGIN, credentials);
  },

  async logout(): Promise<ApiResponse<unknown>> {
    return apiService.post(API_ENDPOINTS.AUTH.LOGOUT);
  },

  async refreshToken(): Promise<ApiResponse<AuthToken | undefined>> {
    const response = await apiClient.post<{ success: boolean; code?: number; message?: string; token?: AuthToken; data?: AuthToken }>(API_ENDPOINTS.AUTH.REFRESH);
    return { success: response.data.success, code: response.data.code, message: response.data.message, data: response.data.token ?? response.data.data };
  },

  async getCurrentUser(): Promise<CurrentUserResponse> {
    const response = await apiClient.get<CurrentUserResponse>(API_ENDPOINTS.USER.PROFILE);
    return response.data;
  },
};

// 导出axios实例供特殊需求使用
export { apiClient };
