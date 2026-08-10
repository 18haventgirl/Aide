import React, { useState, useEffect, useRef } from 'react';
import { CheckSquare, Plus, Calendar, AlertCircle, Edit3, Trash2, X, Save, Clock, Flag, CheckCircle, Circle, BarChart3, MoreHorizontal } from 'lucide-react';
import { Button } from './ui/button';
import type { Todo, TodoCreateRequest, TodoUpdateRequest, PersonDataFilter } from '../lib/types';
import { todoAPI } from '../services/apiService';

interface TodosPanelProps { userId: number }

export function TodosPanel({ userId }: TodosPanelProps) {
  const [todos, setTodos] = useState<Todo[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [opLoading, setOpLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Todo | null>(null);
  const [filter, setFilter] = useState<PersonDataFilter>({});
  const [showStats, setShowStats] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [menuOpen, setMenuOpen] = useState<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const [form, setForm] = useState<TodoCreateRequest>({ title: '', description: '', priority: 'medium', due_date: undefined, note_id: undefined });

  const load = async () => {
    setLoading(true);
    try { const r = await todoAPI.getTodos(userId.toString(), { completed: filter.completed, priority: filter.priority, overdue: filter.overdue, limit: 50 }); setTodos(r.data || []); } catch { setTodos([]); }
    setLoading(false);
  };

  const loadStats = async () => {
    try { const r = await todoAPI.getStats(userId.toString()); setStats(r.data?.data); } catch { /* noop */ }
  };

  const submit = async () => {
    setOpLoading(true);
    const data = { ...form, due_date: form.due_date ? new Date(form.due_date).toISOString() : undefined };
    try {
      if (editing) {
        await todoAPI.updateTodo(userId.toString(), editing.id.toString(), data as TodoUpdateRequest);
      } else {
        await todoAPI.createTodo(userId.toString(), data);
      }
      setShowForm(false); setEditing(null);
      setForm({ title: '', description: '', priority: 'medium', due_date: undefined, note_id: undefined });
      await Promise.all([load(), loadStats()]);
    } catch { /* noop */ }
    setOpLoading(false);
  };

  const remove = async (id: number) => {
    if (!confirm('删除这条待办？')) return;
    setOpLoading(true);
    try { await todoAPI.deleteTodo(userId.toString(), id.toString()); await Promise.all([load(), loadStats()]); } catch { /* noop */ }
    setOpLoading(false);
    setMenuOpen(null);
  };

  const toggle = async (t: Todo) => {
    setOpLoading(true);
    try { t.completed ? await todoAPI.uncompleteTodo(userId.toString(), t.id.toString()) : await todoAPI.completeTodo(userId.toString(), t.id.toString()); await Promise.all([load(), loadStats()]); } catch { /* noop */ }
    setOpLoading(false);
  };

  const startEdit = (t: Todo) => {
    setEditing(t);
    setForm({ title: t.title, description: t.description, priority: t.priority, due_date: t.due_date ? new Date(t.due_date).toISOString().split('T')[0] : undefined, note_id: t.note_id || undefined });
    setShowForm(true);
    setMenuOpen(null);
  };

  useEffect(() => { Promise.all([load(), loadStats()]).catch(() => {}); }, [userId, filter]);
  useEffect(() => { const h = (e: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(null); }; document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h); }, []);

  const fmt = (d: string | null) => d ? new Date(d).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) : '';
  const pc = (p: string) => ({ high: 'text-red-600 bg-red-50', medium: 'text-amber-600 bg-amber-50', low: 'text-green-600 bg-green-50' }[p] || 'bg-gray-50');
  const pt = (p: string) => ({ high: '高', medium: '中', low: '低' }[p] || '中');

  return (
    <div className="h-full flex flex-col">
      {/* Compact header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
        <h3 className="text-sm font-heading font-semibold text-foreground/80 flex items-center gap-1.5">
          <CheckSquare className="w-3.5 h-3.5" />待办
        </h3>
        <div className="flex items-center gap-1">
          <button onClick={() => setShowStats(!showStats)} className={`p-1.5 rounded-md transition-colors ${showStats ? 'bg-primary/10 text-primary' : 'hover:bg-muted text-muted-foreground'}`} title="统计"><BarChart3 className="w-3.5 h-3.5" /></button>
          <button onClick={() => setShowFilters(!showFilters)} className={`p-1.5 rounded-md transition-colors ${showFilters ? 'bg-primary/10 text-primary' : 'hover:bg-muted text-muted-foreground'}`} title="筛选"><FilterIcon className="w-3.5 h-3.5" /></button>
          <button onClick={() => { setEditing(null); setForm({ title: '', description: '', priority: 'medium', due_date: undefined, note_id: undefined }); setShowForm(true); }} className="p-1.5 rounded-md hover:bg-primary/10 text-primary transition-colors" title="新建"><Plus className="w-3.5 h-3.5" /></button>
        </div>
      </div>

      {/* Stats */}
      {showStats && stats && (
        <div className="px-3 py-2 border-b border-border/30 bg-muted/20 animate-fade-in">
          <div className="grid grid-cols-4 gap-2 text-center">
            {[['总计', 'text-blue-600', stats.total], ['完成', 'text-green-600', stats.completed], ['待办', 'text-amber-600', stats.pending], ['过期', 'text-red-600', stats.overdue]].map(([l, c, v]) => (
              <div key={l as string}><div className={`text-lg font-bold ${c}`}>{v}</div><div className="text-[10px] text-muted-foreground">{l}</div></div>
            ))}
          </div>
        </div>
      )}

      {/* Filters */}
      {showFilters && (
        <div className="px-3 py-2 border-b border-border/30 bg-muted/20 flex gap-1.5 animate-fade-in">
          <select value={filter.completed !== undefined ? String(filter.completed) : ''} onChange={e => setFilter({ ...filter, completed: e.target.value === '' ? undefined : e.target.value === 'true' })} className="flex-1 px-2 py-1 text-xs border border-border rounded-md bg-white">
            <option value="">全部状态</option><option value="false">未完成</option><option value="true">已完成</option>
          </select>
          <select value={filter.priority || ''} onChange={e => setFilter({ ...filter, priority: (e.target.value || undefined) as any })} className="flex-1 px-2 py-1 text-xs border border-border rounded-md bg-white">
            <option value="">全部优先级</option><option value="high">高</option><option value="medium">中</option><option value="low">低</option>
          </select>
          <select value={filter.overdue !== undefined ? String(filter.overdue) : ''} onChange={e => setFilter({ ...filter, overdue: e.target.value === '' ? undefined : e.target.value === 'true' })} className="flex-1 px-2 py-1 text-xs border border-border rounded-md bg-white">
            <option value="">全部时间</option><option value="true">已过期</option><option value="false">未过期</option>
          </select>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading ? (
          <div className="flex justify-center py-8"><div className="w-6 h-6 rounded-full border-2 border-primary border-t-transparent animate-spin" /></div>
        ) : todos.length === 0 ? (
          <div className="text-center py-8 text-xs text-muted-foreground">暂无待办</div>
        ) : (
          <div className="p-2 space-y-1">
            {todos.map(t => (
              <div key={t.id} className={`group px-3 py-2 rounded-lg hover:bg-muted/50 transition-colors relative ${t.completed ? 'opacity-60' : ''}`}>
                <div className="flex items-start gap-2">
                  <button onClick={() => toggle(t)} disabled={opLoading} className="mt-0.5 flex-shrink-0">
                    {t.completed ? <CheckCircle className="w-4 h-4 text-green-500" /> : <Circle className="w-4 h-4 text-muted-foreground/40 hover:text-green-500 transition-colors" />}
                  </button>
                  <div className="flex-1 min-w-0">
                    <h4 className={`text-sm truncate ${t.completed ? 'line-through text-muted-foreground' : 'text-foreground font-medium'}`}>{t.title}</h4>
                    {t.description && <p className="text-xs text-muted-foreground truncate mt-0.5">{t.description}</p>}
                    <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                      <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] rounded-full ${pc(t.priority)}`}><Flag className="w-2.5 h-2.5" />{pt(t.priority)}</span>
                      {t.due_date && (
                        <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] rounded-full ${t.is_overdue && !t.completed ? 'bg-red-50 text-red-600' : 'bg-blue-50 text-blue-600'}`}>
                          <Calendar className="w-2.5 h-2.5" />{fmt(t.due_date)}
                        </span>
                      )}
                      {t.is_overdue && !t.completed && <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] bg-red-50 text-red-600 rounded-full"><AlertCircle className="w-2.5 h-2.5" />过期</span>}
                    </div>
                  </div>
                  {/* ... menu */}
                  <div className="relative flex-shrink-0" ref={menuOpen === t.id ? menuRef : undefined}>
                    <button onClick={() => setMenuOpen(menuOpen === t.id ? null : t.id)} className="p-1 rounded-md hover:bg-muted opacity-0 group-hover:opacity-100 transition-opacity">
                      <MoreHorizontal className="w-3.5 h-3.5 text-muted-foreground" />
                    </button>
                    {menuOpen === t.id && (
                      <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-border py-1 z-30 min-w-[100px] animate-fade-in">
                        <button onClick={() => startEdit(t)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted transition-colors"><Edit3 className="w-3 h-3" />编辑</button>
                        <button onClick={() => remove(t.id)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-destructive hover:bg-red-50 transition-colors"><Trash2 className="w-3 h-3" />删除</button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Form modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center z-50" onClick={() => { setShowForm(false); setEditing(null); }}>
          <div className="bg-white rounded-2xl p-5 w-full max-w-md m-4 shadow-xl animate-fade-in" onClick={e => e.stopPropagation()}>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-base font-heading font-semibold">{editing ? '编辑待办' : '新建待办'}</h3>
              <button onClick={() => { setShowForm(false); setEditing(null); }} className="p-1.5 rounded-lg hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} className="w-full px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none" placeholder="标题" />
              <textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className="w-full px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none" rows={2} placeholder="描述（可选）" />
              <div className="flex gap-3">
                <select value={form.priority} onChange={e => setForm({ ...form, priority: e.target.value as any })} className="flex-1 px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none bg-white">
                  <option value="low">低优先级</option><option value="medium">中优先级</option><option value="high">高优先级</option>
                </select>
                <input type="date" value={form.due_date || ''} onChange={e => setForm({ ...form, due_date: e.target.value || undefined })} className="flex-1 px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none" />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <Button variant="outline" onClick={() => { setShowForm(false); setEditing(null); }} size="sm">取消</Button>
              <Button onClick={submit} disabled={!form.title.trim() || opLoading} size="sm">{opLoading ? '保存中...' : editing ? '更新' : '创建'}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Simple filter icon component (no lucide Filter import to keep bundle small)
function FilterIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
    </svg>
  );
}