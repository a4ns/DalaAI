'use strict';
if (process.env.DEBUG || process.env.PWDEBUG || process.env.NODE_OPTIONS) throw new Error('C110 preflight rejects debug/preload capture');
const path = require('node:path');
const { createRequire } = require('node:module');
const { selectedFrontendSha } = require('./c110_contract.cjs');
const root = process.env.DALA_C110_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const pw = createRequire(path.join(root, 'package.json'));
if (pw('./package.json').version !== '1.63.0') throw new Error('C110 preflight requires pinned Playwright');
module.exports = pw(root).defineConfig({
  metadata: { frontend_sha: selectedFrontendSha() },
  testDir: __dirname, testMatch: 'c110_preflight.spec.cjs', workers: 1, retries: 0,
  forbidOnly: true, fullyParallel: false, timeout: 20_000,
  outputDir: path.join(process.env.DALA_C110_DUMMY_OUTPUT, 'results'),
  reporter: [['list', { printSteps: false }], ['json', { outputFile: path.join(process.env.DALA_C110_DUMMY_OUTPUT, 'report.json') }]],
  use: { browserName: 'chromium', ignoreHTTPSErrors: false, trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block' },
  projects: [{ name: 'c110-secrecy-preflight' }],
});
