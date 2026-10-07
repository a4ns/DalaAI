'use strict';
// A5 invokes after Playwright. Empty, filtered, skipped, flaky and expected-fail
// runs cannot promote this journey to PASS. This is not a browser launcher.
const fs = require('node:fs');
const { FRONTEND_SHA, TITLE, UUID } = require('./c110_contract.cjs');
const REQUIRED_STEPS = [
  'separate authenticated browser contexts',
  'master creates unplanned order through composed UI',
  'executor queue accept start pause resume',
  'incomplete result cannot close and master returns for rework',
  'executor supplies actual upload work code and materials',
  'human closure persists and full event history is visible',
];
function requireFact(value, code) { if (!value) throw new Error(code); }
function allSpecs(suites) { return (suites || []).flatMap(s => [...(s.specs || []), ...allSpecs(s.suites)]); }
function validate(report, evidence) {
  requireFact(report && Array.isArray(report.suites), 'REPORT_MISSING');
  requireFact(Array.isArray(report.errors) && report.errors.length === 0, 'RUNNER_ERRORS_OR_MISSING_ERRORS');
  requireFact(report.stats?.expected === 1 && report.stats.unexpected === 0 && report.stats.flaky === 0 && report.stats.skipped === 0, 'EXACT_ONE_PASS_REQUIRED');
  const specs = allSpecs(report.suites);
  requireFact(specs.length === 1 && specs[0].title === TITLE && specs[0].ok === true, 'REQUIRED_JOURNEY_MISSING_OR_EXTRA');
  requireFact(specs[0].tests?.length === 1, 'ONE_PROJECT_REQUIRED');
  const test = specs[0].tests[0];
  requireFact(test.expectedStatus === 'passed' && test.status === 'expected', 'EXPECTED_FAILURE_OR_NONPASS');
  requireFact(test.results?.length === 1 && test.results[0].status === 'passed' && test.results[0].retry === 0, 'RETRY_SKIP_OR_NONPASS');
  requireFact(!test.results[0].errors?.length, 'TEST_ERRORS');
  requireFact(evidence?.schema_version === 1 && evidence.result === 'PASS' && evidence.test === TITLE, 'EVIDENCE_NONPASS');
  requireFact(evidence.frontend_sha === FRONTEND_SHA && /^[0-9a-f]{40}$/.test(evidence.harness_sha || '') && /^[0-9a-f]{40}$/.test(evidence.backend_sha || ''), 'EXACT_SOURCE_IDENTITIES_REQUIRED');
  requireFact(evidence.steps?.length === REQUIRED_STEPS.length && evidence.steps.every((s, i) => s.name === REQUIRED_STEPS[i] && s.result === 'PASS'), 'INCOMPLETE_STEPS');
  requireFact(evidence.browser?.mode === 'ANDROID_EMULATION' && evidence.browser.contexts === 2 && evidence.browser.mobile === true && evidence.browser.touch === true && evidence.browser.playwright === '1.63.0', 'EMULATION_METADATA_REQUIRED');
  for (const gate of ['physical_android', 'native_camera', 'push_delivery', 'provider_model', 'throttled_mobile_upload_10s', 'report_export']) requireFact(evidence.separate_gates?.[gate] === 'NOT_RUN', 'UNSUPPORTED_EVIDENCE_PROMOTION');
  const commands = evidence.commands;
  const actions = ['create', 'queue', 'accept', 'start', 'pause', 'resume', 'submit', 'review', 'start', 'submit', 'review'];
  requireFact(Array.isArray(commands) && commands.length === actions.length && commands.every((c, i) => c.action === actions[i] && c.version === i + 1 && UUID.test(c.operation_id || '') && UUID.test(c.actor_id || '')), 'COMMAND_CHAIN_INCOMPLETE');
  requireFact(new Set(commands.map(c => c.operation_id)).size === commands.length, 'COMMAND_ID_COLLISION');
  requireFact(JSON.stringify(evidence.business_requests) === JSON.stringify(commands.map(({ action, operation_id, actor_id }) => ({ action, operation_id, actor_id }))), 'EXTRA_OR_MISSING_BUSINESS_REQUEST');
  const db = evidence.database;
  requireFact(db?.source === 'actual_postgresql_read_only' && db.identity?.direct_login === true && db.identity?.read_only === true && db.identity?.isolated_schema === true, 'DB_OBSERVATION_REQUIRED');
  requireFact(db.order?.id === evidence.order_id && UUID.test(evidence.order_id || '') && db.order.status === 'closed' && db.order.version === 11, 'FINAL_PERSISTENCE_MISSING');
  requireFact(db.receipts?.length === commands.length && commands.every(c => db.receipts.filter(r => r.operation_id === c.operation_id && r.actor_id === c.actor_id && r.committed === true).length === 1), 'RECEIPTS_INCOMPLETE');
  requireFact(db.events?.length === 13 && db.submissions?.length === 2 && db.reviews?.length === 2 && db.photos?.length === 1 && db.materials?.length === 1 && db.assessments?.length === 0, 'PERSISTENCE_CHAIN_INCOMPLETE');
  requireFact(db.submissions[0].completeness === 'incomplete' && db.submissions[1].completeness === 'complete' && db.reviews[1].decision === 'close' && db.reviews[1].final_score === null, 'INCOMPLETE_OR_NULL_SCORE_SEMANTICS');
  return test.results[0];
}
function main(args) {
  try {
    requireFact(args.length === 2, 'USAGE_REPORT_JSON_EVIDENCE_JSON');
    const raw = fs.readFileSync(args[1]);
    const result = validate(JSON.parse(fs.readFileSync(args[0], 'utf8')), JSON.parse(raw));
    const attachments = (result.attachments || []).filter(a => a.name === 'c110_evidence' && a.contentType === 'application/json');
    requireFact(attachments.length === 1, 'EVIDENCE_ATTACHMENT_REQUIRED');
    const attached = attachments[0];
    requireFact(attached.body ? Buffer.from(attached.body, 'base64').equals(raw) : attached.path && fs.realpathSync(attached.path) === fs.realpathSync(args[1]), 'EVIDENCE_NOT_BOUND_TO_RUN');
    console.log(JSON.stringify({ status: 'PASS', scope: 'real composed browser/API/PostgreSQL; Android emulation only' }));
    return 0;
  } catch (error) {
    // Avoid arbitrary file/parse errors leaking paths or raw source content.
    const safe = /^[A-Z_]+$/.test(error.message) ? error.message : 'REPORT_OR_EVIDENCE_UNAVAILABLE';
    console.log(JSON.stringify({ status: 'BLOCKED_OR_FAIL', code: safe }));
    return 2;
  }
}
if (require.main === module) process.exitCode = main(process.argv.slice(2));
module.exports = { REQUIRED_STEPS, validate, main };
