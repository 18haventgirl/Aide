export interface WebSocketMessage {
  type: string;
  content: any;
  sender_id?: string;
  receiver_id?: string;
  room_id?: string;
  conversation_id?: string;
  timestamp?: string;
}

export type WebSocketConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error';

export type WebSocketEventHandler = (data: any) => void;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectInterval = 3000;
  private _userId: string;
  private username?: string;
  private token?: string;
  
  // 事件处理器
  private handlers: Record<string, WebSocketEventHandler[]> = {};
  
  // 连接状态
  private _status: WebSocketConnectionStatus = 'disconnected';
  
  constructor(userId: string, username?: string, conversationId?: string, token?: string) {
    this._userId = userId;
    this.username = username;
    this._conversationId = conversationId;
    this.token = token;
  }
  
  private _conversationId?: string;
  
  get status(): WebSocketConnectionStatus {
    return this._status;
  }
  
  get userId(): string {
    return this._userId;
  }
  
  get conversationId(): string | undefined {
    return this._conversationId;
  }
  
  setConversationId(conversationId: string | null) {
    console.log('🔄 WebSocket设置会话ID:', this._conversationId, '->', conversationId);
    this._conversationId = conversationId || undefined;
  }
  
  private setStatus(status: WebSocketConnectionStatus) {
    console.log('📊 WebSocket状态变更:', this._status, '->', status);
    this._status = status;
    this.emit('status', status);
  }
  
  // 连接WebSocket
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        console.log('🔗 WebSocket已经连接，直接返回');
        resolve();
        return;
      }
      
      console.log('🔌 开始建立WebSocket连接...');
      this.setStatus('connecting');
      
      // 构建WebSocket URL
      const wsUrl = new URL('/ws', window.location.origin);
      wsUrl.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsUrl.searchParams.set('user_id', this._userId);
      if (this.username) {
        wsUrl.searchParams.set('username', this.username);
      }
      if (this._conversationId) {
        wsUrl.searchParams.set('conversation_id', this._conversationId);
      }
      if (this.token) {
        wsUrl.searchParams.set('token', this.token);
      }
      
      // 同源 /ws：开发环境由 vite 代理转发到后端，无需在此写死后端端口
      console.log('🌐 WebSocket URL:', wsUrl.toString());
      console.log('🔐 连接参数详情:', {
        userId: this._userId,
        username: this.username,
        hasToken: !!this.token,
        tokenLength: this.token?.length || 0,
        conversationId: this._conversationId
      });
      
      this.ws = new WebSocket(wsUrl.toString());
      
      this.ws.onopen = () => {
        console.log('✅ WebSocket连接已建立');
        this.setStatus('connected');
        this.reconnectAttempts = 0;
        resolve();
      };
      
      this.ws.onmessage = (event) => {
        console.log('📥 收到WebSocket消息:', event.data);
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          this.handleMessage(message);
        } catch (error) {
          console.error('❌ 解析WebSocket消息失败:', error);
        }
      };
      
      this.ws.onclose = (event) => {
        console.log('🔌 WebSocket连接已关闭:', { 
          code: event.code, 
          reason: event.reason,
          wasClean: event.wasClean,
          timestamp: new Date().toISOString()
        });
        
        // 详细的关闭代码分析
        switch (event.code) {
          case 4001:
            console.error('❌ 认证失败：JWT令牌无效或已过期');
            this.emit('auth_error', { error: 'JWT令牌无效或已过期' });
            break;
          case 4003:
            console.error('❌ 认证失败：用户ID与令牌不匹配');
            this.emit('auth_error', { error: '用户ID与令牌不匹配' });
            break;
          case 1000:
            console.log('✅ 正常关闭连接');
            break;
          default:
            console.warn('⚠️ 连接异常关闭，代码:', event.code, '原因:', event.reason);
        }
        
        this.setStatus('disconnected');
        
        // 认证失败时不进行重连
        if (event.code === 1008 || event.code === 1011 || event.code === 4001 || event.code === 4003) {
          console.error('❌ WebSocket认证失败，停止重连');
          this.emit('auth_error', { error: 'WebSocket认证失败' });
          reject(new Error('WebSocket认证失败'));
          return;
        }
        
        // 非正常关闭时尝试重连
        if (event.code !== 1000 && this.reconnectAttempts < this.maxReconnectAttempts) {
          console.log('🔄 准备重连...');
          this.scheduleReconnect();
        }
      };
      
      this.ws.onerror = (error) => {
        console.error('❌ WebSocket错误:', error);
        this.setStatus('error');
        reject(error);
      };
    });
  }
  
  // 断开连接
  disconnect() {
    console.log('🔌 手动断开WebSocket连接');
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    
    if (this.ws) {
      this.ws.close(1000, 'Client disconnect');
      this.ws = null;
    }
    
    this.setStatus('disconnected');
  }
  
  // 发送消息
  send(message: WebSocketMessage) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('⚠️ WebSocket未连接，无法发送消息:', message);
      return;
    }
    
    console.log('📤 发送WebSocket消息:', message);
    this.ws.send(JSON.stringify(message));
  }
  
  // 发送聊天消息
  sendChatMessage(content: string) {
    console.log('💬 发送聊天消息:', content, '会话ID:', this._conversationId);
    
    const message: WebSocketMessage = {
      type: 'chat',
      content: content,
      timestamp: new Date().toISOString()
    };
    
    // 如果有会话ID，添加到消息的metadata中
    if (this._conversationId) {
      message.conversation_id = this._conversationId;
      // 也添加到metadata中以便后端处理
      (message as any).metadata = {
        conversation_id: this._conversationId
      };
    }
    
    this.send(message);
  }
  
  // 发送会话切换消息
  switchConversation(conversationId: string) {
    console.log('🔄 切换会话:', conversationId);
    
    const message: WebSocketMessage = {
      type: 'switch_conversation',
      content: {
        conversation_id: conversationId
      },
      timestamp: new Date().toISOString()
    };
    
    this.send(message);
    
    // 立即更新本地会话ID
    this._conversationId = conversationId;
  }
  
  // 处理接收到的消息
  private handleMessage(message: WebSocketMessage) {
    console.log('🔍 处理WebSocket消息:', message);
    const { type, content } = message;
    
    switch (type) {
      case 'ai_response':
        this.emit('ai_response', content);
        break;
      case 'ai_thinking':
        this.emit('ai_thinking', content);
        break;
      case 'ai_finished':
        this.emit('ai_finished', content);
        break;
      case 'chat_response':
        console.log('💬 收到聊天响应:', content);
        this.emit('chat_response', content);
        break;
      case 'connect':
      case 'connected':
        console.log('🎉 连接成功消息:', content);
        this.emit('connected', content);
        break;
      case 'notification':
        console.log('📢 通知消息:', content);
        // 检查是否是会话切换确认消息
        if (content && content.type === 'conversation_switched') {
          console.log('✅ 会话切换成功:', content.conversation_id);
          this.emit('conversation_switched', content);
        }
        this.emit('notification', content);
        break;
      case 'error':
        console.error('❌ 服务器错误:', content);
        this.emit('error', content);
        break;
      case 'auth_error':
        console.error('❌ 认证错误:', content);
        this.emit('auth_error', content);
        break;
      default:
        console.log('📨 其他消息类型:', type, content);
        this.emit(type, content);
        this.emit('message', message);
    }
  }
  
  // 安排重连
  private scheduleReconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
    
    console.log(`🔄 安排重连 (第${this.reconnectAttempts}次)，${delay}ms后重试`);
    
    this.reconnectTimer = setTimeout(async () => {
      try {
        await this.connect();
      } catch (error) {
        console.error('❌ 重连失败:', error);
      }
    }, delay);
  }
  
  // 事件监听器
  on(event: string, handler: WebSocketEventHandler) {
    if (!this.handlers[event]) {
      this.handlers[event] = [];
    }
    this.handlers[event].push(handler);
  }
  
  // 移除事件监听器
  off(event: string, handler: WebSocketEventHandler) {
    if (this.handlers[event]) {
      this.handlers[event] = this.handlers[event].filter(h => h !== handler);
    }
  }
  
  // 触发事件
  private emit(event: string, data: any) {
    if (this.handlers[event]) {
      this.handlers[event].forEach(handler => {
        try {
          handler(data);
        } catch (error) {
          console.error(`事件处理器执行失败 (${event}):`, error);
        }
      });
    }
  }
}

// 创建全局WebSocket实例
let wsService: WebSocketService | null = null;

export function createWebSocketService(userId: string, username?: string, conversationId?: string, token?: string): WebSocketService {
  // 如果已存在服务且用户ID相同，返回现有服务
  if (wsService && wsService.userId === userId) {
    console.log('♻️ 复用现有WebSocket服务');
    // 不在这里更新会话ID，而是通过专门的方法处理
    return wsService;
  }
  
  // 如果存在不同用户的服务，先断开
  if (wsService) {
    console.log('🔄 断开现有WebSocket服务（用户切换）');
    wsService.disconnect();
  }
  
  console.log('🆕 创建新的WebSocket服务:', { userId, username, conversationId, token: token ? '[TOKEN]' : undefined });
  wsService = new WebSocketService(userId, username, conversationId, token);
  return wsService;
}

export function getWebSocketService(): WebSocketService | null {
  return wsService;
} 