'use strict';
// Fail-closed post-run validator, not a launcher and not part of C110's core gate.
const fs = require('node:fs');
const c = require('./c113_contract.cjs');
const p = require('./c113_preflight_proof.cjs');
function validatePeriod(period) {
  c.check(period && Date.parse(period.start) === Date.parse(c.PERIOD.start) && Date.parse(period.end) === Date.parse(c.PERIOD.end) && period.display_timezone === 'Asia/Almaty', 'CANONICAL_UTC_PERIOD_REQUIRED');
}
function validateDatabase(db, manifest) {
  const users = c.validateManifest(manifest), id = db?.identity;
  c.check(db?.schema_version === 1 && db.source === 'actual_postgresql_read_only' && Number.isFinite(Date.parse(db.observed_at)), 'ACTUAL_DB_REQUIRED');
  c.check(id?.direct_login === true && id.read_only === true && id.isolated_schema === true && ['schema_create','rolsuper','rolcreatedb','rolcreaterole','rolbypassrls'].every(k => id[k] === false), 'RESTRICTED_DB_IDENTITY_REQUIRED');
  c.check(db.observer_mode === 'existing_restricted_runtime_login_read_only_transaction', 'READ_ONLY_TRANSACTION_SCOPE_REQUIRED');
  c.check(db.counts && c.stable(Object.keys(db.counts).sort()) === c.stable(['orders','order_events','submissions','reviews','photos','material_writeoffs','ai_assessments','operation_receipts'].sort()), 'COMPLETE_DB_TABLE_PROJECTION_REQUIRED');
  c.check(db.counts?.orders === 540 && db.counts.submissions === 568 && db.counts.photos === 0 && db.after_photo_references === 444 && Object.values(db.counts).every(n => Number.isInteger(n) && n >= 0), 'CANONICAL_DB_COUNTS_REQUIRED');
  c.check(db.historical_actor_count === 17 && db.historical_actors_disabled === true && db.history_sha256 === c.HISTORY_SHA256 && c.HASH.test(db.identity_mapping_sha256 || '') && c.HASH.test(db.business_sha256 || ''), 'DB_HISTORY_PROVENANCE_REQUIRED');
  for (const [key, count] of [['order_ids',540],['submission_ids',568]]) c.check(Array.isArray(db[key]) && db[key].length === count && new Set(db[key]).size === count && db[key].every(id => c.UUID.test(id)) && c.stable(db[key]) === c.stable([...db[key]].sort()), 'DB_IDENTITIES_REQUIRED');
  c.check(c.stable(db.section_ids) === c.stable([...users.master.section_ids].sort()), 'DB_SECTION_SCOPE_MISMATCH');
  c.check(Array.isArray(db.live_users) && db.live_users.length === 2, 'DB_LIVE_IDENTITIES_REQUIRED');
  for (const role of ['master','executor']) {
    const matches = db.live_users.filter(u => u.id === users[role].id), u = matches[0];
    c.check(matches.length === 1 && u.role === role && u.active === true && u.on_shift === true && u.employee_code === users[role].employee_code && c.stable(u.section_ids) === c.stable([...users[role].section_ids].sort()), 'DB_LIVE_SCOPE_MISMATCH');
  }
}
function allSpecs(suites) { return (suites || []).flatMap(s => [...(s.specs || []), ...allSpecs(s.suites)]); }
function validate(report, e, expected, now = Date.now()) {
  c.check(expected?.frontend_sha === c.FRONTEND_SHA && c.SHA.test(expected.harness_sha || '') && c.SHA.test(expected.backend_sha || '') && /^c113-[a-z0-9][a-z0-9-]{7,57}$/.test(expected.run_id || ''), 'EXPLICIT_IDENTITIES_REQUIRED');
  c.check(report && Array.isArray(report.suites) && Array.isArray(report.errors) && report.errors.length === 0, 'REPORT_REQUIRED');
  c.check(report.stats?.expected === 1 && report.stats.unexpected === 0 && report.stats.flaky === 0 && report.stats.skipped === 0, 'EXACT_ONE_PASS_REQUIRED');
  const specs=allSpecs(report.suites), test=specs[0]?.tests?.[0], result=test?.results?.[0];
  c.check(specs.length===1 && specs[0].title===c.TITLE && specs[0].ok===true && specs[0].tests?.length===1 && test.projectName===c.PROJECT,'EXACT_JOURNEY_REQUIRED');
  c.check(test.expectedStatus==='passed' && test.status==='expected' && test.results?.length===1 && result.status==='passed' && result.retry===0 && Array.isArray(result.errors) && result.errors.length===0,'ONE_UNRETRIED_PASS_REQUIRED');
  c.check(e?.schema_version===1 && e.result==='PASS' && e.test===c.TITLE,'PASS_EVIDENCE_REQUIRED');
  for(const k of ['frontend_sha','harness_sha','run_id'])c.check(e[k]===expected[k] && report.config?.metadata?.[k]===expected[k],'REPORT_SOURCE_RUN_BINDING_REQUIRED');
  c.check(e.backend_sha===expected.backend_sha && c.stable(e.source_files)===c.stable(expected.source_files),'SOURCE_HASH_BINDING_REQUIRED');
  p.validateProof(e.secrecy_proof,expected.harness_sha,expected.source_files,now,expected.frontend_sha,expected.run_id);
  const start=Date.parse(e.started_at),end=Date.parse(e.finished_at),proofAt=Date.parse(e.secrecy_proof.created_at);
  c.check(Number.isFinite(start)&&Number.isFinite(end)&&start>=proofAt&&end>=start&&end<=now&&now-start<=30*60000,'FRESH_JOURNEY_REQUIRED');
  c.check(e.steps?.length===c.REQUIRED_STEPS.length&&e.steps.every((row,i)=>row.name===c.REQUIRED_STEPS[i]&&row.result==='PASS'),'ALL_STEPS_REQUIRED');
  c.check(e.distinct_secure_sessions===true&&e.browser?.mode==='ANDROID_EMULATION'&&e.browser.engine==='chromium'&&e.browser.profile==='Pixel 7'&&e.browser.playwright==='1.63.0'&&e.browser.contexts===2&&e.browser.mobile===true&&e.browser.touch===true&&e.browser.trusted_tls===true&&e.browser.credential_environment==='excluded_from_browser_process'&&e.browser.service_workers==='blocked','MOBILE_SECURITY_PROFILE_REQUIRED');
  c.check(c.stable(e.period)===c.stable(c.PERIOD)&&c.stable(e.ui_period_utc_plus_5)===c.stable(c.LOCAL_PERIOD),'UTC_UI_PERIOD_BINDING_REQUIRED');
  for(const key of ['c110_lifecycle','c112_analytics','physical_android','native_excel','native_camera','push_delivery','provider_model','live_closure','security_clock_expiry'])c.check(e.separate_gates?.[key]==='NOT_RUN','UNSUPPORTED_PROMOTION_FORBIDDEN');
  c.validateManifest(e.manifest);c.check(e.manifest_sha256===c.digest(e.manifest),'MANIFEST_DIGEST_REQUIRED');
  validateDatabase(e.database_before,e.manifest);validateDatabase(e.database_after,e.manifest);
  const before=e.database_before,after=e.database_after;
  c.check(Date.parse(before.observed_at)>=start&&Date.parse(after.observed_at)>=Date.parse(before.observed_at)&&Date.parse(after.observed_at)<=end,'DB_OBSERVATION_WINDOW_REQUIRED');
  for(const key of ['business_sha256','counts','live_users','order_ids','submission_ids','section_ids','identity_mapping_sha256'])c.check(c.stable(before[key])===c.stable(after[key]),'BUSINESS_DB_UNCHANGED_REQUIRED');
  const clock=require('./c113_clock.cjs'),files=require('./c113_downloads.cjs');
  clock.validateJourney(e.clock,start,end);clock.readAfter(e.clock[5].snapshot,e.clock_after_restriction,0);
  c.check(Date.parse(e.clock_after_restriction.real_now)<=end+2000,'FINAL_CLOCK_REAL_WINDOW_REQUIRED');
  c.check(e.selected&&c.UUID.test(e.selected.order_id||'')&&before.order_ids.includes(e.selected.order_id)&&/^[A-Za-z0-9_-]{1,64}$/.test(e.selected.order_number||'')&&[1,2].includes(e.selected.attempts)&&e.selected.photos===e.selected.attempts,'OBSERVED_ORDER_REQUIRED');
  c.check(e.facts&&c.HASH.test(e.facts.body_sha256||'')&&e.facts.order_ids_sha256===c.digest(before.order_ids)&&e.facts.history_sha256===c.HISTORY_SHA256&&e.facts.identity_mapping_sha256===before.identity_mapping_sha256,'FACTS_DATABASE_BINDING_REQUIRED');
  c.check(Array.isArray(e.downloads)&&e.downloads.length===4,'FOUR_DOWNLOADS_REQUIRED');
  const selected={order:{id:e.selected.order_id,number:e.selected.order_number},attempts:Array.from({length:e.selected.attempts},()=>({submission:{payload:{after_photo_ids:['synthetic']}}}))};
  const matrix=[['shift','pdf'],['shift','xlsx'],['order','pdf'],['order','xlsx']];
  for(const [i,[kind,format]] of matrix.entries())files.validateDownload(e.downloads[i],files.expected(kind,selected),format);
  const targets=[{method:'GET',path:'/api/v1/demo/clock'},{method:'POST',path:'/api/v1/demo/clock'},...e.downloads.map(x=>({method:'GET',path:x.path}))];
  c.check(e.executor_ui_absent===true&&e.restrictions?.length===targets.length&&e.restrictions.every((r,i)=>r.path===targets[i].path&&r.method===targets[i].method&&r.status===403&&r.code==='FORBIDDEN'&&r.no_protected_data===true&&r.cache==='private,no-store'),'EXECUTOR_UI_AND_SERVER_RESTRICTIONS_REQUIRED');
  c.check(c.stable(e.network)===c.stable({blocked_external:0,blocked_mutation:0,login_posts:2,master_clock_posts:3,executor_clock_posts:1,export_gets:4}),'EXACT_NETWORK_COUNTS_REQUIRED');
  return result;
}
function main(args) {
  try {
    c.check(args.length === 2, 'USAGE_REPORT_AND_EVIDENCE');
    c.check(args.every(file => fs.lstatSync(file).isFile() && !fs.lstatSync(file).isSymbolicLink() && fs.statSync(file).size <= 4 * 1024 * 1024), 'BOUNDED_REGULAR_ARTIFACTS_REQUIRED');
    const raw = fs.readFileSync(args[1]), e = JSON.parse(raw), proof = p.requireProof();
    c.check(c.stable(e.secrecy_proof) === c.stable(proof), 'ACTUAL_PREFLIGHT_RECEIPT_REQUIRED');
    const result = validate(JSON.parse(fs.readFileSync(args[0], 'utf8')), e, { frontend_sha: c.selectedFrontendSha(), backend_sha: process.env.DALA_E2E_BACKEND_SHA, harness_sha: p.sourceSha(), source_files: p.fingerprint(), run_id: c.runId() });
    const artifactRoot=require('node:path').dirname(require('node:path').resolve(args[1]));
    c.check(artifactRoot===require('node:path').resolve(c.artifactDir()),'EXACT_ARTIFACT_ROOT_REQUIRED');
    for(const row of e.downloads){
      const filename=require('node:path').join(artifactRoot,`saved-${row.kind}.${row.format}`);
      const stat=fs.lstatSync(filename);c.check(stat.isFile()&&!stat.isSymbolicLink()&&stat.size===row.bytes&&stat.size<=c.MAX_DOWNLOAD_BYTES,'SAVED_ARTIFACT_REQUIRED');
      c.check(require('node:crypto').createHash('sha256').update(fs.readFileSync(filename)).digest('hex')===row.saved_sha256,'SAVED_ARTIFACT_HASH_REQUIRED');
    }
    const attached = (result.attachments || []).filter(a => a.name === 'c113_evidence' && a.contentType === 'application/json');
    c.check(attached.length === 1 && (attached[0].body ? Buffer.from(attached[0].body, 'base64').equals(raw) : attached[0].path && fs.realpathSync(attached[0].path) === fs.realpathSync(args[1])), 'EXACT_RUN_ATTACHMENT_REQUIRED');
    console.log(JSON.stringify({ status: 'PASS', test: c.TITLE, run_id: e.run_id, frontend_sha: e.frontend_sha, backend_sha: e.backend_sha, harness_sha: e.harness_sha, scope: 'four protected GUI downloads and explicit demo-clock cycle; Android emulation only' }));
    return 0;
  } catch (error) {
    const code = /^C113 BLOCKED: ([A-Z0-9_]+)$/.exec(error.message)?.[1] || 'REPORT_OR_PROOF_UNAVAILABLE';
    console.log(JSON.stringify({ status: 'BLOCKED_OR_FAIL', code })); return 2;
  }
}
if (require.main === module) process.exitCode = main(process.argv.slice(2));
module.exports = { validatePeriod, validateDatabase, validate, main };
