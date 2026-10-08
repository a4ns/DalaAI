import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Store from '../../src/shared/api/orderStore';
import type * as Notices from '../../src/app/inAppNotifications';
import type { Order, Role } from '../../src/shared/api/wire';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { OrderStore } = sourceModule<typeof Store>('src/shared/api/orderStore.ts');
const { InAppNotificationFeed, MAX_VISIBLE_NOTICES } = sourceModule<typeof Notices>('src/app/inAppNotifications.ts');
const order = (patch: Partial<Order> = {}): Order => ({ ...result().order, status: 'issued', ...patch });
async function setup(role: Role = 'executor') {
  let signed = session(role === 'executor' ? ids.second : ids.first); signed.principal.role = role;
  let read = async () => json({ items: [], next_cursor: null }); let reads = 0;
  const client = new ApiClient({ online: () => true, fetch: async url => {
    if (String(url).endsWith('/auth/login') || String(url).endsWith('/me')) return json(signed);
    reads++; return read();
  } });
  await client.login({ employee_code: 'SYNTHETIC', pin: '0000' });
  const store = new OrderStore(client); const feed = new InAppNotificationFeed(client, store); const detach = feed.attach();
  return {
    client, store, feed, reads: () => reads,
    read: (next: () => Promise<Response>) => { read = next; },
    async confirm(items: Order[]) { read = async () => json({ items, next_cursor: null }); await store.refresh(); },
    async identity(patch: Partial<typeof signed.principal>) { signed = { ...signed, principal: { ...signed.principal, ...patch } }; await client.getMe(); },
    async expires(at: number) { signed = { ...signed, expires_at: new Date(at).toISOString() }; await client.getMe(); },
    close() { detach(); store.dispose(); },
  };
}

test('mount is passive; first successful nonempty snapshot silently establishes the baseline', async () => {
  const h = await setup(); expect(h.reads()).toBe(0); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order()]); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order()]); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('successful empty snapshot is a baseline and a later assignment notifies exactly once', async () => {
  const h = await setup(); await h.confirm([]); await h.confirm([order()]);
  expect(h.feed.getSnapshot()).toHaveLength(1); expect(h.feed.getSnapshot()[0].message).toContain('SYNTHETIC-001');
  h.feed.dismiss(h.feed.getSnapshot()[0].key); await h.confirm([order()]); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('failed and partial first reads never establish a baseline', async () => {
  const h = await setup(); h.read(async () => json({}, 503)); await h.store.refresh();
  let page = 0; h.read(async () => ++page === 1 ? json({ items: [order()], next_cursor: 'next' }) : json({}, 503));
  await h.store.refresh(); expect(h.store.confirmation).toBe(0); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order()]); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order({ version: 3, assignment_revision: 2 })]); expect(h.feed.getSnapshot()).toHaveLength(1); h.close();
});
test('local record does not notify; only next complete confirmation discovers a new assignment', async () => {
  const h = await setup(); await h.confirm([]); const confirmation = h.store.confirmation;
  h.store.record(order(), h.client.epoch); expect(h.store.confirmation).toBe(confirmation); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order()]); expect(h.feed.getSnapshot()).toHaveLength(1); h.close();
});
test('timestamps, overdue and own executor transitions do not repeat an assignment notice', async () => {
  const h = await setup(); await h.confirm([order()]);
  await h.confirm([order({ domain_now: '2026-10-09T00:00:00Z', updated_at: '2026-10-09T00:00:00Z', is_overdue: true })]);
  h.store.record(order({ version: 3, status: 'accepted' }), h.client.epoch);
  await h.confirm([order({ version: 3, status: 'accepted' })]);
  await h.confirm([order({ version: 4, status: 'ai_review', current_submission_id: ids.event })]);
  expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('disappearance and stale reappearance retain seen keys and highest versions', async () => {
  const h = await setup('master'); await h.confirm([order({ version: 5, status: 'closed', current_submission_id: ids.event })]);
  await h.confirm([]); await h.confirm([order({ version: 4, status: 'ai_review', current_submission_id: ids.event })]);
  expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order({ version: 6, status: 'ai_review', current_submission_id: ids.second })]);
  expect(h.feed.getSnapshot()).toHaveLength(1); h.feed.dismiss(h.feed.getSnapshot()[0].key);
  await h.confirm([]); await h.confirm([order({ version: 7, status: 'ai_review', current_submission_id: ids.second })]);
  expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('new assignment revision notifies once; older revisions never do even at higher versions', async () => {
  const h = await setup(); await h.confirm([order({ version: 5, assignment_revision: 3 })]);
  await h.confirm([order({ version: 6, assignment_revision: 4 })]); expect(h.feed.getSnapshot()).toHaveLength(1);
  h.feed.dismiss(h.feed.getSnapshot()[0].key); await h.confirm([]);
  await h.confirm([order({ version: 7, assignment_revision: 2 })]); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('master notices require ai_review and current submission; later attempts have distinct keys', async () => {
  const h = await setup('master'); await h.confirm([]);
  await h.confirm([order()]); await h.confirm([order({ version: 3, status: 'ai_review' })]); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order({ version: 4, status: 'ai_review', current_submission_id: ids.event })]); expect(h.feed.getSnapshot()).toHaveLength(1);
  const firstKey = h.feed.getSnapshot()[0].key; h.feed.dismiss(firstKey);
  h.store.record(order({ version: 5, status: 'rework', current_submission_id: ids.event }), h.client.epoch);
  await h.confirm([order({ version: 5, status: 'rework', current_submission_id: ids.event })]); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order({ version: 6, status: 'ai_review', current_submission_id: ids.second })]);
  expect(h.feed.getSnapshot()).toHaveLength(1); expect(h.feed.getSnapshot()[0].key).not.toBe(firstKey); h.close();
});
test('out-of-scope orders and other executors never notify', async () => {
  const h = await setup(); await h.confirm([]);
  await h.confirm([order({ assignment: { executor_id: ids.first, brigade_id: null } }), order({ id: ids.event, section_id: ids.equipment })]);
  expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
for (const role of ['manager', 'admin'] as const) test(`${role} has no assignment/review notices`, async () => {
  const h = await setup(role); await h.confirm([]); await h.confirm([order({ status: 'ai_review', current_submission_id: ids.event })]); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('bounded stack consumes all discovered keys without a deferred backlog', async () => {
  const h = await setup(); await h.confirm([]);
  const items = Array.from({ length: 5 }, (_, i) => order({ id: `10000000-0000-4000-8000-00000000001${i}`, number: `SYNTHETIC-${i}` }));
  await h.confirm(items); expect(h.feed.getSnapshot()).toHaveLength(MAX_VISIBLE_NOTICES);
  for (const notice of h.feed.getSnapshot()) h.feed.dismiss(notice.key);
  await h.confirm(items); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('access loss clears notices and history; recovery starts with a silent baseline', async () => {
  const h = await setup(); await h.confirm([]); await h.confirm([order()]); expect(h.feed.getSnapshot()).toHaveLength(1);
  h.read(async () => json({}, 403)); await h.store.refresh(); expect(h.feed.getSnapshot()).toEqual([]);
  await h.confirm([order({ version: 3, assignment_revision: 2 })]); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
for (const change of [{ active: false }, { user_id: ids.first }, { role: 'manager' as const }, { section_ids: [ids.equipment] }]) test(`identity or authority change clears old session: ${JSON.stringify(change)}`, async () => {
  const h = await setup(); await h.confirm([]); await h.confirm([order()]); expect(h.feed.getSnapshot()).toHaveLength(1);
  await h.identity(change); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('logout clears visible notices synchronously', async () => {
  const h = await setup(); await h.confirm([]); await h.confirm([order()]); h.client.clearIdentity(); expect(h.feed.getSnapshot()).toEqual([]); h.close();
});
test('real-time session expiry clears notices without another order read', async () => {
  const h = await setup(); await h.confirm([]); await h.confirm([order()]); await h.expires(Date.now() + 100);
  const reads = h.reads(); await expect.poll(() => h.feed.getSnapshot().length).toBe(0); expect(h.reads()).toBe(reads); h.close();
});
test('effect detach and replay leave no old timers or visible data', async () => {
  const h = await setup(); await h.confirm([]); await h.confirm([order()]); expect(h.feed.getSnapshot()).toHaveLength(1); h.close();
  expect(h.feed.getSnapshot()).toEqual([]);
  const detach = h.feed.attach(); expect(h.feed.getSnapshot()).toEqual([]); detach();
});
