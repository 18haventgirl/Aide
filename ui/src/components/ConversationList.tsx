import React, { useState, useEffect, useRef } from 'react';
import { MessageSquare, ChevronDown, ChevronUp, X, Plus, Clock, User, Loader2 } from 'lucide-react';
import { conversationAPI } from '../services/apiService';
import { useToast } from './ui/toast';
import { PAGINATION } from '../lib/config';

interface Conversation {
  id: number;
  id_str: string;
  user_id: number;
  title: string;
  description: string;
  status: 'active' | 'inactive' | 'archived';
  last_active: string;
  created_at: string;
  updated_at: string;
}

interface ConversationListProps {
  isOpen: boolean;
  onClose: () => void;
  onSelectConversation: (conversationId: string) => void;
  currentConversationId: string | null;
  userId: number;
  refreshKey?: number;
}

export function ConversationList({ 
  isOpen, 
  onClose, 
  onSelectConversation, 
  currentConversationId,
  userId,
  refreshKey
}: ConversationListProps) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [page, setPage] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const { error: showError } = useToast();

  const ITEMS_PER_PAGE = PAGINATION.DEFAULT_PAGE_SIZE;

  // 获取会话列表
  const fetchConversations = async (reset: boolean = false) => {
    if (loading) return;
    
    setLoading(true);
    setError(null);
    
    try {
      const offset = reset ? 0 : page * ITEMS_PER_PAGE;
      const response = await conversationAPI.getConversations(userId.toString(), ITEMS_PER_PAGE, offset);
      
      if (reset) {
        setConversations(response.data || []);
        setPage(0);
      } else {
        setConversations(prev => [...prev, ...(response.data || [])]);
      }
      
      // 检查是否还有更多数据 - 如果返回的数据量小于请求的数量，说明没有更多了
      const hasMoreData = (response.data || []).length >= ITEMS_PER_PAGE;
      setHasMore(hasMoreData);
      setPage(prev => prev + 1);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '获取会话列表失败';
      setError(errorMessage);
      showError('获取会话列表失败', errorMessage);
    } finally {
      setLoading(false);
    }
  };

  // 初始加载和根据refreshKey刷新
  useEffect(() => {
    if (isOpen) {
      console.log('会话列表刷新，原因: key 变更或初始加载');
      fetchConversations(true);
    }
  }, [isOpen, userId, refreshKey]);

  // 加载更多
  const loadMore = () => {
    if (!loading && hasMore) {
      fetchConversations(false);
    }
  };

  // 滚动到底部检测
  const handleScroll = (e: React.UIEvent<HTMLDivElement>) => {
    const { scrollTop, scrollHeight, clientHeight } = e.currentTarget;
    if (scrollHeight - scrollTop <= clientHeight + 100) {
      loadMore();
    }
  };

  // 创建新会话
  const createNewConversation = () => {
    onSelectConversation('new');
    onClose();
  };

  // 格式化时间
  const formatTime = (timeString: string) => {
    const date = new Date(timeString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) {
      return date.toLocaleTimeString('zh-CN', { 
        hour: '2-digit', 
        minute: '2-digit' 
      });
    } else if (diffDays === 1) {
      return '昨天';
    } else if (diffDays < 7) {
      return `${diffDays}天前`;
    } else {
      return date.toLocaleDateString('zh-CN', { 
        month: '2-digit', 
        day: '2-digit' 
      });
    }
  };

  // 获取状态颜色
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'active':
        return 'bg-green-100 text-green-800';
      case 'inactive':
        return 'bg-gray-100 text-gray-800';
      case 'archived':
        return 'bg-yellow-100 text-yellow-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  if (!isOpen) return null;

  return (
    <div className="absolute inset-0 z-50 bg-black/30 backdrop-blur-sm flex items-start justify-end">
      <div className="bg-white/95 backdrop-blur-glass w-80 h-full shadow-xl flex flex-col border-l border-border/30 animate-slide-in-right">
        {/* Header */}
        <div className="h-12 bg-gradient-to-r from-primary to-blue-600 text-white px-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4.5 w-4.5" />
            <h2 className="font-heading font-semibold text-sm">会话列表</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/20 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* New Conversation Button */}
        <div className="p-4 border-b border-gray-200">
          <button
            onClick={createNewConversation}
            className="w-full flex items-center gap-2 px-4 py-2.5 bg-primary/5 hover:bg-primary/10 text-primary rounded-xl transition-all border border-primary/10 hover:border-primary/20 font-medium text-sm"
          >
            <Plus className="h-4 w-4" />
            新建会话
          </button>
        </div>

        {/* Conversation List */}
        <div 
          ref={listRef}
          className="flex-1 overflow-y-auto"
          onScroll={handleScroll}
        >
          {error && (
            <div className="p-4 bg-red-50 border-l-4 border-red-400 text-red-700">
              {error}
            </div>
          )}

          {conversations.map((conversation) => (
            <div
              key={conversation.id_str}
              onClick={() => {
                onSelectConversation(conversation.id_str);
                onClose();
              }}
              className={`p-4 border-b border-border/30 cursor-pointer hover:bg-muted/50 transition-all ${
                currentConversationId === conversation.id_str ? 'bg-primary/5 border-l-[3px] border-l-primary' : 'hover:shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="font-medium text-gray-900 truncate">
                      {conversation.title}
                    </h3>
                    <span className={`px-2 py-1 text-xs rounded-full ${getStatusColor(conversation.status)}`}>
                      {conversation.status === 'active' ? '活跃' : 
                       conversation.status === 'inactive' ? '休眠' : '归档'}
                    </span>
                  </div>
                  <p className="text-sm text-gray-500 truncate">
                    {conversation.description}
                  </p>
                  <div className="flex items-center gap-2 mt-2 text-xs text-gray-400">
                    <Clock className="h-3 w-3" />
                    {formatTime(conversation.last_active)}
                  </div>
                </div>
              </div>
            </div>
          ))}

          {loading && (
            <div className="p-4 flex items-center justify-center text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="ml-2 text-sm">加载中...</span>
            </div>
          )}

          {!hasMore && conversations.length > 0 && (
            <div className="p-4 text-center text-muted-foreground text-xs">
              — 已显示全部 —
            </div>
          )}

          {conversations.length === 0 && !loading && !error && (
            <div className="p-8 text-center text-muted-foreground">
              <MessageSquare className="h-10 w-10 mx-auto mb-3 text-muted-foreground/30" />
              <p className="text-sm">暂无会话</p>
              <p className="text-xs mt-1">点击上方按钮开始对话</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
} 