'use strict';
// Local-only anonymous transport fixture, not a deployed login or an iPhone test.
// Args: engine, exact Playwright module path, reviewed candidate client.ts path.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const assert = require('node:assert/strict');
const engine = process.argv[2];
assert.ok(['chromium', 'webkit'].includes(engine), 'Explicit supported engine required');
const pw = require(path.resolve(process.argv[3]));
const source = fs.readFileSync(path.resolve(process.argv[4]), 'utf8');
const fetchLine = source.split('\n').find(line => line.includes('await this.#fetch(BASE + path,'));
assert.ok(fetchLine, 'Reviewed transport call required');
for (const pair of ["credentials: 'same-origin'", "mode: 'same-origin'", "referrerPolicy: 'origin'", "redirect: 'error'", "cache: 'no-store'"]) assert.ok(fetchLine.includes(pair), 'Reviewed transport barrier missing');
assert.ok(!/headers\.set\(['"](?:Origin|Referer|Sec-Fetch-Site)['"]/i.test(source), 'Browser security headers must not be fabricated');
const sourceSha256 = createHash('sha256').update(source).digest('hex');
const downstreamHits = [];
const serve = handler => new Promise(resolve => { const s = http.createServer(handler); s.listen(0, '127.0.0.1', () => resolve(s)); });
const close = server => server && new Promise(resolve => server.close(resolve));
let stage = 'fixture_setup';
(async () => {
  let downstream, server, browser;
  try {
    downstream = await serve((req, res) => { downstreamHits.push(req.method); req.resume(); res.end('unexpected destination'); });
    const other = `http://127.0.0.1:${downstream.address().port}`;
    server = await serve((req, res) => {
      req.resume();
      if (req.url === '/echo') {
        const fields = { origin: req.headers.origin ?? null, referer: req.headers.referer ?? null, secFetchSite: req.headers['sec-fetch-site'] ?? null, dummyCookieRetained: req.headers.cookie === 'origin_fixture=synthetic-only', dummyCsrfRetained: req.headers['x-csrf-token'] === 'synthetic-only' };
        res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); return res.end(JSON.stringify(fields));
      }
      if (req.url === '/redirect-cross') { res.writeHead(307, { Location: other + '/destination' }); return res.end(); }
      if (req.url === '/redirect-same') { res.writeHead(307, { Location: '/same-destination' }); return res.end(); }
      if (req.url === '/same-destination') { downstreamHits.push(req.method); return res.end('unexpected destination'); }
      res.writeHead(200, { 'Content-Type': 'text/html', 'Referrer-Policy': 'no-referrer', 'Set-Cookie': 'origin_fixture=synthetic-only; SameSite=Strict; HttpOnly; Path=/', 'Cache-Control': 'no-store' });
      res.end('<!doctype html><title>Anonymous request-origin fixture</title><p>Local transport fixture</p>');
    });
    const origin = `http://127.0.0.1:${server.address().port}`;
    stage = 'browser_launch';
    browser = await pw[engine].launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: 'block' });
    const page = await context.newPage();
    stage = 'browser_cases';
    await page.goto(origin + '/private-path-canary?private-query-canary=yes');
    const results = await page.evaluate(async ({ other }) => {
      const base = { method: 'POST', body: '{}', credentials: 'same-origin', mode: 'same-origin', cache: 'no-store', redirect: 'error', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'synthetic-only' } };
      const baseline = await (await fetch('/echo', base)).json();
      const candidate = await (await fetch('/echo', { ...base, referrerPolicy: 'origin' })).json();
      const blocked = [];
      for (const target of [other + '/cross-origin', '/redirect-cross', '/redirect-same']) {
        try { await fetch(target, { ...base, referrerPolicy: 'origin' }); blocked.push(false); }
        catch (error) { blocked.push(error instanceof TypeError); }
      }
      return { baseline, candidate, blocked };
    }, { other });
    const { baseline, candidate, blocked } = results;
    const passed = value => value ? 'pass' : 'fail';
    const cases = [
      { id: 'baseline_no_referrer_origin', status: baseline.origin === 'null' && baseline.referer === null ? 'pass' : 'inconclusive' },
      { id: 'candidate_post_origin', status: passed(candidate.origin === origin) },
      { id: 'candidate_referrer_privacy', status: passed(candidate.referer === origin + '/') },
      { id: 'candidate_cookie_csrf', status: passed(candidate.dummyCookieRetained && candidate.dummyCsrfRetained) },
      { id: 'same_origin_metadata', status: passed(candidate.secFetchSite === 'same-origin' || candidate.secFetchSite === null) },
      { id: 'cross_origin_refused', status: passed(blocked[0] && downstreamHits.length === 0) },
      { id: 'cross_origin_redirect_refused', status: passed(blocked[1] && downstreamHits.length === 0) },
      { id: 'same_origin_redirect_refused', status: passed(blocked[2] && downstreamHits.length === 0) },
    ];
    const originClass = value => value === 'null' ? 'opaque_null' : value === origin ? 'exact_origin' : value === null ? 'missing' : 'unexpected';
    const candidatePass = cases.slice(1).every(item => item.status === 'pass');
    const baselineReproduced = cases[0].status === 'pass';
    const outcome = !candidatePass ? 'fail' : !baselineReproduced ? 'inconclusive' : 'pass';
    console.log(JSON.stringify({ schemaVersion: 1, fixture: 'anonymous_request_origin_v1', baselineProductSha: '348b82683b95e4bd20ce2ecbbf980d761e72ae3a', candidateClientSha256: sourceSha256, engine, browserVersion: browser.version(), evidence: 'native browser; HTTP loopback; synthetic headers; no application authentication; not physical iPhone or hosted HTTPS', outcome, candidatePass, baselineReproduced, baselineOrigin: originClass(baseline.origin), candidateOrigin: originClass(candidate.origin), candidateReferrerOriginOnly: candidate.referer === origin + '/', candidateFetchMetadata: candidate.secFetchSite === null ? 'missing_allowed_by_backend' : candidate.secFetchSite === 'same-origin' ? 'same-origin' : 'unexpected', downstreamHits: downstreamHits.length, caseCount: cases.length, cases }, null, 2));
    process.exitCode = outcome === 'pass' ? 0 : outcome === 'inconclusive' ? 2 : 1;
  } finally { if (browser) await browser.close(); await Promise.all([close(server), close(downstream)]); }
})().catch(() => { console.log(JSON.stringify({ schemaVersion: 1, fixture: 'anonymous_request_origin_v1', engine, outcome: 'blocked', stage, candidateClientSha256: sourceSha256, caseCount: 0 })); process.exitCode = 2; });
