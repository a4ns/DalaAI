'use strict';
const path = require('node:path');
const { createRequire } = require('node:module');
const root = process.env.DALA_C113_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const { test, expect } = createRequire(path.join(root, 'package.json'))(root);
const { PRIVATE_ACTION_TIMEOUT_MS, privateLoginBoundary, privateOperationBoundary } = require('./c113_private_boundary.cjs');
const { validateEffectiveRunner } = require('./c113_contract.cjs');
const { PREFLIGHT_TITLE } = require('./c113_preflight_proof.cjs');
test(PREFLIGHT_TITLE, async ({ page }, testInfo) => {
  validateEffectiveRunner(testInfo.config, testInfo.project, path.join(__dirname, 'c113_preflight.config.cjs'),
    path.join(process.env.DALA_C113_DUMMY_OUTPUT, 'report.json'));
  const sentinels = JSON.parse(process.env.DALA_C113_DUMMY_SENTINELS || '[]');
  expect(sentinels).toHaveLength(4);
  // Local dummy DOM only. No server, account, fixture file or business command.
  await page.setContent('<label for="pin">PIN</label><input id="pin" type="password" disabled>');
  let protectedFailures = 0;
  try {
    await privateLoginBoundary('master', async () => {
      await page.getByLabel('PIN', { exact: true }).fill(sentinels[0], { timeout: PRIVATE_ACTION_TIMEOUT_MS });
    });
  } catch (error) {
    expect(error.message).toBe('C113 BLOCKED: synthetic master login failed; credential-bearing details suppressed');
    protectedFailures++;
  }
  try {
    await privateLoginBoundary('executor', async () => {
      // Simulate a lower-layer failure containing DSN/cookie/CSRF dummy values.
      throw new Error(`dummy transport ${sentinels[1]} ${sentinels[2]} ${sentinels[3]}`);
    });
  } catch (error) {
    expect(error.message).toBe('C113 BLOCKED: synthetic executor login failed; credential-bearing details suppressed');
    protectedFailures++;
  }
  for (const dummyPath of ['clock_transport','download_save','download_parser','executor_denial']) {
    try { await privateOperationBoundary(async () => { throw new Error(dummyPath + sentinels.join(' ')); }); }
    catch (error) { expect(error.message).toBe('C113 BLOCKED: operation failed; private details suppressed'); protectedFailures++; }
  }
  expect(protectedFailures).toBe(6);
  // Intentionally unexpected failure: wrapper must require exit 1 and 1 failure.
  // It is not a core test, expected-failure annotation or successful journey.
  throw new Error('C113_DUMMY_FAILURE_EXPECTED');
});
