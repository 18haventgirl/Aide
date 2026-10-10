import type { HealthRecord, HealthRecordChange, HealthRecordCreateRequest } from './types';

export const healthTypeLabels = { symptom: '症状', vital: '测量', medication: '用药', visit: '就诊' };
export const healthDetailLabels: Record<string, string> = {
  body_site: '部位', severity: '程度', onset: '开始时间', duration: '持续时间', trend: '变化',
  temperature_c: '体温（℃）', associated_symptoms: '伴随症状', trigger: '诱因', relief: '缓解情况',
  medication_name: '药品名称', dose_text: '实际服用情况', visit_facility: '就诊机构', user_note: '补充记录',
};

export function healthEditableFields(type: HealthRecord['record_type'], details: Record<string, unknown>): string[] {
  const fields = { symptom: ['body_site', 'severity', 'duration', 'trend', 'associated_symptoms'],
    vital: ['temperature_c'], medication: ['medication_name', 'dose_text'], visit: ['visit_facility', 'user_note'] };
  const aliases: Record<string, string[]> = { temperature_c: ['体温', '体温值'], body_site: ['部位'],
    severity: ['程度'], duration: ['持续时间'], trend: ['变化'], medication_name: ['药品名称', '药名'], dose_text: ['实际服用情况'] };
  const defaults = fields[type].filter(key => key in details || !(aliases[key] || []).some(alias => alias in details));
  return [...new Set([...defaults, ...Object.keys(details).filter(key => !key.startsWith('_'))])];
}

export function chinaToday(now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  return ['year', 'month', 'day'].map(type => parts.find(p => p.type === type)?.value).join('-');
}

export function healthDate(value: string): Date {
  if (value.length === 10) value += 'T00:00:00';
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}+08:00`);
}

export function calendarDayKeys(month: string): string[] {
  if (!/^\d{4}-\d{2}$/.test(month)) throw new Error('Invalid month');
  const [year, number] = month.split('-').map(Number);
  if (year < 1 || number < 1 || number > 12) throw new Error('Invalid month');
  const first = new Date(0); first.setUTCFullYear(year, number - 1, 1); first.setUTCHours(0, 0, 0, 0);
  const start = first.getTime() - ((first.getUTCDay() + 6) % 7) * 86400000;
  return Array.from({ length: 42 }, (_, index) => new Date(start + index * 86400000).toISOString().slice(0, 10));
}

export function moveCalendarMonth(month: string, offset: number): string {
  const [year, number] = month.split('-').map(Number);
  const next = new Date(0); next.setUTCFullYear(year, number - 1 + offset, 1);
  return next.toISOString().slice(0, 7);
}

export function healthTime(record: Pick<HealthRecord, 'observed_at' | 'time_precision'>): string {
  const date = healthDate(record.observed_at);
  const day = date.toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric' });
  if (record.time_precision === 'day') return `${day} · 具体时刻未说明`;
  if (record.time_precision === 'unknown') return `${day} · 时间按对话记录`;
  return date.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

export function healthValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未说明';
  if (Array.isArray(value)) return value.map(healthValue).join('、');
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function historyChanges(change: HealthRecordChange): { label: string; before: string; after: string }[] {
  if (!change.before) return [];
  const fields = { title: '标题', summary: '描述', record_type: '类型', observed_at: '发生时间', time_precision: '时间精度' } as const;
  const rows: { label: string; before: string; after: string }[] = Object.entries(fields).flatMap(([field, label]) => {
    const key = field as keyof typeof fields;
    if (change.before?.[key] === change.after[key]) return [];
    const display = (record: Partial<HealthRecord>) => key === 'observed_at' && record.observed_at
      ? healthTime({ observed_at: record.observed_at, time_precision: record.time_precision || 'unknown' })
      : key === 'record_type' && record.record_type ? healthTypeLabels[record.record_type]
      : key === 'time_precision' ? ({ day: '仅日期', minute: '具体时刻', unknown: '按对话时间' }[record.time_precision || 'unknown'])
      : healthValue(record[key]);
    return [{ label, before: display(change.before!), after: display(change.after) }];
  });
  const keys = new Set([...Object.keys(change.before.details || {}), ...Object.keys(change.after.details || {})]);
  for (const key of keys) {
    if (key.startsWith('_')) continue;
    const before = healthValue(change.before.details?.[key]), after = healthValue(change.after.details?.[key]);
    if (before !== after) rows.push({ label: healthDetailLabels[key] || key, before, after });
  }
  return rows;
}

export interface HealthSaveAttempt { fingerprint: string; key: string }
export function createSaveAttempt(previous: HealthSaveAttempt | null, payload: HealthRecordCreateRequest, random = () => crypto.randomUUID()): HealthSaveAttempt {
  const fingerprint = JSON.stringify(payload);
  return previous?.fingerprint === fingerprint ? previous : { fingerprint, key: random() };
}
