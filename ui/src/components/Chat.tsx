import React, { useState, useRef, useEffect, useCallback } from "react";
import type { Message } from "../lib/types";
import { ChatMarkdown } from "./ChatMarkdown";
import type { WebSocketConnectionStatus } from "../lib/websocket";
import { WifiOff, Send, History, Loader2, Bot, FileText, CheckSquare, MessageCircle, ArrowUpRight, User as UserIcon } from "lucide-react";
import { WorkspaceHeader } from './workspace-header';
import { Button } from './ui/button';
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
    if (!inputText.trim() || wsStatus !== 'connected' || isLoading || isSending) return;
    setIsSending(true);
    try {
      await onSendMessage(inputText);
      setInputText("");
    } catch { /* noop */ }
    setIsSending(false);
  }, [inputText, onSendMessage, wsStatus, isLoading, isSending]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !isComposing) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend, isComposing]);

  const connected = wsStatus === 'connected';

  return (
    <div className="relative flex h-full min-h-0 flex-col">
      <WorkspaceHeader title="智能对话" description="从一个问题、一条灵感，或今天的计划开始。" actions={
        <Button variant="outline" size="sm" onClick={() => setShowConversationList(true)}><History className="h-4 w-4" />会话记录</Button>
      } />

      {/* Connection warning */}
      {!connected && (
        <div className="mx-5 mb-3 flex shrink-0 items-center gap-2 rounded-lg border border-amber-200/60 bg-amber-50 px-3 py-2 text-xs text-amber-800 sm:mx-8">
          <WifiOff className="w-3.5 h-3.5" />
          <span>{wsStatus === 'connecting' ? '连接中...' : '未连接，消息功能不可用'}</span>
        </div>
      )}

      {/* Messages */}
      <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin px-5 py-4 sm:px-8">
        {messages.length === 0 && !streamingResponse && (
          <div className="mx-auto flex min-h-full max-w-3xl flex-col items-center justify-center py-8 text-center">
            <span className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl border border-primary/10 bg-primary/5 text-primary"><Bot className="h-7 w-7" strokeWidth={1.5} /></span>
            <p className="mb-3 text-xs font-medium tracking-[0.15em] text-muted-foreground">AIDE · 你的日常助手</p>
            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">今天，有什么可以帮你？</h2>
            <p className="mt-3 max-w-md text-sm leading-7 text-muted-foreground">记录想法，安排日常，让零散的信息井井有条。</p>
            <div className="mt-8 grid w-full gap-3 text-left sm:grid-cols-3">
              {[
                { title: '整理待办', text: '帮我整理今天需要完成的事情', icon: CheckSquare },
                { title: '记录灵感', text: '帮我把接下来的想法整理成笔记', icon: FileText },
                { title: '聊聊近况', text: '我想记录一下最近的身体状况', icon: MessageCircle },
              ].map(({ title, text, icon: Icon }) => <button key={title} onClick={() => setInputText(text)} disabled={!connected} className="surface-card group p-4 text-left transition-colors hover:border-primary/30 disabled:opacity-60">
                <span className="flex items-center justify-between text-primary"><Icon className="h-5 w-5" strokeWidth={1.5} /><ArrowUpRight className="h-4 w-4 text-slate-300 group-hover:text-primary" /></span>
                <span className="mt-3 block text-sm font-medium">{title}</span><span className="mt-1 block text-xs leading-6 text-muted-foreground">{text}</span>
              </button>)}
            </div>
          </div>
        )}
        <div className="mx-auto max-w-4xl">

        {messages.map((msg, idx) => {
          if (msg.content === "DISPLAY_SEAT_MAP") return null;
          const isUser = msg.type === 'user';
          const isError = msg.content.startsWith('系统异常:');
          const citations = Array.isArray(msg.metadata?.citations) ? msg.metadata.citations : [];
          return (
            <div key={msg.id || idx} className={`flex mb-4 msg-enter ${isUser ? 'justify-end' : 'justify-start'}`} style={{ animationDelay: `${Math.min(idx * 30, 300)}ms` }}>
              {!isUser && (
                <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
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
                <div className="w-7 h-7 rounded-full bg-primary flex items-center justify-center flex-shrink-0 ml-2.5 mt-0.5">
                  <UserIcon className="w-4 h-4 text-white" />
                </div>
              )}
            </div>
          );
        })}

        {/* Streaming response */}
        {streamingResponse && (
          <div className="flex mb-4 justify-start animate-fade-in">
            <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
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
            <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 mr-2.5 mt-0.5">
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
      </div>

      {/* Input area */}
      <div className="shrink-0 px-5 pb-5 pt-3 sm:px-8">
        <div className="chat-input-container mx-auto max-w-4xl">
          <div className="flex items-end gap-1.5">
            <textarea
              aria-label="聊天消息"
              rows={2}
              placeholder={connected ? "输入消息，Enter 发送，Shift + Enter 换行" : "等待聊天服务连接…"}
              className={`min-w-0 flex-1 resize-none bg-transparent text-sm px-3 py-2.5 outline-none placeholder:text-muted-foreground/50 min-h-[44px] max-h-[120px] ${
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
              aria-label="发送消息"
              disabled={!connected || !inputText.trim() || isSending || isLoading}
              onClick={handleSend}
              className={`h-10 w-10 flex items-center justify-center rounded-xl transition-all duration-200 flex-shrink-0 ${
                connected && inputText.trim() && !isSending
                  ? 'bg-primary text-white hover:bg-primary/90'
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
