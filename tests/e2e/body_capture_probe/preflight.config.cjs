'use strict';
const path = require('node:path'), { createRequire } = require('node:module'), k = require('./contract.cjs');
k.validatePublic();
const root = process.env.DALA_BCP_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const pw = createRequire(path.join(root, 'package.json'));
k.check(path.isAbsolute(root) && pw('./package.json').name === '@playwright/test' && pw('./package.json').version === '1.63.0', 'LOCKED_PLAYWRIGHT');
module.exports = pw(root).defineConfig({ metadata: { scope: 'DUMMY_BODY_PROBE_ONLY', run_id: k.runId() }, testDir: __dirname, testMatch: 'preflight.spec.cjs',
  outputDir: path.join(k.privateOutput(), 'results'), forbidOnly: true, fullyParallel: false, workers: 1, retries: 0, timeout: 30000,
  reporter: [['list', { printSteps: false }], ['json', { outputFile: path.join(k.privateOutput(), 'report.json') }]],
  use: k.runnerUse(), projects: [{ name: 'body-probe-dummy-privacy' }] });
