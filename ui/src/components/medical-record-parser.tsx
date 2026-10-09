import { useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowUpRight, CheckCircle2, ClipboardCheck, ChevronRight, FileText, History, Loader2, Plus, RefreshCw, ScanLine, Trash2, Upload } from 'lucide-react';
import { WorkspaceHeader } from './workspace-header';
import { Button } from './ui/button';
import { ConfirmDialog, type Confirmation } from './ui/confirm-dialog';
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
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
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
  const open = async (id: string, discardChanges = false) => {
    if (busy) return;
    if (!discardChanges && draft && !saved && Object.keys(fields).some(key => fields[key] !== draft.result.fields[key]?.value)) {
      setConfirmation({ title: '打开其他记录？', description: '尚未保存的字段修正会丢失，原解析结果仍会保留。', confirmLabel: '继续打开', onConfirm: () => void open(id, true) });
      return;
    }
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
  const remove = async (id: string, confirmed = false) => {
    if (busy) return;
    if (!confirmed) {
      setConfirmation({ title: '删除这份解析记录？', description: '这份解析记录及其原文将被删除。已确认保存的健康记录仍会保留。', confirmLabel: '删除记录', destructive: true, onConfirm: () => void remove(id, true) });
      return;
    }
    setBusy('deleting'); setError('');
    try { await medicalDocumentAPI.remove(id); if (mounted.current) { if (draft?.id === id) reset(); await loadHistory(); } }
    catch (e) { if (mounted.current) setError(errorMessage(e)); }
    finally { if (mounted.current) setBusy(null); }
  };
  const newDocument = () => {
    if (draft && !saved) {
      setConfirmation({ title: '开始新的解析？', description: '未保存的字段修正会丢失。原解析结果可在「最近记录」中重新打开。', confirmLabel: '新建解析', onConfirm: reset });
      return;
    }
    reset();
  };

  return <section className="flex h-full min-h-0 flex-col" aria-label="病历解析工作区">
    {confirmation && <ConfirmDialog confirmation={confirmation} onDismiss={() => setConfirmation(null)} />}
    <WorkspaceHeader title="病历解析" description="从一份病历开始，整理每一次就诊。" actions={<>
      <Button variant="outline" size="sm" aria-expanded={historyOpen} onClick={() => { setHistoryOpen(!historyOpen); if (!historyOpen) void loadHistory(); }}><History className="h-4 w-4" />最近记录</Button>
      {draft && <Button size="sm" disabled={!!busy} onClick={newDocument}><Plus className="h-4 w-4" />新建解析</Button>}
    </>} />
    {historyOpen && <div className="mx-5 mb-4 max-h-64 shrink-0 overflow-y-auto rounded-xl border border-border bg-card p-4 sm:mx-8">
      <div className="mb-2 flex items-center justify-between text-xs text-muted-foreground"><span>最近 50 份记录</span><Button variant="ghost" size="icon" onClick={() => void loadHistory()} aria-label="刷新最近记录" className="h-8 w-8"><RefreshCw className="h-4 w-4" /></Button></div>
      {historyError && <p role="alert" className="text-sm text-amber-700">{historyError}</p>}
      {!historyError && history.length === 0 && <p className="py-5 text-center text-sm text-muted-foreground">还没有解析记录，上传第一份病历开始吧。</p>}
      {history.map(item => <div key={item.id} className="flex items-center gap-2 border-t border-border py-1">
        <button disabled={!!busy} onClick={() => void open(item.id)} className="flex min-w-0 flex-1 items-center gap-3 rounded-lg py-3 text-left text-sm hover:text-primary"><FileText className="h-4 w-4 shrink-0 text-muted-foreground" /><span className="truncate">{item.filename}</span><span className={`ml-auto shrink-0 rounded-md px-2 py-1 text-[11px] ${item.status === 'confirmed' ? 'bg-primary/5 text-primary' : 'bg-muted text-muted-foreground'}`}>{item.status === 'confirmed' ? '已保存' : '待核对'}</span><ChevronRight className="h-3.5 w-3.5 shrink-0" /></button>
        <Button variant="ghost" size="icon" disabled={!!busy} onClick={() => void remove(item.id)} aria-label={`删除 ${item.filename}`} className="h-8 w-8 text-muted-foreground hover:bg-red-50 hover:text-red-600"><Trash2 className="h-4 w-4" /></Button>
      </div>)}
    </div>}
    {error && <div role="alert" className="mx-5 mb-4 flex items-start gap-2 rounded-lg border border-destructive/20 bg-red-50 p-3 text-sm text-red-700 sm:mx-8"><AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />{error}</div>}
    <div aria-live="polite" className="sr-only">{busy === 'parsing' ? '正在读取文档并提取字段' : saved ? '已保存到身体状况' : draft ? '解析完成，请核对字段' : ''}</div>

    {!draft ? <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6 sm:px-8 sm:pb-8">
      <div className="mx-auto max-w-6xl">
        <ol aria-label="解析流程" className="mb-6 grid grid-cols-3 gap-2 rounded-xl border border-border bg-card p-3 sm:gap-6 sm:p-5">
          {['导入病历', '核对信息', '保存记录'].map((label, index) => <li key={label} className="flex items-center gap-1 sm:gap-3">
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-semibold sm:h-8 sm:w-8 sm:text-xs ${index === 0 ? 'bg-primary text-white' : 'bg-muted text-muted-foreground'}`}>0{index + 1}</span>
            <span className={`whitespace-nowrap text-[11px] sm:text-sm ${index === 0 ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>{label}</span>
            {index < 2 && <ChevronRight className="ml-auto hidden h-4 w-4 text-border sm:block" />}
          </li>)}
        </ol>
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
          <div className="surface-card overflow-hidden">
            <div className="border-b border-border px-5 pt-5 sm:px-6">
              <h2 className="text-base font-semibold">导入你的病历</h2>
              <p className="mt-1 text-xs leading-6 text-muted-foreground">支持门诊病历、出院小结，一次整理一份就诊材料。</p>
              <div className="mt-4 flex gap-6" role="tablist" aria-label="输入方式">
                {(['file', 'text'] as const).map(tab => <button role="tab" aria-selected={mode === tab} key={tab} disabled={!!busy} onClick={() => setMode(tab)} className={`rounded-none border-b-2 pb-3 text-sm ${mode === tab ? 'border-primary font-medium text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}>{tab === 'file' ? '上传文件' : '粘贴文字'}</button>)}
              </div>
            </div>
            <div className="p-5 sm:p-6">
              {mode === 'file' ? <>
                <input ref={fileInput} type="file" className="sr-only" aria-label="选择病历文件" accept=".pdf,.png,.jpg,.jpeg,.docx,.txt" disabled={!!busy} onChange={e => chooseFile(e.target.files?.[0])} />
                <button type="button" disabled={!!busy} onClick={() => fileInput.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) chooseFile(e.dataTransfer.files[0]); }} className="flex min-h-48 w-full flex-col items-center justify-center rounded-xl border border-dashed border-primary/30 bg-primary/[0.025] px-4 py-6 text-center hover:border-primary hover:bg-primary/5 disabled:opacity-60 sm:min-h-48">
                  <span className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl border border-border bg-card text-primary shadow-sm"><Upload className="h-6 w-6" strokeWidth={1.5} /></span>
                  <span className="max-w-full break-all text-sm font-medium text-foreground">{file ? file.name : '点击上传，或将文件拖到这里'}</span>
                  <span className="mt-2 text-xs leading-6 text-muted-foreground">{file ? `${(file.size / 1024).toFixed(0)} KB · 点击重新选择` : 'PDF / PNG / JPG / DOCX / TXT'}</span>
                  {!file && <span className="mt-4 rounded-md border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground">单份不超过 10 MB · 最多 12 页</span>}
                </button>
                <p className="mt-3 text-xs leading-6 text-muted-foreground">请保持照片清晰、方向正确，完整保留就诊日期与医嘱。</p>
              </> : <>
                <label htmlFor="medical-source-input" className="sr-only">病历原文</label>
                <textarea id="medical-source-input" value={text} disabled={!!busy} onChange={e => setText(e.target.value)} maxLength={40000} rows={10} placeholder="在这里粘贴病历原文…

保留就诊日期、诊断中的限定词和完整医嘱，方便逐项核对。" className="field-control min-h-60 resize-y sm:min-h-56" />
                <p className="mt-2 text-right text-xs tabular-nums text-muted-foreground">{text.length.toLocaleString()} / 40,000</p>
              </>}
              <div className="mt-5 flex flex-col gap-4 border-t border-border pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="max-w-xs text-xs leading-5 text-muted-foreground">解析后可逐项核对、修改，<br className="hidden sm:block" />确认后再保存到身体状况。</p>
                <Button onClick={() => void parse()} disabled={!!busy || (mode === 'file' ? !file : text.trim().length < 10)} className="shrink-0">{busy === 'parsing' ? <><Loader2 className="h-4 w-4 animate-spin" />正在解析…</> : <><ScanLine className="h-4 w-4" />开始解析</>}</Button>
              </div>
            </div>
          </div>
          <aside className="space-y-6">
            <div className="surface-card p-5">
              <span className="mb-4 inline-flex rounded-lg bg-primary/5 p-2 text-primary"><FileText className="h-5 w-5" /></span>
              <h2 className="text-sm font-semibold">先用一份样例试试</h2>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">没有病历在手边？用虚构材料体验完整的解析流程。</p>
              <div className="mt-4 space-y-2">{(['outpatient', 'discharge'] as const).map(type => <button disabled={!!busy} key={type} onClick={() => { setMode('text'); setText(samples[type]); setFile(null); setError(''); }} className="flex w-full items-center justify-between rounded-lg border border-border px-3 py-3 text-sm hover:border-primary/30 hover:bg-primary/5 hover:text-primary">{typeLabel(type)}<ArrowUpRight className="h-4 w-4 text-muted-foreground" /></button>)}</div>
              <p className="mt-3 text-[11px] text-muted-foreground">仅供演示 · 不包含真实个人信息</p>
            </div>
            <div className="px-1">
              <h3 className="flex items-center gap-2 text-sm font-medium"><ClipboardCheck className="h-4 w-4 text-primary" />提取信息，原文可查</h3>
              <p className="mt-2 text-xs leading-6 text-muted-foreground">提取基本信息、就诊经过、原文诊断与医嘱。点击字段依据，随时回到原文核对。</p>
              <div className="mt-4 border-t border-border pt-4 text-xs leading-6 text-muted-foreground">原文将发送至已配置的解析模型。成功后保留待核对记录，可在「最近记录」中管理。</div>
            </div>
          </aside>
        </div>
      </div>
    </div> : <>
      <div className="mx-5 mb-4 flex flex-wrap items-center gap-2 text-xs sm:mx-8">
        <span className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 ${saved ? 'bg-primary/10 text-primary' : 'bg-amber-50 text-amber-800'}`}><CheckCircle2 className="h-3.5 w-3.5" />{saved ? '已保存到身体状况' : '解析完成 · 待核对'}</span>
        <span className="text-muted-foreground">{typeLabel(draft.document_type)}</span><span className="max-w-full truncate text-muted-foreground">· {draft.filename}</span>
      </div>
      <div className="mx-5 mb-5 grid min-h-0 flex-1 auto-rows-max grid-cols-1 gap-5 overflow-y-auto lg:auto-rows-fr lg:grid-cols-2 lg:overflow-hidden sm:mx-8">
        <div className="surface-card flex h-80 flex-col overflow-hidden lg:h-auto lg:min-h-0">
          <div className="flex items-center justify-between border-b border-border px-5 py-4"><h2 className="flex items-center gap-2 text-sm font-semibold"><FileText className="h-4 w-4 text-muted-foreground" />病历原文</h2>{preview && <div className="flex gap-3 text-xs"><button onClick={() => setSourceTab('text')} className={sourceTab === 'text' ? 'text-primary' : 'text-muted-foreground'}>文字</button><button onClick={() => setSourceTab('file')} className={sourceTab === 'file' ? 'text-primary' : 'text-muted-foreground'}>文件预览</button></div>}</div>
          <div className="max-h-96 flex-1 overflow-auto p-4 lg:max-h-none">
            {sourceTab === 'file' && preview ? file?.name.toLowerCase().endsWith('.pdf') ? <iframe title="上传的病历 PDF" src={preview} className="h-[600px] w-full rounded-lg border bg-card" /> : <img src={preview} alt="上传的病历原件" className="w-full rounded-lg border bg-card" /> : <>
              <p className="mb-4 text-xs leading-5 text-muted-foreground">点击字段下的「查看原文」，定位提取依据。</p>
              {draft.result.source_lines.map(line => <div key={line.id} ref={line.id === highlight[0] ? firstLine : undefined} className={`flex gap-3 rounded-sm border-l-2 px-2 py-1.5 ${highlight.includes(line.id) ? 'border-primary bg-primary/5' : 'border-transparent'}`}><span className="mt-1 w-11 shrink-0 font-mono text-[10px] text-slate-400">{line.id}</span><p className="min-w-0 whitespace-pre-wrap break-words text-sm leading-7 text-foreground/80">{line.text}{line.method === 'ocr' && <span className="ml-2 text-[10px] text-muted-foreground">OCR</span>}</p></div>)}
            </>}
          </div>
        </div>
        <div className="surface-card lg:min-h-0 lg:overflow-y-auto">
          <div className="border-b border-border px-5 py-4"><h2 className="flex items-center gap-2 text-sm font-semibold"><ClipboardCheck className="h-4 w-4 text-muted-foreground" />{saved ? '确认后的信息' : '核对并修正信息'}</h2><p className="mt-2 text-xs leading-5 text-muted-foreground">{saved ? '已保存，可在「个人数据 → 身体状况」查看。' : '可直接编辑；未提取到的字段会留空。'}</p></div>
          <div className="p-5">
            {draft.result.warnings.length > 0 && <div className="mb-5 rounded-lg border border-amber-100 bg-amber-50 p-3 text-xs leading-6 text-amber-800">{draft.result.warnings.map((warning, i) => <p key={i}>{warning}</p>)}</div>}
            {groups.map((group, index) => <div key={group.title} className="mb-7 last:mb-0"><h3 className="mb-4 flex items-center gap-2 text-xs font-semibold text-muted-foreground"><span className="font-mono text-primary/70">0{index + 1}</span>{group.title}</h3><div className={`grid gap-5 ${index === 0 ? 'sm:grid-cols-2' : ''}`}>{group.keys.map(key => draft.result.fields[key] && <MedicalParserField key={key} name={key} field={draft.result.fields[key]} value={fields[key] || ''} disabled={saved || !!busy} onChange={value => setFields(current => ({ ...current, [key]: value }))} onEvidence={() => { setSourceTab('text'); setHighlight(draft.result.fields[key].evidence.map(line => line.id)); }} />)}</div></div>)}
          </div>
        </div>
      </div>
      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border bg-card px-5 py-3 sm:px-8">
        <div className="flex flex-wrap items-center gap-2"><label htmlFor="medical-observed-date" className="text-xs text-muted-foreground">记录归属日期</label><input type="date" id="medical-observed-date" value={observedDate} disabled={saved || !!busy} onChange={e => setObservedDate(e.target.value)} className="field-control w-auto py-1.5" />{!observedDate && <p className="text-xs text-amber-700">请填写日期后保存</p>}</div>
        <Button onClick={() => void confirm()} disabled={!!busy || !observedDate || saved} className="w-full sm:w-auto">{busy === 'saving' ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}{saved ? '已保存' : '确认并保存到身体状况'}</Button>
      </footer>
    </>}
  </section>;
}
