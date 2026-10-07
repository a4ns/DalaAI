'use strict';
// Run only in A5's authorized disposable browser environment. No real PIN input.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { randomBytes, createHash } = require('node:crypto');
const { createRequire } = require('node:module');
const { selectedFrontendSha } = require('./c110_contract.cjs');
const { PROOF_VERSION, fingerprint, sourceSha, containsSentinel, preflightOutcome } = require('./c110_preflight_proof.cjs');
function main() {
  let output;
  try {
    if (process.env.DEBUG || process.env.PWDEBUG || process.env.NODE_OPTIONS) throw new Error('capture settings');
    if (['DALA_E2E_MASTER_PIN_FILE', 'DALA_E2E_EXECUTOR_PIN_FILE', 'DALA_E2E_FIXTURE_FILE', 'DALA_C110_OBSERVER_DATABASE_URL'].some(k => process.env[k])) throw new Error('real fixture inputs forbidden in preflight');
    const root = process.env.DALA_C110_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
    const pw = createRequire(path.join(root, 'package.json'));
    if (pw('./package.json').version !== '1.63.0') throw new Error('wrong dependency');
    const sha = sourceSha(), hashes = fingerprint(), frontendSha = selectedFrontendSha();
    const receipt = process.env.DALA_C110_PREFLIGHT_RECEIPT;
    if (!receipt || !path.isAbsolute(receipt)) throw new Error('explicit public receipt destination required');
    const sentinels = Array.from({ length: 4 }, (_, i) => `C110_DUMMY_${i}_${randomBytes(24).toString('hex')}`);
    output = fs.mkdtempSync(path.join(os.tmpdir(), 'c110-dummy-output-'));
    const env = { ...process.env, DALA_C110_DUMMY_OUTPUT: output, DALA_C110_DUMMY_SENTINELS: JSON.stringify(sentinels) };
    // This child has no actual fixture, PIN-file or DB observer inputs.
    for (const key of Object.keys(env)) if ((key.startsWith('DALA_E2E_') && key !== 'DALA_E2E_FRONTEND_SHA') || key.startsWith('PG') || /DALA_C110_(OBSERVER|DATABASE|AUTHORIZED|FAILURE_OUTPUT)/.test(key)) delete env[key];
    const run = spawnSync(process.execPath, [path.join(root, 'cli.js'), 'test', '--config', path.join(__dirname, 'c110_preflight.config.cjs')],
      { env, timeout: 60_000, maxBuffer: 4 * 1024 * 1024 });
    if (run.error || run.signal) throw new Error('runner unavailable');
    const outputs = [run.stdout || Buffer.alloc(0), run.stderr || Buffer.alloc(0)];
    let visited = 0, totalBytes = outputs.reduce((n, bytes) => n + bytes.length, 0);
    const visit = (directory, depth = 0) => {
      if (depth > 4) throw new Error('unbounded artifact depth');
      for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
        if (++visited > 64) throw new Error('unbounded artifact count');
        const file = path.join(directory, entry.name);
        if (entry.isSymbolicLink()) throw new Error('unexpected artifact link');
        if (entry.isDirectory()) visit(file, depth + 1);
        else {
          if (!entry.isFile() || fs.statSync(file).size > 4 * 1024 * 1024 || !/\.(json|txt|md)$/.test(entry.name)) throw new Error('unscannable artifact');
          totalBytes += fs.statSync(file).size;
          if (totalBytes > 8 * 1024 * 1024) throw new Error('unbounded total output');
          outputs.push(fs.readFileSync(file));
        }
        if (outputs.length > 32) throw new Error('unbounded artifacts');
      }
    };
    visit(output);
    if (outputs.some(bytes => containsSentinel(bytes, sentinels))) throw new Error('dummy credential exposure');
    const report = JSON.parse(fs.readFileSync(path.join(output, 'report.json'), 'utf8'));
    if (!preflightOutcome(report, run.status)) throw new Error('missing intentional failure');
    if (sourceSha() !== sha || JSON.stringify(fingerprint()) !== JSON.stringify(hashes)) throw new Error('source changed during preflight');
    const proof = { version: PROOF_VERSION, result: 'PASS', playwright: '1.63.0', source_sha: sha, frontend_sha: frontendSha, source_files: hashes,
      created_at: new Date().toISOString(), expected_dummy_failures: 1, observed_dummy_failures: 1,
      scanned_outputs: outputs.length, sentinel_matches: 0,
      scanned_output_sha256: createHash('sha256').update(Buffer.concat(outputs)).digest('hex') };
    fs.writeFileSync(receipt, JSON.stringify(proof, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    process.stdout.write(JSON.stringify({ status: 'PASS', frontend_sha: frontendSha, scope: 'dummy failure-output preflight only; core journey NOT_RUN' }) + '\n');
    return 0;
  } catch {
    // Never echo child errors/output/sentinels, credential paths or raw reports.
    process.stdout.write('{"status":"BLOCKED","code":"C110_FAILURE_OUTPUT_PREFLIGHT_NOT_PROVEN"}\n');
    return 2;
  } finally {
    if (output) fs.rmSync(output, { recursive: true, force: true });
  }
}
if (require.main === module) process.exitCode = main();
module.exports = { main };
