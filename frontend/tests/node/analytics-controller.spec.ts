import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, session } from '../support/synthetic';
import facts from '../fixtures/analytics/analytics-shift.json' with { type: 'json' };
import shift from '../fixtures/analytics/report-shift.json' with { type: 'json' };
import order from '../fixtures/analytics/report-order.json' with { type: 'json' };
import type * as Client from '../../src/shared/api/client';
import type * as Controller from '../../src/features/analytics/controller';
import type { PeriodRequest } from '../../src/shared/api/analyticsProtocol';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { AnalyticsController } = sourceModule<typeof Controller>('src/features/analytics/controller.ts');
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };
const period: PeriodRequest = { start: facts.period.start, end: facts.period.end };
const later: PeriodRequest = { start: '2026-10-07T20:00:00Z', end: '2026-10-08T01:00:00Z' };
const factsAt = (selected: PeriodRequest) => ({ ...facts, period: { ...selected, display_timezone: 'Asia/Almaty' } });
async function setup(send: (url: string, init?: RequestInit) => Promise<Response>, role: 'master'|'executor'|'manager'|'admin' = 'master') {
  const signed = session(); signed.principal.role = role;
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => String(url).endsWith('/auth/login') ? json(signed) : send(String(url), init) });
  await client.login(credentials); const controller = new AnalyticsController(client); const cleanup = controller.attach();
  return { client, controller, cleanup };
}

test('analytics and report requests use only same-origin JSON GET parameters with no client authority or credential fields', async () => {
  const sent: { url: URL; init: RequestInit }[] = [];
  const h = await setup(async (url, init) => {
    const parsed = new URL(url, 'https://synthetic.example.invalid'); sent.push({ url: parsed, init: init! });
    return json(parsed.pathname.includes('/analytics/') ? facts : parsed.pathname.includes('/orders/') ? order : shift);
  });
  await h.client.getShiftAnalytics(period); await h.client.getShiftReport(period); await h.client.getOrderReport(order.order.order.id, period);
  expect(sent.map(request => request.url.pathname)).toEqual(['/api/v1/analytics/shift', '/api/v1/reports/shift', `/api/v1/reports/orders/${order.order.order.id}`]);
  for (const request of sent) {
    expect([...request.url.searchParams.keys()].sort()).toEqual(['end', 'format', 'start']);
    expect(request.url.searchParams.get('format')).toBe('json');
    expect(request.init).toMatchObject({ method: 'GET', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error' });
    expect(request.init.body).toBeUndefined();
    expect(new Headers(request.init.headers).get('Authorization')).toBeNull();
  }
  h.cleanup();
});

test('non-master and overlong-period requests fail before the network rather than disclosing report data', async () => {
  for (const role of ['executor', 'manager', 'admin'] as const) {
    let sends = 0; const h = await setup(async () => { sends++; return json(facts); }, role);
    await expect(h.client.getShiftAnalytics(period)).rejects.toMatchObject({ status: 403 });
    expect(sends).toBe(0); h.cleanup();
  }
  let sends = 0; const h = await setup(async () => { sends++; return json(facts); });
  await expect(h.client.getShiftAnalytics({ start: '2026-06-30T19:00:00Z', end: '2026-10-01T19:00:01Z' })).rejects.toMatchObject({ status: 422 });
  expect(sends).toBe(0); h.cleanup();
});

test('a delayed old query cannot overwrite a newer ready period even when fake transport ignores abort', async () => {
  const old = deferred<Response>(); let calls = 0;
  const h = await setup(async () => ++calls === 1 ? old.promise : json(factsAt(later)));
  const pending = h.controller.load(period);
  await h.controller.load(later);
  expect(h.controller.getSnapshot()).toMatchObject({ period: later, facts: { status: 'ready', data: { period: { start: later.start } } } });
  old.resolve(json(facts)); await pending;
  expect(h.controller.getSnapshot().facts.data?.period.start).toBe(later.start);
  expect(calls).toBe(2); h.cleanup();
});

test('new query clears old figures immediately and a late old report cannot repopulate them', async () => {
  const report = deferred<Response>(); const newQuery = deferred<Response>(); let analyticsCalls = 0;
  const h = await setup(async url => url.includes('/reports/') ? report.promise : ++analyticsCalls === 1 ? json(facts) : newQuery.promise);
  await h.controller.load(period); const previousReport = h.controller.openReport(null);
  const pending = h.controller.load(later);
  expect(h.controller.getSnapshot()).toMatchObject({ facts: { status: 'loading', data: null }, report: { status: 'idle', data: null }, period: later });
  report.resolve(json(shift)); await previousReport;
  expect(h.controller.getSnapshot().report.data).toBeNull();
  newQuery.resolve(json(factsAt(later))); await pending;
  expect(h.controller.getSnapshot().facts.status).toBe('ready'); h.cleanup();
});

test('session invalidation hides data synchronously and suppresses a late previous report', async () => {
  const late = deferred<Response>();
  const h = await setup(async url => url.includes('/reports/') ? late.promise : json(facts));
  await h.controller.load(period); const pending = h.controller.openReport(null);
  h.client.clearIdentity();
  expect(h.controller.getSnapshot()).toMatchObject({ facts: { data: null }, report: { data: null }, period: null });
  late.resolve(json(shift)); await pending;
  expect(h.controller.getSnapshot().report.data).toBeNull(); h.cleanup();
});

test('capture cap is an explicit unavailable error, never an empty successful report', async () => {
  const cap = { code: 'REPORT_LIMIT_EXCEEDED', message: 'Synthetic cap', request_id: ids.event, retryable: false, current_version: null, field_errors: [] };
  const h = await setup(async () => json(cap, 422));
  await h.controller.load(period);
  expect(h.controller.getSnapshot().facts).toMatchObject({ status: 'error', data: null });
  expect(h.controller.getSnapshot().facts.error).toContain('не пустая выборка'); h.cleanup();
});

test('wrong-period and wrong-order successful JSON responses are rejected before publication', async () => {
  const h = await setup(async url => url.includes('/orders/') ? json(order) : json(factsAt(later)));
  await h.controller.load(period);
  expect(h.controller.getSnapshot().facts).toMatchObject({ status: 'error', data: null });
  await expect(h.client.getOrderReport(ids.second, period)).rejects.toThrow(/другого наряда/);
  h.cleanup();
});

test('report403 clears current figures and former detail instead of leaving private prior data visible', async () => {
  const h = await setup(async url => url.includes('/reports/') ? json({}, 403) : json(facts));
  await h.controller.load(period); await h.controller.openReport(null);
  expect(h.controller.getSnapshot()).toMatchObject({ facts: { data: null }, report: { status: 'error', data: null } });
  expect(h.controller.getSnapshot().report.error).toContain('Доступ'); h.cleanup();
});

test('an order404 invalidates prior facts that may contain now-inaccessible order details', async () => {
  const h = await setup(async url => url.includes('/reports/orders/') ? json({}, 404) : json(facts));
  await h.controller.load(period);
  expect(h.controller.getSnapshot().facts.data?.orders[0].order.description).toContain('synthetic literal task');
  await h.controller.openReport(order.order.order.id);
  expect(h.controller.getSnapshot().report).toMatchObject({ status: 'error', data: null });
  expect(h.controller.getSnapshot().facts.data).toBeNull();
  h.cleanup();
});
