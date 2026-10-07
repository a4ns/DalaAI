'use strict';
// Source sequencing regression, not a browser/React rendering reproduction.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { FRONTEND_SHA } = require('./c110_contract.cjs');
const { fingerprint, validateProof, PROOF_VERSION } = require('./c110_preflight_proof.cjs');
function hasWaitedResumeTransition(source) {
  const begin = source.indexOf("await executorCommand('resume', 'Продолжить работу', 'in_progress');");
  const end = source.indexOf("await stage('incomplete result", begin);
  if (begin < 0 || end < 0) return false;
  const transition = source.slice(begin, end);
  return !transition.includes('.isVisible(') &&
    /await expect\(back\)\.toBeVisible\(\{ timeout: 10_000 \}\);\s*await back\.click\(\);\s*await expect\(executor\.page\.getByLabel\('Что выполнено', \{ exact: false \}\)\)\.toBeVisible\(\{ timeout: 10_000 \}\);/.test(transition);
}
test('resume must wait for Back, click it, then wait for the result field', () => {
  const source = fs.readFileSync(path.join(__dirname, 'c110_core.spec.cjs'), 'utf8');
  assert.equal(hasWaitedResumeTransition(source), true);
  const oldRace = source.replace('await expect(back).toBeVisible({ timeout: 10_000 });\n        await back.click();', 'if (await back.isVisible()) await back.click();');
  assert.equal(hasWaitedResumeTransition(oldRace), false);
  assert.equal(hasWaitedResumeTransition(source.replace("await expect(executor.page.getByLabel('Что выполнено', { exact: false })).toBeVisible({ timeout: 10_000 });", '')), false);
});
test('frontend selection and resume source changes invalidate a prior preflight fingerprint', () => {
  const hashes = fingerprint();
  assert.ok(hashes['c110_contract.cjs']); assert.ok(hashes['c110_core.spec.cjs']); assert.ok(hashes['c110_playwright.config.cjs']);
  const now = Date.parse('2026-10-07T21:42:00Z');
  const proof = { version: PROOF_VERSION, result: 'PASS', playwright: '1.63.0', frontend_sha: FRONTEND_SHA, source_sha: 'a'.repeat(40), source_files: hashes,
    created_at: new Date(now).toISOString(), expected_dummy_failures: 1, observed_dummy_failures: 1, scanned_outputs: 3,
    sentinel_matches: 0, scanned_output_sha256: 'b'.repeat(64) };
  for (const changed of ['c110_contract.cjs', 'c110_core.spec.cjs', 'c110_playwright.config.cjs']) {
    assert.throws(() => validateProof(proof, 'a'.repeat(40), { ...hashes, [changed]: 'c'.repeat(64) }, now, FRONTEND_SHA));
  }
});
