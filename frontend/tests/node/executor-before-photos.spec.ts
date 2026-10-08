import { expect, test } from '@playwright/test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { sourceModule } from '../support/source';
import { ssrSourceModule } from '../support/ssr-source';
import { deferred, ids, result, session } from '../support/synthetic';
import type * as Before from '../../src/mobile/executor/beforePhotos';
import type * as Component from '../../src/mobile/executor/ExecutorBeforePhotos';
import type * as Client from '../../src/shared/api/client';
import type * as Adapters from '../../src/app/adapters';
import type { Order, Session } from '../../src/shared/api/wire';
import type { OrderStore } from '../../src/shared/api/orderStore';
import type { ResourceState } from '../../src/shared/ui/types';

const { BeforePhotosController } = sourceModule<typeof Before>('src/mobile/executor/beforePhotos.ts');
const { ApiError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const image = () => new Blob(['synthetic-test-bytes'], { type: 'image/png' });
const photoId = (n: number) => `20000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
async function settle() { for (let i = 0; i < 6; i++) await Promise.resolve(); }
function harness(photoIds = [photoId(1)], read: (id: string, signal?: AbortSignal) => Promise<Blob> = async () => image()) {
  const order: Order = { ...result().order, before_photo_ids: photoIds };
  let state: ResourceState<Order[]> = { snapshot: [order], freshness: 'fresh', loadStatus: 'ready', error: null, lastConfirmedAt: '2026-10-08T08:00:00Z', incomplete: false };
  const clientListeners = new Set<() => void>(); const orderListeners = new Set<() => void>();
  const calls: { id: string; signal?: AbortSignal }[] = []; const created: Blob[] = []; const revoked: string[] = [];
  const client = { epoch: 1, session: { ...session(ids.second), principal: { ...session(ids.second).principal, role: 'executor' } } as Session | null,
    subscribe(listener: () => void) { clientListeners.add(listener); return () => { clientListeners.delete(listener); }; },
    getPhoto(id: string, signal?: AbortSignal) { calls.push({ id, signal }); return read(id, signal); } };
  const orders = { access: 'allowed', confirmation: 1, getSnapshot: () => state,
    subscribe(listener: () => void) { orderListeners.add(listener); return () => { orderListeners.delete(listener); }; } };
  const scope = { orderId: order.id, sectionId: order.section_id, assignmentRevision: order.assignment_revision, photoIds };
  const controller = new BeforePhotosController(client as unknown as Client.ApiClient, orders as unknown as OrderStore, scope, () => true,
    { createObjectURL(blob) { if (!(blob instanceof Blob)) throw new Error("Expected Blob"); created.push(blob); return `blob:synthetic/${created.length}`; }, revokeObjectURL(url) { revoked.push(url); } });
  return { client, orders, controller, calls, created, revoked, scope, order,
    setState(next: Partial<ResourceState<Order[]>>) { state = { ...state, ...next }; orderListeners.forEach(fn => fn()); },
    identityChanged() { clientListeners.forEach(fn => fn()); },
    listeners: () => clientListeners.size + orderListeners.size };
}

test('current assigned order loads actual returned Blob and revokes its URL on unmount', async () => {
  const blob = image(); const h = harness([photoId(1)], async () => blob); const stop = h.controller.attach();
  await h.controller.load(); expect(h.calls.map(call => call.id)).toEqual([photoId(1)]); expect(h.created).toEqual([blob]);
  expect(h.controller.getSnapshot()).toMatchObject({ status: 'ready', photos: [{ id: photoId(1), status: 'ready', url: 'blob:synthetic/1' }] });
  stop(); expect(h.revoked).toEqual(['blob:synthetic/1']); expect(h.controller.getSnapshot().photos).toEqual([]); expect(h.listeners()).toBe(0);
});
test('read boundary is five unique IDs and two concurrent reads; repeated pending loads are inert', async () => {
  const waits = new Map<string, ReturnType<typeof deferred<Blob>>>();
  const allIds = Array.from({ length: 8 }, (_, index) => photoId(index + 1));
  const h = harness(allIds, id => { const wait = deferred<Blob>(); waits.set(id, wait); return wait.promise; }); const stop = h.controller.attach();
  const loading = h.controller.load(); void h.controller.load(); void h.controller.load(); expect(h.calls).toHaveLength(2);
  waits.get(photoId(1))!.resolve(image()); await settle(); expect(h.calls).toHaveLength(3);
  waits.get(photoId(2))!.resolve(image()); await settle(); expect(h.calls).toHaveLength(4);
  waits.get(photoId(3))!.resolve(image()); await settle(); expect(h.calls).toHaveLength(5);
  waits.get(photoId(4))!.resolve(image()); waits.get(photoId(5))!.resolve(image()); await loading;
  expect(h.calls.map(call => call.id)).toEqual(allIds.slice(0, 5)); expect(h.controller.getSnapshot().photos).toHaveLength(5); stop();
});
test('quiet polls and version-only commands preserve authorized URLs without more requests', async () => {
  const h = harness(); const stop = h.controller.attach(); await h.controller.load();
  h.setState({ freshness: 'stale', loadStatus: 'loading' }); expect(h.revoked).toEqual([]);
  h.setState({ freshness: 'fresh', loadStatus: 'ready', snapshot: [{ ...h.order, version: 3, status: 'in_progress' }] });
  expect(h.controller.getSnapshot().photos[0].url).toBe('blob:synthetic/1'); expect(h.calls).toHaveLength(1); stop();
});
for (const loss of ['identity', 'role', 'section', 'assignee', 'revision', 'references', 'missing', 'forbidden', 'partial', 'selection'] as const) {
  test(`${loss} loss synchronously clears URLs and prevents late response publication`, async () => {
    const slow = deferred<Blob>(); const h = harness([photoId(1), photoId(2)], async id => id === photoId(1) ? image() : slow.promise);
    const stop = h.controller.attach(); const pending = h.controller.load(); await settle(); expect(h.created).toHaveLength(1);
    if (loss === 'identity') { h.client.epoch++; h.identityChanged(); }
    if (loss === 'role') { h.client.session!.principal.role = 'master'; h.identityChanged(); }
    if (loss === 'section') { h.client.session!.principal.section_ids = []; h.identityChanged(); }
    if (loss === 'assignee') h.setState({ snapshot: [{ ...h.order, assignment: { ...h.order.assignment, executor_id: ids.first } }] });
    if (loss === 'revision') h.setState({ snapshot: [{ ...h.order, assignment_revision: 2 }] });
    if (loss === 'references') h.setState({ snapshot: [{ ...h.order, before_photo_ids: [photoId(3)] }] });
    if (loss === 'missing') h.setState({ snapshot: [] });
    if (loss === 'forbidden') { h.orders.access = 'forbidden'; h.setState({}); }
    if (loss === 'partial') h.setState({ incomplete: true, loadStatus: 'error' });
    if (loss === 'selection') h.controller.setCurrent(() => false);
    expect(h.revoked).toEqual(['blob:synthetic/1']); expect(h.calls[1].signal?.aborted).toBe(true); expect(h.controller.getSnapshot().photos).toEqual([]);
    slow.resolve(image()); await pending; expect(h.created).toHaveLength(1); await h.controller.load(); expect(h.calls).toHaveLength(2); stop();
  });
}
test('403 clears the whole group, aborts peers and requires a newer authorized order confirmation', async () => {
  const denied = deferred<Blob>(); const h = harness([photoId(1), photoId(2), photoId(3)], id => id === photoId(1) ? Promise.resolve(image()) : denied.promise);
  const stop = h.controller.attach(); const pending = h.controller.load(); await settle(); denied.reject(new ApiError('Synthetic denial', 403)); await pending;
  expect(h.revoked).toEqual(['blob:synthetic/1']); expect(h.controller.getSnapshot().photos).toEqual([]); expect(h.calls.every(call => call.signal?.aborted)).toBe(true);
  const count = h.calls.length; await h.controller.load(); expect(h.calls).toHaveLength(count); stop();
});
test('404 is explicit missing evidence and never creates a URL', async () => {
  const h = harness([photoId(1)], async () => { throw new ApiError('Synthetic missing', 404); }); const stop = h.controller.attach(); await h.controller.load();
  expect(h.controller.getSnapshot()).toMatchObject({ status: 'ready', photos: [{ status: 'missing', url: null }] }); expect(h.created).toEqual([]); stop();
});
test('unselected or unrelated order makes no requests', async () => {
  for (const cause of ['selection', 'assignee']) {
    const h = harness(); if (cause === 'selection') h.controller.setCurrent(() => false);
    else h.setState({ snapshot: [{ ...h.order, assignment: { ...h.order.assignment, executor_id: ids.first } }] });
    const stop = h.controller.attach(); await h.controller.load(); expect(h.calls).toEqual([]); stop();
  }
});
test('unmount aborts slow responses; reattach and retry cannot publish the old run', async () => {
  const old = deferred<Blob>(); const h = harness([photoId(1)], async () => h.calls.length === 1 ? old.promise : image());
  const stop = h.controller.attach(); const pending = h.controller.load(); stop(); expect(h.calls[0].signal?.aborted).toBe(true);
  const stopAgain = h.controller.attach(); await h.controller.load(); old.resolve(image()); await pending;
  expect(h.created).toHaveLength(1); expect(h.controller.getSnapshot().photos[0].url).toBe('blob:synthetic/1'); stopAgain();
});
test('invalid image type and broken image display never remain evidence', async () => {
  const h = harness([photoId(1), photoId(2)], async id => id === photoId(1) ? image() : new Blob(['text'], { type: 'text/html' }));
  const stop = h.controller.attach(); await h.controller.load(); expect(h.created).toHaveLength(1);
  h.controller.imageFailed(photoId(1)); expect(h.revoked).toEqual(['blob:synthetic/1']); expect(h.controller.getSnapshot().photos.every(photo => photo.status === 'failed' && photo.url === null)).toBe(true); stop();
});
test('adapter copies only attached IDs and disabled real React component renders no photo subtree', () => {
  const { executorOrder } = sourceModule<typeof Adapters>('src/app/adapters.ts'); const h = harness();
  const model = executorOrder(h.order, null); expect(model.beforePhotoIds).toEqual([photoId(1)]); expect(model.beforePhotoIds).not.toBe(h.order.before_photo_ids);
  const { ExecutorBeforePhotos } = ssrSourceModule<typeof Component>('src/mobile/executor/ExecutorBeforePhotos.tsx');
  const html = renderToStaticMarkup(createElement(ExecutorBeforePhotos, { client: h.client as unknown as Client.ApiClient, orders: h.orders as unknown as OrderStore, sessionKey: 'synthetic', scope: h.scope, enabled: false, isAuthReady: () => false }));
  expect(html).toBe(''); expect(h.calls).toEqual([]);
});

test('denied photos retry only explicitly after a newer authorized confirmation', async () => {
  let denied = true; const h = harness([photoId(1)], async () => { if (denied) throw new ApiError('Synthetic denial', 403); return image(); });
  const stop = h.controller.attach(); await h.controller.load(); expect(h.controller.getSnapshot().canRetry).toBe(false);
  denied = false; h.orders.confirmation++; h.setState({}); expect(h.controller.getSnapshot().canRetry).toBe(true);
  expect(h.calls).toHaveLength(1); await h.controller.load(); expect(h.calls).toHaveLength(2); expect(h.controller.getSnapshot().photos[0].status).toBe('ready'); stop();
});

test('the existing eight-MiB photo limit accepts its boundary and rejects one excess byte', async () => {
  const limit = 8 * 1024 * 1024;
  const h = harness([photoId(1), photoId(2)], async id => new Blob([new Uint8Array(limit + (id === photoId(2) ? 1 : 0))], { type: 'image/png' }));
  const stop = h.controller.attach(); await h.controller.load(); expect(h.created).toHaveLength(1); expect(h.created[0].size).toBe(limit);
  expect(h.controller.getSnapshot().photos.map(photo => photo.status)).toEqual(['ready', 'failed']); stop();
});
