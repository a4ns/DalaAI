'use strict';
if (process.env.DEBUG || process.env.PWDEBUG || process.env.NODE_OPTIONS) throw new Error('C113 BLOCKED: capture overrides forbidden');
const { source_sha } = require('./c113_preflight_proof.cjs').requireProof();
const path = require('node:path');
const { createRequire } = require('node:module');
const { selectedFrontendSha, runnerUse, runId, artifactDir, PROJECT } = require('./c113_contract.cjs');
const root = process.env.DALA_C113_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const pw = createRequire(path.join(root, 'package.json'));
if (pw('./package.json').name !== '@playwright/test' || pw('./package.json').version !== '1.63.0') throw new Error('C113 requires pinned Playwright');
module.exports = pw(root).defineConfig({
  metadata: { frontend_sha: selectedFrontendSha(), harness_sha: source_sha, run_id: runId() },
  testDir: __dirname, testMatch: 'c113_download_clock.spec.cjs', outputDir: path.join(artifactDir(), 'results'),
  forbidOnly: true, fullyParallel: false, workers: 1, retries: 0, timeout: 240_000,
  expect: { timeout: 15_000 },
  reporter: [['list', { printSteps: false }], ['json', { outputFile: path.join(artifactDir(), 'playwright.json') }]],
  use: runnerUse(), projects: [{ name: PROJECT }],
  // No webServer, setup, seed, dependency install, or C110 test selection.
});
