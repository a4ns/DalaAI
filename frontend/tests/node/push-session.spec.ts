import { expect, test } from '@playwright/test';
import { sourceModule } from '../support/source';
import { deferred, ids, json, session } from '../support/synthetic';
import type * as Client from '../../src/shared/api/client';
import type * as PushSessionModule from '../../src/app/pushSession';
import type { PushBrowserPort, BrowserSubscription } from '../../src/pwa/push/types';
const { ApiClient, SessionChangedError } = sourceModule<typeof Client>('src/shared/api/client.ts');
const { PushSession, createPushBackend, isCurrentPushContext } = sourceModule<typeof PushSessionModule>('src/app/pushSession.ts');
const credentials = { employee_code: 'SYNTHETIC-UI-TEST', pin: '0000' };
const config = { enabled: true, application_server_key: Buffer.from([4, ...Array<number>(64).fill(1)]).toString('base64url'), delivery_semantics: 'provider_acceptance_is_not_device_delivery', device_policy: 'latest_registration_per_user' };
const subscriptionData = { endpoint: 'https://push.example.invalid/synthetic-session', keys: { p256dh: 'synthetic-public-key', auth: 'synthetic-auth-value' } };
const subscription: BrowserSubscription = { toJSON: () => ({ ...subscriptionData, keys: { ...subscriptionData.keys } }) };
function browser(): { port: PushBrowserPort; calls: { prepare: number; subscribe: number; unsubscribe: number } } {
  const calls = { prepare: 0, subscribe: 0, unsubscribe: 0 };
  return { calls, port: { supported: () => true, permission: () => 'granted', prepare: async () => { calls.prepare++; return null; }, subscribe: async () => { calls.subscribe++; return subscription; }, unsubscribe: async () => { calls.unsubscribe++; return true; } } };
}
async function clientWith(send: (url: string, init?: RequestInit) => Promise<Response>) {
  const client = new ApiClient({ online: () => true, fetch: async (url, init) => String(url).endsWith('/auth/login') ? json(session()) : send(String(url), init) });
  await client.login(credentials); return client;
}

test('push binding construction and StrictMode-style attach cleanup attach remain inert', async () => {
  let requests = 0; const fake = browser();
  const client = await clientWith(async () => { requests++; return json(config); });
  const binding = new PushSession(client, () => true, () => fake.port);
  const cleanupFirst = binding.attach(); cleanupFirst(); const cleanupSecond = binding.attach();
  expect(binding.getSnapshot().phase).toBe('idle');
  expect(requests).toBe(0);
  expect(fake.calls).toEqual({ prepare: 0, subscribe: 0, unsubscribe: 0 });
  binding.prepare(); await expect.poll(() => binding.getSnapshot().phase).toBe('ready');
  expect(requests).toBe(1); expect(fake.calls.prepare).toBe(1); expect(fake.calls.subscribe).toBe(0);
  cleanupSecond(); binding.enable();
  expect(fake.calls.subscribe).toBe(0);
});

test('push backend checks current context before send and after reply; expiry and logout latch suppress effects', async () => {
  const late = deferred<Response>(); let sends = 0; let ready = true;
  const client = await clientWith(async () => { sends++; return late.promise; });
  const epoch = client.epoch;
  const current = () => isCurrentPushContext(client, epoch, ids.first, () => ready);
  const backend = createPushBackend(client, current);
  expect(current()).toBe(true); ready = false;
  await expect(backend.getConfig()).rejects.toBeInstanceOf(SessionChangedError);
  await expect(backend.register(JSON.stringify(subscriptionData))).rejects.toBeInstanceOf(SessionChangedError);
  await expect(backend.remove(subscriptionData.endpoint)).rejects.toBeInstanceOf(SessionChangedError);
  expect(sends).toBe(0);
  ready = true; const pending = backend.getConfig();
  ready = false; late.resolve(json(config));
  await expect(pending).rejects.toBeInstanceOf(SessionChangedError);
  expect(sends).toBe(1);
  ready = true;
  const originalNow = Date.now;
  try { Date.now = () => Date.parse('2100-01-01T00:00:00Z'); expect(current()).toBe(false); } finally { Date.now = originalNow; }
  client.clearIdentity(); expect(current()).toBe(false);
});

test('native subscription completion after synchronous logout latch never registers or cleans up another context', async () => {
  const native = deferred<BrowserSubscription>(); const fake = browser(); let ready = true; let posts = 0;
  fake.port.subscribe = () => { fake.calls.subscribe++; return native.promise; };
  const client = await clientWith(async (url, init) => { if (init?.method === 'POST') posts++; return json(url.endsWith('/config') ? config : { enabled: true }); });
  const binding = new PushSession(client, () => ready, () => fake.port); const cleanup = binding.attach();
  binding.prepare(); await expect.poll(() => binding.getSnapshot().phase).toBe('ready');
  binding.enable(); expect(fake.calls.subscribe).toBe(1);
  ready = false; native.resolve(subscription); await new Promise(resolve => setTimeout(resolve, 0));
  expect(posts).toBe(0); expect(fake.calls.unsubscribe).toBe(0);
  expect(binding.getSnapshot().backendBinding).toBe('unconfirmed');
  cleanup();
});

test('actual push bridge keeps unknown registration across offline retry and reuses captured bytes without another native subscription', async () => {
  const fake = browser(); let online = true; const bodies: string[] = [];
  const client = new ApiClient({ online: () => online, fetch: async (url, init) => {
    if (String(url).endsWith('/auth/login')) return json(session());
    if (String(url).endsWith('/config')) return json(config);
    bodies.push(String(init?.body));
    if (bodies.length === 1) throw new TypeError('Synthetic register response lost');
    return json({ enabled: true });
  } });
  await client.login(credentials);
  const binding = new PushSession(client, () => true, () => fake.port); const cleanup = binding.attach();
  binding.prepare(); await expect.poll(() => binding.getSnapshot().phase).toBe('ready');
  binding.enable(); await expect.poll(() => binding.getSnapshot().phase).toBe('unknown');
  online = false; binding.retry(); await expect.poll(() => binding.getSnapshot().phase).toBe('unknown');
  expect(bodies).toHaveLength(1); expect(fake.calls.subscribe).toBe(1);
  online = true; await new Promise(resolve => setTimeout(resolve, 0)); expect(bodies).toHaveLength(1);
  binding.retry(); await expect.poll(() => binding.getSnapshot().phase).toBe('connected');
  expect(bodies).toHaveLength(2); expect(bodies[1]).toBe(bodies[0]); expect(fake.calls.subscribe).toBe(1);
  cleanup();
});

test('partial push disable preserves server-removed fact and retries only browser cleanup', async () => {
  const fake = browser(); let removals = 0;
  fake.port.unsubscribe = async () => { fake.calls.unsubscribe++; return fake.calls.unsubscribe > 1; };
  const client = await clientWith(async url => {
    if (url.endsWith('/config')) return json(config);
    if (url.endsWith('/remove')) { removals++; return new Response(null, { status: 204 }); }
    return json({ enabled: true });
  });
  const binding = new PushSession(client, () => true, () => fake.port); const cleanup = binding.attach();
  binding.prepare(); await expect.poll(() => binding.getSnapshot().phase).toBe('ready');
  binding.enable(); await expect.poll(() => binding.getSnapshot().phase).toBe('connected');
  binding.disable(); await expect.poll(() => binding.getSnapshot().phase).toBe('local-cleanup');
  expect(binding.getSnapshot()).toMatchObject({ browserSubscription: 'present', backendBinding: 'removed' });
  binding.retry(); await expect.poll(() => binding.getSnapshot().phase).toBe('off');
  expect(removals).toBe(1); expect(fake.calls.unsubscribe).toBe(2); expect(fake.calls.subscribe).toBe(1);
  cleanup();
});

test('additive subscription conflict survives API validation and produces safe explicit-reset guidance', async () => {
  const fake = browser();
  const problem = { code: 'SUBSCRIPTION_CONFLICT', message: `SYNTHETIC_PRIVATE ${subscriptionData.endpoint}`, request_id: ids.event, retryable: false, current_version: null, field_errors: [] };
  const client = await clientWith(async url => url.endsWith('/config') ? json(config) : json(problem, 409));
  const binding = new PushSession(client, () => true, () => fake.port); const cleanup = binding.attach();
  binding.prepare(); await expect.poll(() => binding.getSnapshot().phase).toBe('ready');
  binding.enable(); await expect.poll(() => binding.getSnapshot().phase).toBe('error');
  expect(binding.getSnapshot().message).toContain('другой учётной записью');
  expect(JSON.stringify(binding.getSnapshot())).not.toContain('SYNTHETIC_PRIVATE');
  expect(JSON.stringify(binding.getSnapshot())).not.toContain(subscriptionData.endpoint);
  expect(binding.getSnapshot()).toMatchObject({ backendBinding: 'unconfirmed', browserSubscription: 'present' });
  expect(fake.calls.unsubscribe).toBe(0);
  cleanup();
});
