'use strict';
const test = require('node:test'), assert = require('node:assert/strict'), vm = require('node:vm');
const { createHash, webcrypto } = require('node:crypto');
const { installReaderTap } = require('./browser_tap.cjs');
const URL = 'https://localhost:18443/api/v1/reports/shift.pdf?start=2026-07-01T00%3A00%3A00Z&end=2026-10-01T00%3A00%3A00Z';
const NONCE = '3'.repeat(64), CONFIG = { nonce: NONCE, runId: 'bcp-dummy-source-test', sourceSha: 'a'.repeat(40) };
const HEADER = { 'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="naryadai-shift.pdf"',
  'cache-control': 'private, no-store', vary: 'Cookie', 'x-content-type-options': 'nosniff', 'content-security-policy': "default-src 'none'; sandbox", 'content-length': '5' };
const INIT = () => ({ method: 'GET', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', signal: new AbortController().signal });
const settle = () => new Promise(resolve => setImmediate(resolve));
async function until(work) { for (let i = 0; i < 2000; i++) { if (work()) return; await new Promise(r => setTimeout(r, 1)); } throw new Error('dummy condition missing'); }
function environment(options = {}) {
  const timers = new Map(); let nextTimer = 0, fetchCalls = [], readCalls = [], originalPromises = [], cancellation = [];
  const chunks = options.chunks || [new Uint8Array([37, 80]), new Uint8Array([68, 70, 45])]; let index = 0;
  const nativeRead = function (...args) {
    readCalls.push({ receiver: this, args });
    if (options.throwRead) throw options.throwRead;
    const p = options.read ? options.read() : Promise.resolve(index < chunks.length ? { done: false, value: chunks[index++] } : { done: true, value: undefined });
    originalPromises.push(p); return p;
  };
  const reader = { read: nativeRead, cancel: function (...args) { cancellation.push({ receiver: this, args }); return Promise.resolve('native cancellation'); } };
  const stream = { locked: false, getReader: function (...args) { if (options.throwGetReader) throw options.throwGetReader; return reader; } };
  const response = new Response(null, { status: options.status || 200, headers: { ...HEADER, ...options.headers } });
  Object.defineProperties(response, { url: { value: options.url || URL }, type: { value: options.type || 'basic' }, body: { value: stream } });
  const fetchPromise = options.fetchPromise || Promise.resolve(response);
  const nativeFetch = function (...args) { fetchCalls.push({ receiver: this, args }); if (options.throwFetch) throw options.throwFetch; return fetchPromise; };
  const sandbox = { fetch: nativeFetch, Promise, Response, Uint8Array, ArrayBuffer, crypto: options.crypto || webcrypto,
    setTimeout(fn, delay) { timers.set(++nextTimer, { fn, delay }); return nextTimer; }, clearTimeout(id) { timers.delete(id); } };
  const context = vm.createContext(sandbox);
  vm.runInContext(`(${installReaderTap.toString()})(${JSON.stringify(CONFIG)})`, context);
  const api = sandbox.__DALA_BODY_CAPTURE_PROBE__;
  return { sandbox, api, timers, reader, stream, response, nativeRead, fetchPromise, nativeFetch, fetchCalls, readCalls, originalPromises, cancellation,
    snap: () => JSON.parse(JSON.stringify(api.snapshot(NONCE))), arm: () => api.arm(NONCE), dispose: () => api.dispose(NONCE),
    fire(delay) { for (const [id, item] of timers) if (item.delay === delay) { timers.delete(id); item.fn(); return; } throw new Error('timer missing'); } };
}
async function consume(e) {
  e.arm(); const init = INIT(), p = Reflect.apply(e.sandbox.fetch, e.sandbox, [URL, init]);
  assert.equal(p, e.fetchPromise); const r = await p; assert.equal(r, e.response);
  const reader = r.body.getReader(); assert.equal(reader, e.reader);
  for (;;) { const next = reader.read(); assert.equal(next, e.originalPromises.at(-1)); const item = await next; if (item.done) break; }
  await until(() => ['COMPLETE', 'NOT_COMPARABLE'].includes(e.snap().state));
  return init;
}
test('same fetch promise, Response, reader, read promises, chunks, this and arguments', async () => {
  const e = environment(); const init = await consume(e); const s = e.snap();
  assert.equal(e.fetchCalls.length, 1); assert.equal(e.fetchCalls[0].receiver, e.sandbox); assert.equal(e.fetchCalls[0].args[1], init);
  assert.equal(e.readCalls.length, 3); assert(e.readCalls.every(x => x.receiver === e.reader && x.args.length === 0));
  assert.equal(s.state, 'COMPLETE'); assert.equal(s.sha256, createHash('sha256').update('%PDF-').digest('hex'));
  assert.equal(s.retained_capture_bytes, 0); assert.equal(s.fetches, 1); assert.equal(s.readers, 1); assert.equal(s.eof, true);
  const completed = e.dispose(); assert.equal(completed.disposed, true); assert.equal(e.sandbox.fetch, e.nativeFetch); assert.equal(e.reader.read, e.nativeRead);
  assert.equal(e.timers.size, 0); assert.equal(e.sandbox.__DALA_BODY_CAPTURE_PROBE__, undefined); assert.equal(e.cancellation.length, 0);
});
test('observation runs before the original app continuation without replacing chunks', async () => {
  const chunk = new Uint8Array([37, 80, 68, 70, 45]); const e = environment({ chunks: [chunk] }); e.arm();
  await e.sandbox.fetch(URL, INIT()); const r = e.response.body.getReader(); const result = await r.read();
  assert.equal(result.value, chunk); assert.equal(e.snap().observed_bytes, 5); assert.equal(e.snap().state, 'READING'); e.dispose();
});
test('unrelated fetch has no read observation and exact forwarding', async () => {
  const e = environment(); const p = e.sandbox.fetch('/api/v1/auth/login', { body: 'DUMMY_SECRET' });
  assert.equal(p, e.fetchPromise); await p; assert.equal(e.stream.getReader(), e.reader); assert.equal(e.reader.read, e.nativeRead);
  assert.equal(e.snap().retained_capture_bytes, 0); assert.equal(e.snap().fetches, 0); e.dispose();
});
for (const [label, change, reason] of [
  ['wrong query', () => [URL + '&x=1', INIT()], 'REQUEST_BINDING_FAILED'],
  ['wrong period', () => [URL.replace('2026-07', '2026-06'), INIT()], 'REQUEST_BINDING_FAILED'],
  ['wrong method', () => [URL, { ...INIT(), method: 'POST' }], 'REQUEST_BINDING_FAILED'],
  ['body supplied', () => [URL, { ...INIT(), body: 'dummy' }], 'REQUEST_BINDING_FAILED'],
  ['getter failure', () => [URL, { get method() { throw new Error('dummy private error'); } }], 'OBSERVER_FAILED'],
]) test(label + ' invalidates diagnostics but forwards original fetch', async () => {
  const e = environment(); e.arm(); const args = change(); assert.equal(e.sandbox.fetch(...args), e.fetchPromise); await settle();
  assert.equal(e.fetchCalls.length, 1); assert.equal(e.snap().reason, reason); assert.equal(e.snap().retained_capture_bytes, 0); e.dispose();
});
for (const [name, value] of [['zero', '0'], ['missing', null], ['invalid', 'x'], ['overcap', String(8 * 1024 * 1024 + 1)]]) {
  test(name + ' Content-Length allocates nothing', async () => { const e = environment({ headers: { 'content-length': value } }); e.arm(); await e.sandbox.fetch(URL, INIT());
    assert.equal(e.snap().reason, 'HEADERS_OR_LENGTH_FAILED'); assert.equal(e.snap().retained_capture_bytes, 0); e.dispose(); });
}
for (const [name, chunks, reason] of [
  ['overflow', [new Uint8Array(6)], 'OVERFLOW'], ['truncation', [new Uint8Array(4)], 'TRUNCATED'], ['empty', [], 'TRUNCATED'], ['bad chunk', ['dummy secret'], 'INVALID_CHUNK'],
]) test(name + ' is never comparable', async () => {
  const e = environment({ chunks }); e.arm(); await e.sandbox.fetch(URL, INIT()); const r = e.response.body.getReader();
  for (let i = 0; i <= chunks.length; i++) { await r.read(); if (e.snap().state === 'NOT_COMPARABLE') break; }
  assert.equal(e.snap().reason, reason); assert.equal(e.snap().comparability, 'NOT_COMPARABLE'); assert.equal(e.snap().retained_capture_bytes, 0); e.dispose();
});
test('8 MiB is allowed without a second retained capture buffer', async () => {
  const bytes = new Uint8Array(8 * 1024 * 1024); const e = environment({ headers: { 'content-length': String(bytes.length) }, chunks: [bytes] });
  await consume(e); assert.equal(e.snap().observed_bytes, bytes.length); assert.equal(e.snap().retained_capture_bytes, 0); e.dispose();
});
test('duplicate request invalidates even a completed capture', async () => {
  const e = environment(); await consume(e); e.sandbox.fetch(URL, INIT()); assert.equal(e.snap().reason, 'DUPLICATE_REQUEST'); assert.equal(e.snap().sha256, null); e.dispose();
});
test('unarmed, wrong capability and replay are terminal', async () => {
  const e = environment(); await e.sandbox.fetch(URL, INIT()); assert.equal(e.snap().reason, 'UNARMED_REQUEST'); assert.throws(e.arm, /ARM_REJECTED/); e.dispose();
  const n = environment(); assert.throws(() => n.api.arm('WRONG'), /CAPABILITY_REJECTED/); assert.equal(n.snap().reason, 'CAPABILITY_REJECTED'); n.dispose();
  const a = environment(); a.arm(); assert.throws(a.arm, /ARM_REJECTED/); assert.equal(a.snap().reason, 'ARM_REPLAY'); a.dispose();
});
test('original synchronous fetch and reader throws preserved by identity', async () => {
  const secret = new Error('dummy secret'); const f = environment({ throwFetch: secret }); f.arm(); assert.throws(() => f.sandbox.fetch(URL, INIT()), x => x === secret); f.dispose();
  const g = environment({ throwGetReader: secret }); g.arm(); await g.sandbox.fetch(URL, INIT()); assert.throws(() => g.stream.getReader(), x => x === secret); g.dispose();
  const r = environment({ throwRead: secret }); r.arm(); await r.sandbox.fetch(URL, INIT()); const reader = r.stream.getReader(); assert.throws(() => reader.read(), x => x === secret); r.dispose();
});
test('original fetch/read rejections retained without private text in projection', async () => {
  const secret = new Error('PRIVATE_SENTINEL'); const f = environment({ fetchPromise: Promise.reject(secret) }); f.arm();
  await assert.rejects(f.sandbox.fetch(URL, INIT()), x => x === secret); assert.equal(f.snap().reason, 'FETCH_REJECTED'); assert(!JSON.stringify(f.snap()).includes('PRIVATE_SENTINEL')); f.dispose();
  const e = environment({ read: () => Promise.reject(secret) }); e.arm(); await e.sandbox.fetch(URL, INIT());
  const p = e.stream.getReader().read(); assert.equal(p, e.originalPromises[0]); await assert.rejects(p, x => x === secret);
  assert.equal(e.snap().reason, 'READ_REJECTED'); assert(!JSON.stringify(e.snap()).includes('PRIVATE_SENTINEL')); e.dispose();
});
test('read timeout and late callbacks cannot resurrect capture', async () => {
  let resolve; const pending = new Promise(r => { resolve = r; }); const e = environment({ read: () => pending });
  e.arm(); await e.sandbox.fetch(URL, INIT()); const p = e.stream.getReader().read(); e.fire(20000);
  resolve({ done: false, value: new Uint8Array(5) }); await p; assert.equal(e.snap().reason, 'READ_TIMEOUT'); assert.equal(e.snap().observed_bytes, 0); e.dispose();
});
test('digest timeout and disposal ignore late resolution', async () => {
  let resolve; const e = environment({ crypto: { subtle: { digest: () => new Promise(r => { resolve = r; }) } } });
  e.arm(); await e.sandbox.fetch(URL, INIT()); const reader = e.stream.getReader(); await reader.read(); await reader.read(); await reader.read();
  assert.equal(e.snap().state, 'HASHING'); e.fire(5000); resolve(new ArrayBuffer(32)); await settle();
  assert.equal(e.snap().reason, 'DIGEST_TIMEOUT'); assert.equal(e.snap().retained_capture_bytes, 0); e.dispose();
});
test('observer install failure does not change native response or read flow', async () => {
  const e = environment(); Object.freeze(e.stream); e.arm(); assert.equal(await e.sandbox.fetch(URL, INIT()), e.response);
  assert.equal(e.snap().reason, 'OBSERVER_FAILED'); assert.equal(e.stream.getReader().read, e.nativeRead); e.dispose();
});
test('concurrent read, explicit app cancel, and unsupported reader invalidate only observation', async () => {
  const e = environment({ read: () => new Promise(() => {}) }); e.arm(); await e.sandbox.fetch(URL, INIT()); const r = e.stream.getReader(); r.read(); r.read();
  assert.equal(e.snap().reason, 'CONCURRENT_READ'); e.dispose();
  const c = environment(); c.arm(); await c.sandbox.fetch(URL, INIT()); const cr = c.stream.getReader(); const arg = new Error('PRIVATE_CANCEL'); const p = cr.cancel(arg);
  assert.equal(await p, 'native cancellation'); assert.equal(c.cancellation[0].args[0], arg); assert.equal(c.snap().reason, 'CLIENT_CANCELLED'); c.dispose();
  const u = environment(); u.arm(); await u.sandbox.fetch(URL, INIT()); assert.equal(u.stream.getReader({ mode: 'byob' }), u.reader); assert.equal(u.snap().reason, 'UNSUPPORTED_READER'); u.dispose();
});
test('cleanup never overwrites a later owner and never cancels the reader', async () => {
  const e = environment(); e.arm(); await e.sandbox.fetch(URL, INIT()); const replacement = () => 'later owner'; e.sandbox.fetch = replacement;
  e.dispose(); assert.equal(e.sandbox.fetch, replacement); assert.equal(e.cancellation.length, 0); assert.equal(e.timers.size, 0);
});
test('source forbids clone, tee, transforms, raw byte bridge, or original acceptance receipt', () => {
  const source = installReaderTap.toString(); assert(!/\.clone\(|\.tee\(|new\s+Response\(|TransformStream|console\.|JSON\.stringify/.test(source));
  const e = environment(); const keys = Object.keys(e.snap()); assert(!keys.some(k => /nonce|cookie|csrf|content|payload|error|response_bytes/.test(k))); e.dispose();
});
test('real native stream reader brand and same chunk identity survive observation', async () => {
  const chunk = new Uint8Array([37,80,68,70,45]); const stream = new ReadableStream({ start(controller) { controller.enqueue(chunk); controller.close(); } });
  const response = new Response(stream, { headers: HEADER }); Object.defineProperties(response,{url:{value:URL},type:{value:'basic'}});
  const promise = Promise.resolve(response), originalFetch = function(){return promise;};
  const sandbox = {fetch:originalFetch,Promise,Response,ReadableStream,Uint8Array,ArrayBuffer,crypto:webcrypto,setTimeout,clearTimeout};
  const context=vm.createContext(sandbox);vm.runInContext(`(${installReaderTap.toString()})(${JSON.stringify(CONFIG)})`,context);
  const tap=sandbox.__DALA_BODY_CAPTURE_PROBE__;tap.arm(NONCE);assert.equal(sandbox.fetch(URL,INIT()),promise);
  assert.equal(await promise,response);const reader=response.body.getReader();assert(reader instanceof ReadableStreamDefaultReader);
  const first=await reader.read();assert.equal(first.value,chunk);assert.equal((await reader.read()).done,true);reader.releaseLock();
  await until(()=>tap.snapshot(NONCE).state==='COMPLETE');assert.equal(tap.dispose(NONCE).sha256,createHash('sha256').update(chunk).digest('hex'));
});
test('wrong native reader receiver retains native rejection', async () => {
  const stream=new ReadableStream({start(controller){controller.enqueue(new Uint8Array([37,80,68,70,45]));controller.close();}});
  const response=new Response(stream,{headers:HEADER});Object.defineProperties(response,{url:{value:URL},type:{value:'basic'}});
  const promise=Promise.resolve(response),sandbox={fetch:()=>promise,Promise,Response,Uint8Array,ArrayBuffer,crypto:webcrypto,setTimeout,clearTimeout};
  const context=vm.createContext(sandbox);vm.runInContext(`(${installReaderTap.toString()})(${JSON.stringify(CONFIG)})`,context);
  const tap=sandbox.__DALA_BODY_CAPTURE_PROBE__;tap.arm(NONCE);await sandbox.fetch(URL,INIT());const reader=response.body.getReader();
  await assert.rejects(Reflect.apply(reader.read,{},[]),TypeError);assert.equal(tap.snapshot(NONCE).comparability,'NOT_COMPARABLE');tap.dispose(NONCE);reader.releaseLock();
});
test('page disposal while a native read is pending ignores later bytes', async () => {
  let resolve;const pending=new Promise(r=>{resolve=r;});const e=environment({read:()=>pending});e.arm();await e.sandbox.fetch(URL,INIT());const p=e.stream.getReader().read();
  const final=e.dispose();assert.equal(final.retained_capture_bytes,0);resolve({done:false,value:new Uint8Array(5)});await p;
  assert.equal(e.sandbox.fetch,e.nativeFetch);assert.equal(e.reader.read,e.nativeRead);assert.equal(e.timers.size,0);assert.throws(()=>e.api.snapshot(NONCE),/CAPABILITY_REJECTED/);
});
