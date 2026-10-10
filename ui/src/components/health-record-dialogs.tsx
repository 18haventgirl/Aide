import { useEffect, useRef, useState } from 'react';
import { History, X } from 'lucide-react';
import { Button } from './ui/button';
import { ApiRequestError, healthRecordAPI } from '../services/apiService';
import type { HealthRecord, HealthRecordChange, HealthRecordCreateRequest, HealthRecordType } from '../lib/types';
import { createSaveAttempt, healthDetailLabels, healthEditableFields, healthTime, healthTypeLabels, healthValue, historyChanges } from '../lib/health-records';
import type { HealthSaveAttempt } from '../lib/health-records';

const cancelled = (error: unknown) => (error as { code?: string })?.code === 'ERR_CANCELED';
const message = (error: unknown) => error instanceof Error ? error.message : '操作失败，请重试';

function useModal(close: () => void, busy = false) {
  const root = useRef<HTMLDivElement>(null);
  const state = useRef({ close, busy });
  state.current = { close, busy };
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    root.current?.querySelector<HTMLElement>('button')?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !state.current.busy) { event.preventDefault(); state.current.close(); }
      if (event.key === 'Tab') {
        const controls = [...(root.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input,select,textarea,a[href]') || [])].filter(el => el.offsetParent !== null);
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); if (previous?.isConnected) previous.focus(); };
  }, []);
  return root;
}

interface DetailProps { userId: number; recordId: number; onClose: () => void; onEdit: (record: HealthRecord) => void; onChanged: () => void }
export function HealthRecordDetailDialog({ userId, recordId, onClose, onEdit, onChanged }: DetailProps) {
  const [record, setRecord] = useState<HealthRecord | null>(null);
  const [history, setHistory] = useState<HealthRecordChange[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [retry, setRetry] = useState(0);
  const [deleting, setDeleting] = useState(false);
  const root = useModal(onClose, deleting);
  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setLoading(true); setHistoryLoading(true); setRecord(null); setError(null); setHistoryError(null);
    void healthRecordAPI.getRecord(String(userId), String(recordId), controller.signal).then(response => {
      if (!response.success || !response.data) throw new Error(response.message || '记录已不存在');
      if (active) setRecord(response.data);
    }).catch(err => { if (active && !cancelled(err)) setError(message(err)); }).finally(() => { if (active) setLoading(false); });
    void healthRecordAPI.getHistory(String(userId), String(recordId), controller.signal).then(response => {
      if (!response.success || !Array.isArray(response.data?.history)) throw new Error(response.message || '加载更正历史失败');
      if (active) setHistory(response.data.history);
    }).catch(err => { if (active && !cancelled(err)) setHistoryError(message(err)); }).finally(() => { if (active) setHistoryLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [userId, recordId, retry]);
  const remove = async () => {
    if (deleting || !window.confirm('删除这条身体状况记录？')) return;
    setDeleting(true); setError(null);
    try {
      const response = await healthRecordAPI.deleteRecord(String(userId), String(recordId));
      if (!response.success) throw new Error(response.message || '删除失败');
      onChanged(); onClose();
    } catch (err) { setError(message(err)); setDeleting(false); }
  };
  return <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" onClick={() => { if (!deleting) onClose(); }}>
    <div ref={root} role="dialog" aria-modal="true" aria-labelledby="health-detail-title" className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl bg-white p-5 shadow-xl" onClick={event => event.stopPropagation()}>
      <div className="flex justify-between gap-3"><h3 id="health-detail-title" className="font-semibold break-words">{record?.title || '身体状况详情'}</h3><button aria-label="关闭详情" onClick={onClose} disabled={deleting} className="rounded-lg p-1.5 hover:bg-muted"><X className="w-4 h-4" /></button></div>
      {loading ? <p className="py-6 text-sm text-muted-foreground">加载详情中...</p> : <>
        {error && <div role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}<button className="ml-2 underline" onClick={() => setRetry(value => value + 1)}>重新加载</button></div>}
        {record && <><p className="mt-1 text-xs text-muted-foreground">{healthTime(record)} · {healthTypeLabels[record.record_type]}</p>
          {record.time_expression && <p className="mt-2 text-xs text-muted-foreground">原始时间描述：{record.time_expression}</p>}
          <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-6">{record.summary || '暂无补充描述'}</p>
          <dl className="mt-4 space-y-2 text-xs">{Object.entries(record.details || {}).filter(([key]) => !key.startsWith('_')).map(([key, value]) => <div key={key} className="grid grid-cols-[minmax(0,100px)_minmax(0,1fr)] gap-3"><dt className="text-muted-foreground">{healthDetailLabels[key] || key}</dt><dd className="whitespace-pre-wrap break-words">{healthValue(value)}</dd></div>)}</dl>
          <p className="mt-4 text-[11px] text-muted-foreground">来源：{record.source === 'conversation' ? '医疗对话' : '手动记录'}{record.confidence === 'inferred_time' ? ' · 时间由对话时刻推定' : ''}</p>
          <button aria-expanded={expanded} onClick={() => setExpanded(value => !value)} className="mt-4 flex items-center gap-1 text-xs text-primary"><History className="w-3.5 h-3.5" />{expanded ? '收起更正历史' : '查看更正历史'}</button>
          {expanded && <div className="mt-3 space-y-3 border-t pt-3">{historyLoading ? <p className="text-xs text-muted-foreground">加载历史中...</p> : historyError ? <p role="alert" className="text-xs text-red-700">{historyError}</p> : history.length === 0 ? <p className="text-xs text-muted-foreground">这条旧记录尚无保存的变更历史</p> : history.map(change => <div key={change.revision} className="rounded-lg bg-muted/40 p-3 text-xs"><p className="font-medium">{change.operation === 'created' ? '创建记录' : change.operation === 'updated' ? '更正记录' : '删除记录'} · 第{change.revision}版</p><p className="mt-1 text-[11px] text-muted-foreground">{new Date(change.at + (/[zZ]$|[+-]\d{2}:\d{2}$/.test(change.at) ? '' : 'Z')).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</p>{historyChanges(change).map(row => <div key={row.label} className="mt-2 break-words"><p className="font-medium">{row.label}</p><p className="text-muted-foreground">更正前：{row.before}</p><p>更正后：{row.after}</p></div>)}{change.operation === 'created' && <p className="mt-2 break-words">{change.after.summary || change.after.title}</p>}</div>)}{history.length === 100 && <p className="text-xs text-muted-foreground">此处显示最近100次变更</p>}</div>}
          <div className="mt-5 flex justify-between"><button onClick={() => void remove()} disabled={deleting} className="text-xs text-red-600 disabled:opacity-50">{deleting ? '删除中...' : '删除记录'}</button><Button size="sm" onClick={() => onEdit(record)} disabled={deleting}>更正记录</Button></div>
        </>}
      </>}
    </div>
  </div>;
}

interface FormProps { userId: number; selectedDate: string; record?: HealthRecord; onClose: () => void; onSaved: (record: HealthRecord) => void; onReload?: () => void }
export function HealthRecordFormDialog({ userId, selectedDate, record, onClose, onSaved, onReload }: FormProps) {
  const [precision, setPrecision] = useState<'day' | 'minute' | 'unknown'>(record?.time_precision || 'day');
  const [at, setAt] = useState(record?.observed_at.slice(0, 16) || `${selectedDate}T12:00`);
  const [type, setType] = useState<HealthRecordType>(record?.record_type || 'symptom');
  const [title, setTitle] = useState(record?.title || '');
  const [summary, setSummary] = useState(record?.summary || '');
  const [detailEdits, setDetailEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const inFlight = useRef(false);
  const attempt = useRef<HealthSaveAttempt | null>(null);
  const root = useModal(onClose, saving);
  const save = async () => {
    if (inFlight.current || !title.trim() || !at) return;
    inFlight.current = true; setSaving(true); setError(null); setConflict(false);
    try {
      const details = { ...(record?.details || {}) };
      for (const [key, value] of Object.entries(detailEdits)) {
        if (key === 'severity' || key === 'temperature_c') {
          const number = value.trim() ? Number(value) : null;
          if (number !== null && (!Number.isFinite(number) || (key === 'severity' && (number < 0 || number > 10)))) throw new Error('请填写有效的测量数值，疼痛程度应为0至10');
          details[key] = number;
        } else details[key] = key === 'associated_symptoms' ? value.split(/[,，、;；]/).map(text => text.trim()).filter(Boolean) : value.trim() || null;
      }
      const unchangedTime = record && at === record.observed_at.slice(0, 16) && precision === record.time_precision;
      const base = { observed_at: unchangedTime ? record.observed_at : precision === 'day' ? `${at.slice(0, 10)}T00:00:00` : `${at.slice(0, 16)}:00`, time_precision: precision, record_type: type, title: title.trim(), summary: summary.trim(), ...(Object.keys(detailEdits).length ? { details } : {}) };
      let response;
      if (record) response = await healthRecordAPI.updateRecord(String(userId), String(record.id), { ...base, expected_revision: record.revision });
      else {
        const payload: HealthRecordCreateRequest = { ...base, details, source: 'manual', confidence: 'user_confirmed' };
        attempt.current = createSaveAttempt(attempt.current, payload);
        response = await healthRecordAPI.createRecord(String(userId), { ...payload, idempotency_key: attempt.current.key });
      }
      if (!response.success || !response.data) throw new Error(response.message || '保存失败');
      onSaved(response.data);
    } catch (err) { setError(message(err)); setConflict(err instanceof ApiRequestError && err.status === 409); }
    finally { inFlight.current = false; setSaving(false); }
  };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => { if (!saving) onClose(); }}>
    <div ref={root} role="dialog" aria-modal="true" aria-labelledby="health-form-title" className="w-full max-w-lg max-h-[85vh] overflow-y-auto rounded-2xl bg-white p-5 shadow-xl" onClick={event => event.stopPropagation()}>
      <div className="flex justify-between gap-3"><h3 id="health-form-title" className="font-semibold">{record ? '更正身体状况' : '记录身体状况'}</h3><button aria-label="关闭记录表单" disabled={saving} onClick={onClose} className="p-1.5"><X className="w-4 h-4" /></button></div>
      <form className="mt-4 space-y-3" onSubmit={event => { event.preventDefault(); void save(); }}>
        <label className="block text-xs">时间精度<select value={precision} onChange={event => setPrecision(event.target.value as typeof precision)} disabled={saving} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"><option value="day">只记日期，具体时刻未说明</option><option value="minute">已知具体时刻</option>{record?.time_precision === 'unknown' && <option value="unknown">保留按对话时间记录</option>}</select></label>
        <label className="block text-xs">发生{precision === 'day' ? '日期' : '时间'}（中国时间）<input required type={precision === 'day' ? 'date' : 'datetime-local'} value={precision === 'day' ? at.slice(0, 10) : at} onChange={event => setAt(precision === 'day' ? `${event.target.value}T12:00` : event.target.value)} disabled={saving || precision === 'unknown'} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" /></label>
        <label className="block text-xs">类型<select value={type} onChange={event => setType(event.target.value as HealthRecordType)} disabled={saving} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm">{Object.entries(healthTypeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <label className="block text-xs">标题<input required maxLength={200} value={title} onChange={event => setTitle(event.target.value)} disabled={saving} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" placeholder="例如：头痛、体温" /></label>
        <label className="block text-xs">补充描述<textarea rows={3} maxLength={2000} value={summary} onChange={event => setSummary(event.target.value)} disabled={saving} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" /></label>
        {healthEditableFields(type, record?.details || {}).map(key => <label key={key} className="block text-xs">{healthDetailLabels[key] || key}<input value={detailEdits[key] ?? (record?.details[key] === null || record?.details[key] === undefined ? '' : healthValue(record.details[key]))} onChange={event => setDetailEdits(value => ({ ...value, [key]: event.target.value }))} disabled={saving} className="mt-1 w-full rounded-lg border px-3 py-2 text-sm" /></label>)}
        {error && <div role="alert" className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}{conflict && onReload && <button type="button" onClick={onReload} className="mt-2 block underline">关闭草稿，重新加载最新记录</button>}</div>}
        <div className="flex justify-end gap-2 pt-2"><Button type="button" size="sm" variant="outline" onClick={onClose} disabled={saving}>取消</Button><Button type="submit" size="sm" disabled={saving || !title.trim() || !at}>{saving ? '保存中...' : '保存'}</Button></div>
      </form>
    </div>
  </div>;
}
