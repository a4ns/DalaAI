import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Store from '../../src/shared/api/orderStore';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { OrderStore, mergeOrderVersion } = sourceModule<typeof Store>('src/shared/api/orderStore.ts');

test('an old command receipt never rolls back a newer order version', () => {
  const old = result().order;
  const newer = { ...old, version: 8, status: 'closed' as const };
  expect(mergeOrderVersion(newer, old)).toEqual(newer);
});

test('equal-version fresh server time updates computed overdue without rollback from older time', () => {
  const old = result().order;
  const fresh = { ...old, domain_now: '2026-10-08T05:00:00Z', is_overdue: true };
  expect(mergeOrderVersion(old, fresh).is_overdue).toBe(true);
  expect(mergeOrderVersion(fresh, old).domain_now).toBe(fresh.domain_now);
});

test('first load failure is unknown, not a confirmed empty list', async () => {
  const client = new ApiClient({ online: () => true, fetch: async () => { throw new TypeError('Synthetic offline'); } });
  const store = new OrderStore(client);
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({ snapshot: null, freshness: 'never', incomplete: true });
  expect(store.getSnapshot().loadStatus).not.toBe('ready');
  store.dispose();
});

test('partial failed sweep preserves prior membership and marks it stale/incomplete', async () => {
  const initial = result().order;
  const additional = { ...initial, id: ids.second, number: 'SYNTHETIC-002' };
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => {
    calls += 1;
    if (calls === 1) return json({ items: [initial], next_cursor: null });
    if (calls === 2) return json({ items: [additional], next_cursor: 'page-2' });
    throw new TypeError('Synthetic second page failure');
  } });
  const store = new OrderStore(client);
  await store.refresh();
  const previousConfirmed = store.getSnapshot().lastConfirmedAt;
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({ freshness: 'stale', incomplete: true, lastConfirmedAt: previousConfirmed });
  expect(store.getSnapshot().snapshot?.map(order => order.id)).toEqual([initial.id]);
  store.dispose();
});

test('only a complete successful fresh sweep can remove old list membership', async () => {
  let calls = 0;
  const second = deferred<Response>();
  const initial = result().order;
  const other = { ...initial, id: ids.second, number: 'SYNTHETIC-002' };
  const client = new ApiClient({ online: () => true, fetch: async () => {
    calls += 1;
    if (calls === 1) return json({ items: [initial], next_cursor: null });
    if (calls === 2) return json({ items: [other], next_cursor: 'page-2' });
    return second.promise;
  } });
  const store = new OrderStore(client);
  await store.refresh();
  const refresh = store.refresh();
  await expect.poll(() => calls).toBe(3);
  expect(store.getSnapshot().snapshot?.map(order => order.id)).toContain(initial.id);
  second.resolve(json({ items: [], next_cursor: null }));
  await refresh;
  expect(store.getSnapshot()).toMatchObject({ freshness: 'fresh', loadStatus: 'ready', incomplete: false });
  expect(store.getSnapshot().snapshot?.map(order => order.id)).toEqual([other.id]);
  store.dispose();
});

test('repeated server cursors terminate as incomplete, never as complete or an infinite loop', async () => {
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => {
    calls += 1;
    if (calls > 3) throw new Error('Cursor loop exceeded bounded assertion');
    return json({ items: [result().order], next_cursor: 'same' });
  } });
  const store = new OrderStore(client);
  await store.refresh();
  expect(calls).toBe(2);
  expect(store.getSnapshot()).toMatchObject({ snapshot: null, freshness: 'never', incomplete: true });
  store.dispose();
});

test('clearing identity immediately hides snapshots and ignores the late previous sweep', async () => {
  const late = deferred<Response>();
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => ++calls === 1 ? json({ items: [result().order], next_cursor: null }) : late.promise });
  const store = new OrderStore(client);
  await store.refresh();
  expect(store.getSnapshot().snapshot).toHaveLength(1);
  const refresh = store.refresh();
  client.clearIdentity();
  expect(store.getSnapshot().snapshot).toBeNull();
  late.resolve(json({ items: [result().order], next_cursor: null }));
  await refresh;
  expect(store.getSnapshot()).toMatchObject({ snapshot: null, freshness: 'never', loadStatus: 'idle' });
  store.record(result().order, client.epoch - 1);
  expect(store.getSnapshot().snapshot).toBeNull();
  store.dispose();
});

test('a newer receipt arriving during refresh survives an older page response', async () => {
  const delayed = deferred<Response>();
  const client = new ApiClient({ online: () => true, fetch: async url => String(url).endsWith('/auth/login') ? json(session()) : delayed.promise });
  await client.login({ employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' });
  const store = new OrderStore(client);
  const refresh = store.refresh();
  store.record({ ...result().order, version: 6, status: 'closed' }, client.epoch);
  delayed.resolve(json({ items: [result().order], next_cursor: null }));
  await refresh;
  expect(store.getSnapshot().snapshot?.[0]).toMatchObject({ version: 6, status: 'closed' });
  store.dispose();
});

test('only an explicit 403 marks access forbidden; transport errors retain stale data without inventing denial', async () => {
  for (const status of [403, 503]) {
    const client = new ApiClient({ online: () => true, fetch: async () => json({}, status) });
    const store = new OrderStore(client);
    store.record(result().order, client.epoch);
    await store.refresh();
    expect(store.access).toBe(status === 403 ? 'forbidden' : 'allowed');
    if (status === 403) expect(store.getSnapshot().snapshot).toBeNull();
    else expect(store.getSnapshot()).toMatchObject({ freshness: 'stale', incomplete: true, snapshot: [result().order] });
    store.dispose();
  }
});

test('a confirmed allowed response or identity reset clears an old forbidden flag', async () => {
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => ++calls === 1 ? json({}, 403) : json({ items: [], next_cursor: null }) });
  const store = new OrderStore(client);
  await store.refresh();
  expect(store.access).toBe('forbidden');
  await store.refresh();
  expect(store.access).toBe('allowed');
  expect(store.getSnapshot()).toMatchObject({ snapshot: [], freshness: 'fresh', loadStatus: 'ready' });
  client.clearIdentity();
  expect(store.access).toBe('allowed');
  expect(store.getSnapshot().snapshot).toBeNull();
  store.dispose();
});


test('an initial partial page failure leaves membership unknown instead of publishing page discoveries', async () => {
  let calls = 0;
  const client = new ApiClient({ online: () => true, fetch: async () => {
    if (++calls === 1) return json({ items: [result().order], next_cursor: 'next-page' });
    throw new TypeError('Synthetic later page failure');
  } });
  const store = new OrderStore(client);
  await store.refresh();
  expect(store.getSnapshot()).toMatchObject({ snapshot: null, freshness: 'never', incomplete: true, lastConfirmedAt: null });
  expect(store.getSnapshot().loadStatus).not.toBe('ready');
  store.dispose();
});

test('a failed sweep preserves concurrent confirmed receipt updates without publishing discovered page membership', async () => {
  const laterPage = deferred<Response>();
  let calls = 0;
  const initial = result().order;
  const discovered = { ...initial, id: ids.second, number: 'SYNTHETIC-002' };
  const receipt = { ...initial, id: ids.equipment, number: 'SYNTHETIC-003', version: 9 };
  const client = new ApiClient({ online: () => true, fetch: async () => {
    calls += 1;
    if (calls === 1) return json({ items: [initial], next_cursor: null });
    if (calls === 2) return json({ items: [discovered], next_cursor: 'next-page' });
    return laterPage.promise;
  } });
  const store = new OrderStore(client);
  await store.refresh();
  const refresh = store.refresh();
  await expect.poll(() => calls).toBe(3);
  store.record({ ...initial, version: 8 }, client.epoch);
  store.record(receipt, client.epoch);
  laterPage.reject(new TypeError('Synthetic failure after independently confirmed receipts'));
  await refresh;
  expect(store.getSnapshot()).toMatchObject({ freshness: 'stale', incomplete: true });
  expect(store.getSnapshot().snapshot?.map(order => order.id).sort()).toEqual([initial.id, receipt.id].sort());
  expect(store.getSnapshot().snapshot?.find(order => order.id === initial.id)?.version).toBe(8);
  store.dispose();
});
