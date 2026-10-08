'use strict';
// Advisory source-only tests. No browser, credentials, network or DB involved.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const d = require('./c112_diagnostics.cjs');
const p = require('./c112_preflight_proof.cjs');
test('diagnostic state contains only three fixed-label fields', () => {
  assert.deepEqual(d.createDiagnostics(), { substep: 'NOT_STARTED', failure_category: 'NONE', analytics_response: 'NOT_OBSERVED' });
});
test('every supported checkpoint is an exact source label', () => {
  for (const label of d.SUBSTEPS) { const state=d.createDiagnostics(); d.checkpoint(state,label); assert.equal(state.substep,label); }
  assert.equal(new Set(d.SUBSTEPS).size,d.SUBSTEPS.length);
});
test('arbitrary values and secret-shaped inputs cannot enter diagnostics', () => {
  const sentinel='DUMMY_PIN_DSN_COOKIE_CSRF_NEVER_PUBLISH';
  for(const value of [sentinel,`${sentinel}\n`,{message:sentinel},new Error(sentinel),null,undefined,NaN,Infinity,200.5]) {
    const state=d.createDiagnostics();d.checkpoint(state,value);d.observeAnalyticsStatus(state,value);d.failDiagnostic(state);
    assert.deepEqual(state,{substep:'UNCLASSIFIED_STEP',failure_category:'ASSERTION_OR_OPERATION_FAILED',analytics_response:'HTTP_OTHER_OR_UNAVAILABLE'});
    assert.equal(p.containsSentinel(JSON.stringify(state),[sentinel]),false);
  }
});
test('HTTP diagnostics emit known categories rather than raw statuses', () => {
  for(const [status,category] of [[200,'HTTP_OK'],[403,'HTTP_FORBIDDEN'],[422,'HTTP_VALIDATION'],[503,'HTTP_UNAVAILABLE'],[201,'HTTP_OTHER_OR_UNAVAILABLE'],['200','HTTP_OTHER_OR_UNAVAILABLE']]) {
    const state=d.createDiagnostics();d.observeAnalyticsStatus(state,status);assert.equal(state.analytics_response,category);
  }
});
test('diagnostics are source-bound and exercised by the actual dummy failure output path', () => {
  assert.ok(p.BOUND_FILES.includes('c112_diagnostics.cjs'));
  const dummy=fs.readFileSync(path.join(__dirname,'c112_preflight.spec.cjs'),'utf8');
  assert.match(dummy,/checkpoint\(diagnostic, sentinels\[0\]\)/);
  assert.match(dummy,/observeAnalyticsStatus\(diagnostic, sentinels\[1\]\)/);
  assert.match(dummy,/testInfo\.attach\('c112_safe_diagnostic'/);
  const real=fs.readFileSync(path.join(__dirname,'c112_analytics.spec.cjs'),'utf8');
  assert.match(real,/diagnostics: createDiagnostics\(\)/);
  assert.match(real,/catch \{ evidence\.result = 'FAIL'; failDiagnostic\(evidence\.diagnostics\); \}/);
  for(const label of ['NAVIGATE_ANALYTICS','FILL_PERIOD_START','FILL_PERIOD_END','WAIT_MATCHING_UI_RESPONSE','CHECK_PROTECTED_HEADERS','CHECK_API_DATABASE_IDENTITIES','WAIT_UNAVAILABLE_PHOTO_NOTICE','EXPAND_PROVENANCE_DISCLOSURE','CHECK_ISSUED_UI_METRIC']) assert.ok(real.includes(`'${label}'`));
  assert.doesNotMatch(real,/error\.(message|stack)|console\.(log|error)/);
});
