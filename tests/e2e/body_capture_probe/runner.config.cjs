'use strict';
const path = require('node:path'), { createRequire } = require('node:module'), k = require('./contract.cjs');
const proof = require('./proof.cjs').requireProof();
const root = process.env.DALA_BCP_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const pw = createRequire(path.join(root, 'package.json'));
k.check(path.isAbsolute(root) && pw('./package.json').name === '@playwright/test' && pw('./package.json').version === '1.63.0', 'LOCKED_PLAYWRIGHT');
module.exports = pw(root).defineConfig({ metadata: { scope: 'INSTRUMENTED_DIAGNOSTIC_ONLY', run_id: k.runId(), source_sha: proof.source_sha },
  testDir: __dirname, testMatch: 'runner.spec.cjs', outputDir: path.join(k.privateOutput(), 'results'),
  forbidOnly: true, fullyParallel: false, workers: 1, retries: 0, timeout: 240000, expect: { timeout: 15000 },
  reporter: [['list', { printSteps: false }], ['json', { outputFile: path.join(k.privateOutput(), 'report.json') }]],
  use: k.runnerUse(), projects: [{ name: k.PROJECT }] });
