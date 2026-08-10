import React, { useState, useEffect, useRef } from 'react';
import { FileText, Plus, Search, Tag, Edit3, Trash2, X, Save, MoreHorizontal, ChevronDown } from 'lucide-react';
import { Button } from './ui/button';
import type { Note, NoteCreateRequest, NoteUpdateRequest, PersonDataFilter } from '../lib/types';
import { noteAPI } from '../services/apiService';

const PREDEFINED_TAGS = [
  { value: 'lifestyle tips', label: '生活小贴士' },
  { value: 'cooking advice', label: '烹饪建议' },
  { value: 'weather interpretation', label: '天气解读' },
  { value: 'news context', label: '新闻背景' }
];

interface NotesPanelProps { userId: number }

export function NotesPanel({ userId }: NotesPanelProps) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(false);
  const [opLoading, setOpLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Note | null>(null);
  const [searchQ, setSearchQ] = useState('');
  const [filter, setFilter] = useState<PersonDataFilter>({});
  const [tags, setTags] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);
  const [menuOpen, setMenuOpen] = useState<number | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const [form, setForm] = useState<NoteCreateRequest>({ title: '', content: '', tag: '', status: 'draft' });

  const load = async () => {
    setLoading(true);
    try {
      const r = await noteAPI.getNotes(userId.toString(), { tag: filter.tag, status: filter.status, search: filter.search, limit: 50 });
      setNotes(r.data?.data || []);
    } catch { setNotes([]); }
    setLoading(false);
  };

  const loadTags = async () => {
    try { const r = await noteAPI.getTags(userId.toString()); setTags(r.data?.data || []); } catch { setTags([]); }
  };

  const search = async () => {
    if (!searchQ.trim()) { load(); return; }
    setLoading(true);
    try {
      const r = await noteAPI.searchNotes(userId.toString(), { query: searchQ, tag: filter.tag, status: filter.status, limit: 20, use_vector_search: true });
      setNotes(r.data?.data || []);
    } catch { setNotes([]); }
    setLoading(false);
  };

  const submit = async () => {
    setOpLoading(true);
    try {
      if (editing) {
        await noteAPI.updateNote(userId.toString(), editing.id.toString(), { title: form.title, content: form.content, tag: form.tag, status: form.status });
      } else {
        await noteAPI.createNote(userId.toString(), form);
      }
      setShowForm(false); setEditing(null);
      setForm({ title: '', content: '', tag: '', status: 'draft' });
      await Promise.all([load(), loadTags()]);
    } catch { /* noop */ }
    setOpLoading(false);
  };

  const remove = async (id: number) => {
    if (!confirm('删除这条笔记？')) return;
    setOpLoading(true);
    try { await noteAPI.deleteNote(userId.toString(), id.toString()); await Promise.all([load(), loadTags()]); } catch { /* noop */ }
    setOpLoading(false);
    setMenuOpen(null);
  };

  const startEdit = (n: Note) => { setEditing(n); setForm({ title: n.title, content: n.content, tag: n.tag || '', status: n.status }); setShowForm(true); setMenuOpen(null); };

  useEffect(() => { Promise.all([load(), loadTags()]).catch(() => {}); }, [userId, filter]);
  useEffect(() => { const h = (e: MouseEvent) => { if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(null); }; document.addEventListener('mousedown', h); return () => document.removeEventListener('mousedown', h); }, []);

  const tagLabel = (v: string) => PREDEFINED_TAGS.find(t => t.value === v)?.label || v;
  const fmt = (d: string | null) => d ? new Date(d).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  const sc = (s: string) => ({ draft: 'bg-gray-100 text-gray-600', published: 'bg-green-100 text-green-700', archived: 'bg-yellow-100 text-yellow-700' }[s] || 'bg-gray-100');

  return (
    <div className="h-full flex flex-col">
      {/* Compact header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
        <h3 className="text-sm font-heading font-semibold text-foreground/80 flex items-center gap-1.5">
          <FileText className="w-3.5 h-3.5" />笔记
        </h3>
        <div className="flex items-center gap-1">
          <button onClick={() => setShowFilters(!showFilters)} className={`p-1.5 rounded-md transition-colors ${showFilters ? 'bg-primary/10 text-primary' : 'hover:bg-muted text-muted-foreground'}`} title="筛选"><Search className="w-3.5 h-3.5" /></button>
          <button onClick={() => { setEditing(null); setForm({ title: '', content: '', tag: '', status: 'draft' }); setShowForm(true); }} className="p-1.5 rounded-md hover:bg-primary/10 text-primary transition-colors" title="新建笔记"><Plus className="w-3.5 h-3.5" /></button>
        </div>
      </div>

      {/* Collapsible filter bar */}
      {showFilters && (
        <div className="px-3 py-2 border-b border-border/30 bg-muted/20 space-y-2 animate-fade-in">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <input value={searchQ} onChange={e => setSearchQ(e.target.value)} onKeyDown={e => e.key === 'Enter' && search()} placeholder="搜索..." className="w-full pl-8 pr-3 py-1.5 text-xs border border-border rounded-lg focus:ring-1 focus:ring-primary outline-none bg-white" />
          </div>
          <div className="flex gap-1.5">
            <select value={filter.tag || ''} onChange={e => setFilter({ ...filter, tag: e.target.value || undefined })} className="flex-1 px-2 py-1 text-xs border border-border rounded-md bg-white">
              <option value="">所有标签</option>
              {PREDEFINED_TAGS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
              {tags.filter(t => !PREDEFINED_TAGS.some(p => p.value === t)).map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={filter.status || ''} onChange={e => setFilter({ ...filter, status: e.target.value || undefined })} className="flex-1 px-2 py-1 text-xs border border-border rounded-md bg-white">
              <option value="">所有状态</option>
              <option value="draft">草稿</option>
              <option value="published">已发布</option>
              <option value="archived">已归档</option>
            </select>
          </div>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {loading ? (
          <div className="flex justify-center py-8"><div className="w-6 h-6 rounded-full border-2 border-primary border-t-transparent animate-spin" /></div>
        ) : notes.length === 0 ? (
          <div className="text-center py-8 text-xs text-muted-foreground">暂无笔记</div>
        ) : (
          <div className="p-2 space-y-1.5">
            {notes.map(n => (
              <div key={n.id} className="group px-3 py-2 rounded-lg hover:bg-muted/50 transition-colors relative">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-medium text-foreground truncate">{n.title}</h4>
                    {n.content && <p className="text-xs text-muted-foreground truncate mt-0.5">{n.content}</p>}
                    <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
                      {n.tag && <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] bg-primary/10 text-primary rounded-full"><Tag className="w-2.5 h-2.5" />{tagLabel(n.tag)}</span>}
                      <span className={`px-1.5 py-0.5 text-[10px] rounded-full ${sc(n.status)}`}>{n.status === 'draft' ? '草稿' : n.status === 'published' ? '已发布' : '归档'}</span>
                      <span className="text-[10px] text-muted-foreground/60">{fmt(n.last_updated)}</span>
                    </div>
                  </div>
                  {/* ... menu */}
                  <div className="relative" ref={menuOpen === n.id ? menuRef : undefined}>
                    <button onClick={() => setMenuOpen(menuOpen === n.id ? null : n.id)} className="p-1 rounded-md hover:bg-muted opacity-0 group-hover:opacity-100 transition-opacity">
                      <MoreHorizontal className="w-3.5 h-3.5 text-muted-foreground" />
                    </button>
                    {menuOpen === n.id && (
                      <div className="absolute right-0 top-full mt-1 bg-white rounded-lg shadow-lg border border-border py-1 z-30 min-w-[100px] animate-fade-in">
                        <button onClick={() => startEdit(n)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-muted transition-colors"><Edit3 className="w-3 h-3" />编辑</button>
                        <button onClick={() => remove(n.id)} className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-destructive hover:bg-red-50 transition-colors"><Trash2 className="w-3 h-3" />删除</button>
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
              <h3 className="text-base font-heading font-semibold">{editing ? '编辑笔记' : '新建笔记'}</h3>
              <button onClick={() => { setShowForm(false); setEditing(null); }} className="p-1.5 rounded-lg hover:bg-muted"><X className="w-4 h-4" /></button>
            </div>
            <div className="space-y-3">
              <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} className="w-full px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none" placeholder="标题" />
              <textarea value={form.content} onChange={e => setForm({ ...form, content: e.target.value })} className="w-full px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none" rows={4} placeholder="内容" />
              <div className="flex gap-3">
                <select value={form.tag} onChange={e => setForm({ ...form, tag: e.target.value })} className="flex-1 px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none bg-white">
                  <option value="">选择标签</option>
                  {PREDEFINED_TAGS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
                <select value={form.status} onChange={e => setForm({ ...form, status: e.target.value })} className="flex-1 px-3 py-2 text-sm border rounded-xl focus:ring-2 focus:ring-primary outline-none bg-white">
                  <option value="draft">草稿</option><option value="published">已发布</option><option value="archived">已归档</option>
                </select>
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