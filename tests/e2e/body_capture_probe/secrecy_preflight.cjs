'use strict';
// A5 only: a new real dummy-browser failure proof, never a private fixture runner.
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), { spawnSync } = require('node:child_process');
const { randomBytes, createHash } = require('node:crypto'), { createRequire } = require('node:module');
const k = require('./contract.cjs'), p = require('./proof.cjs');
function preflightNodeEnvironment(env = process.env) {
  const result = { ...k.runnerUse(env).launchOptions.env };
  // This non-secret locator belongs to the Node driver, not Chromium's env.
  // Never inherit the surrounding runner's private inputs or capture overrides.
  if (env.PLAYWRIGHT_BROWSERS_PATH !== undefined) {
    const locator = env.PLAYWRIGHT_BROWSERS_PATH;
    k.check(typeof locator === 'string' && locator.length <= 4096 && path.isAbsolute(locator) && !/[\x00-\x1f\x7f]/.test(locator), 'EXPLICIT_BROWSER_LOCATOR');
    result.PLAYWRIGHT_BROWSERS_PATH = locator;
  }
  return result;
}
function main() {
  let output;
  try {
    const run = k.validatePublic();
    k.check(!Object.entries(process.env).some(([key, value]) => value && (key.startsWith('PG') || /DALA_(E2E_(MASTER_PIN_FILE|EXECUTOR_PIN_FILE|FIXTURE_FILE)|BCP_(OBSERVER_DATABASE_URL|AUTHORIZED|DATABASE_SCHEMA))/.test(key))), 'NO_PRIVATE_PREFLIGHT_INPUT');
    const root = process.env.DALA_BCP_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
    const pw = createRequire(path.join(root, 'package.json'));
    k.check(path.isAbsolute(root) && pw('./package.json').name === '@playwright/test' && pw('./package.json').version === '1.63.0', 'LOCKED_PLAYWRIGHT');
    const sha = p.sourceSha(), hashes = p.fingerprint(), receipt = process.env.DALA_BCP_PREFLIGHT_RECEIPT;
    k.check(path.isAbsolute(receipt || ''), 'NEW_RECEIPT');
    const sentinels = Array.from({ length: 6 }, (_, i) => i === 5 ? randomBytes(32).toString('hex') : `BCP_PRIVATE_DUMMY_${i}_${randomBytes(24).toString('hex')}`);
    output = fs.mkdtempSync(path.join(os.tmpdir(), 'bcp-dummy-private-')); fs.chmodSync(output, 0o700);
    const env = { ...preflightNodeEnvironment(), DALA_BCP_PRODUCT_SHA: k.PRODUCT_SHA, DALA_E2E_FRONTEND_SHA: k.FRONTEND_SHA,
      DALA_BCP_RUN_ID: run, DALA_BCP_PRIVATE_OUTPUT: output, DALA_BCP_DUMMY_SENTINELS: JSON.stringify(sentinels), DALA_BCP_PLAYWRIGHT_PACKAGE: root };
    const child = spawnSync(process.execPath, [path.join(root, 'cli.js'), 'test', '--config', path.join(__dirname, 'preflight.config.cjs')], { env, timeout: 60000, maxBuffer: 4 * 1024 * 1024 });
    k.check(!child.error && !child.signal, 'PREFLIGHT_RUNNER');
    const outputs = [child.stdout || Buffer.alloc(0), child.stderr || Buffer.alloc(0)]; let visited = 0, total = outputs.reduce((n, v) => n + v.length, 0);
    const scan = (dir, depth = 0) => {
      k.check(depth <= 4, 'ARTIFACT_DEPTH');
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        k.check(++visited <= 64 && !entry.isSymbolicLink(), 'ARTIFACT_SHAPE'); const file = path.join(dir, entry.name);
        if (entry.isDirectory()) scan(file, depth + 1);
        else { const size = fs.statSync(file).size; k.check(entry.isFile() && /\.(json|txt|md)$/.test(entry.name) && size <= 4 * 1024 * 1024, 'ARTIFACT_TYPE');
          total += size; k.check(total <= 8 * 1024 * 1024 && outputs.length < 32, 'OUTPUT_BOUND'); outputs.push(fs.readFileSync(file)); }
      }
    };
    scan(output); k.check(!outputs.some(bytes => p.containsSentinel(bytes, sentinels)), 'SENTINEL_EXPOSURE');
    k.check(p.outcome(JSON.parse(fs.readFileSync(path.join(output, 'report.json'))), child.status, run), 'EXPECTED_DUMMY_FAILURE');
    k.check(p.sourceSha() === sha && JSON.stringify(p.fingerprint()) === JSON.stringify(hashes), 'SOURCE_STABILITY');
    const proof = { version: p.VERSION, result: 'PASS', scope: 'DUMMY_PRIVACY_ONLY', playwright: '1.63.0', source_sha: sha, source_files: hashes,
      product_sha: k.PRODUCT_SHA, frontend_sha: k.FRONTEND_SHA, run_id: run, created_at: new Date().toISOString(), expected_failures: 1, observed_failures: 1,
      scanned_outputs: outputs.length, sentinel_matches: 0, scanned_sha256: createHash('sha256').update(Buffer.concat(outputs)).digest('hex') };
    fs.writeFileSync(receipt, JSON.stringify(proof) + '\n', { flag: 'wx', mode: 0o600 });
    process.stdout.write('{"status":"PROOF_ISSUED","scope":"DUMMY_PRIVACY_ONLY","private_journey":"NOT_RUN"}\n'); return 0;
  } catch { process.stdout.write('{"status":"BLOCKED","code":"BODY_PROBE_PRIVACY_UNPROVEN"}\n'); return 2; }
  finally { if (output) fs.rmSync(output, { recursive: true, force: true }); }
}
if (require.main === module) process.exitCode = main();
module.exports = { main, preflightNodeEnvironment };
