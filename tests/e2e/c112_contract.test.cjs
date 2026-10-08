'use strict';
// Isolated mock/source tests only. These are never browser/API/DB evidence.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const c = require('./c112_contract.cjs');
const p = require('./c112_preflight_proof.cjs');
const gate = require('./c112_gate.cjs');
const copy = x => JSON.parse(JSON.stringify(x));
const manifest = JSON.parse(execFileSync('python', ['-c', "import sys,json;sys.path.insert(0,'ops/provision');from history_demo import public_manifest;print(json.dumps(public_manifest()))"], { cwd: path.resolve(__dirname, '../..'), encoding: 'utf8', env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: '1' } }));
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, '0')}`;
const now = Date.parse('2026-10-07T23:35:00Z');
const OLD_FRONTEND_SHA = '9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c';
function fixture() {
  const source_files = p.fingerprint(), expected = { frontend_sha: c.FRONTEND_SHA, backend_sha: 'b'.repeat(40), harness_sha: 'a'.repeat(40), source_files, run_id: 'c112-source-test-0001' };
  const proof = { version: p.PROOF_VERSION, result: 'PASS', playwright: '1.63.0', source_sha: expected.harness_sha, frontend_sha: c.FRONTEND_SHA, source_files, run_id: expected.run_id, created_at: new Date(now - 10_000).toISOString(), expected_dummy_failures: 1, observed_dummy_failures: 1, scanned_outputs: 3, sentinel_matches: 0, scanned_output_sha256: 'c'.repeat(64) };
  const db = { schema_version: 1, source: 'actual_postgresql_read_only', observer_mode: 'existing_restricted_runtime_login_read_only_transaction', observed_at: new Date(now - 7_000).toISOString(), identity: { direct_login: true, read_only: true, isolated_schema: true, schema_create: false, rolsuper: false, rolcreatedb: false, rolcreaterole: false, rolbypassrls: false }, counts: { orders: 540, submissions: 568, photos: 0, order_events: 2160, reviews: 568, ai_assessments: 0, material_writeoffs: 500, operation_receipts: 2160 }, after_photo_references: 444, historical_actor_count: 17, historical_actors_disabled: true, history_sha256: c.HISTORY_SHA256, identity_mapping_sha256: 'd'.repeat(64), business_sha256: 'e'.repeat(64), live_users: manifest.users.map(u => ({ ...u, active: true, section_ids: [...u.section_ids].sort() })), order_ids: Array.from({length: 540}, (_,i) => id(i+1)), submission_ids: Array.from({length:568}, (_,i) => id(i+1001)), section_ids: [...manifest.users.find(u=>u.role==='master').section_ids].sort() };
  const provenance = (i, orders = 540, submissions = 568, photos = 444) => ({ synthetic: true, coverage: 'consistent_snapshot', history_complete: true, source_ref: `runtime-postgres:${id(i)}`, captured_at_real: new Date(now - 5_000 + i).toISOString(), domain_as_of: '2026-10-08T00:00:00Z', historical_evidence: { status: 'synthetic_historical_evidence_unavailable', historical_order_count: orders, historical_submission_count: submissions, historical_after_photo_reference_count: photos, missing_after_photo_row_count: photos, physical_evidence_verified: false, historical_completeness_is_verified_evidence: false, source_commit: c.HISTORY_SOURCE, history_sha256: c.HISTORY_SHA256, loader_version: '1.1.0', identity_mapping_sha256: 'd'.repeat(64) } });
  const base = { status: 200, body_sha256: 'f'.repeat(64), cache: 'private,no-store', vary: 'Cookie', nosniff: true, ui_provenance_visible: true, period: { ...c.PERIOD, display_timezone: 'Asia/Almaty' }, counts: { orders: 540, submissions: 568, photo_references: 444 } };
  const observations = [{ ...base, kind: 'analytics', path: '/api/v1/analytics/shift', provenance: provenance(1), totals_available: true, issued_orders: '540', order_ids_sha256: c.digest(db.order_ids), submission_ids_sha256: c.digest(db.submission_ids) }, { ...base, kind: 'shift_report', path: '/api/v1/reports/shift', provenance: provenance(2), totals_available: true, agrees_with_analytics: true }, { ...base, kind: 'order_report', path: `/api/v1/reports/orders/${id(1)}`, order_id: id(1), provenance: provenance(3,1,1,1), counts: {orders:1,submissions:1,photo_references:1}, agrees_with_analytics:true }];
  const evidence = { schema_version: 1, result: 'PASS', test: c.TITLE, ...expected, secrecy_proof: proof, started_at: new Date(now-8_000).toISOString(), finished_at: new Date(now-1_000).toISOString(), steps: c.REQUIRED_STEPS.map(name=>({name,result:'PASS'})), distinct_secure_sessions: true,
    browser: {mode:'ANDROID_EMULATION',engine:'chromium',profile:'Pixel 7',playwright:'1.63.0',contexts:2,mobile:true,touch:true,trusted_tls:true,credential_environment:'excluded_from_browser_process',service_workers:'blocked'}, period:c.PERIOD,ui_period_utc_plus_5:c.LOCAL_PERIOD,
    separate_gates:Object.fromEntries(['c110_lifecycle','physical_android','native_camera','push_delivery','provider_model','report_export','live_closure'].map(k=>[k,'NOT_RUN'])),manifest,manifest_sha256:c.digest(manifest),database_before:db,database_after:{...copy(db),observed_at:new Date(now-2_000).toISOString()},observations,executor_ui_absent:true,
    restrictions: observations.map(o=>({path:o.path,status:403,code:'FORBIDDEN',no_report_data:true,cache:'private,no-store'})),network:{blocked_external:0,blocked_mutation:0,login_posts:2,business_mutations:0} };
  const report = { config:{metadata:{frontend_sha:c.FRONTEND_SHA,harness_sha:expected.harness_sha,run_id:expected.run_id}},errors:[],stats:{expected:1,unexpected:0,flaky:0,skipped:0},suites:[{specs:[{title:c.TITLE,ok:true,tests:[{projectName:c.PROJECT,expectedStatus:'passed',status:'expected',results:[{status:'passed',retry:0,errors:[]}]}]}]}] };
  return { report, evidence, expected };
}
test('actual public_manifest object is accepted without any private file', () => { const users=c.validateManifest(manifest); assert.equal(users.master.section_ids.length,4); assert.equal(users.executor.section_ids.length,1); assert.equal(manifest.history_orders,540); });
test('only explicit exact reviewed 8e808710 is accepted; old and unknown source selections fail', () => {
  assert.equal(c.FRONTEND_SHA, '8e8087103821b6334ba8d5de0a40c91ee58276f9');
  assert.equal(c.selectedFrontendSha({ DALA_E2E_FRONTEND_SHA: c.FRONTEND_SHA }), c.FRONTEND_SHA);
  for (const selected of [undefined, '', '8e808710', 'da83e9c417a7c6bf7e91b5100e8f2d7616d9f24e', 'da83e9c4', 'd78b9c3b7cabbcbd05b01df77f2a7ec57739afe5', 'd78b9c3b', 'f967d0acf3f04bda304b7fe47e1bf76ca8814634', 'f967d0ac', 'bbe897514e58a4b8f8b6d4f580e5273e34cb5c75', 'bbe89751', '6fa27276f14ef31757cb0da5ee9d7acc15789111', '6fa27276', '8081a2984b2f27b909fa2b86cd9f10ffd01d1e11', '8081a298', 'a880371589aa1dd117dde9e80936c687d146f919', 'a8803715', '1594a930de4b9f15d11dd35bbc59e5b4b0b1d964', '1594a930', 'faef5d3d', 'faef5d3d8b4c640fae013dbfa78074382e512e8f', OLD_FRONTEND_SHA, '3ef269bba80dbd6eafaff0d5e557da21f2d96244', 'f'.repeat(40), c.FRONTEND_SHA.toUpperCase()]) {
    assert.throws(() => c.selectedFrontendSha({ DALA_E2E_FRONTEND_SHA: selected }), /REVIEWED_FRONTEND_REQUIRED/);
    let reads = 0;
    assert.throws(() => c.fixtureFromEnv({ DALA_C112_AUTHORIZED: 'operator-provisioned-synthetic-only', DALA_C112_WORKERS_DISABLED: 'ai,delivery,providers', DALA_E2E_FRONTEND_SHA: selected }, () => { reads++; }, () => ({})), /REVIEWED_FRONTEND_REQUIRED/);
    assert.equal(reads, 0);
  }
});
test('old-source evidence, metadata, selected target and secrecy proof cannot be relabeled', () => {
  for (const mutate of [f => { f.expected.frontend_sha = OLD_FRONTEND_SHA; }, f => { f.report.config.metadata.frontend_sha = OLD_FRONTEND_SHA; }, f => { f.evidence.frontend_sha = OLD_FRONTEND_SHA; }, f => { f.evidence.secrecy_proof.frontend_sha = OLD_FRONTEND_SHA; }]) {
    const f = fixture(); mutate(f); assert.throws(() => gate.validate(f.report, f.evidence, f.expected, now));
  }
  const f = fixture(), receipt = f.evidence.secrecy_proof;
  assert.throws(() => p.validateProof(receipt, f.expected.harness_sha, f.expected.source_files, now, OLD_FRONTEND_SHA, f.expected.run_id));
  assert.throws(() => p.validateProof({ ...receipt, frontend_sha: OLD_FRONTEND_SHA }, f.expected.harness_sha, f.expected.source_files, now, c.FRONTEND_SHA, f.expected.run_id));
  const oldReport = { config: { metadata: { frontend_sha: OLD_FRONTEND_SHA, run_id: f.expected.run_id } }, errors: [], stats: { expected: 0, unexpected: 1, skipped: 0, flaky: 0 }, suites: [{ specs: [{ title: p.PREFLIGHT_TITLE, tests: [{ expectedStatus: 'passed', status: 'unexpected', results: [{ status: 'failed', retry: 0, errors: [{ message: 'C112_DUMMY_FAILURE_EXPECTED' }] }] }] }] }] };
  assert.equal(p.preflightOutcome(oldReport, 1, f.expected.run_id), false);
  oldReport.config.metadata.frontend_sha = c.FRONTEND_SHA;
  assert.equal(p.preflightOutcome(oldReport, 1, f.expected.run_id), true);
});
test('canonical minute-only UTC+5 UI dates retain the exact UTC interval', () => {
  assert.deepEqual(c.LOCAL_PERIOD, { start: '2026-07-01T05:00', end: '2026-10-01T05:00' });
  assert.deepEqual(c.PERIOD, { start: '2026-07-01T00:00:00Z', end: '2026-10-01T00:00:00Z' });
  for(const key of ['start','end']) assert.equal(Date.parse(c.LOCAL_PERIOD[key]+'+05:00'),Date.parse(c.PERIOD[key]));
  gate.validatePeriod({...c.PERIOD,display_timezone:'Asia/Almaty'});
  assert.throws(()=>gate.validatePeriod({start:'2026-06-30T19:00:00Z',end:'2026-09-30T19:00:00Z',display_timezone:'Asia/Almaty'}));
});
test('real journey checks both normalized date fields after filling and before loading analytics', () => {
  const source = fs.readFileSync(path.join(__dirname, 'c112_analytics.spec.cjs'), 'utf8');
  assert.match(source, /const periodStart = scope\.getByLabel\('Начало периода', \{ exact: true \}\);/);
  assert.match(source, /const periodEnd = scope\.getByLabel\('Конец периода \(не включён\)', \{ exact: true \}\);/);
  assert.match(source, /await periodStart\.fill\(c\.LOCAL_PERIOD\.start\);\s*checkpoint\(evidence\.diagnostics, 'FILL_PERIOD_END'\);\s*await periodEnd\.fill\(c\.LOCAL_PERIOD\.end\);\s*await expect\(periodStart\)\.toHaveValue\(c\.LOCAL_PERIOD\.start\);\s*await expect\(periodEnd\)\.toHaveValue\(c\.LOCAL_PERIOD\.end\);\s*const result = await uiRead\(master\.page, '\/api\/v1\/analytics\/shift'/);
});
test('gate rejects noncanonical or shifted local UI period evidence', () => {
  for (const uiPeriod of [
    { start: '2026-07-01T05:00:00', end: '2026-10-01T05:00:00' },
    { start: '2026-07-01T00:00', end: '2026-10-01T00:00' },
    { start: c.LOCAL_PERIOD.start, end: '2026-10-01T05:01' },
  ]) {
    const f = fixture();
    f.evidence.ui_period_utc_plus_5 = uiPeriod;
    assert.throws(() => gate.validate(f.report, f.evidence, f.expected, now), /UTC_UI_PERIOD_BINDING_REQUIRED/);
  }
});
test('wrong wrapper/minimal fixture, scopes, counts, source or live IDs fail closed', () => {
  for(const change of [m=>({fixture:m}),m=>({...m,fixture_version:'dalaai-live-vertical-demo-v1'}),m=>({...m,history_orders:539}),m=>({...m,history_sha256:'0'.repeat(64)}),m=>({...m,historical_actor_state:'active'}),m=>({...m,photos_seeded:444}),m=>({...m,pin:'dummy-never-publish'}),m=>{m.users[0].token='dummy-never-publish';return m;},m=>{m.users[0].section_ids=[];return m;},m=>{m.live_path.executor_id=id(999);return m;}]) assert.throws(()=>c.validateManifest(change(copy(manifest))));
});
test('browser child environment excludes credentials, PIN paths, PG, preload and proxies', () => { assert.deepEqual(c.browserEnvironment({PATH:'/bin',HOME:'/safe',DALA_C112_OBSERVER_DATABASE_URL:'DUMMY',DALA_E2E_MASTER_PIN_FILE:'/private',PGPASSWORD:'DUMMY',NODE_OPTIONS:'--require=bad',HTTP_PROXY:'http://secret',TOKEN:'DUMMY'}),{PATH:'/bin',HOME:'/safe'}); });
test('mandatory proof is checked before public or private inputs', () => { let read=false; assert.throws(()=>c.fixtureFromEnv({DALA_C112_AUTHORIZED:'operator-provisioned-synthetic-only',DALA_C112_WORKERS_DISABLED:'ai,delivery,providers'},()=>{read=true;},()=>{throw Error('blocked');})); assert.equal(read,false); });
test('C112 proof cannot accept C110 receipt, other run/source, stale/future proof or zero failure', () => { const f=fixture(), args=[f.expected.harness_sha,f.expected.source_files,now,c.FRONTEND_SHA,f.expected.run_id]; assert.equal(p.validateProof(f.evidence.secrecy_proof,...args).result,'PASS'); for(const patch of [{version:'c110-failure-output-v2'},{run_id:'c112-another-run-1'},{frontend_sha:'0'.repeat(40)},{source_sha:'0'.repeat(40)},{source_files:{}},{observed_dummy_failures:0},{scanned_outputs:undefined},{scanned_outputs:null},{scanned_outputs:'three'},{scanned_outputs:'3'},{scanned_outputs:Infinity},{scanned_outputs:NaN},{scanned_outputs:33},{sentinel_matches:1},{created_at:new Date(now-31*60_000).toISOString()},{created_at:new Date(now+1).toISOString()}]) assert.throws(()=>p.validateProof({...f.evidence.secrecy_proof,...patch},...args)); });
test('exact one mocked complete result passes pure validator only, never CLI proof', () => { const f=fixture(); assert.equal(gate.validate(f.report,f.evidence,f.expected,now).status,'passed'); });
const failures = {
  missing_db_table:f=>{delete f.evidence.database_before.counts.reviews;}, extra_db_table:f=>{f.evidence.database_before.counts.auth_sessions=2;}, elevated_db_role:f=>{f.evidence.database_before.identity.rolsuper=true;}, writable_tx:f=>{f.evidence.database_before.identity.read_only=false;},
  zero_tests:f=>{f.report.stats.expected=0;f.report.suites=[];}, skipped:f=>{f.report.stats.skipped=1;}, extra_test:f=>{f.report.suites[0].specs.push(copy(f.report.suites[0].specs[0]));}, c110_title:f=>{f.report.suites[0].specs[0].title='C110 real composed master executor lifecycle';}, retry:f=>{f.report.suites[0].specs[0].tests[0].results[0].retry=1;}, expected_failure:f=>{f.report.suites[0].specs[0].tests[0].expectedStatus='failed';}, runner_error:f=>{f.report.errors.push({message:'bad'});}, wrong_project:f=>{f.report.suites[0].specs[0].tests[0].projectName='desktop';}, no_steps:f=>{f.evidence.steps=[];}, stale_run:f=>{f.evidence.run_id='c112-stale-run-0001';}, stale_proof:f=>{f.evidence.secrecy_proof.created_at='2020-01-01T00:00:00Z';}, hash_change:f=>{f.evidence.source_files={};}, no_db:f=>{delete f.evidence.database_before;}, in_memory_db:f=>{f.evidence.database_before.source='mock';}, missing_row:f=>{f.evidence.database_after.counts.orders=539;}, photo_claim:f=>{f.evidence.observations[0].provenance.historical_evidence.physical_evidence_verified=true;}, photos_present:f=>{f.evidence.database_before.counts.photos=444;}, mutable_db:f=>{f.evidence.database_after.business_sha256='0'.repeat(64);}, enabled_actor:f=>{f.evidence.database_before.historical_actors_disabled=false;}, incomplete_scope:f=>{f.evidence.database_before.section_ids=[];}, wrong_api_counts:f=>{f.evidence.observations[0].counts.orders=0;}, missing_shift:f=>{f.evidence.observations.splice(1,1);}, repeated_capture:f=>{f.evidence.observations[1].provenance.source_ref=f.evidence.observations[0].provenance.source_ref;}, unprotected:f=>{f.evidence.observations[0].cache='public';}, ui_unverified:f=>{f.evidence.observations[1].ui_provenance_visible=false;}, guessed_order:f=>{f.evidence.observations[2].order_id=id(10000);}, executor_200:f=>{f.evidence.restrictions[0].status=200;}, executor_ui_visible:f=>{f.evidence.executor_ui_absent=false;}, business_post:f=>{f.evidence.network.business_mutations=1;}, fake_api:f=>{f.evidence.database_before.source='fake_api';}, physical_claim:f=>{f.evidence.separate_gates.physical_android='PASS';}, wrong_period:f=>{f.evidence.period={start:'2026-06-30T19:00:00Z',end:'2026-09-30T19:00:00Z'};}, browser_secret_env:f=>{f.evidence.browser.credential_environment='inherited';}
};
for(const [name,mutate] of Object.entries(failures)) test(`gate rejects ${name}`,()=>{const f=fixture();mutate(f);assert.throws(()=>gate.validate(f.report,f.evidence,f.expected,now));});
test('source binding covers gate, observer, real spec, all preflight/runtime modules and lockfiles',()=>{ for(const file of ['c112_gate.cjs','c112_observe.py','c112_analytics.spec.cjs','c112_contract.cjs','c112_private_boundary.cjs','c112_preflight_proof.cjs','c112_secrecy_preflight.cjs','c112_preflight.config.cjs','c112_preflight.spec.cjs','c112_playwright.config.cjs','package.json','package-lock.json']) assert.ok(p.BOUND_FILES.includes(file)); });
test('real journey has no fake backend, fixture DOM, C110 imports, business post API or TLS bypass',()=>{const s=fs.readFileSync(path.join(__dirname,'c112_analytics.spec.cjs'),'utf8'); for(const forbidden of [/\.fulfill\s*\(/,/\.setContent\s*\(/,/ignoreHTTPSErrors:\s*true/,/context\.request\.(post|put|patch|delete)\s*\(/,/require\(['"]\.\/c110_/]) assert.doesNotMatch(s,forbidden); assert.match(s,/route\.continue\(\)/); assert.match(s,/c112_observe\.py/);});
test('intentional preflight sentinel detection catches raw, escaped and base64 strings',()=>{for(const input of ['DUMMY_PRIVATE',JSON.stringify({x:Buffer.from('DUMMY_PRIVATE').toString('base64')}),'DUMMY_\\u0050RIVATE']) assert.equal(p.containsSentinel(input,['DUMMY_PRIVATE']),true); assert.equal(p.containsSentinel('{"status":"safe"}',['DUMMY_PRIVATE']),false);});
