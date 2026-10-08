import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, result, session } from '../support/synthetic';
import facts from '../fixtures/analytics/analytics-shift.json' with { type: 'json' };
import shift from '../fixtures/analytics/report-shift.json' with { type: 'json' };
import type * as Client from '../../src/shared/api/client';
import type * as Analytics from '../../src/features/analytics/controller';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { AnalyticsController } = sourceModule<typeof Analytics>('src/features/analytics/controller.ts');
const period = { start: facts.period.start, end: facts.period.end };
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };

function clock() {
  let now = Date.now();
  const jobs = new Set<{ at: number; callback: () => void }>();
  const runtime: Analytics.AnalyticsRuntime = {
    now: () => now,
    schedule(callback, delay) { const job = { at: now + delay, callback }; jobs.add(job); return () => { jobs.delete(job); }; },
  };
  return { runtime, jobs, advance(ms: number, fire = true) { now += ms; if (fire) for (const job of [...jobs]) if (job.at <= now) { jobs.delete(job); job.callback(); } } };
}
async function setup(send?: (url: string, init: RequestInit) => Promise<Response>) {
  const time = clock(); const originalNow = Date.now; Date.now = time.runtime.now;
  const signed = session(); signed.expires_at = new Date(Date.now() + 5000).toISOString();
  let online = true; const reads: { url: string; signal: AbortSignal }[] = [];
  const client = new ApiClient({ online: () => online, fetch: async (url, init) => {
    const path = String(url);
    if (path.endsWith('/auth/login') || path.endsWith('/me')) return json(signed);
    reads.push({ url: path, signal: init!.signal as AbortSignal });
    return send ? send(path, init!) : json(path.includes('/analytics/') ? facts : shift);
  } });
  try { await client.login(credentials); } catch (error) { Date.now = originalNow; throw error; }
  const controller = new AnalyticsController(client, time.runtime); let detach = controller.attach();
  return { time, signed, reads, client, controller, offline() { online = false; },
    detach() { detach(); }, reattach() { detach = controller.attach(); },
    stop() { detach(); Date.now = originalNow; },
  };
}
function empty(controller: Analytics.AnalyticsController) {
  expect(controller.getSnapshot()).toMatchObject({ facts: { status: 'idle', data: null }, report: { status: 'idle', data: null }, period: null });
}

test('offline real expiry clears cached analytics facts/native report without clearing identity or sending requests', async () => {
  const h = await setup();
  try {
    await h.controller.load(period); await h.controller.openReport(null);
    expect(h.controller.getSnapshot().facts.data).not.toBeNull(); expect(h.controller.getSnapshot().report.data).not.toBeNull();
    const epoch = h.client.epoch; const identity = h.client.session; const reads = h.reads.length;
    h.offline(); h.time.advance(5000);
    expect(h.client.activeSession).toBe(false); empty(h.controller);
    expect(h.reads).toHaveLength(reads); expect(h.client.epoch).toBe(epoch); expect(h.client.session).toBe(identity); expect(h.time.jobs.size).toBe(0);
  } finally { h.stop(); }
});

for (const kind of ['facts', 'report'] as const) test(`expiry aborts owned pending ${kind} and suppresses its delayed completion`, async () => {
  const late = deferred<Response>();
  const h = await setup(async url => kind === 'facts' || url.includes('/reports/') ? late.promise : json(facts));
  try {
    if (kind === 'report') await h.controller.load(period);
    const pending = kind === 'facts' ? h.controller.load(period) : h.controller.openReport(null);
    const signal = h.reads.at(-1)!.signal; h.offline(); h.time.advance(5000);
    expect(signal.aborted).toBe(true); empty(h.controller);
    late.resolve(json(kind === 'facts' ? facts : shift)); await pending; empty(h.controller);
  } finally { late.resolve(json(kind === 'facts' ? facts : shift)); h.stop(); }
});

for (const kind of ['facts', 'report'] as const) test(`delayed expiry timer cannot permit ${kind} publication after real expiry`, async () => {
  const late = deferred<Response>();
  const h = await setup(async url => kind === 'facts' || url.includes('/reports/') ? late.promise : json(facts));
  try {
    if (kind === 'report') await h.controller.load(period);
    const pending = kind === 'facts' ? h.controller.load(period) : h.controller.openReport(null);
    h.time.advance(5001, false); expect(h.time.jobs.size).toBe(1);
    late.resolve(json(kind === 'facts' ? facts : shift)); await pending;
    // The transport has finished and detached its abort listener; publication must still be refused.
    empty(h.controller); expect(h.time.jobs.size).toBe(0);
  } finally { late.resolve(json(kind === 'facts' ? facts : shift)); h.stop(); }
});

test('same-authority renewal replaces the expiry timer and an old callback cannot erase valid reports', async () => {
  const h = await setup();
  try {
    await h.controller.load(period); await h.controller.openReport(null);
    const cached = h.controller.getSnapshot(); const epoch = h.client.epoch;
    const oldTimer = [...h.time.jobs][0]; h.time.advance(4000);
    h.signed.expires_at = new Date(Date.now() + 10000).toISOString(); await h.client.getMe();
    expect(h.client.epoch).toBe(epoch); expect(h.time.jobs.has(oldTimer)).toBe(false); expect(h.time.jobs.size).toBe(1);
    h.time.advance(1001); oldTimer.callback();
    expect(h.controller.getSnapshot()).toBe(cached); expect(h.time.jobs.size).toBe(1);
    h.time.advance(8999); empty(h.controller); expect(h.client.epoch).toBe(epoch);
  } finally { h.stop(); }
});

for (const cause of ['inactive', 'non-master', 'empty-scope', 'epoch'] as const) test(`current-master fence clears cached reports on ${cause} loss and refuses a new read`, async () => {
  const h = await setup();
  try {
    await h.controller.load(period); await h.controller.openReport(null); const count = h.reads.length;
    if (cause === 'inactive') h.client.session!.principal.active = false;
    if (cause === 'non-master') h.client.session!.principal.role = 'manager';
    if (cause === 'empty-scope') h.client.session!.principal.section_ids = [];
    if (cause === 'epoch') h.client.clearIdentity();
    await h.controller.load(period); await h.controller.openReport(null);
    empty(h.controller); expect(h.reads).toHaveLength(count); expect(h.time.jobs.size).toBe(0);
  } finally { h.stop(); }
});

test('expired reads clear cached data even before a delayed timer fires and never reach transport', async () => {
  const h = await setup();
  try {
    await h.controller.load(period); await h.controller.openReport(null); const count = h.reads.length;
    h.time.advance(5001, false); await h.controller.openReport(null); await h.controller.load(period);
    empty(h.controller); expect(h.reads).toHaveLength(count); expect(h.time.jobs.size).toBe(0);
  } finally { h.stop(); }
});

test('detach cancels the timer and owned request; reattach cannot publish the prior read', async () => {
  const late = deferred<Response>(); let count = 0;
  const h = await setup(async () => ++count === 1 ? late.promise : json(facts));
  try {
    const pending = h.controller.load(period); const signal = h.reads[0].signal;
    h.detach(); empty(h.controller); expect(h.time.jobs.size).toBe(0); expect(signal.aborted).toBe(true);
    h.reattach(); expect(h.time.jobs.size).toBe(1); await h.controller.load(period); const current = h.controller.getSnapshot();
    late.resolve(json(facts)); await pending; expect(h.controller.getSnapshot()).toBe(current);
    h.time.advance(5000); empty(h.controller);
  } finally { late.resolve(json(facts)); h.stop(); }
});

test('online401 retains the existing identity reset and clears all analytics state', async () => {
  let denied = false; const h = await setup(async url => denied ? json({}, 401) : json(url.includes('/analytics/') ? facts : shift));
  try {
    await h.controller.load(period); await h.controller.openReport(null); const epoch = h.client.epoch;
    denied = true; await h.controller.openReport(null);
    empty(h.controller); expect(h.client.session).toBeNull(); expect(h.client.epoch).toBe(epoch + 1); expect(h.time.jobs.size).toBe(0);
  } finally { h.stop(); }
});

test('analytics expiry leaves an unrelated unknown command token replayable with the original operation after renewal', async () => {
  const bodies: string[] = [];
  const h = await setup(async (url, init) => {
    if (url.includes('/commands')) { bodies.push(String(init.body)); if (bodies.length === 1) throw new TypeError('Synthetic lost command response'); return json(result()); }
    return json(url.includes('/analytics/') ? facts : shift);
  });
  try {
    const token = h.client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
    await expect(h.client.execute(token)).rejects.toMatchObject({ outcomeUnknown: true });
    await h.controller.load(period); const epoch = h.client.epoch; h.time.advance(5000); empty(h.controller);
    expect(h.client.epoch).toBe(epoch); expect(h.client.session).not.toBeNull();
    h.signed.expires_at = new Date(Date.now() + 10000).toISOString(); await h.client.getMe(); expect(h.client.epoch).toBe(epoch);
    await expect(h.client.execute(token)).resolves.toMatchObject({ order: { id: ids.order } });
    expect(bodies).toHaveLength(2); expect(bodies[1]).toBe(bodies[0]); expect(JSON.parse(bodies[1]).operation_id).toBe(token.operationId);
  } finally { h.stop(); }
});
