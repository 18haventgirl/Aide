// 运行时配置
//
// 默认全部走同源相对路径：开发时由 vite 代理转发到后端，生产时前端产物由后端直接托管。
// 需要让浏览器直连另一个端口的后端时，用 VITE_API_BASE_URL 覆盖。
const ORIGIN = typeof window !== 'undefined' ? window.location.origin : '';

export const config = {
  // API基础配置
  API_BASE_URL: import.meta.env.VITE_API_BASE_URL ?? ORIGIN,

  // API请求超时配置
  REQUEST_TIMEOUT: 10000,

  // 分页配置
  PAGINATION: {
    DEFAULT_PAGE_SIZE: 10,
    MAX_PAGE_SIZE: 50,
  },
};

// API端点配置
export const API_ENDPOINTS = {
  // 认证相关
  AUTH: {
    LOGIN: '/api/auth/login',
    REGISTER: '/api/auth/register',
    REFRESH: '/api/auth/refresh',
    LOGOUT: '/api/auth/logout',
  },
  
  // 用户相关
  USER: {
    PROFILE: '/api/auth/me',
  },
  
  // 会话相关
  CONVERSATION: {
    LIST: (userId: string) => `/api/conversations/${userId}`,
    DETAIL: (conversationId: string) => `/api/conversations/${conversationId}`,
  },
  
  // 消息相关 - 修复端点配置
  MESSAGE: {
    LIST: (conversationId: string) => `/api/conversations/${conversationId}/messages`,
  },
  
  // 笔记相关
  NOTE: {
    LIST: (userId: string) => `/api/notes/${userId}`,
    CREATE: (userId: string) => `/api/notes/${userId}`,
    UPDATE: (userId: string, noteId: string) => `/api/notes/${userId}/${noteId}`,
    DELETE: (userId: string, noteId: string) => `/api/notes/${userId}/${noteId}`,
    SEARCH: (userId: string) => `/api/notes/${userId}/search`,
    TAGS: (userId: string) => `/api/notes/${userId}/tags`,
  },
  
  // 待办事项相关
  TODO: {
    LIST: (userId: string) => `/api/todos/${userId}`,
    CREATE: (userId: string) => `/api/todos/${userId}`,
    UPDATE: (userId: string, todoId: string) => `/api/todos/${userId}/${todoId}`,
    DELETE: (userId: string, todoId: string) => `/api/todos/${userId}/${todoId}`,
    COMPLETE: (userId: string, todoId: string) => `/api/todos/${userId}/${todoId}/complete`,
    UNCOMPLETE: (userId: string, todoId: string) => `/api/todos/${userId}/${todoId}/uncomplete`,
    STATS: (userId: string) => `/api/todos/${userId}/stats`,
  },
};

// 导出配置项
export const { API_BASE_URL, REQUEST_TIMEOUT, PAGINATION } = config; 