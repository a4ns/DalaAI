/// <reference types="node" />
import assert from 'node:assert/strict';
import test from 'node:test';
import { PushController } from './controller.ts';
import { assertPushConfig, captureSubscription, pushMessage, validPublicKey } from './model.ts';
import { PushOperationError } from './types.ts';
import type { BrowserSubscription, PushBackendPort, PushBrowserPort, PushConfig } from './types.ts';

const PUBLIC_KEY = Buffer.concat([Buffer.from([4]), Buffer.alloc(64, 1)]).toString('base64url');
const CONFIG: PushConfig = { enabled: true, application_server_key: PUBLIC_KEY, delivery_semantics: 'provider_acceptance_is_not_device_delivery', device_policy: 'latest_registration_per_user' };
const DATA = { endpoint: 'https://push.example.invalid/synthetic', keys: { p256dh: 'synthetic_public_key', auth: 'synthetic_auth' }, expirationTime: null };
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (error: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
function harness() {
  const calls = { config: 0, prepare: 0, subscribe: 0, unsubscribe: 0, register: [] as string[], remove: [] as string[] };
  let current = true;
  let permission: NotificationPermission = 'default';
  let existing: BrowserSubscription | null = null;
  const subscription: BrowserSubscription = { toJSON: () => structuredClone(DATA) };
  const browser: PushBrowserPort = {
    supported: () => true, permission: () => permission,
    prepare: async () => { calls.prepare++; return existing; },
    subscribe: async () => { calls.subscribe++; permission = 'granted'; existing = subscription; return subscription; },
    unsubscribe: async () => { calls.unsubscribe++; existing = null; return true; },
  };
  const backend: PushBackendPort = {
    getConfig: async () => { calls.config++; return CONFIG; },
    register: async body => { calls.register.push(body); },
    remove: async endpoint => { calls.remove.push(endpoint); },
  };
  const controller = new PushController({ browser, backend, isCurrentContext: () => current });
  return { calls, browser, backend, controller, subscription, setCurrent: (value: boolean) => { current = value; }, setPermission: (value: NotificationPermission) => { permission = value; }, setExisting: () => { existing = subscription; } };
}

test('construction and observation have no browser or backend side effects', () => {
  const h = harness(); const stop = h.controller.subscribe(() => {}); stop();
  assert.equal(h.controller.state.phase, 'idle'); assert.deepEqual(h.calls, { config: 0, prepare: 0, subscribe: 0, unsubscribe: 0, register: [], remove: [] });
});
test('unsupported browser stops before config and native operations', async () => {
  const h = harness(); h.browser.supported = () => false; await h.controller.prepare(); await h.controller.enable();
  assert.equal(h.controller.state.phase, 'unsupported'); assert.equal(h.calls.config + h.calls.subscribe, 0);
});
test('disabled backend prevents worker registration and subscription', async () => {
  const h = harness(); h.backend.getConfig = async () => ({ ...CONFIG, enabled: false, application_server_key: null }); await h.controller.prepare(); await h.controller.enable();
  assert.equal(h.controller.state.phase, 'disabled'); assert.equal(h.calls.prepare + h.calls.subscribe, 0);
});
test('malformed config fails closed before browser preparation', async () => {
  const h = harness(); h.backend.getConfig = async () => ({ ...CONFIG, application_server_key: 'not-a-key' }); await h.controller.prepare();
  assert.equal(h.controller.state.phase, 'error'); assert.equal(h.calls.prepare, 0);
});
test('denied native permission never subscribes or repeatedly prompts', async () => {
  const h = harness(); h.setPermission('denied'); await h.controller.prepare(); await h.controller.enable(); await h.controller.prepare();
  assert.equal(h.controller.state.phase, 'denied'); assert.equal(h.calls.prepare + h.calls.subscribe, 0);
});
test('dismissing native prompt stays unconfirmed and does not auto retry', async () => {
  const h = harness(); h.browser.subscribe = async () => { h.calls.subscribe++; throw new Error('dismissed'); };
  await h.controller.prepare(); await h.controller.enable();
  assert.equal(h.controller.state.phase, 'error'); assert.equal(h.controller.state.permission, 'default'); assert.equal(h.calls.subscribe, 1); assert.equal(h.calls.register.length, 0);
});
test('prepare does not request native subscription; enable starts it synchronously', async () => {
  const h = harness(); await h.controller.prepare(); assert.equal(h.calls.subscribe, 0);
  const pending = h.controller.enable(); assert.equal(h.calls.subscribe, 1); await pending;
  assert.equal(h.controller.state.phase, 'connected'); assert.equal(h.calls.register.length, 1); assert.equal(h.controller.state.backendBinding, 'confirmed');
});
test('native permission and subscription are not backend success', async () => {
  const h = harness(); const hold = deferred<void>(); h.backend.register = body => { h.calls.register.push(body); return hold.promise; };
  await h.controller.prepare(); const work = h.controller.enable(); await Promise.resolve();
  assert.equal(h.controller.state.phase, 'registering'); assert.equal(h.controller.state.permission, 'granted'); assert.equal(h.controller.state.backendBinding, 'unconfirmed');
  hold.resolve(); await work; assert.equal(h.controller.state.phase, 'connected');
});
test('repeated enable click creates one native subscription and one register request', async () => {
  const h = harness(); const hold = deferred<BrowserSubscription>(); h.browser.subscribe = () => { h.calls.subscribe++; return hold.promise; };
  await h.controller.prepare(); const first = h.controller.enable(); const second = h.controller.enable(); hold.resolve(h.subscription); await Promise.all([first, second]);
  assert.equal(h.calls.subscribe, 1); assert.equal(h.calls.register.length, 1);
});
test('existing browser subscription is unconfirmed and must be explicitly cleared', async () => {
  const h = harness(); h.setExisting(); h.setPermission('granted'); await h.controller.prepare(); await h.controller.enable();
  assert.equal(h.controller.state.phase, 'unconfirmed'); assert.equal(h.calls.register.length + h.calls.subscribe, 0);
  await h.controller.resetExisting(); assert.equal(h.controller.state.phase, 'ready'); assert.equal(h.calls.unsubscribe, 1); assert.equal(h.calls.subscribe, 0);
  await h.controller.enable(); assert.equal(h.calls.register.length, 1);
});
test('failed browser clearing does not proceed with a fresh subscription', async () => {
  const h = harness(); h.setExisting(); h.browser.unsubscribe = async () => false; await h.controller.prepare(); await h.controller.resetExisting(); await h.controller.enable();
  assert.equal(h.controller.state.phase, 'unconfirmed'); assert.equal(h.calls.subscribe, 0);
});
test('409 conflict is not enabled and offers explicit browser reset', async () => {
  const h = harness(); h.backend.register = async () => { throw new PushOperationError('SUBSCRIPTION_CONFLICT'); };
  await h.controller.prepare(); await h.controller.enable(); assert.equal(h.controller.state.phase, 'error'); assert.equal(h.controller.state.backendBinding, 'unconfirmed'); assert.match(pushMessage(h.controller.state), /другой учётной/);
});
test('unknown register retries same captured bytes with no fresh browser subscription', async () => {
  const h = harness(); h.backend.register = async body => { h.calls.register.push(body); if (h.calls.register.length === 1) throw new PushOperationError('NETWORK', true); };
  await h.controller.prepare(); await h.controller.enable(); assert.equal(h.controller.state.phase, 'unknown');
  await h.controller.prepare(); await h.controller.resetExisting(); await h.controller.retry();
  assert.equal(h.controller.state.phase, 'connected'); assert.equal(h.calls.subscribe, 1); assert.equal(h.calls.register[0], h.calls.register[1]);
});
test('offline rejection of unknown retry does not erase earlier uncertainty', async () => {
  const h = harness(); let count = 0; h.backend.register = async () => { throw new PushOperationError('NETWORK', count++ === 0); };
  await h.controller.prepare(); await h.controller.enable(); await h.controller.retry(); assert.equal(h.controller.state.phase, 'unknown'); assert.equal(h.controller.state.backendBinding, 'unknown');
});
test('configuration lookup is not a binding-status lookup', async () => {
  const h = harness(); h.setPermission('granted'); h.setExisting(); await h.controller.prepare();
  assert.equal(h.controller.state.backendBinding, 'unconfirmed'); assert.equal(h.calls.register.length, 0);
});
test('identity change during config does not prepare browser', async () => {
  const h = harness(); const hold = deferred<PushConfig>(); h.backend.getConfig = () => hold.promise;
  const work = h.controller.prepare(); h.setCurrent(false); hold.resolve(CONFIG); await work; assert.equal(h.calls.prepare, 0);
});
test('identity change during native subscription does not register or clean up a newer context', async () => {
  const h = harness(); const hold = deferred<BrowserSubscription>(); h.browser.subscribe = () => hold.promise;
  await h.controller.prepare(); const work = h.controller.enable(); h.setCurrent(false); hold.resolve(h.subscription); await work;
  assert.equal(h.calls.register.length + h.calls.unsubscribe, 0);
});
test('disposed controller ignores late backend success and cannot retry', async () => {
  const h = harness(); const hold = deferred<void>(); h.backend.register = () => hold.promise;
  await h.controller.prepare(); const work = h.controller.enable(); await Promise.resolve(); h.controller.dispose(); hold.resolve(); await work; await h.controller.retry();
  assert.notEqual(h.controller.state.phase, 'connected');
});
test('server revocation precedes browser unsubscribe', async () => {
  const h = harness(); const hold = deferred<void>(); h.backend.remove = () => hold.promise;
  await h.controller.prepare(); await h.controller.enable(); const work = h.controller.disable(); assert.equal(h.calls.unsubscribe, 0); hold.resolve(); await work;
  assert.equal(h.controller.state.phase, 'off'); assert.equal(h.calls.unsubscribe, 1);
});
test('unknown server removal preserves subscription and retries exact endpoint', async () => {
  const h = harness(); h.backend.remove = async endpoint => { h.calls.remove.push(endpoint); if (h.calls.remove.length === 1) throw new PushOperationError('NETWORK', true); };
  await h.controller.prepare(); await h.controller.enable(); await h.controller.disable(); assert.equal(h.controller.state.phase, 'remove-unknown'); assert.equal(h.calls.unsubscribe, 0);
  await h.controller.retry(); assert.equal(h.controller.state.phase, 'off'); assert.equal(h.calls.remove[0], h.calls.remove[1]);
});
test('local unsubscribe failure after server confirmation stays separately visible', async () => {
  const h = harness(); let fail = true; h.browser.unsubscribe = async () => !fail;
  await h.controller.prepare(); await h.controller.enable(); await h.controller.disable(); assert.equal(h.controller.state.phase, 'local-cleanup'); assert.equal(h.controller.state.backendBinding, 'removed');
  fail = false; await h.controller.retry(); assert.equal(h.controller.state.phase, 'off'); assert.equal(h.calls.remove.length, 1);
});
test('stale removal success never unsubscribes browser in another identity context', async () => {
  const h = harness(); const hold = deferred<void>(); h.backend.remove = () => hold.promise;
  await h.controller.prepare(); await h.controller.enable(); const work = h.controller.disable(); h.setCurrent(false); hold.resolve(); await work; assert.equal(h.calls.unsubscribe, 0);
});
test('config validates exact semantics and public-key encoding, without creating keys', () => {
  assert.equal(validPublicKey(PUBLIC_KEY), true); assertPushConfig(CONFIG);
  assert.throws(() => assertPushConfig({ ...CONFIG, delivery_semantics: 'delivered' }));
  assert.throws(() => assertPushConfig({ ...CONFIG, enabled: false }));
});
test('capture rejects unsafe endpoint and oversized data; creates immutable bytes', () => {
  const input = structuredClone(DATA); const saved = captureSubscription(input); input.endpoint = 'https://changed.invalid'; assert.equal(JSON.parse(saved.body).endpoint, DATA.endpoint);
  for (const endpoint of ['http://push.invalid', 'https://user:password@push.invalid', 'https://push.invalid/#secret']) assert.throws(() => captureSubscription({ ...DATA, endpoint }));
  assert.throws(() => captureSubscription({ ...DATA, keys: { ...DATA.keys, auth: 'a'.repeat(5000) } }));
});
