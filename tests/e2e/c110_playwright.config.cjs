'use strict';
// Only test configuration. A5 owns provisioning, CA trust, app start and CI.
if (process.env.DEBUG || process.env.PWDEBUG || process.env.NODE_OPTIONS) throw new Error('C110 BLOCKED: debug/preload capture must be disabled');
require('./c110_preflight_proof.cjs').requireProof();
const path = require('node:path');
const { createRequire } = require('node:module');
const packageRoot = process.env.DALA_C110_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const fromPlaywright = createRequire(path.join(packageRoot, 'package.json'));
const { defineConfig } = fromPlaywright(packageRoot);
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: 'c110_core.spec.cjs',
  outputDir: path.join(__dirname, 'c110_artifacts', 'results'),
  forbidOnly: true,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 180_000,
  expect: { timeout: 10_000 },
  reporter: [['list', { printSteps: false }], ['json', { outputFile: path.join(__dirname, 'c110_artifacts', 'playwright.json') }]],
  use: { browserName: 'chromium', ignoreHTTPSErrors: false, trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block' },
  projects: [{ name: 'c110-android-chromium' }],
  // No webServer/install/bootstrap hook: never start an unapproved substitute.
});
