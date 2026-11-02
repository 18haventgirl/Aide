import axios from 'axios';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function responseErrorMessage(value: unknown): string | undefined {
  if (!isRecord(value)) return undefined;
  for (const key of ['message', 'error', 'detail']) {
    if (typeof value[key] === 'string' && value[key]) return value[key];
  }
  // FastAPI validation details are arrays, which cannot be rendered as React text.
  if (Array.isArray(value.detail)) {
    const messages = value.detail.flatMap(item => isRecord(item) && typeof item.msg === 'string' ? [item.msg] : []);
    if (messages.length) return messages.join('；');
  }
  return undefined;
}

export class ApiError extends Error {
  readonly status?: number;
  readonly code?: number;

  constructor(message: string, status?: number, code?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export function toApiError(error: unknown, fallback = '网络连接失败'): ApiError {
  if (error instanceof ApiError) return error;
  if (axios.isAxiosError<unknown>(error)) {
    const data = error.response?.data;
    const status = error.response?.status;
    const statusMessages: Record<number, string> = {
      400: '请求参数错误', 401: '请先登录', 403: '没有权限访问', 404: '请求的资源不存在',
      500: '服务器内部错误', 502: '网关错误', 503: '服务暂时不可用',
    };
    return new ApiError(
      responseErrorMessage(data) || (status ? statusMessages[status] : undefined) || error.message || fallback,
      status,
      isRecord(data) && typeof data.code === 'number' ? data.code : undefined,
    );
  }
  return new ApiError(error instanceof Error ? error.message : fallback);
}

export function isAuthenticationError(error: unknown): boolean {
  const { status, code } = toApiError(error);
  return status === 401 || (code !== undefined && code >= 1001 && code <= 1004);
}
