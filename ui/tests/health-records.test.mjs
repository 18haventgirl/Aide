import assert from 'node:assert/strict';
import test from 'node:test';
import { calendarDayKeys, chinaToday, createSaveAttempt, healthDate, healthEditableFields, healthTime, historyChanges, moveCalendarMonth } from '../src/lib/health-records.ts';

test('Chinese calendar date crosses UTC midnight correctly', () => {
  assert.equal(chinaToday(new Date('2026-10-06T18:00:00Z')), '2026-10-07');
  assert.equal(healthDate('2026-10-07T00:00:00').toISOString(), '2026-10-06T16:00:00.000Z');
  assert.equal(healthDate('2026-10-07').toISOString(), '2026-10-06T16:00:00.000Z');
});

test('day and inferred precision do not pretend to know a clock', () => {
  assert.match(healthTime({ observed_at: '2026-10-07T00:00:00', time_precision: 'day' }), /具体时刻未说明/);
  assert.match(healthTime({ observed_at: '2026-10-07T12:30:00', time_precision: 'unknown' }), /按对话记录/);
  assert.match(healthTime({ observed_at: '2026-10-07T12:30:00', time_precision: 'minute' }), /12:30/);
});

test('calendar covers leap month and correct neighboring days in Monday order', () => {
  const days = calendarDayKeys('2024-02');
  assert.equal(days.length, 42);
  assert.equal(days[0], '2024-01-29');
  assert.ok(days.includes('2024-02-29'));
  assert.equal(new Set(days).size, 42);
  assert.equal(moveCalendarMonth('2026-01', -1), '2025-12');
  assert.equal(moveCalendarMonth('2026-12', 1), '2027-01');
  assert.throws(() => calendarDayKeys('2026-00'));
});

test('same save retries retain their idempotency key; changed facts get a new key', () => {
  const payload = { title: '合成记录', observed_at: '2026-10-07T00:00:00', time_precision: 'day', record_type: 'symptom', summary: '', details: {} };
  const first = createSaveAttempt(null, payload, () => 'first');
  const retry = createSaveAttempt(first, payload, () => { throw new Error('must reuse'); });
  const edited = createSaveAttempt(first, { ...payload, summary: '补充事实' }, () => 'second');
  assert.equal(retry.key, 'first');
  assert.equal(edited.key, 'second');
});

test('history shows changed health fields and excludes internal metadata', () => {
  const rows = historyChanges({ before: { summary: '原描述', details: { temperature_c: 37.2, _time: { expression: '昨天' } } }, after: { summary: '更正描述', details: { temperature_c: 36.8, _time: { expression: '今天' } } } });
  assert.deepEqual(rows.map(row => row.label), ['描述', '体温（℃）']);
  assert.equal(rows[1].after, '36.8');
  assert.deepEqual(historyChanges({ before: null, after: { title: '创建' } }), []);
});

test('legacy detail names remain editable without adding a duplicate temperature field', () => {
  const fields = healthEditableFields('vital', { 体温: '36.8℃', 测量时间: '09:00', _time: {} });
  assert.deepEqual(fields, ['体温', '测量时间']);
  assert.deepEqual(healthEditableFields('vital', {}), ['temperature_c']);
});
