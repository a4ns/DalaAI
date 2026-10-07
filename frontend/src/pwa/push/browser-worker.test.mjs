import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { createPushBrowserPort } from './browser.ts';

const KEY = Buffer.concat([Buffer.from([4]), Buffer.alloc(64, 1)]).toString('base64url');
function deferred() { let resolve; const promise = new Promise(yes => { resolve = yes; }); return { promise, resolve }; }
async function fakeEnvironment(run) {
  const names = ['window', 'navigator', 'Notification', 'PushManager', 'ServiceWorkerRegistration'];
  const descriptors = new Map(names.map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  let current = null;
  const calls = { register: 0, subscribe: 0, unsubscribe: 0, keys: [] };
  const subscription = { toJSON: () => ({ endpoint: 'https://push.example.invalid/synthetic', keys: { p256dh: 'synthetic', auth: 'synthetic' } }), unsubscribe: async () => { calls.unsubscribe++; current = null; return true; } };
  const registration = { scope: 'https://app.example.invalid/', active: { state: 'activated', scriptURL: 'https://app.example.invalid/sw.js' }, pushManager: { getSubscription: async () => current, subscribe: options => { calls.subscribe++; calls.keys.push(options); current = subscription; return Promise.resolve(subscription); } } };
  const container = { getRegistration: async () => registration, register: async () => { calls.register++; return registration; } };
  class FakeRegistration { showNotification() {} }
  const values = { window: { isSecureContext: true, location: { protocol: 'https:', origin: 'https://app.example.invalid' } }, navigator: { serviceWorker: container }, Notification: { permission: 'default' }, PushManager: class {}, ServiceWorkerRegistration: FakeRegistration };
  for (const name of names) Object.defineProperty(globalThis, name, { configurable: true, writable: true, value: values[name] });
  try { await run({ calls, registration, container, subscription, values, setCurrent: value => { current = value; } }); }
  finally { for (const name of names) { const descriptor = descriptors.get(name); if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name]; } }
}

test('browser port creation is inert; prepare never prompts or subscribes', () => fakeEnvironment(async h => {
  const browser = createPushBrowserPort(); assert.equal(h.calls.register + h.calls.subscribe, 0);
  assert.equal(await browser.prepare(), null); assert.equal(h.calls.subscribe, 0);
  const work = browser.subscribe(KEY); assert.equal(h.calls.subscribe, 1); await work;
  assert.equal(h.calls.keys[0].userVisibleOnly, true); assert.equal(h.calls.keys[0].applicationServerKey.length, 65);
}));
test('browser port refuses insecure origin without registration', () => fakeEnvironment(async h => {
  h.values.window.location.protocol = 'http:';
  const browser = createPushBrowserPort(); assert.equal(browser.supported(), false); await assert.rejects(browser.prepare()); assert.equal(h.calls.register, 0);
}));
test('browser port does not overwrite a different root service worker', () => fakeEnvironment(async h => {
  h.registration.active.scriptURL = 'https://app.example.invalid/another.js';
  await assert.rejects(createPushBrowserPort().prepare()); assert.equal(h.calls.register, 0);
}));
test('browser mutation guard survives controller/port replacement', () => fakeEnvironment(async h => {
  const first = createPushBrowserPort(); await first.prepare();
  const held = deferred(); h.registration.pushManager.subscribe = () => held.promise;
  const work = first.subscribe(KEY); const next = createPushBrowserPort(); await assert.rejects(next.prepare());
  h.setCurrent(h.subscription); held.resolve(h.subscription); await work;
  assert.equal(await next.prepare(), h.subscription); assert.equal(h.calls.unsubscribe, 0);
}));
test('unsubscribe is confirmed by re-reading absence, not its boolean alone', () => fakeEnvironment(async h => {
  h.setCurrent(h.subscription); h.subscription.unsubscribe = async () => true;
  const browser = createPushBrowserPort(); const found = await browser.prepare();
  assert.equal(await browser.unsubscribe(found), false); h.setCurrent(null); assert.equal(await browser.unsubscribe(found), true);
}));
test('unknown subscription handle cannot be unsubscribed', () => fakeEnvironment(async h => {
  const browser = createPushBrowserPort(); await browser.prepare(); await assert.rejects(browser.unsubscribe({ toJSON: () => ({}) })); assert.equal(h.calls.unsubscribe, 0);
}));

const workerSource = await readFile(new URL('../../../public/sw.js', import.meta.url), 'utf8');
function worker(options = {}) {
  const handlers = {};
  const shown = []; const opened = []; const warnings = []; let closed = 0;
  const self = { location: { origin: options.origin ?? 'https://app.example.invalid' }, addEventListener: (type, callback) => { handlers[type] = callback; }, registration: { showNotification: async (...args) => { shown.push(args); } }, clients: { matchAll: async () => options.windows ?? [], openWindow: async url => { opened.push(url); if (options.rejectOpen) throw new Error('blocked'); } } };
  vm.runInNewContext(workerSource, { self, URL, console: { warn: (...args) => { warnings.push(args); } } });
  async function emit(type, data) { let pending; handlers[type]({ data, notification: { data, close: () => { closed++; } }, waitUntil: work => { pending = work; } }); await pending; }
  return { handlers, shown, opened, warnings, emit, closed: () => closed };
}

test('worker exposes only push and notificationclick, no cache or background mutation handlers', () => {
  const h = worker(); assert.deepEqual(Object.keys(h.handlers).sort(), ['notificationclick', 'push']);
  assert.doesNotMatch(workerSource, /\b(?:fetch|importScripts|indexedDB|localStorage|sessionStorage)\s*[.(]|\.caches\b|skipWaiting\s*\(|clients\.claim\s*\(/);
});
const VALID_PAYLOAD = { v: 1, title: 'НарядAI', body: 'Есть обновление наряда. Откройте приложение.', url: '/', tag: 'naryadai-update' };
const pushData = value => ({ text: () => JSON.stringify(value) });
test('only accepted payload produces the fixed generic visible notification', async () => {
  const h = worker(); await h.emit('push', pushData(VALID_PAYLOAD));
  assert.equal(h.shown.length, 1); assert.equal(h.warnings.length, 0);
  const [title, options] = h.shown[0];
  assert.equal(title, VALID_PAYLOAD.title); assert.equal(options.body, VALID_PAYLOAD.body); assert.equal(options.data.url, '/'); assert.deepEqual(Object.keys(options).sort(), ['body', 'data', 'lang', 'tag']);
});
test('empty, malformed, oversized and non-object payloads are dropped with one content-free marker', async () => {
  const h = worker();
  const cases = [null, { text: () => { throw new Error('private error'); } }, { text: () => 'private malformed JSON' }, { text: () => 'x'.repeat(4097) }, pushData(null), pushData([]), pushData('private string'), pushData({})];
  for (const data of cases) await h.emit('push', data);
  assert.equal(h.shown.length, 0); assert.equal(h.opened.length, 0);
  assert.deepEqual(h.warnings, cases.map(() => ['NARYADAI_PUSH_INVALID_PAYLOAD']));
});
test('wrong version, missing/extra fields and hostile values are dropped, never displayed or logged', async () => {
  const h = worker(); const missing = { ...VALID_PAYLOAD }; delete missing.tag;
  const cases = [missing, { ...VALID_PAYLOAD, v: 2 }, { ...VALID_PAYLOAD, v: '1' }, { ...VALID_PAYLOAD, title: 'private employee' }, { ...VALID_PAYLOAD, body: 'private order' }, { ...VALID_PAYLOAD, url: 'https://evil.invalid' }, { ...VALID_PAYLOAD, tag: 'private identifier' }, { ...VALID_PAYLOAD, image: 'https://evil.invalid/track' }];
  for (const data of cases) await h.emit('push', pushData(data));
  assert.equal(h.shown.length, 0); assert.equal(h.opened.length, 0);
  assert.deepEqual(h.warnings, cases.map(() => ['NARYADAI_PUSH_INVALID_PAYLOAD']));
});
test('notification click focuses app root and preserves drafts instead of navigating', async () => {
  let focused = 0; const h = worker({ windows: [{ url: 'https://app.example.invalid/', focus: async () => { focused++; }, navigate: () => { throw new Error('Must not navigate'); } }] });
  await h.emit('notificationclick', { url: 'javascript:alert(1)' }); assert.equal(focused, 1); assert.equal(h.opened.length, 0); assert.equal(h.closed(), 1);
});
test('notification click ignores foreign windows and arbitrary incoming targets', async () => {
  const h = worker({ windows: [{ url: 'https://evil.invalid/', focus: () => { throw new Error('foreign'); } }, { url: 'https://app.example.invalid/api/v1/orders', focus: () => { throw new Error('not app'); } }] });
  await h.emit('notificationclick', { url: '//evil.invalid' }); assert.deepEqual(h.opened, ['https://app.example.invalid/']);
});
test('worker handles rejected focus/openWindow without logging payload or making requests', async () => {
  const h = worker({ windows: [{ url: 'https://app.example.invalid/', focus: async () => { throw new Error('closed'); } }], rejectOpen: true }); await h.emit('notificationclick', {}); assert.equal(h.opened.length, 1);
});
test('worker refuses insecure click origin', async () => {
  const h = worker({ origin: 'http://app.example.invalid' }); await h.emit('notificationclick', {}); assert.equal(h.opened.length, 0);
});
