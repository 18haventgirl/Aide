import React, { useEffect, useState, useCallback, useRef } from "react";
import { useAppDispatch, useAppSelector } from "../store/hooks";
import { logout } from "../store/slices/authSlice";
import { AgentPanel } from "../components/agent-panel";
import { Chat } from "../components/Chat";
import { PersonDataPanel } from "../components/person-data-panel";
import { MedicalRecordParser } from "../components/medical-record-parser";
import ErrorBoundary from "../components/ErrorBoundary";
import type { Agent, AgentEvent, GuardrailCheck, Message } from "../lib/types";
import { createWebSocketService, getWebSocketService, type WebSocketConnectionStatus } from "../lib/websocket";
import {
  Bot, MessageCircle, Wifi, WifiOff, RefreshCw, AlertTriangle, LogOut, User,
  ScanLine, ChevronRight
} from "lucide-react";
import { Button } from "../components/ui/button";
import { AppLogo } from "../components/app-logo";

/* ================================================================
   Session Persistence Helpers
   ================================================================ */
const STORAGE_KEY = 'current_conversation_id';

const saveConversationId = (id: string | null) => {
  try {
    if (id) localStorage.setItem(STORAGE_KEY, id);
    else localStorage.removeItem(STORAGE_KEY);
  } catch { /* noop */ }
};

const restoreConversationId = (): string | null => {
  try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
};

const clearPersistedSession = () => {
  try { localStorage.removeItem(STORAGE_KEY); } catch { /* noop */ }
};

const parseMessageMetadata = (raw: unknown): Record<string, any> => {
  try {
    if (typeof raw === 'string') return JSON.parse(raw) || {};
    return raw && typeof raw === 'object' ? raw as Record<string, any> : {};
  } catch { return {}; }
};

/* ================================================================
   Dashboard Component
   ================================================================ */
const Dashboard: React.FC = () => {
  const dispatch = useAppDispatch();
  const { user, token } = useAppSelector((s) => s.auth);

  /* ---- UI state ---- */
  const [workspace, setWorkspace] = useState<'chat' | 'medical-parser' | 'personal' | 'agents'>('chat');
  const [parserOpened, setParserOpened] = useState(false);
  const [healthRevision, setHealthRevision] = useState(0);

  /* ---- Data state ---- */
  const [messages, setMessages] = useState<Message[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [currentAgent, setCurrentAgent] = useState("");
  const [guardrails, setGuardrails] = useState<GuardrailCheck[]>([]);
  const [context, setContext] = useState<Record<string, any>>({});
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationListKey, setConversationListKey] = useState(0);

  /* ---- Connection state ---- */
  const [wsStatus, setWsStatus] = useState<WebSocketConnectionStatus>('disconnected');
  const [wsError, setWsError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isRestoring, setIsRestoring] = useState(false);
  const [streamingResponse, setStreamingResponse] = useState("");
  const conversationIdRef = useRef<string | null>(null);

  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  /* ---- Restore session on mount ---- */
  useEffect(() => {
    if (!user || !token) return;
    const saved = restoreConversationId();
    if (saved) {
      setConversationId(saved);
      loadHistory(saved);
    }
  }, [user, token]);

  const loadHistory = async (cid: string) => {
    setIsRestoring(true);
    try {
      const { messageAPI } = await import('../services/apiService');
      const res = await messageAPI.getMessages(cid, 50, 0);
      if (res.success && res.data) {
        const msgs: Message[] = res.data
          .map((m: any) => ({
            id: m.id.toString(),
            content: m.content,
            type: (m.sender_type === 'human' ? 'user' : 'ai') as Message['type'],
            agent: m.sender_type === 'human' ? 'user' : (m.sender_id || 'ai'),
            timestamp: new Date(m.created_at || Date.now()),
            metadata: parseMessageMetadata(m.extra_data),
          }))
          .sort((a: Message, b: Message) => a.timestamp.getTime() - b.timestamp.getTime());
        setMessages(msgs);
      } else {
        saveConversationId(null);
        setConversationId(null);
      }
    } catch {
      saveConversationId(null);
      setConversationId(null);
    } finally {
      setIsRestoring(false);
    }
  };

  /* ---- WebSocket ---- */
  useEffect(() => {
    if (!user || !token) { setWsStatus('disconnected'); return; }

    const uid = String(user.user_id);
    const ws = createWebSocketService(uid, user.username, undefined, token);
    if (!ws) { setWsStatus('error'); return; }

    if (conversationIdRef.current) ws.setConversationId(conversationIdRef.current);

    const onStatus = (s: WebSocketConnectionStatus) => { setWsStatus(s); if (s === 'connected') setWsError(''); };
    const onError = (c: any) => { setWsStatus('error'); setWsError(c?.error || '连接失败'); setIsLoading(false); setStreamingResponse(''); };
    const onSwitched = (c: any) => {
      const nid = c.conversation_id;
      if (nid) { setConversationId(nid); saveConversationId(nid); }
    };

    const onStream = (content: any) => {
      if (!content || typeof content !== 'object') return;
      if (content.type === 'completion' || content.is_finished) {
        setStreamingResponse('');
        setIsLoading(false);
        if (content.current_agent) setCurrentAgent(content.current_agent);
        if (content.final_response) processResponse(content.final_response);
        else processResponse(content);
        return;
      }
      if (content.is_error) {
        setMessages(prev => [...prev, {
          id: `err-${Date.now()}`, content: `系统异常: ${content.error_message}`,
          type: 'ai', agent: content.current_agent || 'System', timestamp: new Date(),
        }]);
        setStreamingResponse(''); setIsLoading(false); return;
      }
      if (content.raw_response) setStreamingResponse(content.raw_response);
      if (content.conversation_id && !conversationIdRef.current) {
        conversationIdRef.current = content.conversation_id;
        setConversationId(content.conversation_id);
        ws?.setConversationId(content.conversation_id);
        saveConversationId(content.conversation_id);
        setConversationListKey(k => k + 1);
      }
      if (content.current_agent) setCurrentAgent(content.current_agent);
      if (content.events) setEvents(content.events);
      if (content.agents) setAgents(content.agents);
      if (content.guardrails) setGuardrails(content.guardrails);
      if (content.context) setContext(content.context);
    };

    const processResponse = (r: any) => {
      if (!r) return;
      if (r.conversation_id && !conversationIdRef.current) {
        conversationIdRef.current = r.conversation_id;
        setConversationId(r.conversation_id);
        ws?.setConversationId(r.conversation_id);
        saveConversationId(r.conversation_id);
        setConversationListKey(k => k + 1);
      }
      if (r.current_agent) setCurrentAgent(r.current_agent);
      if (r.is_error) {
        setMessages(prev => [...prev, {
          id: `err-${Date.now()}`, content: `系统异常: ${r.error_message}`,
          type: 'ai', agent: r.current_agent || 'System', timestamp: new Date(),
        }]);
        setIsLoading(false); setStreamingResponse(''); return;
      }
      if (r.messages && Array.isArray(r.messages)) {
        const newMsgs: Message[] = r.messages.map((m: any) => ({
          id: `${Date.now()}-${Math.random()}`,
          content: m.content, type: m.agent === 'user' ? 'user' : 'ai',
          agent: m.agent, timestamp: new Date(),
          metadata: (Array.isArray(r.citations) && r.citations.length > 0) || r.knowledge_status
            ? { citations: r.citations || [], knowledge_status: r.knowledge_status }
            : {},
        }));
        setMessages(prev => {
          const last = prev[prev.length - 1];
          const aiMsgs = newMsgs.filter((m: Message) => m.type === 'ai');
          if (aiMsgs.length && last?.type === 'user') return [...prev, ...aiMsgs];
          return newMsgs;
        });
      }
      if (r.events) setEvents(r.events);
      if (r.agents) setAgents(r.agents);
      if (r.guardrails) setGuardrails(r.guardrails);
      if (r.context) setContext(r.context);
    };

    ws.on('status', onStatus);
    ws.on('connected', () => { setWsStatus('connected'); setWsError(''); });
    ws.on('error', onError);
    ws.on('auth_error', onError);
    ws.on('ai_error', onError);
    ws.on('ai_response', onStream);
    ws.on('ai_thinking', onStream);
    ws.on('ai_finished', onStream);
    const onChatResponse = (r: any) => processResponse(r);
    ws.on('chat_response', onChatResponse);
    ws.on('conversation_switched', onSwitched);

    ws.connect().catch(() => { setWsStatus('error'); });

    return () => {
      ws.off('status', onStatus);
      ws.off('error', onError);
      ws.off('auth_error', onError);
      ws.off('ai_error', onError);
      ws.off('ai_response', onStream);
      ws.off('ai_thinking', onStream);
      ws.off('ai_finished', onStream);
      ws.off('chat_response', onChatResponse);
      ws.off('conversation_switched', onSwitched);
      ws.disconnect();
    };
  }, [user, token]);

  /* ---- Actions ---- */
  const handleSelectConversation = useCallback(async (cid: string) => {
    const ws = getWebSocketService();
    if (cid === 'new') {
      conversationIdRef.current = null;
      setConversationId(null); setMessages([]); setEvents([]);
      setGuardrails([]); setContext({}); setCurrentAgent("");
      setIsLoading(false); setStreamingResponse('');
      ws?.setConversationId(null);
      saveConversationId(null);
      return;
    }
    conversationIdRef.current = cid;
    setConversationId(cid);
    saveConversationId(cid);
    if (ws?.status === 'connected') ws.switchConversation(cid);
    else ws?.setConversationId(cid);
    setMessages([]); setIsLoading(true);
    try {
      const { messageAPI } = await import('../services/apiService');
      const res = await messageAPI.getMessages(cid, 50, 0);
      if (res.success && res.data) {
        setMessages(res.data
          .map((m: any) => ({
            id: m.id.toString(), content: m.content,
            type: (m.sender_type === 'human' ? 'user' : 'ai') as Message['type'],
            agent: m.sender_type === 'human' ? 'user' : (m.sender_id || 'ai'),
            timestamp: new Date(m.created_at || Date.now()),
            metadata: parseMessageMetadata(m.extra_data),
          }))
          .sort((a: Message, b: Message) => a.timestamp.getTime() - b.timestamp.getTime()));
      }
    } catch { /* noop */ }
    setIsLoading(false);
  }, []);

  const handleSendMessage = useCallback(async (content: string, mode: 'general' | 'medical' = 'general') => {
    if (!content.trim() || isLoading) return;
    setIsLoading(true); setStreamingResponse('');
    setMessages(prev => [...prev, {
      id: `user-${Date.now()}`, content: content.trim(),
      type: 'user', agent: 'user', timestamp: new Date(),
    }]);
    const ws = getWebSocketService();
    ws?.sendChatMessage(content.trim(), mode);
  }, [isLoading]);

  const handleLogout = () => {
    clearPersistedSession();
    dispatch(logout());
  };

  /* ---- Status helpers ---- */
  const statusConfig = {
    connected:    { icon: <Wifi className="w-4 h-4" />, text: '已连接', color: 'text-success' },
    connecting:   { icon: <RefreshCw className="w-4 h-4 animate-spin" />, text: '连接中', color: 'text-warning' },
    error:        { icon: <AlertTriangle className="w-4 h-4" />, text: '异常', color: 'text-destructive' },
    disconnected: { icon: <WifiOff className="w-4 h-4" />, text: '断开', color: 'text-muted-foreground' },
  }[wsStatus];

  const navigation = [
    { id: 'chat', label: '智能对话', icon: MessageCircle, description: '你的日常助手' },
    { id: 'medical-parser', label: '病历解析', icon: ScanLine, description: '整理就诊信息' },
    { id: 'personal', label: '个人数据', icon: User, description: '笔记、待办与健康' },
    { id: 'agents', label: '智能体', icon: Bot, description: '查看协作过程' },
  ] as const;
  const selectWorkspace = (next: typeof workspace) => {
    if (next === 'medical-parser') setParserOpened(true);
    setWorkspace(next);
  };
  const activeNavigation = navigation.find(item => item.id === workspace)!;

  return (
    <ErrorBoundary>
      <div className="app-shell flex overflow-hidden bg-background">
        <aside className="hidden w-[216px] shrink-0 flex-col bg-[#141e30] text-white md:flex">
          <div className="px-6 pb-9 pt-7"><AppLogo /></div>
          <p className="px-6 pb-3 text-[10px] font-medium tracking-[0.2em] text-slate-500">工作空间</p>
          <nav aria-label="主导航" className="space-y-1.5 px-3">
            {navigation.map(({ id, label, icon: Icon }) => <button key={id}
              onClick={() => selectWorkspace(id)} aria-current={workspace === id ? 'page' : undefined}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left text-sm transition-colors ${workspace === id ? 'bg-primary text-white' : 'text-slate-400 hover:bg-white/5 hover:text-white'}`}>
              <Icon className="h-[18px] w-[18px]" /><span>{label}</span>
              {workspace === id && <ChevronRight className="ml-auto h-3.5 w-3.5 opacity-70" />}
            </button>)}
          </nav>
          <div className="mt-auto px-5 pb-5">
            <div className="mb-5 rounded-xl border border-white/10 p-4">
              <p className="flex items-center gap-2 text-xs font-medium text-slate-300"><ScanLine className="h-4 w-4 text-blue-400" />从原文到清晰记录</p>
              <p className="mt-2 text-xs leading-6 text-slate-500">上传、核对、保存。让每一次就诊都有迹可循。</p>
            </div>
            <div className="flex items-center gap-3 border-t border-white/10 pt-5">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-white/10 text-sm text-slate-200">{user?.username?.slice(0, 1).toUpperCase() || 'A'}</span>
              <div className="min-w-0 flex-1"><p className="truncate text-sm text-slate-200">{user?.username}</p><p className="mt-0.5 text-[11px] text-slate-500">个人工作空间</p></div>
              <Button variant="ghost" size="icon" onClick={handleLogout} aria-label="退出登录" className="h-8 w-8 text-slate-400 hover:bg-white/10 hover:text-white"><LogOut className="h-4 w-4" /></Button>
            </div>
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 shrink-0 items-center justify-between border-b border-border bg-card px-4 sm:px-8">
            <div className="flex min-w-0 items-center gap-3">
              <div className="md:hidden"><AppLogo compact /></div>
              <span className="hidden text-xs text-muted-foreground md:inline">工作空间</span>
              <ChevronRight className="hidden h-3.5 w-3.5 text-slate-300 md:block" />
              <span className="text-sm font-medium">{activeNavigation.label}</span>
            </div>
            <div className="flex items-center gap-3">
              <span title={wsError || `聊天服务${statusConfig.text}`} className={`inline-flex items-center gap-1.5 text-xs ${statusConfig.color}`}>
                {statusConfig.icon}<span className="hidden sm:inline">聊天服务 · {statusConfig.text}</span>
              </span>
              <Button variant="ghost" size="icon" onClick={handleLogout} aria-label="退出登录" className="h-8 w-8 text-muted-foreground md:hidden"><LogOut className="h-4 w-4" /></Button>
            </div>
          </header>

          <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className={`${workspace === 'chat' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}>
              <Chat messages={messages} onSendMessage={handleSendMessage} isLoading={isLoading || isRestoring}
                streamingResponse={streamingResponse} wsStatus={wsStatus} conversationId={conversationId}
                onSelectConversation={handleSelectConversation} conversationListKey={conversationListKey} />
            </div>
            {parserOpened && <div className={`${workspace === 'medical-parser' ? 'flex' : 'hidden'} min-h-0 flex-1 flex-col`}>
              <MedicalRecordParser key={user?.user_id} onSaved={() => setHealthRevision(value => value + 1)} />
            </div>}
            {workspace === 'personal' && <PersonDataPanel key={healthRevision} userId={parseInt(user?.user_id || '1')} />}
            {workspace === 'agents' && <AgentPanel agents={agents} currentAgent={currentAgent} events={events} guardrails={guardrails} context={context} />}
          </main>

          <nav aria-label="移动端主导航" className="safe-bottom grid shrink-0 grid-cols-4 border-t border-border bg-card md:hidden">
            {navigation.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => selectWorkspace(id)}
              aria-current={workspace === id ? 'page' : undefined}
              className={`flex min-h-16 flex-col items-center justify-center gap-1 rounded-none text-[11px] ${workspace === id ? 'text-primary' : 'text-muted-foreground'}`}>
              <span className={`rounded-lg px-4 py-1 ${workspace === id ? 'bg-primary/10' : ''}`}><Icon className="h-[18px] w-[18px]" /></span>{label}
            </button>)}
          </nav>
        </div>
      </div>
    </ErrorBoundary>
  );
};

export default Dashboard;
