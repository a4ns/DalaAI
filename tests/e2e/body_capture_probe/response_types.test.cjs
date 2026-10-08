'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const o = require('./observations.cjs'), k = require('./contract.cjs');
const { privateOperationBoundary } = require('../c113_private_boundary.cjs');
const ORIGIN = 'https://localhost:18443', PATH = '/api/v1/reports/shift.pdf';
const HEADERS = { 'cache-control': 'private, no-store', vary: 'Cookie', 'x-content-type-options': 'nosniff' };
function response(kind = 'page', overrides = {}) {
  return { url: () => k.EXACT_URL, status: () => 403, headers: () => ({ ...HEADERS }),
    ...(kind === 'page' ? { fromServiceWorker: () => false } : {}), ...overrides };
}
function check(value, kind = 'page') { return o.protectedResponseHeaders(value, ORIGIN, PATH, 403, false, kind); }
for (const kind of ['page', 'api']) {
  test(`${kind} response retains exact protected 403 validation`, () => {
    assert.deepEqual(check(response(kind), kind), HEADERS);
  });
  for (const [name, overrides] of [
    ['wrong origin', { url: () => k.EXACT_URL.replace(ORIGIN, 'https://example.invalid') }],
    ['wrong path', { url: () => ORIGIN + '/api/v1/reports/orders/other.pdf' }],
    ['wrong status', { status: () => 200 }],
    ['missing private cache', { headers: () => ({ ...HEADERS, 'cache-control': 'no-store' }) }],
    ['missing no-store', { headers: () => ({ ...HEADERS, 'cache-control': 'private' }) }],
    ['missing Vary Cookie', { headers: () => ({ ...HEADERS, vary: 'Accept' }) }],
    ['missing nosniff', { headers: () => ({ ...HEADERS, 'x-content-type-options': undefined }) }],
  ]) test(`${kind} response rejects ${name}`, () => assert.throws(() => check(response(kind, overrides), kind)));
}
test('APIResponse method absence cannot silently relax default page response checks', () => {
  assert.throws(() => o.protectedResponseHeaders(response('api'), ORIGIN, PATH, 403), /RESPONSE_TRANSPORT_TYPE/);
  assert.throws(() => check(response('page'), 'api'), /RESPONSE_TRANSPORT_TYPE/);
  assert.throws(() => check(response('api'), 'unknown'), /RESPONSE_KIND/);
});
for (const [name, value] of [
  ['missing', undefined], ['nonfunction false', false], ['nonfunction private text', 'PRIVATE_SENTINEL'],
  ['service worker true', () => true], ['ambiguous undefined result', () => undefined], ['ambiguous zero result', () => 0],
]) test(`page transport rejects ${name} fromServiceWorker`, () => {
  assert.throws(() => check(response('page', { fromServiceWorker: value })), /RESPONSE_TRANSPORT_TYPE/);
});
for (const value of [null, false, 'PRIVATE_SENTINEL', () => false, () => true]) {
  test('explicit APIResponse rejects an incompatible service-worker member: ' + typeof value, () => {
    assert.throws(() => check(response('api', { fromServiceWorker: value }), 'api'), /RESPONSE_TRANSPORT_TYPE/);
  });
}
test('protected page check calls the original method with its correct receiver once', () => {
  let calls = 0; const value = response('page', { fromServiceWorker() { assert.equal(this, value); calls++; return false; } });
  check(value); assert.equal(calls, 1);
});
test('executor denial body still requires FORBIDDEN without protected report fields', () => {
  assert.doesNotThrow(() => o.requireExecutorDenial({ code: 'FORBIDDEN' }));
  for (const body of [null, {}, { code: 'OK' }, ...['provenance', 'orders', 'order'].map(key => ({ code: 'FORBIDDEN', [key]: undefined }))]) {
    assert.throws(() => o.requireExecutorDenial(body));
  }
});
test('actual API header/body failures remain inside private output boundary', async () => {
  const sentinel = 'PRIVATE_HEADER_BODY_SENTINEL';
  for (const operation of [
    () => check(response('api', { headers() { throw new Error(sentinel); } }), 'api'),
    () => o.requireExecutorDenial({ get code() { throw new Error(sentinel); } }),
    () => check(response('page', { fromServiceWorker() { throw new Error(sentinel); } })),
  ]) await assert.rejects(privateOperationBoundary(operation), error => !error.message.includes(sentinel) && error.message.includes('private details suppressed'));
});
test('the sole APIRequestContext denial opts in explicitly; original CDP call and body gate remain', () => {
  const source = fs.readFileSync(path.join(__dirname, 'runner.spec.cjs'), 'utf8');
  assert(source.includes("headers(denied,'/api/v1/reports/shift.pdf',403,false,'api')"));
  assert.equal((source.match(/403,false,'api'/g) || []).length, 1);
  assert(source.includes('const denial = await denied.json(); o.requireExecutorDenial(denial);'));
  assert.equal((source.match(/files\.boundedResponseBody\(response\)/g) || []).length, 1);
});
