import { FileSearch } from 'lucide-react';
import type { MedicalField } from '../services/medicalDocumentAPI';

interface Props {
  name: string; field: MedicalField; value: string; disabled: boolean;
  onChange: (value: string) => void; onEvidence: () => void;
}

export function MedicalParserField({ name, field, value, disabled, onChange, onEvidence }: Props) {
  const modified = value !== field.value;
  const compact = ['patient_name', 'sex', 'age', 'hospital', 'department', 'visit_date', 'admission_date', 'discharge_date'].includes(name);
  const controlProps = {
    id: `medical-${name}`, value, maxLength: 4000, disabled,
    onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value),
    placeholder: '未提取，可补充',
    className: 'field-control',
  };
  return <div className="min-w-0 space-y-2">
    <div className="flex items-center justify-between gap-2">
      <label htmlFor={`medical-${name}`} className="text-xs font-medium text-foreground">{field.label}</label>
      <span className={`text-[10px] ${modified ? 'text-blue-600' : field.status === 'needs_review' ? 'text-amber-700' : 'text-slate-400'}`}>
        {modified ? '已修正' : field.status === 'missing' ? '未提取' : field.status === 'needs_review' ? '待核对' : ''}
      </span>
    </div>
    {compact ? <input {...controlProps} /> : <textarea {...controlProps} rows={value.length > 70 ? 4 : 3} />}
    {field.evidence.length > 0 && <button type="button" onClick={onEvidence}
      className="inline-flex items-center gap-1 text-[11px] text-primary hover:underline">
      <FileSearch className="h-3 w-3" />{modified ? '查看修改前的提取依据' : `查看原文 · 第 ${[...new Set(field.evidence.map(line => line.page))].join('、')} 页`}
    </button>}
  </div>;
}
