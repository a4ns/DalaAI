'use strict';
const fs = require('node:fs'), path = require('node:path'), { createHash } = require('node:crypto'), { execFileSync } = require('node:child_process');
const k = require('./contract.cjs');
const VERSION = 'isolated-body-reader-proof-v1';
const REPO = path.resolve(__dirname, '../../..');
const IMPORTS = ['c113_contract.cjs', 'c113_downloads.cjs', 'c113_clock.cjs', 'c113_gate.cjs', 'c113_private_boundary.cjs', 'c113_observe.py', 'c113_inspect_download.py', 'c113_preflight_proof.cjs', 'package.json', 'package-lock.json'];
const git = args => execFileSync('git', args, { cwd: REPO, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
function paths() { return [...fs.readdirSync(__dirname).filter(n => /^[a-z_]+(?:\.test|\.spec|\.config)?\.cjs$/.test(n)).map(n => `tests/e2e/body_capture_probe/${n}`), ...IMPORTS.map(n => `tests/e2e/${n}`)].sort(); }
function fingerprint() { return Object.fromEntries(paths().map(file => [file, createHash('sha256').update(fs.readFileSync(path.join(REPO, file))).digest('hex')])); }
function assertProductWorkingTreeClean(readGit = git) {
  // Committed-tree equality alone does not bind bytes built from the worktree.
  // Include staged, unstaged, deleted, renamed and non-ignored untracked inputs.
  readGit(['diff', '--exit-code', 'HEAD', '--', 'frontend', 'backend']);
  k.check(readGit(['status', '--porcelain', '--untracked-files=all', '--', 'frontend', 'backend']) === '', 'CLEAN_PRODUCT_WORKTREE');
}
function sourceSha() {
  const files = paths(), sha = git(['rev-parse', 'HEAD']); k.check(/^[0-9a-f]{40}$/.test(sha), 'SOURCE_SHA');
  git(['ls-files', '--error-unmatch', '--', ...files]); git(['diff', '--exit-code', 'HEAD', '--', ...files]);
  k.check(git(['status', '--porcelain', '--untracked-files=all', '--', 'tests/e2e/body_capture_probe']) === '', 'CLEAN_SOURCE');
  assertProductWorkingTreeClean();
  for (const tree of ['frontend', 'backend']) k.check(git(['rev-parse', `HEAD:${tree}`]) === git(['rev-parse', `${k.PRODUCT_SHA}:${tree}`]), 'UNCHANGED_PRODUCT');
  return sha;
}
function containsSentinel(bytes, sentinels) {
  const text = Buffer.from(bytes).toString('utf8');
  if (sentinels.some(s => [s, Buffer.from(s).toString('base64'), encodeURIComponent(s)].some(v => text.includes(v)))) return true;
  return require('../c113_preflight_proof.cjs').containsSentinel(bytes, sentinels);
}
function outcome(report, exitCode, run) {
  const specs = []; const visit = suites => { for (const s of suites || []) { specs.push(...s.specs || []); visit(s.suites); } }; visit(report?.suites);
  const t = specs[0]?.tests?.[0];
  return exitCode === 1 && report?.config?.metadata?.run_id === run && report?.config?.metadata?.scope === 'DUMMY_BODY_PROBE_ONLY' && report.errors?.length === 0 && specs.length === 1 && specs[0].title === k.DUMMY_TITLE && specs[0].tests.length === 1 && report.stats?.expected === 0 && report.stats.unexpected === 1 && report.stats.skipped === 0 && report.stats.flaky === 0 && t.expectedStatus === 'passed' && t.status === 'unexpected' && t.results?.length === 1 && t.results[0].status === 'failed' && t.results[0].retry === 0 && t.results[0].errors?.some(e => e.message?.includes('BODY_PROBE_DUMMY_FAILURE_EXPECTED'));
}
function validateProof(proof, sha, hashes, env, now = Date.now()) {
  k.check(proof && proof.version === VERSION && proof.result === 'PASS' && proof.scope === 'DUMMY_PRIVACY_ONLY' && proof.playwright === '1.63.0' && proof.source_sha === sha && JSON.stringify(proof.source_files) === JSON.stringify(hashes) && proof.run_id === k.validatePublic(env) && proof.product_sha === k.PRODUCT_SHA && proof.frontend_sha === k.FRONTEND_SHA && proof.expected_failures === 1 && proof.observed_failures === 1 && Number.isInteger(proof.scanned_outputs) && proof.scanned_outputs >= 3 && proof.scanned_outputs <= 32 && proof.sentinel_matches === 0 && /^[0-9a-f]{64}$/.test(proof.scanned_sha256 || '') && Number.isFinite(Date.parse(proof.created_at)) && now >= Date.parse(proof.created_at) && now - Date.parse(proof.created_at) < 30 * 60000, 'FRESH_OWN_PROOF');
  return proof;
}
function requireProof(env = process.env) {
  try {
    const file = env.DALA_BCP_PREFLIGHT_RECEIPT;
    k.check(path.isAbsolute(file || '') && !['DALA_E2E_MASTER_PIN_FILE', 'DALA_E2E_EXECUTOR_PIN_FILE', 'DALA_E2E_FIXTURE_FILE'].some(key => env[key] === file), 'OWN_RECEIPT');
    const s = fs.lstatSync(file); k.check(s.isFile() && !s.isSymbolicLink() && s.size < 65536, 'BOUNDED_RECEIPT');
    return validateProof(JSON.parse(fs.readFileSync(file, 'utf8')), sourceSha(), fingerprint(), env);
  } catch { throw new Error('BODY_PROBE_BLOCKED:FRESH_OWN_SOURCE_PRIVACY_PROOF_REQUIRED'); }
}
module.exports = { VERSION, IMPORTS, paths, fingerprint, sourceSha, assertProductWorkingTreeClean, containsSentinel, outcome, validateProof, requireProof };
