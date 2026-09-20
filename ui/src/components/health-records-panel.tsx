import React, { useEffect, useMemo, useState } from 'react';
import { Activity, ChevronLeft, ChevronRight, Clock, Plus, X } from 'lucide-react';
import { Button } from './ui/button';
import type { HealthRecord, HealthRecordCreateRequest, HealthRecordType } from '../lib/types';
import { healthRecordAPI } from '../services/apiService';

interface HealthRecordsPanelProps { userId: number }

const typeLabels: Record<HealthRecordType, string> = {
  symptom: '症状', vital: '测量', medication: '用药', visit: '就诊',
};

const pad = (value: number) => String(value).padStart(2, '0');
const dateKey = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
const monthTitle = (date: Date) => date.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' });
const displayTime = (value: string) => new Date(value).toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });

function calendarDays(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const mondayOffset = (first.getDay() + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayOffset);
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return day;
  });
}

export function HealthRecordsPanel({ userId }: HealthRecordsPanelProps) {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [records, setRecords] = useState<HealthRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedDate, setSelectedDate] = useState(dateKey(new Date()));
  const [detail, setDetail] = useState<HealthRecord | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    observed_at: `${dateKey(new Date())}T${pad(new Date().getHours())}:${pad(new Date().getMinutes())}`,
    record_type: 'symptom' as HealthRecordType,
    title: '', summary: '',
  });

  const load = async () => {
    setLoading(true); setError(null);
    const start = dateKey(new Date(month.getFullYear(), month.getMonth(), 1));
    const end = dateKey(new Date(month.getFullYear(), month.getMonth() + 1, 0));
    try {
      const response = await healthRecordAPI.getRecords(String(userId), { start_date: start, end_date: end, limit: 500 });
      if (response.success === false) throw new Error(response.message || '加载身体状况失败');
      setRecords(response.data?.records || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载身体状况失败');
      setRecords([]);
    } finally { setLoading(false); }
  };

  useEffect(() => { void load(); }, [userId, month.getFullYear(), month.getMonth()]);

  const grouped = useMemo(() => records.reduce<Record<string, HealthRecord[]>>((result, record) => {
    const key = dateKey(new Date(record.observed_at));
    (result[key] ||= []).push(record);
    return result;
  }, {}), [records]);

  const selectedRecords = [...(grouped[selectedDate] || [])].sort((a, b) =>
    new Date(b.observed_at).getTime() - new Date(a.observed_at).getTime());
  const days = calendarDays(month);

  const moveMonth = (offset: number) => {
    const next = new Date(month.getFullYear(), month.getMonth() + offset, 1);
    setMonth(next);
    setSelectedDate(dateKey(next));
  };

  const openCreate = () => {
    const now = new Date();
    setForm({
      observed_at: `${selectedDate}T${pad(now.getHours())}:${pad(now.getMinutes())}`,
      record_type: 'symptom', title: '', summary: '',
    });
    setShowForm(true);
  };

  const save = async () => {
    if (!form.title.trim()) return;
    setSaving(true);
    const payload: HealthRecordCreateRequest = {
      observed_at: form.observed_at,
      time_precision: 'minute', record_type: form.record_type,
      title: form.title.trim(), summary: form.summary.trim(), details: {},
      source: 'manual', confidence: 'user_confirmed',
    };
    try {
      const response = await healthRecordAPI.createRecord(String(userId), payload);
      if (response.success === false) throw new Error(response.message || '保存失败');
      setShowForm(false); await load();
    } catch (err) { setError(err instanceof Error ? err.message : '保存失败'); }
    finally { setSaving(false); }
  };

  const remove = async (record: HealthRecord) => {
    if (!window.confirm('删除这条身体状况记录？')) return;
    try { await healthRecordAPI.deleteRecord(String(userId), String(record.id)); setDetail(null); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : '删除失败'); }
  };

  return (
    <div className="h-full flex flex-col min-w-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
        <h3 className="text-sm font-heading font-semibold text-foreground/80 flex items-center gap-1.5"><Activity className="w-3.5 h-3.5" />身体状况</h3>
        <button onClick={openCreate} className="p-1.5 rounded-md hover:bg-primary/10 text-primary" title="手动记录"><Plus className="w-3.5 h-3.5" /></button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-3">
        <div className="flex items-center justify-between">
          <button onClick={() => moveMonth(-1)} className="p-1.5 rounded-md hover:bg-muted" title="上个月"><ChevronLeft className="w-4 h-4" /></button>
          <div className="flex items-center gap-2"><span className="text-sm font-semibold">{monthTitle(month)}</span><button onClick={() => { const now = new Date(); setMonth(new Date(now.getFullYear(), now.getMonth(), 1)); setSelectedDate(dateKey(now)); }} className="text-xs text-primary hover:underline">今天</button></div>
          <button onClick={() => moveMonth(1)} className="p-1.5 rounded-md hover:bg-muted" title="下个月"><ChevronRight className="w-4 h-4" /></button>
        </div>

        <div className="grid grid-cols-7 gap-1 text-center text-[10px] text-muted-foreground">
          {['一', '二', '三', '四', '五', '六', '日'].map(label => <div key={label} className="py-1">{label}</div>)}
          {days.map(day => {
            const key = dateKey(day); const inMonth = day.getMonth() === month.getMonth(); const count = grouped[key]?.length || 0;
            return <button key={key} onClick={() => setSelectedDate(key)} className={`min-h-10 rounded-lg p-1 flex flex-col items-center justify-center ${inMonth ? 'text-foreground' : 'text-muted-foreground/40'} ${selectedDate === key ? 'bg-primary text-white' : 'hover:bg-muted'}`}><span className="text-xs">{day.getDate()}</span>{count > 0 && <span className={`mt-0.5 min-w-4 px-1 rounded-full text-[9px] ${selectedDate === key ? 'bg-white/25 text-white' : 'bg-primary/10 text-primary'}`}>{count}</span>}</button>;
          })}
        </div>

        <div className="flex items-center justify-between border-t border-border/30 pt-3"><h4 className="text-sm font-semibold">{selectedDate} 的记录</h4><button onClick={openCreate} className="text-xs text-primary hover:underline">添加记录</button></div>
        {loading ? <div className="py-8 text-center text-xs text-muted-foreground">加载中...</div> : error ? <div className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{error}</div> : selectedRecords.length === 0 ? <div className="py-8 text-center text-xs text-muted-foreground">这一天还没有身体状况记录</div> : <div className="space-y-2">{selectedRecords.map(record => <button key={record.id} onClick={() => setDetail(record)} className="w-full text-left rounded-lg border border-border/60 bg-white p-3 hover:border-primary/40 hover:bg-primary/[0.02]"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-primary" /><span className="text-xs text-muted-foreground">{new Date(record.observed_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span><span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px]">{typeLabels[record.record_type]}</span></div><p className="mt-1 text-sm font-medium break-words">{record.title}</p>{record.summary && <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">{record.summary}</p>}</div><span className="text-[10px] text-primary">查看</span></div></button>)}</div>}
      </div>

      {detail && <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" onClick={() => setDetail(null)}><div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl" onClick={e => e.stopPropagation()}><div className="flex items-start justify-between gap-3"><div><h3 className="text-base font-semibold">{detail.title}</h3><p className="mt-1 text-xs text-muted-foreground">{displayTime(detail.observed_at)} · {typeLabels[detail.record_type]}</p></div><button onClick={() => setDetail(null)} className="rounded-lg p-1.5 hover:bg-muted"><X className="w-4 h-4" /></button></div><p className="mt-4 whitespace-pre-wrap text-sm leading-6">{detail.summary || '暂无补充描述'}</p><div className="mt-4 space-y-1 text-xs">{Object.entries(detail.details || {}).map(([key, value]) => <div key={key} className="grid grid-cols-[auto_1fr] gap-3"><span className="text-muted-foreground">{key}</span><span className="break-words">{Array.isArray(value) ? value.join('、') : String(value)}</span></div>)}</div><p className="mt-4 text-[11px] text-muted-foreground">来源：{detail.source === 'conversation' ? '医疗对话' : '手动记录'}{detail.confidence === 'inferred_time' ? ' · 时间按对话时间记录' : ''}</p><div className="mt-4 flex justify-end"><button onClick={() => void remove(detail)} className="text-xs text-red-600 hover:underline">删除记录</button></div></div></div>}

      {showForm && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4" onClick={() => setShowForm(false)}><div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl" onClick={e => e.stopPropagation()}><div className="flex items-center justify-between"><h3 className="text-base font-semibold">记录身体状况</h3><button onClick={() => setShowForm(false)} className="rounded-lg p-1.5 hover:bg-muted"><X className="w-4 h-4" /></button></div><div className="mt-4 space-y-3"><input type="datetime-local" value={form.observed_at} onChange={e => setForm({ ...form, observed_at: e.target.value })} className="w-full rounded-xl border px-3 py-2 text-sm" /><div className="flex gap-2"><select value={form.record_type} onChange={e => setForm({ ...form, record_type: e.target.value as HealthRecordType })} className="flex-1 rounded-xl border px-3 py-2 text-sm bg-white">{Object.entries(typeLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} className="flex-[2] rounded-xl border px-3 py-2 text-sm" placeholder="例如：头痛、体温" /></div><textarea value={form.summary} onChange={e => setForm({ ...form, summary: e.target.value })} className="w-full rounded-xl border px-3 py-2 text-sm" rows={3} placeholder="补充描述" /></div><div className="mt-5 flex justify-end gap-2"><Button variant="outline" onClick={() => setShowForm(false)} size="sm">取消</Button><Button onClick={() => void save()} disabled={!form.title.trim() || saving} size="sm">{saving ? '保存中...' : '保存'}</Button></div></div></div>}
    </div>
  );
}
