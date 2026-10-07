import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ssrSourceModule } from '../support/ssr-source';
import { sourceModule } from '../support/source';
import rawFacts from '../fixtures/analytics/analytics-shift.json' with { type: 'json' };
import rawShift from '../fixtures/analytics/report-shift.json' with { type: 'json' };
import rawOrder from '../fixtures/analytics/report-order.json' with { type: 'json' };
import type * as Protocol from '../../src/shared/api/analyticsProtocol';
import type * as Reports from '../../src/features/analytics/Reports';
import type * as View from '../../src/features/analytics/AnalyticsView';
const protocol = sourceModule<typeof Protocol>('src/shared/api/analyticsProtocol.ts');
const reports = ssrSourceModule<typeof Reports>('src/features/analytics/Reports.tsx');
const { AnalyticsView } = ssrSourceModule<typeof View>('src/features/analytics/AnalyticsView.tsx', { './Reports': reports, './analytics.css': {} });
function shift(): Protocol.ShiftReport { const data: unknown = structuredClone(rawShift); if (!protocol.isShiftReport(data)) throw new Error('Invalid pinned synthetic shift fixture'); return data; }
function order(): Protocol.OrderReport { const data: unknown = structuredClone(rawOrder); if (!protocol.isOrderReport(data)) throw new Error('Invalid pinned synthetic order fixture'); return data; }
function facts(): Protocol.AnalyticsFacts { const data: unknown = structuredClone(rawFacts); if (!protocol.isAnalyticsFacts(data)) throw new Error('Invalid pinned synthetic facts fixture'); return data; }
const renderOrder = (data: Protocol.OrderReport) => renderToStaticMarkup(createElement(reports.OrderReportView, { data }));

test('report source strings render as literal escaped text without scripts, image loads, links or HTML insertion', () => {
  const html = renderOrder(order());
  expect(html).toContain('&lt;script&gt;synthetic literal task&lt;/script&gt;');
  expect(html).toContain('&lt;img src=');
  expect(html).not.toMatch(/<script\b|<img\b|<iframe\b|<a\b|onerror=/);
  const shiftHtml = renderToStaticMarkup(createElement(reports.ShiftReportView, { data: shift() }));
  expect(shiftHtml).toContain('&lt;img src=x onerror=alert(1)&gt;');
  expect(shiftHtml).not.toMatch(/<img\b/);
});

test('human missing and zero remain distinct from the separate rules recommendation99', () => {
  const data = order();
  const missing = renderOrder(data);
  expect(missing).toContain('Оценка мастера: <strong>Не оценено</strong>');
  expect(missing).toContain('Балл рекомендации: 99');
  data.order.attempts[0].review!.final_score = 0;
  const zero = renderOrder(data);
  expect(zero).toContain('Оценка мастера: <strong>0</strong>');
  expect(zero).toContain('Балл рекомендации: 99');
  expect(zero).toContain('Рекомендация не заменяет решение мастера');
});

test('period flows and domain-time snapshot stocks render in separate sections with lossless quantities', () => {
  const html = renderToStaticMarkup(createElement(reports.ShiftReportView, { data: shift() }));
  const split = html.indexOf('<h3>Состояние на доменное время снимка</h3>');
  const ratings = html.indexOf('<h3>Показатели исполнителей</h3>');
  expect(split).toBeGreaterThan(0);
  expect(html.slice(0, split)).toContain('Закрыто нарядов');
  expect(html.slice(0, split)).not.toContain('Просроченные активные наряды');
  expect(html.slice(split, ratings)).toContain('Просроченные активные наряды');
  expect(html.slice(split, ratings)).toContain('2026-10-08 07:00:00 UTC+5');
  expect(html).toContain('1.250 кг');
  expect(html).toContain('0.000000000000');
  expect(html).toContain('не подтверждённые складские списания');
});

test('historical unavailable disclosure uses scoped counts and preserves both false verification facts', () => {
  const data = shift();
  data.provenance.historical_evidence = { status: 'synthetic_historical_evidence_unavailable', historical_order_count: 1, historical_submission_count: 1, historical_after_photo_reference_count: 2, missing_after_photo_row_count: 2, physical_evidence_verified: false, historical_completeness_is_verified_evidence: false, source_commit: '8af3897f03aa2f41f0af07ec74ec2c807a4a535a', history_sha256: '7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1', loader_version: '1.1.0', identity_mapping_sha256: '56ec343e53e4f44208dfd5d5910e235b4626cda7c89f6b642e195c78945a5a64' };
  expect(protocol.isShiftReport(data)).toBe(true);
  const html = renderToStaticMarkup(createElement(reports.Provenance, { source: data.provenance, period: data.period }));
  expect(html).toContain('ссылок на фото после работ: 2');
  expect(html).toContain('отсутствующих записей фото: 2');
  expect(html).not.toContain('444');
  expect(html).toContain('Физические доказательства не проверены');
  expect(html).toContain('не означает проверку фото, выполнение ИИ или успешное живое закрытие');
  expect(html).toContain(data.provenance.historical_evidence.history_sha256);
  expect(html).toContain(data.provenance.historical_evidence.identity_mapping_sha256);
  expect(protocol.isShiftReport({ ...data, provenance: { ...data.provenance, historical_evidence: { ...data.provenance.historical_evidence, physical_evidence_verified: true } } })).toBe(false);
  const ordinary = renderToStaticMarkup(createElement(reports.Provenance, { source: shift().provenance, period: shift().period }));
  expect(ordinary).not.toContain('Исторические доказательства недоступны');
});

test('unavailable totals and unsupported inputs do not become zeroes, composite rankings or industrial efficacy', () => {
  const data = shift(); data.totals_available = false; data.metrics = null; data.ratings = null; data.closed_materials = null;
  const html = renderToStaticMarkup(createElement(reports.ShiftReportView, { data }));
  expect(html).toContain('Это не нулевой итог смены');
  expect(html).not.toContain('class="analytics-value"');
  expect(html).toContain('composite_rating:unsupported_inputs');
  expect(html).toContain('ai_job_state:not_supplied');
  expect(html).toContain('не вычисляются из отсутствующих показателей');
});

test('recorded stale assessment after human decision is labelled without inventing current AI-job status', () => {
  const data = order(); const assessment = data.order.attempts[0].assessments[0];
  assessment.stale = true; assessment.created_at = '2026-10-08T01:00:00Z'; assessment.mode = 'model'; assessment.model = 'SYNTHETIC-MODEL-LABEL';
  const html = renderOrder(data);
  expect(html).toContain('Устаревшая оценка');
  expect(html).toContain('Записана после решения мастера');
  expect(html).toContain('SYNTHETIC-MODEL-LABEL');
  expect(html).not.toContain('OpenAI');
  expect(html).not.toContain('Оценка текущей попытки по данным источника');
});

function viewProps(): View.AnalyticsViewProps {
  return { state: { facts: { status: 'idle', data: null, error: null }, report: { status: 'idle', data: null, error: null }, period: null }, draft: { start: '', end: '' }, onDraftChange() {}, onLoad() {}, onOpenReport() {}, domainNow: null, onRefreshClock() {}, validationError: null, selectedOrderId: '', onSelectOrder() {}, onPreset() {} };
}
test('idle, loading and failed analytics have no fake empty-data statement or previously captured figures', () => {
  const props = viewProps();
  const idle = renderToStaticMarkup(createElement(AnalyticsView, props));
  expect(idle).toContain('Время устройства не используется');
  expect(idle).toContain('Начало периода'); expect(idle).toContain('Конец периода (не включён)');
  for (const status of ['idle', 'loading', 'error'] as const) {
    props.state.facts = { status, data: null, error: status === 'error' ? 'SYNTHETIC_CAPTURE_LIMIT_NOT_EMPTY' : null };
    const html = renderToStaticMarkup(createElement(AnalyticsView, props));
    expect(html).not.toContain('В успешно полученном снимке нет доступных нарядов');
    expect(html).not.toContain('SYNTHETIC-OLD-CLOSED');
    expect(html).not.toContain('class="analytics-value"');
    if (status === 'error') expect(html).toContain('SYNTHETIC_CAPTURE_LIMIT_NOT_EMPTY');
  }
});

test('ready analytics shows its own captured period separately from newly edited controls', () => {
  const props = viewProps(); props.state.facts = { status: 'ready', data: facts(), error: null }; props.state.period = { ...rawFacts.period };
  props.draft = { start: '2026-09-01T00:00', end: '2026-09-02T00:00' };
  const html = renderToStaticMarkup(createElement(AnalyticsView, props));
  expect(html).toContain('value="2026-09-01T00:00"');
  expect(html).toContain('Период: 2026-10-08 00:00:00 UTC+5');
  expect(html).toContain('собственным временем снимка');
  expect(html).toContain('&lt;script&gt;synthetic literal task');
});
