'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const PROOF_VERSION = 'c110-failure-output-v1';
const PREFLIGHT_TITLE = 'C110 dummy credential failure output';
const BOUND_FILES = ['c110_core.spec.cjs', 'c110_playwright.config.cjs', 'c110_contract.cjs',
  'c110_private_boundary.cjs', 'c110_preflight_proof.cjs', 'c110_secrecy_preflight.cjs',
  'c110_preflight.config.cjs', 'c110_preflight.spec.cjs', 'c110_observe.py', 'package.json', 'package-lock.json'];
function fingerprint() {
  return Object.fromEntries(BOUND_FILES.map(file => [file, createHash('sha256').update(fs.readFileSync(path.join(__dirname, file))).digest('hex')]));
}
function sourceSha() {
  const cwd = path.resolve(__dirname, '../..');
  const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  execFileSync('git', ['ls-files', '--error-unmatch', '--', ...BOUND_FILES.map(file => `tests/e2e/${file}`)], { cwd, stdio: 'ignore' });
  execFileSync('git', ['diff', '--exit-code', 'HEAD', '--', 'tests/e2e/c110_*', 'tests/e2e/package*.json'], { cwd, stdio: 'ignore' });
  if (!/^[0-9a-f]{40}$/.test(sha)) throw new Error('source unavailable');
  return sha;
}
function containsSentinel(bytes, sentinels) {
  const buffer = Buffer.isBuffer(bytes) ? bytes : Buffer.from(bytes);
  const text = buffer.toString('utf8');
  if (sentinels.some(s => text.includes(s))) return true;
  // Also detect escaped values in plain diagnostic output, not just valid JSON.
  const unescaped = text.replace(/\\u([0-9a-f]{4})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
  if (sentinels.some(s => unescaped.includes(s))) return true;
  let decoded;
  try { decoded = JSON.parse(text); } catch { return false; }
  // Traversal failures/limits are unsafe, never treated as clean plain stdout.
  try {
    const pending = [decoded]; let visited = 0;
    while (pending.length) {
      if (++visited > 20_000 || pending.length > 20_000) return true;
      const value = pending.pop();
      if (typeof value === 'string') {
        if (sentinels.some(s => value.includes(s) || Buffer.from(value, 'base64').includes(Buffer.from(s)))) return true;
      } else if (value && typeof value === 'object') {
        for (const child of Object.values(value)) {
          if (pending.length >= 20_000) return true;
          pending.push(child);
        }
      }
    }
  } catch { return true; }
  return false;
}
function preflightOutcome(report, exitCode) {
  const specs = [];
  const visit = suites => { for (const suite of suites || []) { specs.push(...suite.specs || []); visit(suite.suites); } };
  visit(report?.suites);
  const t = specs[0]?.tests?.[0];
  return exitCode === 1 && report.errors?.length === 0 && specs.length === 1 && specs[0].title === PREFLIGHT_TITLE && specs[0].tests.length === 1 &&
    report.stats?.expected === 0 && report.stats.unexpected === 1 && report.stats.skipped === 0 && report.stats.flaky === 0 &&
    t.expectedStatus === 'passed' && t.status === 'unexpected' && t.results?.length === 1 && t.results[0].status === 'failed' && t.results[0].retry === 0 &&
    t.results[0].errors?.some(e => e.message?.includes('C110_DUMMY_FAILURE_EXPECTED'));
}
function validateProof(proof, currentSha, hashes, now = Date.now()) {
  if (!proof || proof.version !== PROOF_VERSION || proof.result !== 'PASS' || proof.playwright !== '1.63.0' ||
      proof.source_sha !== currentSha || JSON.stringify(proof.source_files) !== JSON.stringify(hashes) ||
      proof.expected_dummy_failures !== 1 || proof.observed_dummy_failures !== 1 || proof.scanned_outputs < 3 ||
      proof.sentinel_matches !== 0 || !/^[0-9a-f]{64}$/.test(proof.scanned_output_sha256 || '') ||
      !Number.isFinite(Date.parse(proof.created_at)) || now < Date.parse(proof.created_at) || now - Date.parse(proof.created_at) > 30 * 60_000) {
    throw new Error('C110 BLOCKED: missing, stale or source-mismatched dummy-failure secrecy proof');
  }
  return proof;
}
function requireProof(env = process.env) {
  try {
    if (!env.DALA_C110_PREFLIGHT_RECEIPT) throw new Error('missing receipt');
    if (['DALA_E2E_MASTER_PIN_FILE', 'DALA_E2E_EXECUTOR_PIN_FILE'].some(k => env[k] === env.DALA_C110_PREFLIGHT_RECEIPT)) throw new Error('receipt cannot be a PIN path');
    const stat = fs.lstatSync(env.DALA_C110_PREFLIGHT_RECEIPT);
    if (stat.isSymbolicLink()) throw new Error('receipt link forbidden');
    if (!stat.isFile() || stat.size > 16_384) throw new Error('invalid receipt');
    return validateProof(JSON.parse(fs.readFileSync(env.DALA_C110_PREFLIGHT_RECEIPT, 'utf8')), sourceSha(), fingerprint());
  } catch { throw new Error('C110 BLOCKED: verified current-source dummy-failure secrecy proof required before credential reads'); }
}
module.exports = { PROOF_VERSION, PREFLIGHT_TITLE, fingerprint, sourceSha, containsSentinel, preflightOutcome, validateProof, requireProof };
