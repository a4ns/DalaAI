import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Store from '../../src/shared/api/orderStore';
import type * as Executor from '../../src/app/executorController';
import type * as Photos from '../../src/app/photoStore';
import type { Order } from '../../src/shared/api/wire';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { OrderStore } = sourceModule<typeof Store>('src/shared/api/orderStore.ts');
const { ExecutorController, executorScope } = sourceModule<typeof Executor>('src/app/executorController.ts');
const { PhotoStore } = sourceModule<typeof Photos>('src/app/photoStore.ts');
const order = (): Order => ({ ...result().order, version: 1, status: 'issued', assignment: { executor_id: ids.first, brigade_id: null } });
const page = (items = [order()], cursor: string | null = null) => json({ items, next_cursor: cursor });
const intent = () => ({ orderId: ids.order, expectedVersion: 1, expectedAssignmentRevision: 1, action: 'accept' as const, payload: {} });
async function setup() {
  let online = true; let read: () => Promise<Response> = async () => page(); let write: () => Promise<Response> = async () => json({ ...result(), order: { ...order(), version: 2, status: 'accepted' } });
  let reads = 0; const posts: string[] = []; const signals: AbortSignal[] = [];
  const signed = session(); signed.principal.role = 'executor';
  const client = new ApiClient({ online: () => online, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(signed);
    if ((init?.method ?? 'GET') === 'POST') { posts.push(String(init?.body)); return write(); }
    reads++; if (init?.signal) signals.push(init.signal); return read();
  } });
  await client.login({ employee_code: 'SYNTHETIC', pin: '0000' });
  const store = new OrderStore(client); const executor = new ExecutorController(client, store, new PhotoStore(client), 'synthetic');
  await store.refresh();
  return { client, store, executor, posts, signals, reads: () => reads, read: (next: () => Promise<Response>) => { read = next; }, write: (next: () => Promise<Response>) => { write = next; }, online: (value: boolean) => { online = value; } };
}
const tick = () => new Promise<void>(resolve => setImmediate(resolve));

test('healthy automatic poll retains the confirmed snapshot and an explicit executor action sends exactly once', async () => {
  const h = await setup(); const held = deferred<Response>(); h.read(() => held.promise);
  const snapshot = h.store.getSnapshot(); const poll = h.store.refresh({ background: true }); await tick();
  expect(h.store.getSnapshot()).toBe(snapshot); expect(h.store.actionReady).toBe(true);
  expect((await h.executor.act(intent())).kind).toBe('confirmed'); expect(h.posts).toHaveLength(1);
  expect(JSON.parse(h.posts[0])).toMatchObject({ expected_version: 1, action: 'accept' });
  held.resolve(page()); await poll;
  expect(h.store.getSnapshot().snapshot?.[0].version).toBe(2); expect(h.posts).toHaveLength(1); h.store.dispose();
});
test('manual refresh joins an existing background promise but blocks commands synchronously', async () => {
  const h = await setup(); const held = deferred<Response>(); h.read(() => held.promise);
  const poll = h.store.refresh({ background: true }); const joined = h.store.refresh();
  expect(joined).toBe(poll); expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot().loadStatus).toBe('loading');
  expect((await h.executor.act(intent())).kind).toBe('rejected'); expect(h.posts).toHaveLength(0);
  held.resolve(page()); await joined; expect(h.reads()).toBe(2); h.store.dispose();
});
test('cold or previously failed refresh never gains background eligibility', async () => {
  const h = await setup(); h.read(async () => { throw new TypeError('Synthetic failure'); }); await h.store.refresh();
  const held = deferred<Response>(); h.read(() => held.promise); const retry = h.store.refresh({ background: true });
  expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot().freshness).toBe('stale');
  held.resolve(page()); await retry; expect(h.store.actionReady).toBe(true); h.store.dispose();
  const client = new ApiClient({ online: () => true, fetch: async () => page() }); const cold = new OrderStore(client); const first = cold.refresh({ background: true });
  expect(cold.getSnapshot()).toMatchObject({ snapshot: null, freshness: 'never', loadStatus: 'loading' }); expect(cold.actionReady).toBe(false); await first; cold.dispose();
});
test('healthy pages stage privately; a later page failure blocks and never publishes partial membership', async () => {
  const h = await setup(); const held = deferred<Response>(); let reads = 0;
  const discovered = { ...order(), id: ids.equipment, number: 'SYNTHETIC-NEW' };
  h.read(async () => ++reads === 1 ? page([order(), discovered], 'next') : held.promise);
  const snapshot = h.store.getSnapshot(); const poll = h.store.refresh({ background: true }); await tick();
  expect(h.store.getSnapshot()).toBe(snapshot); expect(h.store.actionReady).toBe(true); expect(h.store.getSnapshot().snapshot).toHaveLength(1);
  held.reject(new TypeError('Synthetic page2 failure')); await poll;
  expect(h.store.getSnapshot()).toMatchObject({ freshness: 'stale', incomplete: true }); expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot().snapshot).toHaveLength(1); expect(h.posts).toHaveLength(0); h.store.dispose();
});
test('an observed higher version blocks immediately while its page remains unpublished', async () => {
  const h = await setup(); const held = deferred<Response>(); let reads = 0;
  h.read(async () => ++reads === 1 ? page([{ ...order(), version: 2, assignment_revision: 2 }], 'next') : held.promise);
  const poll = h.store.refresh({ background: true }); await tick();
  expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot().snapshot?.[0].version).toBe(1);
  expect((await h.executor.act(intent())).kind).toBe('rejected'); expect(h.posts).toHaveLength(0);
  held.resolve(page([])); await poll; expect(h.store.getSnapshot().snapshot?.[0].version).toBe(2); expect((await h.executor.act(intent())).kind).toBe('conflict'); expect(h.posts).toHaveLength(0); h.store.dispose();
});
test('same-version identity changes fail closed, while computed domain time alone is allowed', async () => {
  for (const patch of [{ assignment_revision: 2 }, { section_id: ids.second }, { current_submission_id: ids.event }, { status: 'accepted' as const }]) {
    const h = await setup(); h.read(async () => page([{ ...order(), ...patch, domain_now: '2026-10-08T05:00:00Z' }])); await h.store.refresh({ background: true });
    expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot()).toMatchObject({ incomplete: true, freshness: 'stale' }); expect(h.store.getSnapshot().snapshot?.[0]).toEqual(order()); h.store.dispose();
  }
  const h = await setup(); h.read(async () => page([{ ...order(), domain_now: '2026-10-08T05:00:00Z', is_overdue: true }])); await h.store.refresh({ background: true }); expect(h.store.actionReady).toBe(true); expect(h.store.getSnapshot().snapshot?.[0].is_overdue).toBe(true); h.store.dispose();
});
test('offline invalidates immediately and a canceled late read cannot mint a new confirmation', async () => {
  const h = await setup(); const held = deferred<Response>(); h.read(() => held.promise); const confirmation = h.store.confirmation;
  const poll = h.store.refresh({ background: true }); await tick(); h.online(false); h.store.invalidateOffline();
  expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot().loadStatus).toBe('offline'); expect(h.signals.at(-1)?.aborted).toBe(true);
  held.resolve(page()); await poll; expect(h.store.confirmation).toBe(confirmation); expect(h.store.getSnapshot().loadStatus).toBe('offline');
  expect((await h.executor.act(intent())).kind).toBe('rejected'); expect(h.posts).toHaveLength(0);
  h.online(true); h.read(async () => page()); await h.store.refresh(); expect(h.store.actionReady).toBe(true); h.store.dispose();
});
test('a delayed watchdog cannot let a late completed read renew the expired confirmation', async () => {
  const h = await setup(); const held = deferred<Response>(); h.read(() => held.promise); const confirmation = h.store.confirmation;
  const poll = h.store.refresh({ background: true }); await tick(); const originalNow = Date.now; const after = Date.parse(h.store.getSnapshot().lastConfirmedAt!) + 16000;
  try { Date.now = () => after; expect(h.store.actionReady).toBe(false); held.resolve(page()); await poll; expect(h.store.confirmation).toBe(confirmation); expect(h.store.actionReady).toBe(false); expect(h.store.getSnapshot()).toMatchObject({ loadStatus: 'error', incomplete: true }); }
  finally { Date.now = originalNow; h.store.dispose(); }
});
test('the whole-sweep bound does not restart for later pages', async () => {
  const h = await setup(); const first = deferred<Response>(); const second = deferred<Response>(); let reads = 0; h.read(() => ++reads === 1 ? first.promise : second.promise);
  const confirmation = h.store.confirmation; const confirmedAt = Date.parse(h.store.getSnapshot().lastConfirmedAt!); const poll = h.store.refresh({ background: true }); await tick(); const originalNow = Date.now;
  try { let now = confirmedAt + 14000; Date.now = () => now; first.resolve(page([order()], 'next')); await tick(); expect(reads).toBe(2); now = confirmedAt + 16000; second.resolve(page([])); await poll; expect(h.store.confirmation).toBe(confirmation); expect(h.store.actionReady).toBe(false); }
  finally { Date.now = originalNow; h.store.dispose(); }
});
test('epoch loss hides the snapshot and ignores an old successful background completion', async () => {
  const h = await setup(); const held = deferred<Response>(); h.read(() => held.promise); const poll = h.store.refresh({ background: true }); await tick(); h.client.clearIdentity();
  held.resolve(page()); await poll; expect(h.store.getSnapshot().snapshot).toBeNull(); expect(h.store.confirmation).toBe(0); expect(h.store.actionReady).toBe(false); expect(h.posts).toHaveLength(0); h.store.dispose();
});
test('current scope loss is refused even before an identity notification or delayed page response', async () => {
  const h = await setup(); const held = deferred<Response>(); h.read(() => held.promise); const poll = h.store.refresh({ background: true }); await tick(); h.client.session!.principal.section_ids = [];
  expect(h.store.actionReady).toBe(false); expect((await h.executor.act(intent())).kind).toBe('rejected'); held.resolve(page()); await poll; expect(h.store.getSnapshot().snapshot).toBeNull(); expect(h.posts).toHaveLength(0); h.store.dispose();
});
test('local expiry blocks new commands and preserves an earlier unknown effect on explicit retry', async () => {
  const h = await setup(); h.write(async () => { throw new TypeError('Synthetic lost POST'); }); expect((await h.executor.act(intent())).kind).toBe('unknown'); expect(h.posts).toHaveLength(1);
  h.client.session!.expires_at = '2000-01-01T00:00:00Z'; expect(h.store.actionReady).toBe(false);
  expect(() => h.client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} })).toThrow();
  expect((await h.executor.retry(executorScope(ids.order, 1))).kind).toBe('unknown'); expect(h.posts).toHaveLength(1); expect(h.executor.view(order()).mutation.status).toBe('unknown_result'); h.store.dispose();
});
