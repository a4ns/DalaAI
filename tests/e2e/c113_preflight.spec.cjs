'use strict';
const path = require('node:path');
const { createRequire } = require('node:module');
const root = process.env.DALA_C113_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const { test, expect } = createRequire(path.join(root, 'package.json'))(root);
const { PRIVATE_ACTION_TIMEOUT_MS, privateLoginBoundary, privateOperationBoundary } = require('./c113_private_boundary.cjs');
const { validateEffectiveRunner } = require('./c113_contract.cjs');
const downloads = require('./c113_downloads.cjs');
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
  try{await privateOperationBoundary(()=>downloads.boundedResponseBody({body:()=>Promise.reject(new Error(sentinels.join(' ')))}));}
  catch(error){expect(error.message).toBe('C113 BLOCKED: operation failed; private details suppressed');protectedFailures++;}
  expect(protectedFailures).toBe(7);
  const diagnostic=downloads.createDownloadDiagnostic();
  downloads.downloadCheckpoint(diagnostic,sentinels[0],sentinels[1]);
  downloads.downloadResponse(diagnostic,sentinels[2]);
  downloads.downloadTransport(diagnostic,{'content-encoding':sentinels[0],'content-length':sentinels[1]});
  diagnostic.inspector=downloads.inspectorFailure({stdout:JSON.stringify({status:'BLOCKED',code:'C113_DOWNLOAD_INSPECTION_FAILED',stage:sentinels[3]})});
  const pageEvents=new (require('node:events').EventEmitter)();
  const dummyRequest={failure:()=>({errorText:sentinels[0]})};
  const observer=downloads.requestCompletionObserver(pageEvents);
  pageEvents.emit('requestfailed',dummyRequest);observer.bind(dummyRequest);
  diagnostic.request_after_body=observer.snapshot();observer.dispose();
  diagnostic.body_failure=downloads.bodyFailure(new Error(`Protocol error (Network.getResponseBody): ${sentinels[1]}`));
  diagnostic.frontend_before_body=await downloads.sampleDownloadUi({getByRole(){throw new Error(sentinels[3]);}},'pdf');
  diagnostic.frontend_after_body=downloads.frontendState([sentinels[2],false,false,false]);
  await testInfo.attach('c113_safe_download_diagnostic',{body:Buffer.from(JSON.stringify(diagnostic)),contentType:'application/json'});
  // Intentionally unexpected failure: wrapper must require exit 1 and 1 failure.
  // It is not a core test, expected-failure annotation or successful journey.
  throw new Error('C113_DUMMY_FAILURE_EXPECTED');
});
