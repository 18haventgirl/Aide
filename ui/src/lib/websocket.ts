import { isRecord } from './api-errors';
import { parseChatResponse, type ChatResponse } from './chat-payload';
export type { ChatResponse } from './chat-payload';

export interface WebSocketMessage {
  type: string;
  content: unknown;
  sender_id?: string;
  receiver_id?: string;
  room_id?: string;
  conversation_id?: string;
  timestamp?: string;
  metadata?: { mode?: 'general' | 'medical'; conversation_id?: string };
}

export type WebSocketConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';
export interface WebSocketEvents {
  status: WebSocketConnectionStatus;
  connected: { connection_id?: string };
  error: { error: string };
  auth_error: { error: string };
  ai_error: { error: string };
  ai_response: ChatResponse;
  ai_thinking: ChatResponse;
  ai_finished: ChatResponse;
  chat_response: ChatResponse;
  conversation_switched: { conversation_id?: string };
  notification: Record<string, unknown>;
  message: WebSocketMessage;
}
export type WebSocketEventHandler<K extends keyof WebSocketEvents> = (data: WebSocketEvents[K]) => void;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private pendingConnection: Promise<void> | null = null;
  private rejectConnection: ((error: Error) => void) | null = null;
  private _status: WebSocketConnectionStatus = 'disconnected';
  private _conversationId?: string;
  private handlers: { [K in keyof WebSocketEvents]: Set<WebSocketEventHandler<K>> } = {
    status: new Set(), connected: new Set(), error: new Set(), auth_error: new Set(), ai_error: new Set(),
    ai_response: new Set(), ai_thinking: new Set(), ai_finished: new Set(), chat_response: new Set(),
    conversation_switched: new Set(), notification: new Set(), message: new Set(),
  };
  private readonly _userId: string;
  private readonly username?: string;
  private readonly token?: string;

  constructor(userId: string, username?: string, conversationId?: string, token?: string) {
    this._userId = userId;
    this.username = username;
    this.token = token;
    this._conversationId = conversationId;
  }
  get status() { return this._status; }
  get userId() { return this._userId; }
  get conversationId() { return this._conversationId; }
  matchesCredentials(userId: string, username?: string, token?: string) {
    return this._userId === userId && this.username === username && this.token === token;
  }
  setConversationId(conversationId: string | null) { this._conversationId = conversationId || undefined; }
  private setStatus(status: WebSocketConnectionStatus) { this._status = status; this.emit('status', status); }

  connect(): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN) return Promise.resolve();
    if (this.pendingConnection) return this.pendingConnection;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const url = new URL('/ws', window.location.origin);
    url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    url.searchParams.set('user_id', this._userId);
    if (this.username) url.searchParams.set('username', this.username);
    if (this.token) url.searchParams.set('token', this.token);
    if (this._conversationId) url.searchParams.set('conversation_id', this._conversationId);
    // Use the same-origin Vite /ws proxy in development as well as production.
    const socket = new WebSocket(url.toString());
    this.ws = socket;
    this.setStatus('connecting');
    this.pendingConnection = new Promise<void>((resolve, reject) => {
      this.rejectConnection = reject;
      socket.onopen = () => {
        if (this.ws !== socket) return;
        this.pendingConnection = null; this.rejectConnection = null;
        this.setStatus('connected'); resolve();
      };
      socket.onmessage = event => {
        if (this.ws !== socket) return;
        try {
          const raw: unknown = JSON.parse(event.data);
          if (isRecord(raw) && typeof raw.type === 'string') this.handleMessage({ type: raw.type, content: raw.content });
        } catch { this.emit('error', { error: '无法读取服务端消息' }); }
      };
      socket.onerror = () => {
        if (this.ws !== socket) return;
        this.setStatus('error');
        this.pendingConnection = null; this.rejectConnection = null;
        reject(new Error('WebSocket连接失败'));
      };
      socket.onclose = event => {
        if (this.ws !== socket) return;
        this.ws = null;
        this.pendingConnection = null; this.rejectConnection = null;
        this.setStatus('disconnected');
        const authFailure = [1008, 4001, 4003].includes(event.code);
        const message = authFailure ? 'WebSocket认证失败' : 'WebSocket连接已关闭';
        reject(new Error(message));
        if (authFailure) this.emit('auth_error', { error: message });
        // 1011 is a server error, not evidence that credentials are invalid.
        else if (event.code !== 1000 && this.reconnectAttempts < 5) this.scheduleReconnect();
      };
    });
    return this.pendingConnection;
  }

  disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    const socket = this.ws;
    this.ws = null; // Ignore delayed callbacks from this socket after a reconnect.
    this.rejectConnection?.(new Error('连接已取消'));
    this.pendingConnection = null; this.rejectConnection = null;
    socket?.close(1000, 'Client disconnect');
    this.setStatus('disconnected');
  }
  send(message: WebSocketMessage): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(message));
    return true;
  }
  sendChatMessage(content: string, mode: 'general' | 'medical' = 'general'): boolean {
    return this.send({ type: 'chat', content, timestamp: new Date().toISOString(),
      conversation_id: this._conversationId, metadata: { mode, conversation_id: this._conversationId } });
  }
  switchConversation(conversationId: string) {
    this._conversationId = conversationId;
    return this.send({ type: 'switch_conversation', content: { conversation_id: conversationId }, timestamp: new Date().toISOString() });
  }
  private handleMessage(message: WebSocketMessage) {
    const { type, content } = message;
    switch (type) {
      case 'ai_response': case 'ai_thinking': case 'ai_finished': case 'chat_response':
        this.emit(type, parseChatResponse(content)); break;
      case 'connect': case 'connected':
        // A transport handshake alone does not mean backend initialization succeeded.
        this.reconnectAttempts = 0;
        this.emit('connected', { connection_id: isRecord(content) && typeof content.connection_id === 'string' ? content.connection_id : undefined }); break;
      case 'error': case 'auth_error': case 'ai_error':
        this.emit(type, { error: isRecord(content) && typeof content.error === 'string' ? content.error : '服务暂时不可用' }); break;
      case 'notification':
        if (isRecord(content)) {
          if (content.type === 'conversation_switched' && typeof content.conversation_id === 'string') {
            this.emit('conversation_switched', { conversation_id: content.conversation_id });
          }
          this.emit('notification', content);
        }
        break;
      default: this.emit('message', message);
    }
  }
  private scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    const delay = Math.min(1000 * 2 ** ++this.reconnectAttempts, 30000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect().catch(() => { /* onclose controls bounded retry. */ });
    }, delay);
  }
  on<K extends keyof WebSocketEvents>(event: K, handler: WebSocketEventHandler<K>) { this.handlers[event].add(handler); }
  off<K extends keyof WebSocketEvents>(event: K, handler: WebSocketEventHandler<K>) { this.handlers[event].delete(handler); }
  private emit<K extends keyof WebSocketEvents>(event: K, data: WebSocketEvents[K]) {
    this.handlers[event].forEach(handler => {
      try { handler(data); } catch (error) { console.error(`事件处理失败 (${event})`, error); }
    });
  }
}

let wsService: WebSocketService | null = null;
export function createWebSocketService(userId: string, username?: string, conversationId?: string, token?: string): WebSocketService {
  if (wsService?.matchesCredentials(userId, username, token)) return wsService;
  wsService?.disconnect();
  wsService = new WebSocketService(userId, username, conversationId, token);
  return wsService;
}
export function getWebSocketService(): WebSocketService | null { return wsService; }
