'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { FRONTEND_SHA } = require('./c110_contract.cjs');
const { privateLoginBoundary, PRIVATE_ACTION_TIMEOUT_MS } = require('./c110_private_boundary.cjs');
const { PROOF_VERSION, PREFLIGHT_TITLE, containsSentinel, preflightOutcome, validateProof } = require('./c110_preflight_proof.cjs');
const sentinel = 'NONSECRET_UNIT_SENTINEL_12345';
test('the shared production login boundary suppresses original failures', async () => {
  assert.equal(PRIVATE_ACTION_TIMEOUT_MS, 5000);
  await assert.rejects(privateLoginBoundary('master', async () => { throw new Error(sentinel); }),
    error => error.message.includes('credential-bearing details suppressed') && !error.message.includes(sentinel));
  assert.equal(await privateLoginBoundary('master', async () => 7), 7);
});
test('scanner rejects literal and base64 attachment sentinel leaks', () => {
  assert.equal(containsSentinel(`error ${sentinel}`, [sentinel]), true);
  assert.equal(containsSentinel(JSON.stringify({ attachments: [{ body: Buffer.from(`value=${sentinel}`).toString('base64') }] }), [sentinel]), true);
  assert.equal(containsSentinel('{"message":"generic failure"}', [sentinel]), false);
  const escaped = [...sentinel].map(c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')).join('');
  const large = '{"secret":"' + escaped + '","padding":' + JSON.stringify(Array(200000).fill(0)) + '}';
  assert.equal(containsSentinel(large, [sentinel]), true);
  assert.equal(containsSentinel(JSON.stringify(Array(200000).fill(0)), [sentinel]), true); // traversal budget fails closed
});
function report() {
  return { config: { metadata: { frontend_sha: FRONTEND_SHA } }, errors: [], stats: { expected: 0, unexpected: 1, skipped: 0, flaky: 0 }, suites: [{ specs: [{ title: PREFLIGHT_TITLE,
    tests: [{ expectedStatus: 'passed', status: 'unexpected', results: [{ status: 'failed', retry: 0, errors: [{ message: 'Error: C110_DUMMY_FAILURE_EXPECTED' }] }] }] }] }] };
}
test('preflight requires one intentional unexpected failure and exact nonzero exit', () => {
  assert.equal(preflightOutcome(report(), 1), true);
  for (const exit of [0, 2, null]) assert.equal(preflightOutcome(report(), exit), false);
  for (const alter of [r => r.config.metadata.frontend_sha = '9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c', r => r.suites = [], r => r.stats.skipped = 1, r => r.stats.unexpected = 2, r => r.errors.push({}),
    r => r.suites[0].specs[0].tests[0].results[0].retry = 1,
    r => r.suites[0].specs[0].tests[0].results[0].errors[0].message = 'Browser failed to launch']) {
    const r = report(); alter(r); assert.equal(Boolean(preflightOutcome(r, 1)), false);
  }
});
function proof(now) {
  return { version: PROOF_VERSION, result: 'PASS', playwright: '1.63.0', frontend_sha: FRONTEND_SHA, source_sha: 'a'.repeat(40), source_files: { helper: 'b'.repeat(64) },
    created_at: new Date(now).toISOString(), expected_dummy_failures: 1, observed_dummy_failures: 1, scanned_outputs: 3,
    sentinel_matches: 0, scanned_output_sha256: 'c'.repeat(64) };
}
test('proof is bound to exact source hashes version freshness count and zero leaks', () => {
  const now = Date.parse('2026-10-07T21:00:00Z'); const p = proof(now);
  assert.equal(validateProof(p, 'a'.repeat(40), { helper: 'b'.repeat(64) }, now, FRONTEND_SHA), p);
  assert.throws(() => validateProof(p, 'a'.repeat(40), { helper: 'b'.repeat(64) }, now, '3ef269bba80dbd6eafaff0d5e557da21f2d96244'));
  assert.throws(() => validateProof(p, 'a'.repeat(40), { helper: 'b'.repeat(64) }, now, '9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c'));
  assert.throws(() => validateProof(p, 'a'.repeat(40), { helper: 'b'.repeat(64) }, now));
  for (const patch of [{ frontend_sha: '9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c' }, { frontend_sha: '3ef269bba80dbd6eafaff0d5e557da21f2d96244' }, { source_sha: 'd'.repeat(40) }, { source_files: { helper: 'd'.repeat(64) } }, { playwright: '1.62.0' },
    { sentinel_matches: 1 }, { observed_dummy_failures: 0 }, { scanned_outputs: 2 }, { result: 'NOT_RUN' },
    { created_at: new Date(now - 31 * 60_000).toISOString() }, { created_at: new Date(now + 1).toISOString() }]) {
    assert.throws(() => validateProof({ ...p, ...patch }, 'a'.repeat(40), { helper: 'b'.repeat(64) }, now, FRONTEND_SHA));
  }
});

test('effective runner refuses foreign config/reporters/retries/repeats and hidden capture options', () => {
  const { validateEffectiveRunner } = require('./c110_contract.cjs');
  const config = () => ({ configFile: '/approved/config.cjs', workers: 1, reporter: [['list', { printSteps: false }], ['json', { outputFile: '/approved/report.json' }]] });
  const project = () => ({ retries: 0, repeatEach: 1, use: { browserName: 'chromium', ignoreHTTPSErrors: false, trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block' } });
  validateEffectiveRunner(config(), project(), '/approved/config.cjs', '/approved/report.json');
  for (const key of ['contextOptions', 'recordHar', 'recordVideo', 'logger', 'storageState', 'launchOptions', 'connectOptions']) {
    const p = project(); p.use[key] = {}; assert.throws(() => validateEffectiveRunner(config(), p, '/approved/config.cjs', '/approved/report.json'));
  }
  for (const mutate of [c => c.workers = 2, c => c.configFile = '/foreign/config.cjs', c => c.reporter[0] = ['html'], c => c.reporter[0][1].printSteps = true]) {
    const c = config(); mutate(c); assert.throws(() => validateEffectiveRunner(c, project(), '/approved/config.cjs', '/approved/report.json'));
  }
  for (const key of ['retries', 'repeatEach']) { const p = project(); p[key] = 2; assert.throws(() => validateEffectiveRunner(config(), p, '/approved/config.cjs', '/approved/report.json')); }
});
