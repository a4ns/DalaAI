import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import { deferred, ids, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as ReportProtocol from '../../src/features/aiReports/protocol';
import type * as ReportController from '../../src/features/aiReports/controller';
import type * as AssigneeProtocol from '../../src/features/assigneeRecommendations/protocol';
import type * as AssigneeController from '../../src/features/assigneeRecommendations/controller';
import type * as ReportView from '../../src/features/aiReports/AiReportView';
import type * as AssigneeView from '../../src/features/assigneeRecommendations/AssigneeRecommendationsView';
import type * as Reports from '../../src/features/analytics/Reports';
import type { AssistanceRuntime, AssistanceSession } from '../../src/features/aiReports/session';

const { ApiError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const reportProtocol = sourceModule<typeof ReportProtocol>('src/features/aiReports/protocol.ts');
const assigneeProtocol = sourceModule<typeof AssigneeProtocol>('src/features/assigneeRecommendations/protocol.ts');
const { AiReportController } = sourceModule<typeof ReportController>('src/features/aiReports/controller.ts');
const { AssigneeRecommendationsController, assigneeContextKey } = sourceModule<typeof AssigneeController>('src/features/assigneeRecommendations/controller.ts');
const reports = ssrSourceModule<typeof Reports>('src/features/analytics/Reports.tsx');
const { AiReportView } = ssrSourceModule<typeof ReportView>('src/features/aiReports/AiReportView.tsx', { '../analytics/Reports': reports, './aiReports.css': {} });
const { AssigneeRecommendationsView } = ssrSourceModule<typeof AssigneeView>('src/features/assigneeRecommendations/AssigneeRecommendationsView.tsx', { './assigneeRecommendations.css': {} });
const asOf = '2026-10-08T04:00:00Z';
const selection: ReportProtocol.AiReportSelection = { start: '2026-10-07T04:00:00Z', end: asOf, sourceRef: 'SYNTHETIC-SNAPSHOT-1' };
const body: ReportProtocol.AiReportRequest = { operation_id: ids.event, start: selection.start, end: selection.end, report_kind: 'shift' };
const context: AssigneeController.AssigneeContext = { sectionId: ids.section, workCodeId: null, brigadeId: '', draftKey: 'SYNTHETIC-DRAFT-1', dictionaryKey: 'SYNTHETIC-DICT-1' };
const executor: AssigneeController.EligibleExecutor = { id: ids.second, label: 'Синтетический исполнитель', sectionIds: [ids.section], brigadeId: null, onShift: true };

class FakeSession implements AssistanceSession {
  epoch = 1; session: Client.ApiClient['session'] = session(); listeners = new Set<() => void>();
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  clear() { this.epoch++; this.session = null; this.notify(); }
  notify() { this.listeners.forEach(listener => listener()); }
}
function time() {
  let now = Date.parse(asOf); let uuidCount = 0;
  const jobs = new Set<{ at: number; callback: () => void }>();
  const runtime: AssistanceRuntime = { now: () => now, uuid: () => { uuidCount++; return ids.event; }, schedule: (callback, delay) => { const job = { at: now + delay, callback }; jobs.add(job); return () => { jobs.delete(job); }; } };
  return { runtime, jobs, uuidCount: () => uuidCount, set: (next: number) => { now = next; }, advance: (ms: number) => { now += ms; for (const job of [...jobs]) if (job.at <= now) { jobs.delete(job); job.callback(); } } };
}
function report(request = body): ReportProtocol.AiReport {
  return {
    schema_version: 'ai-report-summary/1', operation_id: request.operation_id, report_kind: request.report_kind,
    mode: 'deterministic_fallback', label: 'Синтетическая фактическая сводка', summary: '<script>synthetic literal summary</script>',
    highlights: [{ fact_id: 'm_closed_orders', text: 'Закрыто: 1', source_table: 'reviews', source_ids: [ids.first], equipment_id: null }],
    recommendations: [{ code: 'check_small_sample', text: '<img src=x onerror=alert(1)>', fact_ids: ['m_closed_orders'] }],
    provenance: { synthetic: true, source_ref: 'SYNTHETIC-RECAPTURE-2', scope_description: 'Синтетический разрешённый участок', domain_as_of: asOf, captured_at_real: asOf, coverage: 'consistent_snapshot', history_complete: true },
    period: { start: request.start, end: request.end, display_timezone: 'Asia/Almaty' }, limitations: ['Фото недоступны'], unavailable_reasons: [],
    fallback_reason: 'key_unavailable', model: null, generated_at_real: asOf, advisory: true, reserved_upper_bound_microusd: 0, actual_billed_cost: null,
  };
}
function advice(): AssigneeProtocol.AssigneeRecommendations {
  return {
    schema_version: '1', mode: 'rules_baseline', model: null, model_status: 'disabled_for_purpose', advisory_only: true, synthetic: true,
    section_id: ids.section, work_code_id: null, as_of: asOf, domain_as_of: asOf, expires_at: '2026-10-08T04:00:30Z', eligible_count: 1, returned_count: 1,
    candidates: [{ executor_id: ids.second, employee_code: 'SYNTHETIC-EXECUTOR', rank: 1, on_shift: true,
      workload: { outstanding_count: 0, active_count: 0, queued_count: 0, awaiting_review_count: 0, overdue_count: 0, norm_minutes_total: 0, status_counts: { issued: 0, queued: 0, accepted: 0, in_progress: 0, paused: 0, rework: 0, done: 0, ai_review: 0 }, scope: 'current_master_authorized_sections', evidence: [], evidence_truncated: false },
      history: { status: 'no_observations', window_start: '2026-07-10T04:00:00Z', window_end: asOf, closed_count: 0, matching_work_code_count: null, human_score_mean: null, human_score_count: 0, on_time_rate: null, on_time_count: 0, latest_closed_at: null, evidence: [], evidence_truncated: false },
      reason_codes: ['ACTIVE_ON_SHIFT', 'SELECTED_SECTION_MEMBER', 'NO_VISIBLE_OUTSTANDING_ORDERS', 'NO_CLOSED_HISTORY', 'HUMAN_SCORE_UNKNOWN', 'WORK_CODE_NOT_SELECTED'],
    }], limitations: ['DETERMINISTIC_RULES_NOT_AI', 'QUALIFICATIONS_UNVERIFIED', 'WORKLOAD_VISIBLE_SCOPE_ONLY', 'WORKLOAD_NORM_NOT_REMAINING', 'SNAPSHOT_NOT_RESERVATION', 'HISTORICAL_OBSERVATIONS_NOT_SKILL', 'SYNTHETIC_DATA', 'ONLY_ONE_ELIGIBLE_EXECUTOR'], ranking_policy: 'outstanding_then_active_then_observed_work_code_v1',
  };
}
function reportHarness(send: ReportController.AiReportTransport = async request => report(request)) {
  const client = new FakeSession(); const clock = time(); let ready = true;
  const controller = new AiReportController(client, send, () => ready, undefined, clock.runtime);
  controller.setSelection(selection); const stop = controller.attach();
  return { client, clock, controller, stop, setReady: (value: boolean) => { ready = value; } };
}
function adviceHarness(send: AssigneeController.AssigneeTransport = async () => advice()) {
  const client = new FakeSession(); const clock = time(); let selected = { ...context }; let executors = [{ ...executor }]; let ready = true;
  const controller = new AssigneeRecommendationsController(client, send, () => selected, () => executors, () => ready, undefined, clock.runtime);
  controller.synchronize(); const stop = controller.attach();
  return { client, clock, controller, stop, context: () => selected, setContext: (next: AssigneeController.AssigneeContext) => { selected = next; }, setExecutors: (next: AssigneeController.EligibleExecutor[]) => { executors = next; }, setReady: (value: boolean) => { ready = value; } };
}

test('report and recommendation mounts remain inert; no transport is invoked without an explicit action', () => {
  let calls = 0; const r = reportHarness(async request => { calls++; return report(request); }); const a = adviceHarness(async () => { calls++; return advice(); });
  expect(calls).toBe(0); expect(r.controller.getSnapshot().status).toBe('idle'); expect(a.controller.getSnapshot().status).toBe('idle'); r.stop(); a.stop();
});
test('report decoder binds exact operation, period and kind, rejecting unsupported provenance or invented fact references', () => {
  expect(reportProtocol.decodeAiReport(report(), body).provenance.source_ref).toBe('SYNTHETIC-RECAPTURE-2');
  for (const wrong of [{ ...report(), operation_id: ids.first }, { ...report(), report_kind: 'history' }, { ...report(), period: { ...report().period, start: '2026-10-07T05:00:00Z' } }, { ...report(), mode: 'unknown' }, { ...report(), advisory: false }, { ...report(), mode: 'openai' }, { ...report(), model: 'fake-model' }, { ...report(), recommendations: [{ code: 'x', text: 'x', fact_ids: ['invented'] }] }]) expect(() => reportProtocol.decodeAiReport(wrong, body)).toThrow();
});
test('report request caps distinguish shift and history and refuse provider work before invalid requests', async () => {
  let calls = 0; const h = reportHarness(async request => { calls++; return report(request); });
  h.controller.setSelection({ ...selection, start: '2026-10-06T04:00:00Z' }); await h.controller.generate('shift');
  expect(calls).toBe(0); expect(h.controller.getSnapshot().status).toBe('error');
  await h.controller.generate('history'); expect(calls).toBe(1); h.stop();
});
test('report double click shares one pending request; lost response retries exact frozen body and operation', async () => {
  const late = deferred<unknown>(); const requests: Readonly<ReportProtocol.AiReportRequest>[] = [];
  const h = reportHarness(async request => { requests.push(request); return requests.length === 1 ? late.promise : report(request); });
  const first = h.controller.generate('shift'); await h.controller.generate('history'); expect(requests).toHaveLength(1); expect(Object.isFrozen(requests[0])).toBe(true);
  late.reject(new ApiError('Lost', 0, null, true, null, true)); await first;
  expect(h.controller.getSnapshot().status).toBe('unknown_result'); await h.controller.generate('history'); expect(requests).toHaveLength(1);
  await h.controller.retry(); expect(requests).toHaveLength(2); expect(requests[1]).toBe(requests[0]); expect(h.clock.uuidCount()).toBe(1); expect(h.controller.getSnapshot().status).toBe('ready'); h.stop();
});
test('unknown report remains unknown after an explicit retry encounters a cooldown', async () => {
  let calls = 0; const h = reportHarness(async () => { if (++calls === 1) throw new ApiError('Lost', 0, null, true); throw new ApiError('Cooldown', 429); });
  await h.controller.generate('shift'); await h.controller.retry(); expect(h.controller.getSnapshot().status).toBe('unknown_result'); await h.controller.generate('history'); expect(calls).toBe(2); h.stop();
});
test('malformed successful report is unknown, not fabricated success or a fresh operation', async () => {
  const h = reportHarness(async () => ({ ...report(), operation_id: ids.first })); await h.controller.generate('shift');
  expect(h.controller.getSnapshot()).toMatchObject({ status: 'unknown_result', data: null }); h.stop();
});
test('report new selection hides old content and ignores a late previous response, even when abort is ignored', async () => {
  const late = deferred<unknown>(); const h = reportHarness(async () => late.promise);
  const pending = h.controller.generate('shift'); h.controller.setSelection({ ...selection, sourceRef: 'NEW-SNAPSHOT' });
  late.resolve(report()); await pending; expect(h.controller.getSnapshot()).toMatchObject({ status: 'idle', data: null }); h.stop();
});
test('report logout, changed authority, auth busy and expiry all fence delayed publication', async () => {
  for (const invalidate of ['logout', 'authority', 'busy', 'expiry'] as const) {
    const late = deferred<unknown>(); const h = reportHarness(async () => late.promise); const pending = h.controller.generate('shift');
    if (invalidate === 'logout') h.client.clear();
    if (invalidate === 'authority') { h.client.epoch++; h.client.notify(); }
    if (invalidate === 'busy') h.setReady(false);
    if (invalidate === 'expiry') { h.client.session!.expires_at = asOf; h.client.notify(); }
    late.resolve(report()); await pending; expect(h.controller.getSnapshot().data).toBeNull(); expect(h.controller.current()).toBe(false); h.stop();
  }
});
test('session expiry timer clears an already displayed report without provider polling', async () => {
  const h = reportHarness(); h.client.session!.expires_at = '2026-10-08T04:00:05Z'; h.client.notify(); await h.controller.generate('shift');
  expect(h.controller.getSnapshot().status).toBe('ready'); h.clock.advance(5000); expect(h.controller.getSnapshot().data).toBeNull(); h.stop();
});
test('role guards refuse both features for executor, manager, admin or inactive principal', async () => {
  for (const role of ['executor', 'manager', 'admin'] as const) {
    let calls = 0; const h = reportHarness(async request => { calls++; return report(request); }); const a = adviceHarness(async () => { calls++; return advice(); });
    h.client.session!.principal.role = role; a.client.session!.principal.role = role;
    await h.controller.generate('shift'); await a.controller.load(); expect(calls).toBe(0); h.stop(); a.stop();
  }
  let calls = 0; const h = adviceHarness(async () => { calls++; return advice(); }); h.client.session!.principal.active = false; await h.controller.load(); expect(calls).toBe(0); h.stop();
});
test('recommendation decoder refuses wrong scope, stale TTL, unknown model and missing/zero confusion', () => {
  const request = { section_id: ids.section, work_code_id: null, limit: 3 }; expect(assigneeProtocol.decodeAssigneeRecommendations(advice(), request, Date.parse(asOf))).toBeTruthy();
  const scoredWithoutObservations = advice(); scoredWithoutObservations.candidates[0].history.human_score_mean = 0;
  for (const invalid of [{ ...advice(), section_id: ids.first }, { ...advice(), work_code_id: ids.order }, { ...advice(), expires_at: asOf }, { ...advice(), expires_at: '2026-10-08T04:02:00Z' }, { ...advice(), mode: 'openai' }, { ...advice(), returned_count: 2 }, scoredWithoutObservations]) expect(() => assigneeProtocol.decodeAssigneeRecommendations(invalid, request, Date.parse(asOf))).toThrow();
});
test('recommendation does not choose on load and choose rechecks current dictionary rather than trusting response', async () => {
  const h = adviceHarness(); await h.controller.load(); expect(h.controller.getSnapshot().status).toBe('ready');
  expect(h.controller.choose(ids.first)).toBeNull(); await h.controller.load(); expect(h.controller.choose(ids.second)).toBe(ids.second);
  h.setExecutors([]); expect(h.controller.choose(ids.second)).toBeNull(); expect(h.controller.getSnapshot().data).toBeNull(); h.stop();
});
test('recommendation rejects changed on-shift/section/brigade eligibility at the choose boundary', async () => {
  for (const changed of [{ ...executor, onShift: false }, { ...executor, sectionIds: [ids.first] }, { ...executor, brigadeId: ids.order }]) {
    const h = adviceHarness(); if (changed.brigadeId) h.setContext({ ...context, brigadeId: ids.first });
    await h.controller.load(); h.setExecutors([changed]); expect(h.controller.choose(ids.second)).toBeNull(); h.stop();
  }
});
test('recommendation context changes invalidate results for equipment/task/dictionary changes and stale responses', async () => {
  for (const change of [{ ...context, draftKey: 'different-equipment' }, { ...context, dictionaryKey: 'new-dictionary' }, { ...context, sectionId: ids.first }]) {
    const late = deferred<unknown>(); const h = adviceHarness(async () => late.promise); const pending = h.controller.load(); h.setContext(change); h.controller.synchronize();
    late.resolve(advice()); await pending; expect(h.controller.getSnapshot().data).toBeNull(); expect(h.controller.choose(ids.second)).toBeNull(); h.stop();
  }
});
test('recommendation expiry clears data; delayed timer never permits an expired choice', async () => {
  const h = adviceHarness(); await h.controller.load(); h.clock.advance(30000); expect(h.controller.getSnapshot()).toMatchObject({ status: 'expired', data: null }); h.stop();
  const delayed = adviceHarness(); await delayed.controller.load(); delayed.clock.set(Date.parse(asOf) + 31000); expect(delayed.controller.choose(ids.second)).toBeNull(); expect(delayed.controller.getSnapshot().status).toBe('expired'); delayed.stop();
});
test('recommendation refresh failures hide old private data, and session loss ignores late response', async () => {
  let calls = 0; const h = adviceHarness(async () => { if (++calls === 1) return advice(); throw new ApiError('Forbidden', 403); });
  await h.controller.load(); await h.controller.load(); expect(h.controller.getSnapshot()).toMatchObject({ status: 'error', data: null }); h.stop();
  const late = deferred<unknown>(); const lost = adviceHarness(async () => late.promise); const pending = lost.controller.load(); lost.client.clear(); late.resolve(advice()); await pending;
  expect(lost.controller.getSnapshot().data).toBeNull(); lost.stop();
});
test('recommendation source count is not fabricated when only one candidate or no candidates exist', async () => {
  const h = adviceHarness(); await h.controller.load(); expect(h.controller.getSnapshot().data?.candidates).toHaveLength(1); h.stop();
  const empty = advice(); empty.eligible_count = 0; empty.returned_count = 0; empty.candidates = []; empty.limitations = ['NO_ELIGIBLE_EXECUTORS'];
  const none = adviceHarness(async () => empty); await none.controller.load(); expect(none.controller.getSnapshot()).toMatchObject({ status: 'ready', data: { candidates: [], eligible_count: 0 } }); none.stop();
});
test('report literal rendering escapes model/server text and discloses mode, snapshot dates and missing photos', () => {
  const value = report(); value.provenance.historical_evidence = { status: 'synthetic_historical_evidence_unavailable', historical_order_count: 1, historical_submission_count: 1, historical_after_photo_reference_count: 2, missing_after_photo_row_count: 2, physical_evidence_verified: false, historical_completeness_is_verified_evidence: false, source_commit: 'synthetic', history_sha256: 'synthetic', loader_version: '1', identity_mapping_sha256: 'synthetic' };
  const render = (data: ReportProtocol.AiReport) => renderToStaticMarkup(createElement(AiReportView, { state: { status: 'ready', selectionKey: '', data, error: null }, selection, disabled: false, onGenerate: () => {}, onRetry: () => {} }));
  const html = render(value); expect(html).toContain('&lt;script&gt;synthetic literal summary&lt;/script&gt;'); expect(html).not.toMatch(/<script\b|<img\b|<iframe\b|<a\b/);
  expect(html).toContain('Фактическая сводка по правилам, без ответа модели'); expect(html).toContain('Физические доказательства не проверены'); expect(html).toContain('UTC+5'); expect(html).toContain('m_closed_orders');
  expect(render({ ...value, mode: 'recorded_fixture', model: 'recorded-model', fallback_reason: null })).toContain('Записанный пример, без живого вызова модели');
  expect(render({ ...value, mode: 'openai', model: 'synthetic-model', fallback_reason: null })).toContain('OpenAI выбрал факты и рекомендации; текст построен сервером');
});
test('recommendation rendering labels rules, one candidate, unknown quality and explicit human choice without HTML interpretation', () => {
  const value = advice(); value.candidates[0].employee_code = '<script>synthetic</script>';
  const html = renderToStaticMarkup(createElement(AssigneeRecommendationsView, { state: { status: 'ready', contextKey: assigneeContextKey(context), data: value, error: null }, context, executors: [executor], disabled: false, onLoad: () => {}, onChoose: () => {} }));
  expect(html).toContain('Модель ИИ не вызывается'); expect(html).toContain('Доступен один исполнитель'); expect(html).toContain('Качество и опыт неизвестны'); expect(html).toContain('Средняя оценка мастера: неизвестна'); expect(html).toContain('Выбрать Синтетический исполнитель в черновике'); expect(html).toContain('&lt;script&gt;synthetic&lt;/script&gt;'); expect(html).not.toContain('<script>');
});

test('backend serializer report fixture and frozen recommendation example pass exact frontend decoders', async () => {
  const rawReport = (await import('../../src/features/aiReports/__fixtures__/serializer-response.json', { with: { type: 'json' } })).default;
  const rawAdvice = (await import('../../src/features/assigneeRecommendations/__fixtures__/contract-response.json', { with: { type: 'json' } })).default;
  expect(reportProtocol.isAiReport(rawReport)).toBe(true);
  const decoded = reportProtocol.decodeAiReport(rawReport, { operation_id: rawReport.operation_id, start: rawReport.period.start, end: rawReport.period.end, report_kind: rawReport.report_kind as ReportProtocol.AiReportKind });
  expect(decoded.mode).toBe('deterministic_fallback');
  expect(assigneeProtocol.decodeAssigneeRecommendations(rawAdvice, { section_id: rawAdvice.section_id, work_code_id: null, limit: 3 }, Date.parse(rawAdvice.as_of)).eligible_count).toBe(1);
});

test('session expiry remains armed through initially busy UI and clears a later ready response', async () => {
  const client = new FakeSession(); const clock = time(); let ready = false;
  client.session!.expires_at = '2026-10-08T04:00:05Z';
  const controller = new AiReportController(client, async request => report(request), () => ready, undefined, clock.runtime);
  controller.setSelection(selection); const stop = controller.attach(); ready = true;
  await controller.generate('shift'); expect(controller.getSnapshot().status).toBe('ready');
  clock.advance(5000); expect(controller.getSnapshot().data).toBeNull(); stop();
});
