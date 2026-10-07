import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { ids, json, result, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as Photos from '../../src/app/photoStore';
import type { PreparedPhoto } from '../../src/pwa/photoPreparation';
const { ApiClient, ApiError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { PhotoStore } = sourceModule<typeof Photos>('src/app/photoStore.ts');

for (const retryFailure of ['offline', '403', 'cooldown'] as const) {
  test(`unresolved photo effect stays unknown after ${retryFailure} retry failure and cannot be discarded`, async () => {
  let online = true; let sends = 0;
  const client = new ApiClient({ online: () => online, fetch: async url => {
    if (String(url).endsWith('/auth/login')) return json(session());
    sends += 1;
    if (sends > 1) return retryFailure === '403' ? json({}, 403) : new Response('{}', { status: 503, headers: { 'Retry-After': '60' } });
    throw new TypeError('Synthetic response lost after request may have committed');
  } });
  await client.login({ employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' });
  const store = new PhotoStore(client);
  const context: Photos.PhotoContext = { key: 'synthetic-unknown-upload', phase: 'after', sectionId: ids.section, orderId: ids.order, assignmentRevision: 1 };
  const file: PreparedPhoto = { id: 'synthetic-file', file: new File(['synthetic bytes'], 'synthetic.jpg', { type: 'image/jpeg' }), originalName: 'synthetic.jpg', originalBytes: 15, width: 1, height: 1, preparedAt: '2026-10-07T19:00:00Z' };
  store.select(context, [file]);
  await expect.poll(() => store.get(context).jobs[file.id]?.status).toBe('unknown');
  online = retryFailure !== 'offline';
  store.retry(context, file);
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(store.get(context).jobs[file.id]?.status).toBe('unknown');
  expect(store.transportLocked(context)).toBe(true);
  store.select(context, []);
  expect(store.get(context).files).toHaveLength(1);
  if (retryFailure === 'cooldown') {
    store.retry(context, file);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(store.get(context).jobs[file.id]?.status).toBe('unknown');
  }
  expect(sends).toBe(retryFailure === 'offline' ? 1 : 2);
  });
}


test('shared command/photo failure transition never resolves an already unknown effect from another failure', () => {
  const { mutationFailureState } = sourceModule<typeof import('../../src/app/mutationFailure')>('src/app/mutationFailure.ts');
  for (const status of [0, 403, 409, 422, 429, 503]) expect(mutationFailureState(new ApiError('Synthetic retry rejection', status), true)).toBe('unknown_result');
  expect(mutationFailureState(new Error('Synthetic preflight exception'), true)).toBe('unknown_result');
  expect(mutationFailureState(new ApiError('Synthetic conflict', 409), false)).toBe('conflict');
  expect(mutationFailureState(new ApiError('Synthetic known rejection', 422), false)).toBe('failed');
});

test('wrong-order command receipt remains unknown and retry retains the original operation identity', async () => {
  const bodies: string[] = [];
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    bodies.push(String(init?.body));
    const response = result();
    if (bodies.length === 1) response.order.id = ids.second;
    return json(response);
  } });
  await client.login({ employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' });
  const token = client.prepareCommand(ids.order, { expected_version: 1, action: 'accept', payload: {} });
  await expect(client.execute(token)).rejects.toMatchObject({ outcomeUnknown: true, status: 200 });
  await expect(client.execute(token)).resolves.toMatchObject({ order: { id: ids.order } });
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toBe(bodies[1]);
});

test('pending-first guard never reaches version/photo validation or UUID allocation while an effect is unresolved', async () => {
  const { withNewIntentGuard } = sourceModule<typeof import('../../src/app/mutationFailure')>('src/app/mutationFailure.ts');
  for (const intent of [{ status: 'pending' }, { status: 'unknown_result' }, { status: 'failed', unresolved: true }, { status: 'conflict', unresolved: true }]) {
    let began = 0;
    const outcome = await withNewIntentGuard(intent, async () => { began += 1; return { kind: 'conflict', message: 'Synthetic stale-version preflight must not run' }; });
    expect(outcome.kind).toBe('unknown');
    expect(began).toBe(0);
  }
});

test('new-intent guard permits a genuinely resolved or absent intent exactly once', async () => {
  const { withNewIntentGuard } = sourceModule<typeof import('../../src/app/mutationFailure')>('src/app/mutationFailure.ts');
  for (const intent of [undefined, { status: 'confirmed', unresolved: false }, { status: 'failed', unresolved: false }]) {
    let began = 0;
    const outcome = await withNewIntentGuard(intent, async () => { began += 1; return { kind: 'rejected', message: 'Known synthetic preflight rejection' }; });
    expect(began).toBe(1);
    expect(outcome.kind).toBe('rejected');
  }
});

test('conflict resolution cannot discard an unresolved token, even with a fresh complete snapshot', () => {
  const { canResolveIntent } = sourceModule<typeof import('../../src/app/mutationFailure')>('src/app/mutationFailure.ts');
  const fresh = { freshness: 'fresh', loadStatus: 'ready', incomplete: false };
  for (const intent of [{ status: 'pending' }, { status: 'unknown_result' }, { status: 'failed', unresolved: true }, { status: 'conflict', unresolved: true }]) expect(canResolveIntent(intent, fresh)).toBe(false);
  const conflict = { status: 'conflict', unresolved: false };
  expect(canResolveIntent(conflict, fresh)).toBe(true);
  for (const patch of [{ freshness: 'stale' }, { loadStatus: 'loading' }, { incomplete: true }]) expect(canResolveIntent(conflict, { ...fresh, ...patch })).toBe(false);
});
