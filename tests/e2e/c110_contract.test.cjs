'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { inflateSync } = require('node:zlib');
const { FRONTEND_SHA, TITLE, fixtureFromEnv, syntheticPng, dueLocal } = require('./c110_contract.cjs');
const { REQUIRED_STEPS, validate } = require('./c110_gate.cjs');
const OLD_FRONTEND_SHA = '9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c';
// These values are input-validation data only, never accounts or a live DB.
const uuid = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
function env() {
  return { DALA_C110_AUTHORIZED: 'operator-provisioned-synthetic-only', DALA_E2E_MASTER_PIN_FILE: '/unit-placeholder-m', DALA_E2E_EXECUTOR_PIN_FILE: '/unit-placeholder-e',
    DALA_C110_DATABASE_SCHEMA: 'c110_unit_only', DALA_C110_OBSERVER_DATABASE_URL: 'not-used-by-unit-tests',
    DALA_E2E_FIXTURE_FILE: '/public-unit-fixture', DALA_C110_RUN_ID: 'unit-only-0001', DALA_E2E_BACKEND_SHA: 'a'.repeat(40), DALA_E2E_FRONTEND_SHA: FRONTEND_SHA,
    DALA_E2E_BASE_URL: 'https://localhost:18443', DALA_C110_WORKERS_DISABLED: 'ai,delivery,providers' };
}
function fixture() {
  const section = '6907df3e-d9e3-53e2-aa91-c874b453d960';
  return { fixture_version: 'dalaai-live-vertical-demo-v1', data_classification: 'synthetic demo only',
    section: { id: section }, equipment: { id: '2348bd85-4627-542e-8638-1a7297e4e6c5' },
    work_code: { id: 'e7c29005-c026-5017-adcc-2292434500b8' }, material: { id: '92444401-f0ee-56f3-b49b-3d329f50f54d' },
    users: [{ role: 'master', id: '8d27067c-4e86-50a2-87c4-f1012f53a2bb', employee_code: 'DALA-DEMO-MASTER', section_ids: [section], on_shift: true },
      { role: 'executor', id: '37baa480-be02-54bc-837c-6c0b2a00ec12', employee_code: 'DALA-DEMO-EXECUTOR', section_ids: [section], on_shift: true }] };
}
const load = (e = env(), f = fixture()) => fixtureFromEnv(e, () => JSON.stringify(f), () => {});
test('requires explicit provisioning; absence is BLOCKED and never skip', () => {
  assert.throws(() => fixtureFromEnv({}), /BLOCKED/); assert.equal(load().synthetic, true);
});
test('rejects public hosts, HTTP, query data, wrong source metadata and live providers', () => {
  for (const patch of [{ DALA_E2E_BASE_URL: 'https://example.org' }, { DALA_E2E_BASE_URL: 'http://localhost:18443' },
    { DALA_E2E_BASE_URL: 'https://localhost:18443/?pin=never' }, { DALA_E2E_BASE_URL: 'https://user:never@localhost:18443' },
    { DALA_E2E_BASE_URL: 'https://localhost:18443/path' }, { DALA_E2E_BACKEND_SHA: 'unrecorded' }, { DALA_C110_WORKERS_DISABLED: '' }]) {
    assert.throws(() => load({ ...env(), ...patch }), /BLOCKED/);
  }
});
test('requires accepted actors schema and IDs without echoing input or reading private paths', () => {
  const e = env(); delete e.DALA_E2E_MASTER_PIN_FILE; assert.throws(() => load(e), /path missing/);
  assert.throws(() => load({ ...env(), DALA_C110_DATABASE_SCHEMA: 'public' }), /isolated schema/);
  const f = fixture(); f.section.id = 'PRIVATE_VALUE'; assert.throws(() => load(env(), f), e => !e.message.includes('PRIVATE_VALUE'));
  let reads = 0; fixtureFromEnv(env(), file => { reads++; assert.equal(file, '/public-unit-fixture'); return JSON.stringify(fixture()); }, () => {}); assert.equal(reads, 1);
});
test('debug or preload capture is blocked before any fixture or credential file read', () => {
  for (const key of ['DEBUG', 'PWDEBUG', 'NODE_OPTIONS']) {
    let reads = 0; assert.throws(() => fixtureFromEnv({ ...env(), [key]: 'sentinel' }, () => { reads++; return '{}'; }), /capture/); assert.equal(reads, 0);
  }
});
test('missing source-bound failure proof blocks before any fixture or credential file read', () => {
  let reads = 0; const e = env();
  assert.throws(() => fixtureFromEnv(e, () => { reads++; return '{}'; }), /secrecy proof required/); assert.equal(reads, 0);
});
test('UTC+5 deadline uses real future time without time-freezing', () => {
  assert.equal(dueLocal(Date.parse('2026-10-07T21:00:00Z')), '2026-10-08T04:00');
});
test('synthetic photo is reproducible decodable-size PNG with no metadata', () => {
  const png = syntheticPng(); assert.deepEqual(png, syntheticPng()); assert.equal(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  let offset = 8; const chunks = [];
  while (offset < png.length) { const size = png.readUInt32BE(offset); const name = png.subarray(offset + 4, offset + 8).toString(); chunks.push(name);
    if (name === 'IDAT') assert.equal(inflateSync(png.subarray(offset + 8, offset + 8 + size)).length, 64 * (64 * 3 + 1)); offset += size + 12; }
  assert.deepEqual(chunks, ['IHDR', 'IDAT', 'IEND']);
});
function evidencePair() {
  const commands = ['create', 'queue', 'accept', 'start', 'pause', 'resume', 'submit', 'review', 'start', 'submit', 'review'].map((action, i) => ({ action, version: i + 1, operation_id: uuid(i + 30), actor_id: uuid(action === 'review' || action === 'create' ? 1 : 2) }));
  const evidence = { schema_version: 1, result: 'PASS', test: TITLE, frontend_sha: FRONTEND_SHA, harness_sha: 'c'.repeat(40), backend_sha: 'a'.repeat(40),
    steps: REQUIRED_STEPS.map(name => ({ name, result: 'PASS' })), browser: { mode: 'ANDROID_EMULATION', contexts: 2, mobile: true, touch: true, playwright: '1.63.0' },
    separate_gates: Object.fromEntries(['physical_android', 'native_camera', 'push_delivery', 'provider_model', 'throttled_mobile_upload_10s', 'report_export'].map(k => [k, 'NOT_RUN'])),
    commands, business_requests: commands.map(({ action, operation_id, actor_id }) => ({ action, operation_id, actor_id })), order_id: uuid(10), database: { source: 'actual_postgresql_read_only', identity: { direct_login: true, read_only: true, isolated_schema: true },
      order: { id: uuid(10), version: 11, status: 'closed' }, receipts: commands.map(c => ({ ...c, committed: true })), events: Array(13).fill({}),
      submissions: [{ completeness: 'incomplete' }, { completeness: 'complete' }], reviews: [{ decision: 'rework' }, { decision: 'close', final_score: null }], photos: [{}], materials: [{}], assessments: [] } };
  const report = { config: { metadata: { frontend_sha: FRONTEND_SHA } }, errors: [], stats: { expected: 1, unexpected: 0, skipped: 0, flaky: 0 }, suites: [{ specs: [{ title: TITLE, ok: true,
    tests: [{ expectedStatus: 'passed', status: 'expected', results: [{ status: 'passed', retry: 0, errors: [] }] }] }] }] };
  return { report, evidence };
}
test('gate accepts a structurally complete synthetic parser fixture, not live evidence', () => {
  const { report, evidence } = evidencePair(); assert.equal(validate(report, evidence, FRONTEND_SHA).status, 'passed');
});
test('gate rejects empty filtered skipped failed flaky expected-failed and retried reports', () => {
  const changes = [r => r.suites = [], r => r.stats.skipped = 1, r => r.stats.flaky = 1, r => r.errors.push({}),
    r => r.suites[0].specs[0].tests[0].expectedStatus = 'failed', r => r.suites[0].specs[0].tests[0].results[0].status = 'skipped',
    r => r.suites[0].specs[0].tests[0].results[0].retry = 1, r => r.suites[0].specs[0].tests[0].results.push({ status: 'passed' })];
  for (const change of changes) { const { report, evidence } = evidencePair(); change(report); assert.throws(() => validate(report, evidence, FRONTEND_SHA)); }
});
test('gate rejects absent DB, receipt loss, missing steps and physical-phone promotion', () => {
  for (const change of [e => e.database.source = 'mock', e => e.database.receipts.pop(), e => e.steps.pop(), e => e.separate_gates.physical_android = 'PASS', e => e.database.reviews[1].final_score = 0, e => e.business_requests.push(e.business_requests[0])]) {
    const { report, evidence } = evidencePair(); change(evidence); assert.throws(() => validate(report, evidence, FRONTEND_SHA));
  }
});

test('only exact reviewed 8e808710 source is accepted and preserved', () => {
  assert.equal(FRONTEND_SHA, '8e8087103821b6334ba8d5de0a40c91ee58276f9');
  assert.equal(load().frontend_sha, FRONTEND_SHA);
  for (const selected of [undefined, '', '8e808710', 'da83e9c417a7c6bf7e91b5100e8f2d7616d9f24e', 'da83e9c4', 'd78b9c3b7cabbcbd05b01df77f2a7ec57739afe5', 'd78b9c3b', 'f967d0acf3f04bda304b7fe47e1bf76ca8814634', 'f967d0ac', 'bbe897514e58a4b8f8b6d4f580e5273e34cb5c75', 'bbe89751', '6fa27276f14ef31757cb0da5ee9d7acc15789111', '6fa27276', '8081a2984b2f27b909fa2b86cd9f10ffd01d1e11', '8081a298', 'a880371589aa1dd117dde9e80936c687d146f919', 'a8803715', '1594a930de4b9f15d11dd35bbc59e5b4b0b1d964', '1594a930', 'faef5d3d', 'faef5d3d8b4c640fae013dbfa78074382e512e8f', OLD_FRONTEND_SHA, '3ef269bba80dbd6eafaff0d5e557da21f2d96244', 'ca320bf692c01d89dd79496fe18d1bc2742052df', '2beb2244c4639c09004e4cdb5a7598d447ad68f6', '45a65ae2b0b23c1a717fec9baa7a30369b2dd117', 'f'.repeat(40), FRONTEND_SHA.toUpperCase()]) {
    let reads = 0;
    assert.throws(() => fixtureFromEnv({ ...env(), DALA_E2E_FRONTEND_SHA: selected }, () => { reads++; return '{}'; }, () => {}), /reviewed frontend/);
    assert.equal(reads, 0);
  }
});
test('gate rejects old-source relabels and mismatched or absent selected identity', () => {
  const { report, evidence } = evidencePair();
  assert.throws(() => validate(report, evidence), /EXPLICIT_REVIEWED_FRONTEND_REQUIRED/);
  assert.throws(() => validate(report, evidence, OLD_FRONTEND_SHA), /EXPLICIT_REVIEWED_FRONTEND_REQUIRED/);
  assert.throws(() => validate(report, evidence, 'f'.repeat(40)), /EXPLICIT_REVIEWED_FRONTEND_REQUIRED/);
  evidence.frontend_sha = OLD_FRONTEND_SHA;
  assert.throws(() => validate(report, evidence, FRONTEND_SHA), /EXACT_SOURCE_IDENTITIES_REQUIRED/);
  evidence.frontend_sha = FRONTEND_SHA; report.config.metadata.frontend_sha = OLD_FRONTEND_SHA;
  assert.throws(() => validate(report, evidence, FRONTEND_SHA), /EXACT_SOURCE_IDENTITIES_REQUIRED/);
  report.config.metadata.frontend_sha = FRONTEND_SHA;
  assert.equal(validate(report, evidence, FRONTEND_SHA).status, 'passed');
});
