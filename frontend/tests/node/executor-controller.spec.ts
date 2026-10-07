import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Store from '../../src/shared/api/orderStore';
import type * as Photos from '../../src/app/photoStore';
import type * as Executor from '../../src/app/executorController';
import type { Order } from '../../src/shared/api/wire';
import type { ExecutorDraft, ExecutorIntent } from '../../src/mobile/executor/types';
const { ApiClient } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { OrderStore } = sourceModule<typeof Store>('src/shared/api/orderStore.ts');
const { PhotoStore } = sourceModule<typeof Photos>('src/app/photoStore.ts');
const { ExecutorController, executorScope } = sourceModule<typeof Executor>('src/app/executorController.ts');

const B_ID = '10000000-0000-4000-8000-000000000007';
function order(id = ids.order, patch: Partial<Order> = {}): Order {
  return { ...result().order, id, number: id === ids.order ? 'SYNTHETIC-A' : 'SYNTHETIC-B', version: 1, status: 'issued', assignment: { executor_id: ids.first, brigade_id: null }, ...patch };
}
function draft(text: string): ExecutorDraft {
  return { workDescription: text, workCodeId: '', materials: [], afterPhotoIds: [], comment: '', reason: '' };
}
function accept(item: Order): ExecutorIntent {
  return { orderId: item.id, expectedVersion: item.version, expectedAssignmentRevision: item.assignment_revision, action: 'accept', payload: {} };
}
async function setup(send: (url: string, body: string) => Promise<Response>) {
  let items = [order(), order(B_ID)];
  let online = true;
  const requests: { url: string; body: string }[] = [];
  const executorSession = session(); executorSession.principal.role = 'executor';
  const client = new ApiClient({ online: () => online, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(executorSession);
    if ((init?.method ?? 'GET') === 'GET') return json({ items, next_cursor: null });
    const request = { url: String(url), body: String(init?.body) }; requests.push(request);
    return send(request.url, request.body);
  } });
  await client.login({ employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' });
  const orders = new OrderStore(client); const photos = new PhotoStore(client);
  const controller = new ExecutorController(client, orders, photos, 'synthetic-executor-session');
  await orders.refresh();
  return { client, orders, controller, requests, setItems: (next: Order[]) => { items = next; }, setOnline: (next: boolean) => { online = next; } };
}
function receipt(item: Order): Response { return json({ ...result(), order: { ...item, version: item.version + 1, status: 'accepted' } }); }

test('lost A then authorized omission and retry403 quarantines only A; B confirms independently', async () => {
  let aSends = 0;
  const h = await setup(async url => {
    if (url.includes(ids.order)) { if (++aSends === 1) throw new TypeError('Synthetic lost A response'); return json({}, 403); }
    return receipt(order(B_ID));
  });
  const a = order(); const b = order(B_ID); const scopeA = executorScope(a.id, 1);
  h.controller.setDraft(a.id, 1, draft('SYNTHETIC_PRIVATE_A'));
  h.controller.setDraft(b.id, 1, draft('SYNTHETIC_B_DRAFT'));
  expect((await h.controller.act(accept(a))).kind).toBe('unknown');
  h.setItems([b]); await h.orders.refresh();
  expect((await h.controller.retry(scopeA)).kind).toBe('unknown');
  expect(h.controller.quarantinedScopes()).toEqual([scopeA]);
  expect(h.controller.visibleOrders().map(item => item.id)).toEqual([B_ID]);
  expect(JSON.stringify(h.controller.view(a))).not.toContain('SYNTHETIC_PRIVATE_A');
  expect(h.controller.view(a).pendingIntent).toBeNull();
  expect(h.controller.draft(a).workDescription).toBe('');
  expect((await h.controller.act(accept(b))).kind).toBe('confirmed');
  expect(h.controller.draft(b).workDescription).toBe('SYNTHETIC_B_DRAFT');
  expect(h.controller.quarantinedScopes()).toEqual([scopeA]);
  expect(h.requests).toHaveLength(3);
  expect(h.requests[0].body).toBe(h.requests[1].body);
  expect(JSON.parse(h.requests[2].body).operation_id).not.toBe(JSON.parse(h.requests[0].body).operation_id);
  h.orders.dispose();
});

test('late A receipt after newer omission cannot resurrect A, modify B draft or release B pending intent', async () => {
  const lateA = deferred<Response>(); const lateB = deferred<Response>(); let aSends = 0;
  const h = await setup(async url => {
    if (url.includes(ids.order)) { if (++aSends === 1) throw new TypeError('Synthetic lost A response'); return lateA.promise; }
    return lateB.promise;
  });
  const a = order(); const b = order(B_ID); const scopeA = executorScope(a.id, 1);
  await h.controller.act(accept(a));
  const retryA = h.controller.retry(scopeA);
  h.setItems([b]); await h.orders.refresh();
  h.controller.setDraft(b.id, 1, draft('B must survive A completion'));
  const pendingB = h.controller.act(accept(b));
  lateA.resolve(receipt(a)); expect((await retryA).kind).toBe('confirmed');
  expect(h.controller.visibleOrders().map(item => item.id)).toEqual([B_ID]);
  expect(h.orders.getSnapshot().snapshot?.map(item => item.id)).toEqual([B_ID]);
  expect(h.controller.view(b).mutation.status).toBe('pending');
  expect(h.controller.draft(b).workDescription).toBe('B must survive A completion');
  expect((await h.controller.act(accept(b))).kind).toBe('unknown');
  expect(h.requests).toHaveLength(3);
  lateB.resolve(receipt(b)); expect((await pendingB).kind).toBe('confirmed');
  expect(h.controller.quarantinedScopes()).toEqual([]);
  h.orders.dispose();
});

test('unknown old assignment of A blocks new A assignment before preparing a new UUID but permits B', async () => {
  const h = await setup(async url => { if (url.includes(ids.order)) throw new TypeError('Synthetic lost A response'); return receipt(order(B_ID)); });
  const a = order(); const newerA = order(ids.order, { version: 5, assignment_revision: 2 });
  await h.controller.act(accept(a));
  h.setItems([newerA, order(B_ID)]); await h.orders.refresh();
  h.controller.setDraft(a.id, 2, draft('Must not replace frozen A draft'));
  expect(h.controller.canEdit(a.id, 2)).toBe(false);
  expect((await h.controller.act(accept(newerA))).kind).toBe('unknown');
  expect(h.requests).toHaveLength(1);
  h.controller.resolveConflict(executorScope(a.id, 1));
  expect((await h.controller.act(accept(newerA))).kind).toBe('unknown');
  expect(h.controller.view(newerA).mutation.status).toBe('unknown_result');
  expect((await h.controller.act(accept(order(B_ID)))).kind).toBe('confirmed');
  expect(h.requests).toHaveLength(2);
  h.orders.dispose();
});

test('offline retry preserves A uncertainty and frozen draft without automatic resends', async () => {
  const h = await setup(async () => { throw new TypeError('Synthetic lost response'); });
  const a = order(); const scope = executorScope(a.id, 1);
  h.controller.setDraft(a.id, 1, draft('Original A draft'));
  await h.controller.act(accept(a)); h.setOnline(false);
  expect((await h.controller.retry(scope)).kind).toBe('unknown');
  h.controller.setDraft(a.id, 1, draft('Must not overwrite'));
  expect(h.controller.draft(a).workDescription).toBe('Original A draft');
  expect(h.controller.view(a).mutation.status).toBe('unknown_result');
  h.setOnline(true); await h.orders.refresh();
  h.controller.view(a); h.controller.visibleOrders(); h.controller.quarantinedScopes();
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(h.requests).toHaveLength(1);
  h.orders.dispose();
});

test('explicit403 hides cached A until a newer complete authorized list, independently of B receipts', async () => {
  const h = await setup(async url => url.includes(ids.order) ? json({}, 403) : receipt(order(B_ID)));
  const a = order(); const b = order(B_ID);
  expect((await h.controller.act(accept(a))).kind).toBe('rejected');
  const confirmation = h.orders.confirmation;
  expect(h.controller.visibleOrders().map(item => item.id)).toEqual([B_ID]);
  await h.controller.act(accept(b));
  expect(h.orders.confirmation).toBe(confirmation);
  expect(h.controller.visibleOrders().map(item => item.id)).toEqual([B_ID]);
  await h.orders.refresh();
  expect(h.orders.confirmation).toBe(confirmation + 1);
  expect(h.controller.visibleOrders().map(item => item.id)).toContain(a.id);
  h.orders.dispose();
});

test('old assignment draft callback cannot mutate newer assignment or another identity', async () => {
  const h = await setup(async () => receipt(order()));
  const a = order(); const newA = order(ids.order, { assignment_revision: 2, version: 3 });
  h.controller.setDraft(a.id, 1, draft('Old assignment'));
  h.setItems([newA]); await h.orders.refresh();
  h.controller.setDraft(a.id, 1, draft('Late old assignment callback'));
  expect(h.controller.draft(newA).workDescription).toBe('');
  h.controller.setDraft(a.id, 2, draft('New assignment'));
  h.client.clearIdentity();
  h.controller.setDraft(a.id, 2, draft('Late previous identity callback'));
  expect(h.controller.visibleOrders()).toEqual([]);
  expect(h.controller.draft(newA).workDescription).toBe('');
  expect((await h.controller.act(accept(newA))).kind).toBe('rejected');
  expect(h.requests).toHaveLength(0);
  h.orders.dispose();
});
