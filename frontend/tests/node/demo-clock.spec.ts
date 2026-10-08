import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, session } from '../support/synthetic';
import { clock } from '../support/demo-clock';
import type * as Client from '../../src/shared/api/client';
import type * as Protocol from '../../src/shared/api/demoClockProtocol';
import type * as Controller from '../../src/features/demoClock/controller';
const { ApiClient, SessionChangedError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { isDemoClockSnapshot, isDemoClockChange, isDemoClockControl, mergeDemoClock } = sourceModule<typeof Protocol>('src/shared/api/demoClockProtocol.ts');
const { DemoClockController } = sourceModule<typeof Controller>('src/features/demoClock/controller.ts');
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };

async function setup(send: (url: string, init: RequestInit) => Promise<Response>) {
  let ready = true;
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => String(url).endsWith('/auth/login') ? json(session()) : send(String(url), init!) });
  await client.login(credentials); const controller = new DemoClockController(client, () => ready); const cleanup = controller.attach();
  return { client, controller, cleanup, blockAuth: () => { ready = false; } };
}
const success = (scale: number) => clock({ version: 4, scale });

test('clock guards require actual capability fields and exact bounded CAS changes, without reset or operation IDs', () => {
  expect(isDemoClockSnapshot(clock())).toBe(true);
  for (const patch of [{ mode: 'wall_time' }, { reset_supported: true }, { storage: ['postgres_shared'] }, { scale: 61 }, { version: 2147483648 }, { domain_now: '2026-10-16T00:00:00Z' }]) expect(isDemoClockSnapshot({ ...clock(), ...patch })).toBe(false);
  for (const scale of [0, 1, 60]) expect(isDemoClockChange({ action: 'set_scale', scale })).toBe(true);
  for (const seconds of [1, 3600]) expect(isDemoClockChange({ action: 'advance', seconds })).toBe(true);
  for (const change of [{ action: 'reset' }, { action: 'advance', seconds: 0 }, { action: 'advance', seconds: 3601 }, { action: 'set_scale', scale: 0.5 }, { action: 'set_scale', scale: 1, instance_id: ids.first }]) expect(isDemoClockChange(change)).toBe(false);
  const control = { instance_id: clock().instance_id, expected_version: 3, action: 'set_scale', scale: 0 };
  expect(isDemoClockControl(control)).toBe(true);
  expect(isDemoClockControl({ ...control, operation_id: ids.event })).toBe(false);
});

test('clock read is explicit and absent or denied capability never becomes a fake clock', async () => {
  for (const status of [403, 404, 503]) {
    let reads = 0; let posts = 0;
    const h = await setup(async (_url, init) => { if (init.method === 'POST') posts++; else reads++; return json({}, status); });
    expect(reads).toBe(0); expect(h.controller.getSnapshot().snapshot).toBeNull();
    await h.controller.refresh(); expect(h.controller.getSnapshot().snapshot).toBeNull();
    expect(h.controller.getSnapshot().readStatus).toBe(status === 503 ? 'error' : 'unavailable');
    expect(await h.controller.change({ action: 'set_scale', scale: 0 })).toBe(false); expect(posts).toBe(0); h.cleanup();
  }
});

test('prepared clock intent captures immutable instance/version/body and sends exactly once with CSRF', async () => {
  const sent: { url: string; init: RequestInit }[] = [];
  const h = await setup(async (url, init) => { sent.push({ url, init }); return json(success(0)); });
  const snapshot = clock(); const change: Protocol.DemoClockChange = { action: 'set_scale', scale: 0 };
  const token = h.client.prepareDemoClock(snapshot, change);
  snapshot.version = 90; snapshot.instance_id = ids.second; change.scale = 60;
  const first = h.client.executeDemoClock(token); const second = h.client.executeDemoClock(token);
  expect(first).toBe(second); await first; await h.client.executeDemoClock(token);
  expect(sent).toHaveLength(1); expect(sent[0].url).toBe('/api/v1/demo/clock');
  expect(JSON.parse(String(sent[0].init.body))).toEqual({ instance_id: clock().instance_id, expected_version: 3, action: 'set_scale', scale: 0 });
  expect(new Headers(sent[0].init.headers).get('X-CSRF-Token')).toBe(session().csrf_token);
  expect(sent[0].init).toMatchObject({ method: 'POST', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store' });
  expect(Object.isFrozen(token.intent)).toBe(true); h.cleanup();
});

test('unknown clock token never resends after rejection; a later GET cannot prove or unlock its effect', async () => {
  let tokenPosts = 0;
  const direct = await setup(async () => { tokenPosts++; throw new TypeError('Synthetic response lost'); });
  const token = direct.client.prepareDemoClock(clock(), { action: 'advance', seconds: 60 });
  await expect(direct.client.executeDemoClock(token)).rejects.toMatchObject({ outcomeUnknown: true });
  await expect(direct.client.executeDemoClock(token)).rejects.toMatchObject({ outcomeUnknown: true });
  expect(tokenPosts).toBe(1); direct.cleanup();
  let posts = 0; let reads = 0;
  const h = await setup(async (_url, init) => {
    if (init.method === 'POST') { posts++; throw new TypeError('Synthetic controller-owned response lost'); }
    reads++; return json(reads === 1 ? clock() : clock({ version: 5, scale: 60 }));
  });
  await h.controller.refresh(); await h.controller.change({ action: 'advance', seconds: 60 });
  await h.controller.refresh(); h.controller.resolveConflict();
  expect(h.controller.getSnapshot()).toMatchObject({ operation: 'unknown', snapshot: { version: 5 } });
  expect(await h.controller.change({ action: 'set_scale', scale: 0 })).toBe(false); expect(posts).toBe(1);
  h.cleanup(); const reattached = h.controller.attach(); await h.controller.refresh();
  expect(h.controller.getSnapshot().operation).toBe('unknown');
  expect(await h.controller.change({ action: 'set_scale', scale: 0 })).toBe(false); expect(posts).toBe(1); reattached();
});

test('wrong-instance, wrong-version and wrong-change successful responses remain ambiguous and are never retried', async () => {
  for (const response of [clock({ instance_id: ids.second, version: 4, scale: 0 }), clock({ version: 5, scale: 0 }), clock({ version: 4, scale: 5 }), {}]) {
    let posts = 0; const h = await setup(async () => { posts++; return json(response); });
    const token = h.client.prepareDemoClock(clock(), { action: 'set_scale', scale: 0 });
    await expect(h.client.executeDemoClock(token)).rejects.toMatchObject({ outcomeUnknown: true });
    await expect(h.client.executeDemoClock(token)).rejects.toMatchObject({ outcomeUnknown: true }); expect(posts).toBe(1); h.cleanup();
  }
});

test('advance result must move forward at least the requested amount within the same horizon', async () => {
  for (const domain of ['2026-10-09T00:00:30Z', '2026-10-09T00:01:00Z']) {
    const h = await setup(async () => json(clock({ version: 4, domain_now: domain, domain_anchor: domain })));
    const token = h.client.prepareDemoClock(clock(), { action: 'advance', seconds: 60 });
    if (domain.endsWith('30Z')) await expect(h.client.executeDemoClock(token)).rejects.toMatchObject({ outcomeUnknown: true });
    else await expect(h.client.executeDemoClock(token)).resolves.toMatchObject({ version: 4, domain_now: domain });
    h.cleanup();
  }
});

test('double-click reserves one clock mutation and pending input changes cannot issue another command', async () => {
  const late = deferred<Response>(); let posts = 0;
  const h = await setup(async (_url, init) => { if (init.method === 'POST') { posts++; return late.promise; } return json(clock()); });
  await h.controller.refresh(); const first = h.controller.change({ action: 'set_scale', scale: 0 });
  expect(await h.controller.change({ action: 'advance', seconds: 3600 })).toBe(false);
  late.resolve(json(success(0))); expect(await first).toBe(true); expect(posts).toBe(1); h.cleanup();
});

test('409 requires a read started after the conflict and explicit acknowledgement, without a replay', async () => {
  const priorRead = deferred<Response>(); const denied = deferred<Response>(); let reads = 0; let posts = 0; const bodies: string[] = [];
  const h = await setup(async (_url, init) => {
    if (init.method === 'POST') { bodies.push(String(init.body)); posts++; return posts === 1 ? denied.promise : json(clock({ version: 5, scale: 1 })); }
    reads++; return reads === 1 ? json(clock()) : reads === 2 ? priorRead.promise : json(clock({ version: 4, scale: 5 }));
  });
  await h.controller.refresh(); const write = h.controller.change({ action: 'set_scale', scale: 0 }); const oldRead = h.controller.refresh();
  denied.resolve(json({}, 409)); await write;
  priorRead.resolve(json(clock({ version: 4, scale: 5 }))); await oldRead;
  h.controller.resolveConflict(); expect(h.controller.getSnapshot().operation).toBe('conflict'); expect(h.controller.getSnapshot().canResolveConflict).toBe(false);
  await h.controller.refresh(); expect(h.controller.getSnapshot().canResolveConflict).toBe(true);
  expect(h.controller.getSnapshot().operation).toBe('conflict'); expect(posts).toBe(1);
  h.controller.resolveConflict(); expect(h.controller.getSnapshot().operation).toBe('idle'); expect(posts).toBe(1);
  expect(await h.controller.change({ action: 'set_scale', scale: 1 })).toBe(true);
  expect(JSON.parse(bodies[1])).toMatchObject({ expected_version: 4, scale: 1 }); expect(posts).toBe(2); h.cleanup();
});

test('late lower-version GET does not roll back a confirmed control snapshot', async () => {
  const late = deferred<Response>(); const writeReply = deferred<Response>(); let reads = 0;
  const h = await setup(async (_url, init) => init.method === 'POST' ? writeReply.promise : ++reads === 1 ? json(clock()) : late.promise);
  await h.controller.refresh(); const write = h.controller.change({ action: 'set_scale', scale: 0 }); const read = h.controller.refresh();
  writeReply.resolve(json(success(0))); await write; late.resolve(json(clock())); await read;
  expect(h.controller.getSnapshot()).toMatchObject({ operation: 'confirmed', snapshot: { version: 4, scale: 0 } }); h.cleanup();
  expect(mergeDemoClock(clock({ version: 4 }), clock()).version).toBe(4);
});

test('epoch and synchronous logout latch prevent new controls and suppress old responses', async () => {
  const late = deferred<Response>(); let posts = 0;
  const h = await setup(async (_url, init) => { if (init.method === 'POST') { posts++; return late.promise; } return json(clock()); });
  await h.controller.refresh(); h.blockAuth(); expect(await h.controller.change({ action: 'set_scale', scale: 0 })).toBe(false); expect(posts).toBe(0); h.cleanup();
  const other = await setup(async (_url, init) => init.method === 'POST' ? late.promise : json(clock()));
  await other.controller.refresh(); const pending = other.controller.change({ action: 'set_scale', scale: 0 });
  other.client.clearIdentity(); late.resolve(json(success(0))); await pending;
  expect(other.controller.getSnapshot().snapshot).toBeNull(); expect(other.controller.getSnapshot().operation).toBe('idle'); other.cleanup();
});

test('old prepared clock intent cannot cross identity even before its queued send starts', async () => {
  let posts = 0; const h = await setup(async () => { posts++; return json(success(0)); });
  const token = h.client.prepareDemoClock(clock(), { action: 'set_scale', scale: 0 });
  const pending = h.client.executeDemoClock(token); const rejected = expect(pending).rejects.toBeInstanceOf(SessionChangedError);
  h.client.clearIdentity(); await rejected; expect(posts).toBe(0); h.cleanup();
});


test('real auth expiry becomes unavailable on interaction and preserves an already pending clock effect as unknown', async () => {
  const originalNow = Date.now; let now = originalNow(); Date.now = () => now;
  try {
    for (const wasPending of [false, true]) {
      const signed = session(); signed.expires_at = new Date(now + 5000).toISOString();
      const late = deferred<Response>(); let posts = 0; let reads = 0;
      const client = new ApiClient({ online: () => true, fetch: async (url, init) => {
        if (String(url).endsWith('/auth/login')) return json(signed);
        if (init?.method === 'POST') { posts++; return late.promise; }
        reads++; return json(clock());
      } });
      await client.login(credentials); const controller = new DemoClockController(client); const cleanup = controller.attach();
      await controller.refresh(); const pending = wasPending ? controller.change({ action: 'set_scale', scale: 0 }) : null;
      await new Promise(resolve => setTimeout(resolve, 0));
      now += 5001; await controller.refresh();
      expect(controller.getSnapshot()).toMatchObject({ snapshot: null, readStatus: 'unavailable' });
      expect(controller.getSnapshot().readError).toContain('Сессия');
      expect(reads).toBe(1); expect(await controller.change({ action: 'advance', seconds: 1 })).toBe(false);
      expect(posts).toBe(wasPending ? 1 : 0);
      if (pending) { expect(controller.getSnapshot().operation).toBe('unknown'); late.resolve(json(success(0))); await pending; expect(controller.getSnapshot().operation).toBe('unknown'); }
      cleanup();
    }
  } finally { Date.now = originalNow; }
});
