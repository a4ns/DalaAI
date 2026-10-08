'use strict';
const path = require('node:path'), { createRequire } = require('node:module'), { randomBytes } = require('node:crypto');
const k = require('./contract.cjs'), p = require('./proof.cjs'), o = require('./observations.cjs'), { installReaderTap } = require('./browser_tap.cjs');
const { privateLoginBoundary, privateOperationBoundary, PRIVATE_ACTION_TIMEOUT_MS } = require('../c113_private_boundary.cjs');
const files = require('../c113_downloads.cjs');
const root = process.env.DALA_BCP_PLAYWRIGHT_PACKAGE || path.dirname(require.resolve('@playwright/test/package.json'));
const { test, expect } = createRequire(path.join(root, 'package.json'))(root);
test(k.DUMMY_TITLE, async ({ page }, info) => {
  k.validateRunner(info.config, info.project, path.join(__dirname, 'preflight.config.cjs'), path.join(k.privateOutput(), 'report.json'));
  const sentinels = JSON.parse(process.env.DALA_BCP_DUMMY_SENTINELS || '[]'); expect(sentinels).toHaveLength(6);
  const nonce = sentinels[5], sha = p.sourceSha(), run = k.runId();
  await page.route('https://localhost:18443/__body_probe_dummy__', route => route.fulfill({ contentType: 'text/html', body: '<label for="pin">PIN</label><input id="pin" type="password" disabled>' }));
  await page.goto('https://localhost:18443/__body_probe_dummy__');
  let privateFailures = 0;
  try { await privateLoginBoundary('master', () => page.getByLabel('PIN', { exact: true }).fill(sentinels[0], { timeout: PRIVATE_ACTION_TIMEOUT_MS })); } catch { privateFailures++; }
  const client = await privateOperationBoundary(async () => {
    await page.evaluate(({ content, exact }) => {
      const bytes = new TextEncoder().encode(content);
      const response = new Response(bytes, { headers: { 'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="naryadai-shift.pdf"',
        'cache-control': 'private, no-store', vary: 'Cookie', 'x-content-type-options': 'nosniff', 'content-security-policy': "default-src 'none'; sandbox", 'content-length': String(bytes.length) } });
      Object.defineProperties(response, { url: { value: exact }, type: { value: 'basic' } });
      globalThis.fetch = function () { return Promise.resolve(response); }; // Dummy page only, no network.
    }, { content: sentinels[4], exact: k.EXACT_URL });
    await page.evaluate(installReaderTap, { nonce, sourceSha: sha, runId: run });
    const result = await page.evaluate(async ({ nonce, exact }) => {
      const tap = globalThis.__DALA_BODY_CAPTURE_PROBE__; tap.arm(nonce);
      const response = await fetch(exact, { method: 'GET', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', signal: new AbortController().signal });
      const reader = response.body.getReader(); for (;;) { if ((await reader.read()).done) break; } reader.releaseLock();
      const until = performance.now() + 6000;
      while (tap.snapshot(nonce).state === 'HASHING' && performance.now() < until) await new Promise(r => setTimeout(r, 10));
      return tap.dispose(nonce);
    }, { nonce, exact: k.EXACT_URL });
    return o.validateClient(result, sha, run);
  });
  expect(client.comparability).toBe('COMPARABLE');
  // Actual tap failure path, with a rejected native reader carrying a canary.
  const failedClient = await privateOperationBoundary(async () => {
    await page.evaluate(({ secret, exact }) => {
      const stream = new ReadableStream({ start(controller) { controller.error(new Error(secret)); } });
      const response = new Response(stream, { headers: { 'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="naryadai-shift.pdf"',
        'cache-control': 'private, no-store', vary: 'Cookie', 'x-content-type-options': 'nosniff', 'content-security-policy': "default-src 'none'; sandbox", 'content-length': '5' } });
      Object.defineProperties(response, { url: { value: exact }, type: { value: 'basic' } });
      globalThis.fetch = () => Promise.resolve(response);
    }, { secret: sentinels[2], exact: k.EXACT_URL });
    await page.evaluate(installReaderTap, { nonce, sourceSha: sha, runId: run });
    const value = await page.evaluate(async ({ nonce, exact }) => {
      const tap = globalThis.__DALA_BODY_CAPTURE_PROBE__; tap.arm(nonce);
      const response = await fetch(exact, { method: 'GET', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', signal: new AbortController().signal });
      try { await response.body.getReader().read(); } catch {}
      return tap.dispose(nonce);
    }, { nonce, exact: k.EXACT_URL });
    return o.validateClient(value, sha, run);
  });
  expect(failedClient.reason).toBe('READ_REJECTED');
  expect(failedClient.comparability).toBe('NOT_COMPARABLE');
  for (const stage of ['bridge', 'save', 'inspector', 'current_auth', 'reader_rejection']) {
    try { await privateOperationBoundary(async () => { throw new Error(stage + sentinels.join(' ')); }); } catch { privateFailures++; }
  }
  let cdp;
  try { await privateOperationBoundary(() => files.boundedResponseBody({ body: () => Promise.reject(new Error('Protocol error (Network.getResponseBody): ' + sentinels[5])) })); }
  catch { privateFailures++; cdp = { status: 'FAILED', failure: 'BODY_PROTOCOL_FAILURE' }; }
  const safe = { client, failed_client: failedClient, cdp, inspector: files.inspectorFailure({ stdout: JSON.stringify({ status: 'BLOCKED', code: 'C113_DOWNLOAD_INSPECTION_FAILED', stage: sentinels[3] }) }),
    interpretation: o.interpretation(cdp, client, { status: 'NOT_RUN' }, { invalid: true }, 'NOT_ESTABLISHED') };
  expect(privateFailures).toBe(7);
  await info.attach('body_probe_dummy_safe_projection', { body: Buffer.from(JSON.stringify(safe)), contentType: 'application/json' });
  throw new Error('BODY_PROBE_DUMMY_FAILURE_EXPECTED');
});
