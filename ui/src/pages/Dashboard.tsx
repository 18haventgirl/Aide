import React, { useEffect, useState, useCallback } from "react";
import { useAppDispatch, useAppSelector } from "../store/hooks";
import { logout } from "../store/slices/authSlice";
import { AgentPanel } from "../components/agent-panel";
import { Chat } from "../components/Chat";
import { PersonDataPanel } from "../components/person-data-panel";
import ErrorBoundary from "../components/ErrorBoundary";
import type { Agent, AgentEvent, GuardrailCheck, Message } from "../lib/types";
import { createWebSocketService, getWebSocketService, type WebSocketConnectionStatus } from "../lib/websocket";
import {
  Bot, MessageCircle, Wifi, WifiOff, RefreshCw, AlertTriangle, LogOut, User,
  PanelLeftClose, PanelLeftOpen, ChevronLeft, Zap
} from "lucide-react";
import { Button } from "../components/ui/button";

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

/* ================================================================
   Dashboard Component
   ================================================================ */
const Dashboard: React.FC = () => {
  const dispatch = useAppDispatch();
  const { user, token } = useAppSelector((s) => s.auth);

  /* ---- UI state ---- */
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [sidebarTab, setSidebarTab] = useState<'agent' | 'person'>('agent');
  const [mobileTab, setMobileTab] = useState<'chat' | 'agent' | 'person'>('chat');

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

    if (conversationId) ws.setConversationId(conversationId);

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
      if (content.conversation_id && !conversationId) {
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
      if (r.conversation_id && !conversationId) {
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
    ws.on('chat_response', (r: any) => processResponse(r));
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
      ws.off('chat_response', (r: any) => processResponse(r));
      ws.off('conversation_switched', onSwitched);
    };
  }, [user, token]);

  /* ---- Actions ---- */
  const handleSelectConversation = useCallback(async (cid: string) => {
    const ws = getWebSocketService();
    if (cid === 'new') {
      setConversationId(null); setMessages([]); setEvents([]);
      setGuardrails([]); setContext({}); setCurrentAgent("");
      setIsLoading(false); setStreamingResponse('');
      ws?.setConversationId(null);
      saveConversationId(null);
      return;
    }
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
          }))
          .sort((a: Message, b: Message) => a.timestamp.getTime() - b.timestamp.getTime()));
      }
    } catch { /* noop */ }
    setIsLoading(false);
  }, []);

  const handleSendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isLoading) return;
    setIsLoading(true); setStreamingResponse('');
    setMessages(prev => [...prev, {
      id: `user-${Date.now()}`, content: content.trim(),
      type: 'user', agent: 'user', timestamp: new Date(),
    }]);
    const ws = getWebSocketService();
    ws?.sendChatMessage(content.trim());
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

  /* ================================================================
     RENDER
     ================================================================ */
  return (
    <ErrorBoundary>
      <div className="h-screen flex flex-col overflow-hidden relative" style={{ background: 'linear-gradient(135deg, #eef2ff 0%, #f8fafc 40%, #f0f4ff 70%, #fce7f3 100%)' }}>
        {/* ====== ANIMATED MESH GRADIENT BLOBS ====== */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none z-0">
          <div className="absolute rounded-full bg-blue-400/40 w-[900px] h-[900px] -top-[25%] -right-[15%] blur-[100px]" style={{ animation: 'drift 18s ease-in-out infinite' }} />
          <div className="absolute rounded-full bg-indigo-400/35 w-[700px] h-[700px] top-[25%] -left-[10%] blur-[90px]" style={{ animation: 'drift 22s ease-in-out infinite 3s' }} />
          <div className="absolute rounded-full bg-purple-400/30 w-[600px] h-[600px] -bottom-[15%] left-[25%] blur-[80px]" style={{ animation: 'drift 20s ease-in-out infinite 6s' }} />
          <div className="absolute rounded-full bg-amber-300/25 w-[500px] h-[500px] top-[40%] right-[10%] blur-[70px]" style={{ animation: 'drift 24s ease-in-out infinite 9s' }} />
          <div className="absolute rounded-full bg-cyan-300/25 w-[400px] h-[400px] top-[60%] left-[50%] blur-[60px]" style={{ animation: 'drift 19s ease-in-out infinite 12s' }} />
        </div>
        <style>{`
          @keyframes drift {
            0%, 100% { transform: translate(0, 0) scale(1); }
            25% { transform: translate(30px, -20px) scale(1.05); }
            50% { transform: translate(-20px, 25px) scale(0.95); }
            75% { transform: translate(-25px, -15px) scale(1.08); }
          }
        `}</style>

        {/* ====== TOP BAR ====== */}
        <header className="h-14 flex-shrink-0 bg-white/25 backdrop-blur-[30px] border-b border-white/30 z-10 px-4 flex items-center justify-between" style={{ WebkitBackdropFilter: 'blur(30px)' }}>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="p-2 rounded-lg hover:bg-muted transition-colors hidden md:flex"
              title={sidebarOpen ? '收起面板' : '展开面板'}
            >
              {sidebarOpen ? <PanelLeftClose className="w-4 h-4" /> : <PanelLeftOpen className="w-4 h-4" />}
            </button>
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-blue-600 flex items-center justify-center">
                <Zap className="w-4 h-4 text-white" />
              </div>
              <h1 className="text-base font-heading font-semibold text-foreground">Aide</h1>
            </div>
            <div className={`flex items-center gap-2 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig.color} bg-muted/50`}>
              {statusConfig.icon}
              <span className="hidden sm:inline">{statusConfig.text}</span>
              {wsError && <span className="text-destructive/80 truncate max-w-[120px]">{wsError}</span>}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground hidden sm:block">{user?.username}</span>
            <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center">
              <User className="w-4 h-4 text-primary" />
            </div>
            <Button variant="ghost" size="sm" onClick={handleLogout} className="text-muted-foreground hover:text-destructive hover:bg-destructive/10">
              <LogOut className="w-4 h-4" />
            </Button>
          </div>
        </header>

        {/* ====== MAIN CONTENT ====== */}
        <div className="flex-1 flex overflow-hidden">
          {/* Desktop: Sidebar */}
          <div className={`hidden md:flex flex-col transition-all duration-300 ease-in-out overflow-hidden ${sidebarOpen ? 'w-[340px] min-w-[340px] border-r border-border/30' : 'w-0 min-w-0'}`}>
            {sidebarOpen && (
              <div className="flex flex-col h-full">
                {/* Tab switcher */}
                <div className="flex border-b border-border/30 bg-muted/30">
                  {(['agent', 'person'] as const).map(t => (
                    <button
                      key={t}
                      onClick={() => setSidebarTab(t)}
                      className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                        sidebarTab === t
                          ? 'text-primary border-b-2 border-primary bg-white/50'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      {t === 'agent' ? '智能体' : '个人数据'}
                    </button>
                  ))}
                </div>
                <div className="flex-1 overflow-hidden">
                  {sidebarTab === 'agent' ? (
                    <AgentPanel agents={agents} currentAgent={currentAgent} events={events} guardrails={guardrails} context={context} />
                  ) : (
                    <PersonDataPanel userId={parseInt(user?.user_id || "1")} />
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Chat area */}
          <div className="flex-1 flex flex-col min-w-0">
            <Chat
              messages={messages}
              onSendMessage={handleSendMessage}
              isLoading={isLoading || isRestoring}
              streamingResponse={streamingResponse}
              wsStatus={wsStatus}
              conversationId={conversationId}
              onSelectConversation={handleSelectConversation}
              conversationListKey={conversationListKey}
            />
          </div>
        </div>

        {/* ====== MOBILE BOTTOM NAV ====== */}
        <div className="md:hidden flex-shrink-0 bg-white/40 backdrop-blur-[20px] border-t border-white/40 safe-bottom z-10" style={{ WebkitBackdropFilter: 'blur(30px)' }}>
          <div className="flex">
            {([
              ['agent', Bot, '智能体'],
              ['chat', MessageCircle, '聊天'],
              ['person', User, '数据'],
            ] as const).map(([tab, Icon, label]) => (
              <button
                key={tab}
                onClick={() => setMobileTab(tab)}
                className={`flex-1 py-2.5 flex flex-col items-center gap-0.5 text-xs font-medium transition-colors ${
                  mobileTab === tab ? 'text-primary' : 'text-muted-foreground'
                }`}
              >
                <Icon className="w-5 h-5" />
                <span>{label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Mobile: Sidebar overlay */}
        {mobileTab !== 'chat' && (
          <div className="md:hidden fixed inset-0 top-14 bottom-[72px] z-20 bg-background animate-fade-in">
            <div className="flex items-center gap-2 p-3 border-b border-border/30">
              <button onClick={() => setMobileTab('chat')} className="p-1.5 rounded-lg hover:bg-muted">
                <ChevronLeft className="w-5 h-5" />
              </button>
              <span className="font-medium text-sm">{mobileTab === 'agent' ? '智能体' : '个人数据'}</span>
            </div>
            <div className="flex-1 overflow-hidden">
              {mobileTab === 'agent' ? (
                <AgentPanel agents={agents} currentAgent={currentAgent} events={events} guardrails={guardrails} context={context} />
              ) : (
                <PersonDataPanel userId={parseInt(user?.user_id || "1")} />
              )}
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
};

export default Dashboard;