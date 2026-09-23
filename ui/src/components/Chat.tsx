import React, { useState, useRef, useEffect, useCallback } from "react";
import type { Message } from "../lib/types";
import { ChatMarkdown } from "./ChatMarkdown";
import type { WebSocketConnectionStatus } from "../lib/websocket";
import { WifiOff, Send, Menu, Loader2, Bot, User as UserIcon } from "lucide-react";
import { ConversationList } from "./ConversationList";
import { useAppSelector } from "../store/hooks";

interface ChatProps {
  messages: Message[];
  onSendMessage: (message: string) => void;
  isLoading?: boolean;
  streamingResponse?: string;
  wsStatus?: WebSocketConnectionStatus;
  conversationId?: string | null;
  onSelectConversation?: (conversationId: string) => void;
  conversationListKey?: number;
}

export function Chat({
  messages, onSendMessage, isLoading, streamingResponse,
  wsStatus = 'disconnected', conversationId, onSelectConversation, conversationListKey,
}: ChatProps) {
  const { user } = useAppSelector(s => s.auth);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [inputText, setInputText] = useState("");
  const [isComposing, setIsComposing] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [showConversationList, setShowConversationList] = useState(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "instant" });
  }, [messages, streamingResponse]);

  const handleSend = useCallback(async () => {
    if (!inputText.trim() || wsStatus !== 'connected') return;
    setIsSending(true);
    try {
      await onSendMessage(inputText);
      setInputText("");
    } catch { /* noop */ }
    setIsSending(false);
  }, [inputText, onSendMessage, wsStatus]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !isComposing) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend, isComposing]);

  const connected = wsStatus === 'connected';

  return (
    <div className="flex flex-col h-full bg-transparent relative">
      {/* Header */}
      <div className="h-12 flex-shrink-0 bg-white/25 backdrop-blur-[30px] border-b border-white/40 px-4 flex items-center justify-between" style={{ WebkitBackdropFilter: 'blur(30px)' }}>
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center">
            <Bot className="w-3.5 h-3.5 text-white" />
          </div>
          <h2 className="font-heading font-semibold text-sm">Assistant</h2>
        </div>
        <button
          onClick={() => setShowConversationList(true)}
          className="p-1.5 rounded-lg hover:bg-muted transition-colors"
          title="会话列表"
        >
          <Menu className="w-4 h-4 text-muted-foreground" />
        </button>
      </div>

      {/* Connection warning */}
      {!connected && (
        <div className="flex-shrink-0 bg-warning/10 border-b border-warning/20 px-4 py-2 flex items-center gap-2 text-sm text-warning/90">
          <WifiOff className="w-3.5 h-3.5" />
          <span>{wsStatus === 'connecting' ? '连接中...' : '未连接，消息功能不可用'}</span>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 py-4 bg-transparent">
        {messages.length === 0 && !streamingResponse && (
          <div className="h-full flex flex-col items-center justify-center text-center px-8">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-blue-100 flex items-center justify-center mb-4">
              <Bot className="w-8 h-8 text-primary" />
            </div>
            <h3 className="font-heading font-semibold text-foreground mb-1">开始对话</h3>
            <p className="text-sm text-muted-foreground max-w-xs">输入消息与 AI 助手交流，我会帮你管理待办、笔记和更多</p>
          </div>
        )}

        {messages.map((msg, idx) => {
          if (msg.content === "DISPLAY_SEAT_MAP") return null;
          const isUser = msg.type === 'user';
          const isError = msg.content.startsWith('系统异常:');
          const citations = Array.isArray(msg.metadata?.citations) ? msg.metadata.citations : [];
          return (
            <div key={msg.id || idx} className={`flex mb-4 msg-enter ${isUser ? 'justify-end' : 'justify-start'}`} style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}>
              {!isUser && (
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary/15 to-blue-100 flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
                  <Bot className="w-4 h-4 text-primary" />
                </div>
              )}
              <div className={`min-w-0 ${isUser ? 'max-w-[78%]' : 'max-w-[94%] sm:max-w-[85%]'} overflow-hidden px-4 py-2.5 text-sm leading-relaxed break-words ${
                isUser
                  ? 'msg-user'
                  : isError ? 'msg-error' : 'msg-ai'
              }`}>
                <ChatMarkdown content={msg.content} />
                {!isUser && citations.length > 0 && (
                  <div className="mt-3 border-t border-blue-100 pt-2 space-y-1.5">
                    <p className="text-xs font-semibold text-slate-600">资料来源</p>
                    {citations.map((source: any, sourceIndex: number) => {
                      const url = typeof source.url === 'string' && /^https?:\/\//i.test(source.url)
                        ? source.url : null;
                      return (
                        <div key={`${source.doc_id}-${sourceIndex}`} className="rounded-lg border border-blue-100 bg-blue-50/70 px-2.5 py-2 text-xs">
                          {url ? (
                            <a href={url} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-700 underline underline-offset-2 hover:text-blue-900">
                              [{source.evidence_id || sourceIndex + 1}] {source.title}
                            </a>
                          ) : <span>{source.title}</span>}
                          <p className="mt-0.5 text-slate-500">{source.source_org}{source.status === 'clinician_reviewed' ? ` · 医疗复核 ${source.reviewed_at || ''}` : ' · 原文核对，本机研究'}</p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
              {isUser && (
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center flex-shrink-0 ml-2.5 mt-0.5">
                  <UserIcon className="w-4 h-4 text-white" />
                </div>
              )}
            </div>
          );
        })}

        {/* Streaming response */}
        {streamingResponse && (
          <div className="flex mb-4 justify-start animate-fade-in">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary/15 to-blue-100 flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
              <Bot className="w-4 h-4 text-primary" />
            </div>
            <div className="min-w-0 max-w-[94%] sm:max-w-[85%] overflow-hidden px-4 py-2.5 msg-streaming text-sm leading-relaxed break-words">
              <div className="flex items-center gap-2 mb-2 text-xs text-primary/70 font-medium">
                <div className="flex gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse-dot" />
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse-dot" style={{ animationDelay: '0.2s' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse-dot" style={{ animationDelay: '0.4s' }} />
                </div>
                正在回复...
              </div>
              <ChatMarkdown content={streamingResponse} />
              <span className="inline-block w-1.5 h-4 bg-primary/60 ml-0.5 animate-pulse rounded-sm align-text-bottom" />
            </div>
          </div>
        )}

        {/* Loading skeleton */}
        {isLoading && !streamingResponse && (
          <div className="flex mb-4 justify-start animate-fade-in">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary/15 to-blue-100 flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
              <Bot className="w-4 h-4 text-primary" />
            </div>
            <div className="max-w-[78%] px-5 py-3 msg-ai">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 animate-spin text-primary" />
                正在处理...
              </div>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="flex-shrink-0 p-3 bg-transparent">
        <div className={`transition-all duration-200 ${connected ? 'bg-white/75 backdrop-blur-[20px] rounded-2xl shadow-lg p-1' : 'bg-muted/50 rounded-2xl p-1'}`} style={connected ? { WebkitBackdropFilter: 'blur(30px)', border: '1px solid rgba(37,99,235,0.15)' } : {}}>
          <div className="flex items-end gap-1.5">
            <textarea
              rows={1}
              placeholder={connected ? "输入消息... (Enter 发送)" : "未连接"}
              className={`flex-1 resize-none bg-transparent text-sm px-3 py-2.5 outline-none placeholder:text-muted-foreground/50 min-h-[44px] max-h-[120px] ${
                !connected && 'text-muted-foreground/50'
              }`}
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              onCompositionStart={() => setIsComposing(true)}
              onCompositionEnd={() => setIsComposing(false)}
              disabled={!connected}
            />
            <button
              disabled={!connected || !inputText.trim() || isSending}
              onClick={handleSend}
              className={`h-10 w-10 flex items-center justify-center rounded-xl transition-all duration-200 flex-shrink-0 ${
                connected && inputText.trim() && !isSending
                  ? 'bg-gradient-to-r from-primary to-blue-600 text-white shadow-md shadow-primary/20 hover:shadow-lg hover:scale-105'
                  : 'bg-muted text-muted-foreground cursor-not-allowed'
              }`}
            >
              {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>

      {/* Conversation List Drawer */}
      <ConversationList
        isOpen={showConversationList}
        onClose={() => setShowConversationList(false)}
        onSelectConversation={(id) => { onSelectConversation?.(id); setShowConversationList(false); }}
        currentConversationId={conversationId || null}
        userId={user?.user_id ? parseInt(String(user.user_id)) : 1}
        refreshKey={conversationListKey}
      />
    </div>
  );
}
