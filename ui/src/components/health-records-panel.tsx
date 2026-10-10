import { useEffect, useState } from 'react';
import { Activity, ChevronLeft, ChevronRight, Clock, Plus, RefreshCw } from 'lucide-react';
import { healthRecordAPI } from '../services/apiService';
import type { HealthRecord, HealthRecordPage } from '../lib/types';
import { calendarDayKeys, chinaToday, healthTime, healthTypeLabels, moveCalendarMonth } from '../lib/health-records';
import { HealthRecordDetailDialog, HealthRecordFormDialog } from './health-record-dialogs';

interface CalendarState { scope: string; counts: Record<string, number>; total: number; loading: boolean; error: string | null }
interface DayState { scope: string; page: HealthRecordPage | null; loading: boolean; error: string | null }
const cancelled = (error: unknown) => (error as { code?: string })?.code === 'ERR_CANCELED';
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '加载失败，请重试';
const PAGE_SIZE = 50;

export function HealthRecordsPanel({ userId }: { userId: number }) {
  const [month, setMonth] = useState(() => chinaToday().slice(0, 7));
  const [selectedDate, setSelectedDate] = useState(chinaToday);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [calendar, setCalendar] = useState<CalendarState>({ scope: '', counts: {}, total: 0, loading: true, error: null });
  const [day, setDay] = useState<DayState>({ scope: '', page: null, loading: true, error: null });
  const [detailId, setDetailId] = useState<number | null>(null);
  const [detailOwner, setDetailOwner] = useState(userId);
  const [form, setForm] = useState<{ owner: number; date: string; record?: HealthRecord } | null>(null);
  const calendarScope = `${userId}:${month}`, dayScope = `${userId}:${selectedDate}:${offset}`;
  const calendarCurrent = calendar.scope === calendarScope;
  const dayCurrent = day.scope === dayScope;
  const counts = calendarCurrent ? calendar.counts : {};
  const page = dayCurrent ? day.page : null;
  const dayLoading = !dayCurrent || day.loading;

  useEffect(() => {
    setDetailId(null); setForm(null); setOffset(0);
  }, [userId]);

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setCalendar({ scope: calendarScope, counts: {}, total: 0, loading: true, error: null });
    void healthRecordAPI.getCalendar(String(userId), month, controller.signal).then(response => {
      if (!response.success || !response.data?.daily_counts) throw new Error(response.message || '日历统计加载失败');
      if (active) setCalendar({ scope: calendarScope, counts: response.data.daily_counts, total: response.data.total, loading: false, error: null });
    }).catch(error => { if (active && !cancelled(error)) setCalendar({ scope: calendarScope, counts: {}, total: 0, loading: false, error: errorMessage(error) }); });
    return () => { active = false; controller.abort(); };
  }, [userId, month, calendarScope, refresh]);

  useEffect(() => {
    const controller = new AbortController(); let active = true;
    setDay({ scope: dayScope, page: null, loading: true, error: null });
    void healthRecordAPI.getRecords(String(userId), { start_date: selectedDate, end_date: selectedDate, limit: PAGE_SIZE, offset }, controller.signal).then(response => {
      if (!response.success || !Array.isArray(response.data?.records)) throw new Error(response.message || '当天记录加载失败');
      if (active) setDay({ scope: dayScope, page: response.data, loading: false, error: null });
    }).catch(error => { if (active && !cancelled(error)) setDay({ scope: dayScope, page: null, loading: false, error: errorMessage(error) }); });
    return () => { active = false; controller.abort(); };
  }, [userId, selectedDate, offset, dayScope, refresh]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const changed = () => { clearTimeout(timer); timer = setTimeout(() => { setOffset(0); setRefresh(value => value + 1); }, 200); };
    window.addEventListener('aide:health-records-changed', changed);
    return () => { clearTimeout(timer); window.removeEventListener('aide:health-records-changed', changed); };
  }, []);

  const reload = () => { setOffset(0); setRefresh(value => value + 1); };
  const openDetail = (id: number) => { setDetailOwner(userId); setDetailId(id); };
  const selectDate = (value: string) => { setSelectedDate(value); setMonth(value.slice(0, 7)); setOffset(0); };
  const saved = (record: HealthRecord) => { setForm(null); selectDate(record.observed_at.slice(0, 10)); reload(); openDetail(record.id); };
  const activeForm = form?.owner === userId ? form : null;

  return <div className="h-full flex flex-col min-w-0">
    <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
      <h3 className="text-sm font-heading font-semibold text-foreground/80 flex items-center gap-1.5"><Activity className="w-3.5 h-3.5" />身体状况</h3>
      <div className="flex gap-1"><button onClick={reload} title="刷新身体状况" aria-label="刷新身体状况" className="p-1.5 rounded-md hover:bg-muted text-muted-foreground"><RefreshCw className="w-3.5 h-3.5" /></button><button onClick={() => setForm({ owner: userId, date: selectedDate })} title="手动记录" aria-label="手动记录" className="p-1.5 rounded-md hover:bg-primary/10 text-primary"><Plus className="w-3.5 h-3.5" /></button></div>
    </div>
    <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-3">
      <div className="flex items-center justify-between"><button onClick={() => selectDate(`${moveCalendarMonth(month, -1)}-01`)} aria-label="上个月" className="p-1.5 rounded-md hover:bg-muted"><ChevronLeft className="w-4 h-4" /></button><div className="flex items-center gap-2"><span className="text-sm font-semibold">{month.replace('-', '年')}月</span><button onClick={() => selectDate(chinaToday())} className="text-xs text-primary hover:underline">今天</button></div><button onClick={() => selectDate(`${moveCalendarMonth(month, 1)}-01`)} aria-label="下个月" className="p-1.5 rounded-md hover:bg-muted"><ChevronRight className="w-4 h-4" /></button></div>
      <p className="text-[11px] text-muted-foreground">{!calendarCurrent || calendar.loading ? '日历统计加载中...' : calendar.error ? <span role="alert" className="text-red-700">{calendar.error}</span> : `本月共 ${calendar.total} 条记录`}</p>
      <div className="grid grid-cols-7 gap-1 text-center text-[10px] text-muted-foreground">
        {['一', '二', '三', '四', '五', '六', '日'].map(label => <div key={label} className="py-1">{label}</div>)}
        {calendarDayKeys(month).map(key => {
          const inMonth = key.startsWith(month), count = inMonth ? counts[key] || 0 : 0;
          return <button key={key} aria-label={`${key}${count ? `，${count}条记录` : ''}`} aria-pressed={selectedDate === key} onClick={() => selectDate(key)} className={`min-h-10 rounded-lg p-1 flex flex-col items-center justify-center ${inMonth ? 'text-foreground' : 'text-muted-foreground/40'} ${selectedDate === key ? 'bg-primary text-white' : 'hover:bg-muted'}`}><span className="text-xs">{Number(key.slice(8))}</span>{count > 0 && <span className={`mt-0.5 min-w-4 px-1 rounded-full text-[9px] ${selectedDate === key ? 'bg-white/25 text-white' : 'bg-primary/10 text-primary'}`}>{count}</span>}</button>;
        })}
      </div>
      <div className="flex items-center justify-between border-t border-border/30 pt-3"><h4 className="text-sm font-semibold">{selectedDate} 的记录</h4><button onClick={() => setForm({ owner: userId, date: selectedDate })} className="text-xs text-primary hover:underline">添加记录</button></div>
      {dayLoading ? <div className="py-8 text-center text-xs text-muted-foreground">当天记录加载中...</div> : day.error ? <div role="alert" className="rounded-lg bg-red-50 p-3 text-xs text-red-700">{day.error}<button onClick={reload} className="ml-2 underline">重试</button></div> : !page?.records.length ? <div className="py-8 text-center text-xs text-muted-foreground">这一天还没有身体状况记录</div> : <div className="space-y-2">{page.records.map(record => <button key={record.id} onClick={() => openDetail(record.id)} className="w-full min-w-0 text-left rounded-lg border border-border/60 bg-white p-3 hover:border-primary/40 hover:bg-primary/[0.02]"><div className="flex items-start justify-between gap-2"><div className="min-w-0"><div className="flex flex-wrap items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-primary" /><span className="text-[11px] text-muted-foreground">{healthTime(record)}</span><span className="rounded-full bg-muted px-1.5 py-0.5 text-[10px]">{healthTypeLabels[record.record_type]}</span></div><p className="mt-1 text-sm font-medium break-words">{record.title}</p>{record.summary && <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2 break-words">{record.summary}</p>}</div><span className="text-[10px] text-primary shrink-0">查看</span></div></button>)}</div>}
      {!dayLoading && page && page.total > PAGE_SIZE && <div className="flex items-center justify-between gap-2 text-xs"><button disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))} className="text-primary disabled:opacity-40">上一页</button><span>{offset + 1}–{Math.min(offset + page.returned, page.total)} / {page.total}</span><button disabled={!page.has_more} onClick={() => setOffset(value => value + PAGE_SIZE)} className="text-primary disabled:opacity-40">下一页</button></div>}
    </div>
    {detailId !== null && detailOwner === userId && <HealthRecordDetailDialog key={`${userId}:${detailId}`} userId={userId} recordId={detailId} onClose={() => setDetailId(null)} onChanged={reload} onEdit={record => { setDetailId(null); setForm({ owner: userId, date: record.observed_at.slice(0, 10), record }); }} />}
    {activeForm && <HealthRecordFormDialog key={`${userId}:${activeForm.record?.id || activeForm.date}`} userId={userId} selectedDate={activeForm.date} record={activeForm.record} onClose={() => setForm(null)} onSaved={saved} onReload={() => { const id = activeForm.record?.id; setForm(null); if (id) openDetail(id); reload(); }} />}
  </div>;
}
