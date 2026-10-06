import { FileSearch } from 'lucide-react';
import type { MedicalField } from '../services/medicalDocumentAPI';

interface Props {
  name: string; field: MedicalField; value: string; disabled: boolean;
  onChange: (value: string) => void; onEvidence: () => void;
}

export function MedicalParserField({ name, field, value, disabled, onChange, onEvidence }: Props) {
  const modified = value !== field.value;
  return <div className="space-y-1.5">
    <div className="flex items-center justify-between gap-2">
      <label htmlFor={`medical-${name}`} className="text-xs font-medium text-slate-600">{field.label}</label>
      <span className={`text-[10px] ${modified ? 'text-blue-600' : field.status === 'needs_review' ? 'text-amber-700' : 'text-slate-400'}`}>
        {modified ? '已修正' : field.status === 'missing' ? '原文未提取' : field.status === 'needs_review' ? '识别待核对' : '有原文依据'}
      </span>
    </div>
    <textarea id={`medical-${name}`} value={value} maxLength={4000} disabled={disabled}
      onChange={event => onChange(event.target.value)} rows={value.length > 70 ? 4 : 2}
      placeholder="未提取，可核对原文后补充"
      className="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 disabled:bg-slate-50 disabled:text-slate-700" />
    {field.evidence.length > 0 && <button type="button" onClick={onEvidence}
      className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline">
      <FileSearch className="h-3 w-3" />{modified ? '查看修改前的提取依据' : `查看原文 · 第 ${[...new Set(field.evidence.map(line => line.page))].join('、')} 页`}
    </button>}
  </div>;
}
