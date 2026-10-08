import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import type { ReactElement, ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import { deferred, ids, json, session } from '../support/synthetic';
import rawReport from '../../src/features/aiReports/__fixtures__/serializer-response.json' with { type: 'json' };
import rawAdvice from '../../src/features/assigneeRecommendations/__fixtures__/contract-response.json' with { type: 'json' };
import facts from '../fixtures/analytics/analytics-shift.json' with { type: 'json' };
import type * as Client from '../../src/shared/api/client';
import type * as Analytics from '../../src/features/analytics/controller';
import type * as Reports from '../../src/features/aiReports/controller';
import type * as Advice from '../../src/features/assigneeRecommendations/controller';
import type * as Master from '../../src/mobile/master/MasterScreen';
import type * as Panel from '../../src/panel/PanelScreen';
import type { AiReportRequest } from '../../src/features/aiReports/protocol';
import type { MasterScreenProps, MasterOrderVM } from '../../src/mobile/master/types';
import type { ResourceState } from '../../src/shared/ui/types';
const { ApiClient, ApiError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { AnalyticsController } = sourceModule<typeof Analytics>('src/features/analytics/controller.ts');
const { AiReportController } = sourceModule<typeof Reports>('src/features/aiReports/controller.ts');
const { AssigneeRecommendationsController } = sourceModule<typeof Advice>('src/features/assigneeRecommendations/controller.ts');
const signed = () => session();
const reportBody: AiReportRequest = { operation_id: rawReport.operation_id, start: rawReport.period.start, end: rawReport.period.end, report_kind: 'shift' };
const adviceQuery = { section_id: ids.section, work_code_id: null, limit: 3 };
const currentAdvice = () => { const now = Date.now(); return { ...structuredClone(rawAdvice), section_id: ids.section, as_of: new Date(now).toISOString(), expires_at: new Date(now + 30000).toISOString() }; };
async function clientWith(send: (url: string, init: RequestInit) => Promise<Response>, timeoutMs?: number) {
  const client = new ApiClient({ online: () => true, timeoutMs, fetch: async (url, init) => String(url).endsWith('/auth/login') ? json(signed()) : send(String(url), init!) });
  await client.login({ employee_code: 'SYNTHETIC', pin: '0000' }); return client;
}

test('shared assistance transports use accepted exact same-origin paths, CSRF and bounded authority-free payloads', async () => {
  const sent: { url: URL; init: RequestInit }[] = [];
  const client = await clientWith(async (url, init) => { sent.push({ url: new URL(url, 'https://synthetic.invalid'), init }); return json(url.includes('/ai-summary') ? rawReport : currentAdvice()); });
  await client.createAiSummary({ ...reportBody, actor: 'NOT-AUTHORITY' } as AiReportRequest); await client.getAssigneeRecommendations(adviceQuery);
  expect(sent.map(row => row.url.pathname)).toEqual(['/api/v1/reports/ai-summary', '/api/v1/recommendations/assignees']);
  expect(JSON.parse(String(sent[0].init.body))).toEqual(reportBody); expect(new Headers(sent[0].init.headers).get('X-CSRF-Token')).toBe(signed().csrf_token);
  expect([...sent[1].url.searchParams.keys()].sort()).toEqual(['limit', 'section_id']); expect(sent[1].init.body).toBeUndefined();
  for (const row of sent) expect(row.init).toMatchObject({ credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error' });
});
test('no assistance network request starts after identity/role/scope loss, invalid input or expiry', async () => {
  for (const cause of ['clear', 'role', 'scope', 'expiry'] as const) {
    let calls = 0; const client = await clientWith(async () => { calls++; return json({}); });
    if (cause === 'clear') client.clearIdentity();
    if (cause === 'role') client.session!.principal.role = 'manager';
    if (cause === 'scope') client.session!.principal.section_ids = [];
    if (cause === 'expiry') client.session!.expires_at = '2000-01-01T00:00:00Z';
    await expect(client.createAiSummary(reportBody)).rejects.toBeInstanceOf(ApiError); await expect(client.getAssigneeRecommendations(adviceQuery)).rejects.toBeInstanceOf(ApiError); expect(calls).toBe(0);
  }
  let calls = 0; const client = await clientWith(async () => { calls++; return json({}); });
  await expect(client.getAssigneeRecommendations({ ...adviceQuery, section_id: ids.first })).rejects.toMatchObject({ status: 403 });
  await expect(client.getAssigneeRecommendations({ ...adviceQuery, limit: 6 })).rejects.toMatchObject({ status: 422 });
  await expect(client.createAiSummary({ ...reportBody, report_kind: 'shift', start: '2020-01-01T00:00:00Z' })).rejects.toMatchObject({ status: 422 }); expect(calls).toBe(0);
});
test('bounded JSON success cancels oversized streams before draining the whole body and marks POST unknown', async () => {
  let pulled = 0; let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({ pull(controller) { pulled++; controller.enqueue(new Uint8Array(262144).fill(32)); }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  const client = await clientWith(async () => new Response(stream, { headers: { 'Content-Type': 'application/json' } }));
  await expect(client.createAiSummary(reportBody)).rejects.toMatchObject({ status: 200, outcomeUnknown: true });
  expect(cancelled).toBe(true); expect(pulled).toBe(5);
});
test('bounded JSON handles UTF-8 split chunks, rejects excessive declared length, and preserves the request deadline', async () => {
  const bytes = new TextEncoder().encode(JSON.stringify(rawReport)); let position = 0;
  const client = await clientWith(async () => new Response(new ReadableStream({ pull(controller) { if (position < bytes.length) controller.enqueue(bytes.slice(position, ++position)); else controller.close(); } })));
  expect((await client.createAiSummary(reportBody)).summary).toBe(rawReport.summary);
  let cancelled = false; const declared = await clientWith(async () => new Response(new ReadableStream({ cancel() { cancelled = true; } }), { headers: { 'Content-Length': '1048577' } }));
  await expect(declared.createAiSummary(reportBody)).rejects.toMatchObject({ outcomeUnknown: true }); expect(cancelled).toBe(true);
  let deadlineCancelled = false; const slow = await clientWith(async () => new Response(new ReadableStream({ cancel() { deadlineCancelled = true; } })), 10);
  await expect(slow.createAiSummary(reportBody)).rejects.toMatchObject({ outcomeUnknown: true }); expect(deadlineCancelled).toBe(true);
});
test('streamed response from a prior session never publishes and malformed/mismatched POST success remains unknown', async () => {
  let target!: ReadableStreamDefaultController<Uint8Array>;
  const client = await clientWith(async () => new Response(new ReadableStream({ start(controller) { target = controller; } })));
  const pending = client.createAiSummary(reportBody); await Promise.resolve(); client.clearIdentity(); target.enqueue(new TextEncoder().encode(JSON.stringify(rawReport))); target.close();
  await expect(pending).rejects.toMatchObject({ name: 'SessionChangedError' });
  for (const response of [{ ...rawReport, operation_id: ids.first }, { ...rawReport, advisory: false }]) {
    const malformed = await clientWith(async () => json(response)); await expect(malformed.createAiSummary(reportBody)).rejects.toMatchObject({ status: 200, outcomeUnknown: true });
  }
});
test('a denied report clears its selected analytics source and no subsequent provider request starts from it', async () => {
  let summaries = 0; const client = await clientWith(async url => url.includes('/analytics/') ? json(facts) : (summaries++, json({}, 403)));
  const analytics = new AnalyticsController(client); const detach = analytics.attach(); await analytics.load(facts.period);
  const source = analytics.getSnapshot().facts.data!;
  const reports = new AiReportController(client, (body, signal) => client.createAiSummary(body, signal), () => analytics.getSnapshot().facts.data === source, error => analytics.sourceAccessLost(error, source));
  const stop = reports.attach(); reports.setSelection({ ...source.period, sourceRef: source.provenance.source_ref });
  await reports.generate('shift'); expect(analytics.getSnapshot().facts.data).toBeNull(); await reports.generate('shift'); expect(summaries).toBe(1); stop(); detach();
});
test('a denied recommendation synchronously fences the dictionary callback and cannot re-request or choose', async () => {
  let calls = 0; let dictionaryReady = true;
  const client = await clientWith(async () => { calls++; return json({}, 403); });
  const controller = new AssigneeRecommendationsController(client, (query, signal) => client.getAssigneeRecommendations(query, signal), () => ({ sectionId: ids.section, workCodeId: null, brigadeId: '', draftKey: 'draft', dictionaryKey: 'dictionary' }), () => [], () => dictionaryReady, () => { dictionaryReady = false; });
  controller.synchronize(); const stop = controller.attach(); await controller.load(); await controller.load(); expect(calls).toBe(1); expect(controller.choose(ids.second)).toBeNull(); stop();
});

/** Deterministic hook harness: real component and JSX, but no browser/DOM claim. */
function masterHarness() {
  const cells: unknown[] = []; let cursor = 0; let effects: (() => void)[] = [];
  const hooks = {
    useId: () => 'synthetic-master',
    useState(initial: unknown) { const position = cursor++; if (!(position in cells)) cells[position] = typeof initial === 'function' ? (initial as () => unknown)() : initial; return [cells[position], (next: unknown) => { cells[position] = typeof next === 'function' ? (next as (old: unknown) => unknown)(cells[position]) : next; }]; },
    useRef(initial: unknown) { const position = cursor++; if (!(position in cells)) cells[position] = { current: initial }; return cells[position]; },
    useMemo(factory: () => unknown) { cursor++; return factory(); },
    useLayoutEffect(effect: () => void) { cursor++; effects.push(effect); },
  };
  const { MasterScreen } = ssrSourceModule<typeof Master>('src/mobile/master/MasterScreen.tsx', { react: hooks, './master.css': {} });
  return { render(props: MasterScreenProps) { cursor = 0; effects = []; const tree = MasterScreen(props); effects.forEach(effect => effect()); return tree; } };
}
function findButton(node: ReactNode, label: string): ReactElement<{ children?: ReactNode; onClick?: () => void }> | null {
  if (Array.isArray(node)) { for (const child of node) { const found = findButton(child, label); if (found) return found; } return null; }
  if (!node || typeof node !== 'object' || !('props' in node)) return null;
  const element = node as ReactElement<{ children?: ReactNode; onClick?: () => void }>;
  return element.type === 'button' && element.props.children === label ? element : findButton(element.props.children, label);
}
const fresh = <T,>(snapshot: T): ResourceState<T> => ({ snapshot, loadStatus: 'ready', freshness: 'fresh', lastConfirmedAt: '2026-10-08T01:00:00Z', incomplete: false, error: null });
test('confirmed master receipt survives refreshed close/rework removal while stale decision controls disappear', async () => {
  for (const decision of ['close', 'rework'] as const) {
    const order: MasterOrderVM = { id: ids.order, number: 'SYNTHETIC-RECEIPT', version: 1, assignmentRevision: 1, status: 'ai_review', type: 'planned', description: 'Synthetic', equipmentLabel: 'Synthetic', executorLabel: 'Synthetic', dueAt: '2026-10-08T04:00:00Z', isOverdue: false, submission: { id: ids.event, assignmentRevision: 1, attemptNumber: 1, workDescription: 'Synthetic', workCodeLabel: 'SYNTHETIC', materials: [], afterPhotoCount: 0, comment: '', completeness: 'complete', missingEvidence: [], assessment: null } };
    const result = deferred<{ kind: 'confirmed' }>(); const harness = masterHarness();
    const props: MasterScreenProps = { dictionaries: fresh({ sections: [], equipment: [], brigades: [], executors: [] }), orders: fresh([order]), createDraft: { type: 'planned', description: '', sectionId: '', equipmentId: '', executorId: '', brigadeId: '', dueLocal: '', normMinutes: '', priority: 'normal', comment: '', beforePhotoIds: [] }, onCreateDraftChange() {}, reviewDrafts: { [order.id]: { reason: 'Synthetic checked', finalScore: '' } }, onReviewDraftChange() {}, online: true, onCreate: async () => ({ kind: 'rejected', message: 'Unused' }), onReview: () => result.promise, onReload: async () => {} };
    const tree = harness.render(props); const click = findButton(tree, decision === 'close' ? 'Принять и закрыть' : 'Вернуть на доработку'); expect(click).not.toBeNull(); click!.props.onClick!(); result.resolve({ kind: 'confirmed' }); await result.promise; await Promise.resolve();
    const refreshed = harness.render({ ...props, orders: fresh([{ ...order, status: decision === 'close' ? 'closed' : 'rework', submission: null }]) });
    const html = renderToStaticMarkup(refreshed); expect(html).toContain('Решение мастера по наряду № SYNTHETIC-RECEIPT подтверждено сервером.'); expect(html).not.toContain('Принять и закрыть'); expect(html).toContain('Скрыть подтверждение');
  }
});
test('panel copy reflects existing master report capability without claiming universal API unavailability', () => {
  const { PanelScreen } = ssrSourceModule<typeof Panel>('src/panel/PanelScreen.tsx', { './panel.css': {} });
  const html = renderToStaticMarkup(createElement(PanelScreen, { orders: fresh([]), selectedOrderId: null, onSelectOrder() {} }));
  expect(html).toContain('Отчёты, экспорт и аналитика доступны мастеру'); expect(html).not.toContain('пока недоступны в подключённом API');
});

test('declared and streamed oversize refuse promptly even if best-effort stream cancellation never settles', async () => {
  for (const declared of [true, false]) {
    let cancellations = 0;
    const stream = new ReadableStream<Uint8Array>({ pull(controller) { if (!declared) controller.enqueue(new Uint8Array(1048577)); }, cancel() { cancellations++; return new Promise<void>(() => {}); } }, { highWaterMark: 0 });
    const client = await clientWith(async () => new Response(stream, declared ? { headers: { 'Content-Length': '1048577' } } : undefined), 50);
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const outcome = await Promise.race([client.createAiSummary(reportBody).then(() => 'unexpected-success', error => { expect(error).toMatchObject({ outcomeUnknown: true }); return 'rejected'; }), new Promise<string>(resolve => { timer = setTimeout(() => resolve('still-pending'), 200); })]);
      expect(outcome).toBe('rejected'); expect(cancellations).toBe(1); expect(stream.locked).toBe(false);
    } finally { clearTimeout(timer); }
  }
});
