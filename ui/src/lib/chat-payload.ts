import { isRecord } from './api-errors';
import type { Agent, AgentEvent, GuardrailCheck, Message } from './types';
import type { StoredMessage } from './api-contracts';

export interface Citation {
  doc_id?: string;
  evidence_id?: string;
  title: string;
  url?: string;
  source_org?: string;
  status?: string;
  reviewed_at?: string;
}

export function readCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).filter(item => typeof item.title === 'string').map(item => ({
    title: item.title as string,
    ...Object.fromEntries(['doc_id', 'evidence_id', 'url', 'source_org', 'status', 'reviewed_at']
      .flatMap(key => typeof item[key] === 'string' ? [[key, item[key]]] : [])),
  }));
}

export function parseMessageMetadata(raw: unknown): Record<string, unknown> {
  try {
    const value: unknown = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return isRecord(value) ? value : {};
  } catch { return {}; }
}

function eventDate(value: unknown): Date {
  // Python emits Unix seconds; also accept existing millisecond/ISO histories.
  const date = typeof value === 'number' ? new Date(value < 1e12 ? value * 1000 : value)
    : typeof value === 'string' ? new Date(value) : new Date();
  return Number.isNaN(date.getTime()) ? new Date() : date;
}

const strings = (value: unknown): string[] => Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
const text = (value: unknown): string => typeof value === 'string' ? value : '';
const rows = (value: unknown): Record<string, unknown>[] => Array.isArray(value) ? value.filter(isRecord) : [];
const eventTypes: AgentEvent['type'][] = ['tool_call', 'handoff', 'context_update', 'error', 'message'];

export interface ChatResponse {
  conversation_id?: string;
  current_agent?: string;
  messages?: { content: string; agent: string }[];
  events?: AgentEvent[];
  agents?: Agent[];
  guardrails?: GuardrailCheck[];
  context?: Record<string, unknown>;
  citations?: Citation[];
  knowledge_status?: string;
  raw_response?: string;
  is_finished?: boolean;
  is_error?: boolean;
  error_message?: string;
  type?: string;
  final_response?: ChatResponse;
}

export function parseChatResponse(raw: unknown): ChatResponse {
  if (!isRecord(raw)) return {};
  const result: ChatResponse = {};
  for (const key of ['conversation_id', 'current_agent', 'knowledge_status', 'raw_response', 'error_message', 'type'] as const) {
    if (typeof raw[key] === 'string') result[key] = raw[key];
  }
  for (const key of ['is_finished', 'is_error'] as const) {
    if (typeof raw[key] === 'boolean') result[key] = raw[key];
  }
  if (Array.isArray(raw.messages)) result.messages = rows(raw.messages)
    .filter(item => typeof item.content === 'string')
    .map(item => ({ content: text(item.content), agent: text(item.agent) }));
  if (Array.isArray(raw.events)) result.events = rows(raw.events).map(item => ({
    id: text(item.id), type: eventTypes.includes(item.type as AgentEvent['type']) ? item.type as AgentEvent['type'] : 'message',
    content: text(item.content), agent: text(item.agent), timestamp: eventDate(item.timestamp),
    metadata: parseMessageMetadata(item.metadata),
  }));
  if (Array.isArray(raw.agents)) result.agents = rows(raw.agents).map(item => ({
    name: text(item.name), description: text(item.description), handoffs: strings(item.handoffs),
    tools: strings(item.tools), input_guardrails: strings(item.input_guardrails),
  }));
  if (Array.isArray(raw.guardrails)) result.guardrails = rows(raw.guardrails).map(item => ({
    id: text(item.id), name: text(item.name), input: text(item.input), reasoning: text(item.reasoning),
    passed: item.passed === true, timestamp: eventDate(item.timestamp),
  }));
  if (isRecord(raw.context)) result.context = raw.context;
  if (Array.isArray(raw.citations)) result.citations = readCitations(raw.citations);
  if (isRecord(raw.final_response)) {
    // Completion envelopes contain one response; do not recurse into untrusted nested envelopes.
    const { final_response, ...response } = raw.final_response;
    void final_response;
    result.final_response = parseChatResponse(response);
  }
  return result;
}

export function historyMessages(rows: StoredMessage[]): Message[] {
  return rows.map((row): Message => ({
    id: String(row.id), content: row.content,
    type: row.sender_type === 'human' ? 'user' : 'ai',
    agent: row.sender_type === 'human' ? 'user' : row.sender_id || 'ai',
    timestamp: eventDate(row.created_at), metadata: parseMessageMetadata(row.extra_data),
  })).sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
}
