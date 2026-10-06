import { useEffect, useRef, useState } from 'react';
import { AlertCircle, Check, CheckCircle2, ChevronRight, FileText, History, Loader2, Plus, RefreshCw, ScanLine, Trash2, Upload } from 'lucide-react';
import { Button } from './ui/button';
import { MedicalParserField } from './medical-parser-field';
import { medicalDocumentAPI } from '../services/medicalDocumentAPI';
import type { MedicalDocument, MedicalDocumentSummary } from '../services/medicalDocumentAPI';

const samples = {
  outpatient: `【虚构演示样例】\n示例医院 门诊病历\n姓名：张示例\n性别：男\n年龄：35岁\n科室：全科门诊\n就诊日期：2026-10-06\n主诉：咳嗽3天。\n现病史：3天前出现干咳，无发热，否认胸痛及呼吸困难。\n既往史：否认高血压、糖尿病史。\n过敏史：青霉素过敏。\n查体：体温36.7℃，双肺呼吸音清。\n初步诊断：上呼吸道感染（待排）。\n处理：本次未开药。\n医嘱：休息、观察症状变化，必要时复诊。`,
  discharge: `【虚构演示样例】\n示例医院 出院小结\n姓名：李示例\n性别：女\n年龄：42岁\n科室：消化内科\n入院日期：2026年9月28日\n出院日期：2026年10月2日\n主诉：腹痛伴恶心1天。\n入院情况：患者腹痛伴恶心，无呕血。\n既往史：既往无手术史。\n过敏史：未详。\n出院诊断：急性胃炎。\n诊疗经过：入院后完善检查，予对症治疗，症状缓解。\n出院医嘱：按原就诊医生安排复诊；本样例未列出院带药。`,
};
const typeLabel = (type: string) => type === 'outpatient' ? '门诊病历' : type === 'discharge' ? '出院小结' : '病历记录';
const groups = [
  { title: '基本信息与时间', keys: ['patient_name', 'sex', 'age', 'hospital', 'department', 'visit_date', 'admission_date', 'discharge_date'] },
  { title: '就诊情况', keys: ['chief_complaint', 'present_history', 'past_history', 'allergies', 'examination'] },
  { title: '原文诊断与诊疗', keys: ['diagnosis', 'treatment', 'discharge_advice'] },
];
const errorMessage = (error: unknown) => {
  const e = error as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e.response?.data?.detail;
  return typeof detail === 'string' ? detail : '操作未完成，请检查服务连接后重试。';
};
function suggestedDate(document: MedicalDocument) {
  if (document.reviewed) return document.reviewed.observed_date;
  for (const key of ['discharge_date', 'visit_date', 'admission_date']) {
    const match = document.result.fields[key]?.value.match(/(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})/);
    if (match) return `${match[1]}-${match[2].padStart(2, '0')}-${match[3].padStart(2, '0')}`;
  }
  return '';
}

export function MedicalRecordParser({ onSaved }: { onSaved: () => void }) {
  const [mode, setMode] = useState<'file' | 'text'>('file');
  const [text, setText] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [draft, setDraft] = useState<MedicalDocument | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [observedDate, setObservedDate] = useState('');
  const [history, setHistory] = useState<MedicalDocumentSummary[]>([]);
  const [historyError, setHistoryError] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [busy, setBusy] = useState<'parsing' | 'saving' | 'opening' | 'deleting' | null>(null);
  const [error, setError] = useState('');
  const [highlight, setHighlight] = useState<string[]>([]);
  const [sourceTab, setSourceTab] = useState<'text' | 'file'>('text');
  const fileInput = useRef<HTMLInputElement>(null);
  const firstLine = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  const saved = draft?.status === 'confirmed';

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!file || !/\.(png|jpe?g|pdf)$/i.test(file.name)) { setPreview(''); return; }
    const url = URL.createObjectURL(file); setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => { firstLine.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }, [highlight]);

  const loadHistory = async () => {
    try {
      const rows = await medicalDocumentAPI.list();
      if (mounted.current) { setHistory(rows); setHistoryError(''); }
    } catch { if (mounted.current) setHistoryError('最近记录加载失败，可点击刷新重试。'); }
  };
  useEffect(() => { void loadHistory(); }, []);

  const applyDraft = (document: MedicalDocument) => {
    setDraft(document);
    setFields(document.reviewed?.fields || Object.fromEntries(Object.entries(document.result.fields).map(([key, value]) => [key, value.value])));
    setObservedDate(suggestedDate(document)); setHighlight([]); setSourceTab('text'); setError('');
  };
  const reset = () => { setDraft(null); setFile(null); setText(''); setFields({}); setError(''); setHighlight([]); };
  const chooseFile = (selected: File | undefined) => {
    if (!selected) return;
    if (selected.size > 10 * 1024 * 1024 || selected.size === 0) { setError('请选择非空文件，且大小不超过 10 MB。'); return; }
    if (!/\.(pdf|png|jpe?g|docx|txt)$/i.test(selected.name)) { setError('支持 PDF、PNG、JPG、DOCX 和 TXT。'); return; }
    setFile(selected); setError('');
  };
  const parse = async () => {
    setBusy('parsing'); setError('');
    try {
      const document = mode === 'file' && file ? await medicalDocumentAPI.parseFile(file) : await medicalDocumentAPI.parseText(text.trim());
      if (mounted.current) { applyDraft(document); await loadHistory(); }
    } catch (e) { if (mounted.current) setError(errorMessage(e)); }
    finally { if (mounted.current) setBusy(null); }
  };
  const open = async (id: string) => {
    if (busy) return;
    if (draft && !saved && Object.keys(fields).some(key => fields[key] !== draft.result.fields[key]?.value)
        && !window.confirm('尚未保存的字段修正会丢失，继续打开其他记录？')) return;
    setBusy('opening'); setError('');
    try { const document = await medicalDocumentAPI.get(id); if (mounted.current) { setFile(null); applyDraft(document); setHistoryOpen(false); } }
    catch (e) { if (mounted.current) setError(errorMessage(e)); }
    finally { if (mounted.current) setBusy(null); }
  };
  const confirm = async () => {
    if (!draft || !observedDate || saved || busy) return;
    setBusy('saving'); setError('');
    try {
      const document = await medicalDocumentAPI.confirm(draft.id, fields, observedDate);
      if (mounted.current) { applyDraft(document); onSaved(); await loadHistory(); }
    } catch (e) { if (mounted.current) setError(errorMessage(e)); }
    finally { if (mounted.current) setBusy(null); }
  };
  const remove = async (id: string) => {
    if (busy || !window.confirm('删除这份解析记录及其原文？已确认保存的健康记录仍会保留。')) return;
    setBusy('deleting'); setError('');
    try { await medicalDocumentAPI.remove(id); if (mounted.current) { if (draft?.id === id) reset(); await loadHistory(); } }
    catch (e) { if (mounted.current) setError(errorMessage(e)); }
    finally { if (mounted.current) setBusy(null); }
  };
  const newDocument = () => {
    if (draft && !saved && !window.confirm('开始新的解析？未保存的字段修正会丢失，原解析结果可在最近记录中重新打开。')) return;
    reset();
  };

  return <section className="flex h-full min-h-0 flex-col bg-slate-50/80" aria-label="病历解析工作区">
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/80 bg-white/80 px-5 py-4">
      <div className="flex items-center gap-3">
        <div className="rounded-xl bg-teal-50 p-2.5 text-teal-700"><ScanLine className="h-5 w-5" /></div>
        <div><h2 className="font-heading text-base font-semibold text-slate-900">病历解析</h2><p className="mt-0.5 text-xs text-slate-500">从门诊病历、出院小结中整理原文事实</p></div>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={() => { setHistoryOpen(!historyOpen); if (!historyOpen) void loadHistory(); }}><History className="mr-1.5 h-3.5 w-3.5" />最近记录</Button>
        {draft && <Button size="sm" variant="outline" disabled={!!busy} onClick={newDocument}><Plus className="mr-1 h-3.5 w-3.5" />新建解析</Button>}
      </div>
    </header>
    {historyOpen && <div className="max-h-64 shrink-0 overflow-y-auto border-b bg-white px-5 py-3">
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500"><span>最近 50 份 · 待核对记录可重新打开</span><button onClick={() => void loadHistory()} aria-label="刷新最近记录" className="rounded p-1 hover:bg-slate-100"><RefreshCw className="h-3.5 w-3.5" /></button></div>
      {historyError && <p role="alert" className="text-xs text-amber-700">{historyError}</p>}
      {!historyError && history.length === 0 && <p className="py-3 text-sm text-slate-400">还没有解析记录</p>}
      {history.map(item => <div key={item.id} className="flex items-center gap-2 border-t border-slate-100 py-2">
        <button disabled={!!busy} onClick={() => void open(item.id)} className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm hover:text-primary"><FileText className="h-4 w-4 shrink-0 text-slate-400" /><span className="truncate">{item.filename}</span><span className="ml-auto shrink-0 text-xs text-slate-500">{item.status === 'confirmed' ? '已保存' : '待核对'}</span><ChevronRight className="h-3 w-3 shrink-0" /></button>
        <button disabled={!!busy} onClick={() => void remove(item.id)} aria-label={`删除 ${item.filename}`} className="rounded p-2 text-slate-400 hover:bg-red-50 hover:text-red-600"><Trash2 className="h-3.5 w-3.5" /></button>
      </div>)}
    </div>}
    {error && <div role="alert" className="mx-5 mt-3 flex items-start gap-2 rounded-xl border border-red-100 bg-red-50 p-3 text-sm text-red-700"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
    <div aria-live="polite" className="sr-only">{busy === 'parsing' ? '正在读取文档并提取字段' : saved ? '已保存到身体状况' : draft ? '解析完成，请核对字段' : ''}</div>
    {!draft ? <div className="flex-1 overflow-y-auto p-5 sm:p-8">
      <div className="mx-auto max-w-2xl">
        <div className="mb-7 flex items-center gap-3 text-xs text-slate-400"><span className="font-medium text-teal-700">01 上传病历</span><span>—</span><span>02 核对信息</span><span>—</span><span>03 保存记录</span></div>
        <h3 className="text-2xl font-heading font-semibold tracking-tight text-slate-900">让病历更容易查阅</h3>
        <p className="mt-2 text-sm leading-6 text-slate-500">提取基本信息、就诊经过、原文诊断和医嘱。逐项核对后，保存到你的身体状况记录。</p>
        <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex border-b border-slate-100 px-5" role="tablist" aria-label="输入方式">
            {(['file', 'text'] as const).map(tab => <button role="tab" aria-selected={mode === tab} key={tab} disabled={!!busy} onClick={() => setMode(tab)} className={`mr-6 border-b-2 py-3 text-sm ${mode === tab ? 'border-teal-600 font-medium text-teal-700' : 'border-transparent text-slate-500'}`}>{tab === 'file' ? '上传文件' : '粘贴文字'}</button>)}
          </div>
          <div className="p-5">
            {mode === 'file' ? <>
              <input ref={fileInput} type="file" className="sr-only" aria-label="选择病历文件" accept=".pdf,.png,.jpg,.jpeg,.docx,.txt" disabled={!!busy} onChange={e => chooseFile(e.target.files?.[0])} />
              <button type="button" disabled={!!busy} onClick={() => fileInput.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) chooseFile(e.dataTransfer.files[0]); }} className="flex w-full flex-col items-center rounded-xl border-2 border-dashed border-teal-200 bg-teal-50/30 px-4 py-10 transition-colors hover:bg-teal-50 focus-visible:outline-teal-600 disabled:opacity-60">
                <Upload className="mb-4 h-8 w-8 text-teal-600" /><span className="max-w-full break-all text-sm font-medium text-slate-700">{file ? file.name : '点击选择，或拖放病历文件'}</span><span className="mt-2 text-xs text-slate-400">{file ? `${(file.size / 1024).toFixed(0)} KB · 点击重新选择` : 'PDF、PNG、JPG、DOCX、TXT · 最大 10 MB / 12 页'}</span>
              </button><p className="mt-3 text-xs text-slate-400">照片与扫描 PDF 使用本地 OCR；建议上传正向、清晰的单次就诊材料。</p>
            </> : <><label htmlFor="medical-source-input" className="sr-only">病历原文</label><textarea id="medical-source-input" value={text} disabled={!!busy} onChange={e => setText(e.target.value)} maxLength={40000} rows={12} placeholder="在这里粘贴完整病历，保留日期、诊断中的限定词和医嘱原文…" className="w-full rounded-xl border border-slate-200 p-3 text-sm leading-7 outline-none focus:border-teal-500 focus:ring-2 focus:ring-teal-50" /><p className="mt-1 text-right text-xs text-slate-400">{text.length.toLocaleString()} / 40,000</p></>}
            <Button onClick={() => void parse()} disabled={!!busy || (mode === 'file' ? !file : text.trim().length < 10)} className="mt-5 w-full bg-teal-700 hover:bg-teal-800">{busy === 'parsing' ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />正在读取并提取，请稍候…</> : <><ScanLine className="mr-2 h-4 w-4" />开始解析</>}</Button>
            <p className="mt-3 text-center text-[11px] leading-5 text-slate-400">原文将发送至已配置的解析模型。成功后保留待核对记录，可在最近记录中删除。</p>
          </div>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-3 text-xs"><span className="text-slate-400">先体验虚构样例</span>{(['outpatient', 'discharge'] as const).map(type => <button disabled={!!busy} key={type} onClick={() => { setMode('text'); setText(samples[type]); setFile(null); setError(''); }} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-slate-600 hover:border-teal-300 hover:text-teal-700">{typeLabel(type)} <span aria-hidden>↗</span></button>)}</div>
      </div>
    </div> : <>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200/70 px-5 py-3 text-xs">
        <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 ${saved ? 'bg-teal-100 text-teal-800' : 'bg-amber-50 text-amber-800'}`}>{saved ? <CheckCircle2 className="h-3 w-3" /> : <Check className="h-3 w-3" />}{saved ? '已保存到身体状况' : '解析完成 · 待核对'}</span><span className="text-slate-500">{typeLabel(draft.document_type)}</span><span className="min-w-0 truncate text-slate-400">{draft.filename}</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(260px,0.9fr)_minmax(340px,1.1fr)] lg:overflow-hidden">
        <div className="flex min-h-[280px] flex-col border-b border-slate-200 bg-slate-100/60 lg:min-h-0 lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between px-5 py-3"><h3 className="text-sm font-semibold text-slate-700">病历原文</h3>{preview && <div className="flex gap-2 text-xs"><button onClick={() => setSourceTab('text')} className={sourceTab === 'text' ? 'text-primary' : 'text-slate-400'}>文字</button><button onClick={() => setSourceTab('file')} className={sourceTab === 'file' ? 'text-primary' : 'text-slate-400'}>文件预览</button></div>}</div>
          <div className="max-h-[380px] flex-1 overflow-auto px-4 pb-5 lg:max-h-none">
            {sourceTab === 'file' && preview ? file?.name.toLowerCase().endsWith('.pdf') ? <iframe title="上传的病历 PDF" src={preview} className="h-[600px] w-full rounded-lg border bg-white" /> : <img src={preview} alt="上传的病历原件" className="w-full rounded-lg border bg-white" /> : <div className="rounded-xl border border-slate-200 bg-white py-4 shadow-sm">
              <p className="mb-3 px-4 text-[10px] text-slate-400">点击字段下的“查看原文”定位提取依据</p>
              {draft.result.source_lines.map(line => <div key={line.id} ref={line.id === highlight[0] ? firstLine : undefined} className={`flex gap-3 px-4 py-1.5 ${highlight.includes(line.id) ? 'border-l-2 border-teal-500 bg-teal-50' : 'border-l-2 border-transparent'}`}><span className="mt-0.5 w-12 shrink-0 font-mono text-[9px] text-slate-400">{line.id}</span><p className="min-w-0 whitespace-pre-wrap break-words text-xs leading-6 text-slate-700">{line.text}{line.method === 'ocr' && <span className="ml-2 text-[9px] text-slate-400">OCR</span>}</p></div>)}
            </div>}
          </div>
        </div>
        <div className="px-5 py-4 lg:overflow-y-auto">
          <h3 className="text-sm font-semibold text-slate-800">{saved ? '确认后的信息' : '核对并修正信息'}</h3>
          <p className="mt-1 text-xs leading-5 text-slate-400">{saved ? '已保存的结果可在「个人数据 → 身体状况」查看。' : '空白表示未提取到，不代表没有该项情况。可直接编辑字段。'}</p>
          {draft.result.warnings.length > 0 && <div className="mt-4 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs leading-6 text-amber-800">{draft.result.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div>}
          {groups.map(group => <div key={group.title} className="mt-6"><h4 className="mb-3 border-b border-slate-200 pb-2 text-xs font-semibold text-slate-500">{group.title}</h4><div className={`grid gap-4 ${group.title === '基本信息与时间' ? 'sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2' : ''}`}>{group.keys.map(key => draft.result.fields[key] && <MedicalParserField key={key} name={key} field={draft.result.fields[key]} value={fields[key] || ''} disabled={saved || !!busy} onChange={value => setFields(current => ({ ...current, [key]: value }))} onEvidence={() => { setSourceTab('text'); setHighlight(draft.result.fields[key].evidence.map(line => line.id)); }} />)}</div></div>)}
        </div>
      </div>
      <footer className="flex shrink-0 flex-wrap items-end justify-between gap-3 border-t border-slate-200 bg-white px-5 py-3">
        <div><label htmlFor="medical-observed-date" className="mb-1 block text-xs text-slate-500">记录归属日期 · 请核对就诊 / 出院时间</label><input type="date" id="medical-observed-date" value={observedDate} disabled={saved || !!busy} onChange={e => setObservedDate(e.target.value)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm outline-none focus:border-primary" />{!observedDate && <p className="mt-1 text-[10px] text-amber-700">未读取到完整日期，请填写后保存。</p>}</div>
        <Button onClick={() => void confirm()} disabled={!!busy || !observedDate || saved} className="bg-teal-700 hover:bg-teal-800">{busy === 'saving' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-2 h-4 w-4" />}{saved ? '已保存' : '确认并保存到我的身体状况'}</Button>
      </footer>
    </>}
  </section>;
}
