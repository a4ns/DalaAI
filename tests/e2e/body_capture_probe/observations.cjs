'use strict';
const k = require('./contract.cjs'), c = require('../c113_contract.cjs');
const REASONS = ['NOT_ARMED','AWAITING_EXACT_REQUEST','AWAITING_ORIGINAL_RESPONSE','AWAITING_CLIENT_READER','DIGEST_PENDING','EOF_EXACT_LENGTH',
  'OBSERVER_FAILED','RESTORE_FAILED','TRUNCATED','DIGEST_FAILED','DIGEST_TIMEOUT','READ_THROW','UNSUPPORTED_READ','CONCURRENT_READ','INVALID_READ_RESULT','INVALID_CHUNK','OVERFLOW','READ_REJECTED','CANCEL_THROW','CLIENT_CANCELLED','RESPONSE_BINDING_FAILED','HEADERS_OR_LENGTH_FAILED','READER_THROW','UNSUPPORTED_READER','UNARMED_REQUEST','DUPLICATE_REQUEST','REQUEST_BINDING_FAILED','FETCH_THROW','FETCH_REJECTED','CAPABILITY_REJECTED','ARM_REPLAY','READ_TIMEOUT'];
const KEYS = ['scope','source_sha','run_id','state','reason','comparability','fetches','readers','reads','declared_bytes','observed_bytes','eof','sha256','retained_capture_bytes','disposed'];
function validateClient(value, sha, run) {
  k.check(value && c.stable(Object.keys(value).sort()) === c.stable([...KEYS].sort()), 'CLIENT_SCHEMA');
  k.check(value.scope === 'INSTRUMENTED_DIAGNOSTIC_ONLY' && value.source_sha === sha && value.run_id === run &&
    ['IDLE','ARMED','FETCHING','READING','HASHING','COMPLETE','NOT_COMPARABLE'].includes(value.state) && REASONS.includes(value.reason) &&
    ['COMPARABLE','NOT_COMPARABLE'].includes(value.comparability) && typeof value.eof === 'boolean' && typeof value.disposed === 'boolean', 'CLIENT_BINDING');
  for (const field of ['fetches','readers','reads','declared_bytes','observed_bytes','retained_capture_bytes']) k.check(Number.isSafeInteger(value[field]) && value[field] >= 0 && value[field] <= 8 * 1024 * 1024, 'CLIENT_BOUNDS');
  k.check(value.sha256 === null || /^[0-9a-f]{64}$/.test(value.sha256), 'CLIENT_HASH');
  if (value.comparability === 'COMPARABLE') k.check(value.state === 'COMPLETE' && value.reason === 'EOF_EXACT_LENGTH' && value.eof && value.declared_bytes > 0 && value.declared_bytes === value.observed_bytes && value.fetches === 1 && value.readers === 1 && value.retained_capture_bytes === 0 && /^[0-9a-f]{64}$/.test(value.sha256), 'COMPLETE_CLIENT_REQUIRED');
  return value;
}
function originalBinding(page, nonce) {
  let armed = false, selected = null, count = 0, failed = false, responseBound = false, finished = false;
  return {
    arm(capability) { k.check(!armed && !finished && capability === nonce, 'NODE_ARM'); armed = true; },
    allow(request) {
      const u = new URL(request.url());
      if (!/\/reports\/.+\.(pdf|xlsx)$/.test(u.pathname)) return true;
      count++;
      if (!armed || finished || count !== 1 || request.url() !== k.EXACT_URL || request.method() !== 'GET' ||
          request.resourceType() !== 'fetch' || request.frame() !== page.mainFrame() || request.redirectedFrom() || request.redirectedTo()) { failed = true; return false; }
      selected = request; return true;
    },
    bind(response) { responseBound = !failed && selected === response.request() && response.url() === k.EXACT_URL && !response.fromServiceWorker() && !selected.redirectedFrom() && !selected.redirectedTo(); k.check(responseBound, 'ORIGINAL_REQUEST_IDENTITY'); },
    finish() { finished = true; },
    snapshot() { return { armed, matching_requests: count, exact_request_bound: responseBound, invalid: failed }; },
    requireBound() { k.check(armed && count === 1 && responseBound && !failed, 'ONE_ORIGINAL_REQUEST'); },
  };
}
function interpretation(cdp, client, saved, binding, authority) {
  if (!binding || !binding.armed || binding.invalid || !binding.exact_request_bound || binding.matching_requests !== 1) return 'INVALID_BINDING';
  if (!client || client.comparability !== 'COMPARABLE') return 'CLIENT_OBSERVATION_NOT_COMPARABLE';
  if (authority !== 'VERIFIED') return 'AUTHORITY_NOT_ESTABLISHED';
  if (saved.status !== 'VERIFIED') return 'SAVED_FILE_NOT_VERIFIED';
  if (saved.sha256 !== client.sha256 || saved.bytes !== client.observed_bytes) return 'CLIENT_SAVED_MISMATCH';
  if (cdp.status === 'FAILED') return 'CDP_UNAVAILABLE_CLIENT_AND_SAVE_VERIFIED_INSTRUMENTED';
  if (cdp.status === 'OK' && cdp.sha256 === saved.sha256 && cdp.bytes === saved.bytes && saved.cdp_exact_equality === 'EQUAL') return 'THREE_OBSERVATIONS_AGREE_INSTRUMENTED';
  return 'CDP_SAVED_MISMATCH';
}
module.exports = { REASONS, KEYS, validateClient, originalBinding, interpretation };
const INTERPRETATIONS = ['NOT_ESTABLISHED','INVALID_BINDING','CLIENT_OBSERVATION_NOT_COMPARABLE','AUTHORITY_NOT_ESTABLISHED','SAVED_FILE_NOT_VERIFIED','CLIENT_SAVED_MISMATCH','CDP_UNAVAILABLE_CLIENT_AND_SAVE_VERIFIED_INSTRUMENTED','THREE_OBSERVATIONS_AGREE_INSTRUMENTED','CDP_SAVED_MISMATCH'];
function exactKeys(value, keys) { k.check(value && c.stable(Object.keys(value).sort()) === c.stable([...keys].sort()), 'EXACT_SAFE_FIELDS'); }
function validateEvidence(e, proof) {
  exactKeys(e,['schema_version','scope','c113_acceptance','status','source_sha','product_sha','frontend_sha','source_files','run_id','baseline_failed_run','baseline_failed_job','phase','cdp','client','binding','request_before','request_after','ui_at_save','ui_before','ui_after','saved','authority','database_unchanged','interpretation','cleanup','timing_effect','raw_artifacts']);
  k.check(e.schema_version===1 && e.scope==='INSTRUMENTED_DIAGNOSTIC_ONLY' && e.c113_acceptance==='NOT_ESTABLISHED' && ['DIAGNOSTIC_COMPLETE','INCONCLUSIVE','BLOCKED'].includes(e.status) && e.source_sha===proof.source_sha && e.run_id===proof.run_id && e.product_sha===k.PRODUCT_SHA && e.frontend_sha===k.FRONTEND_SHA && c.stable(e.source_files)===c.stable(proof.source_files) && e.baseline_failed_run==='37726366034' && e.baseline_failed_job==='113145335028','SAFE_SOURCE_BINDING');
  k.check(['INITIALIZE','READ_DATABASE','CURRENT_SESSIONS','EQUIVALENT_CLOCK_SEQUENCE','CANONICAL_REPORT','ARM_ORIGINAL_REQUEST','ORIGINAL_CDP_BODY','CLIENT_OBSERVATION','ACTUAL_SAVE','ACTUAL_CONTENT_INSPECTION','CURRENT_AUTHORIZATION','FINAL_CORROBORATION','DONE'].includes(e.phase) && INTERPRETATIONS.includes(e.interpretation) && ['NOT_ESTABLISHED','VERIFIED'].includes(e.authority) && typeof e.database_unchanged==='boolean','SAFE_ENUMS');
  k.check(['OWN_CAPTURE_DISPOSED_CONTEXTS_CLOSED','CONTEXTS_CLOSED_TAP_DISPOSAL_UNCONFIRMED','CONTEXT_CLOSURE_UNCONFIRMED'].includes(e.cleanup) && e.timing_effect==='EXTRA_PROMISE_OBSERVERS_AND_BYTE_COPIES' && e.raw_artifacts==='PRIVATE_DELETE_AFTER_RUN','SAFE_LIMITS');
  for(const key of ['ui_before','ui_after','ui_at_save'])k.check(['NOT_OBSERVED','READY','ERROR','LOADING','EXPIRED'].includes(e[key]),'SAFE_UI');
  for(const key of ['request_before','request_after'])if(e[key]!==null){exactKeys(e[key],['completion','failure_present']);k.check(['NOT_OBSERVED','FINISHED','FAILED'].includes(e[key].completion)&&typeof e[key].failure_present==='boolean','SAFE_REQUEST');}
  exactKeys(e.cdp,['status','failure','bytes','sha256']);
  k.check(['NOT_RUN','OK','FAILED'].includes(e.cdp.status)&&['NOT_OBSERVED','TIMEOUT','TARGET_CLOSED','BODY_UNAVAILABLE','BODY_PROTOCOL_FAILURE','OTHER'].includes(e.cdp.failure),'SAFE_CDP');
  if(e.cdp.status==='OK')k.check(Number.isInteger(e.cdp.bytes)&&e.cdp.bytes>0&&e.cdp.bytes<=c.MAX_DOWNLOAD_BYTES&&c.HASH.test(e.cdp.sha256||''),'SAFE_CDP_BYTES');
  else k.check(e.cdp.bytes===null&&e.cdp.sha256===null,'NO_SUBSTITUTED_CDP');
  if(e.client!==null)validateClient(e.client,proof.source_sha,proof.run_id);
  if(e.binding!==null){exactKeys(e.binding,['armed','matching_requests','exact_request_bound','invalid']);k.check(['armed','exact_request_bound','invalid'].every(key=>typeof e.binding[key]==='boolean')&&Number.isInteger(e.binding.matching_requests)&&e.binding.matching_requests>=0&&e.binding.matching_requests<=100,'SAFE_BINDING');}
  exactKeys(e.saved,['status','bytes','sha256','cdp_exact_equality','client_hash_equality','content_inspection','no_export_on_save']);
  k.check(['NOT_RUN','NOT_VERIFIED','VERIFIED'].includes(e.saved.status)&&['UNAVAILABLE','EQUAL','MISMATCH'].includes(e.saved.cdp_exact_equality)&&typeof e.saved.client_hash_equality==='boolean'&&typeof e.saved.no_export_on_save==='boolean'&&['NOT_RUN','VERIFIED',...require('../c113_downloads.cjs').INSPECTOR_STAGES].includes(e.saved.content_inspection),'SAFE_SAVED');
  if(e.saved.status==='NOT_RUN')k.check(e.saved.bytes===null&&e.saved.sha256===null,'NO_INVENTED_SAVE');
  else k.check(Number.isInteger(e.saved.bytes)&&e.saved.bytes>0&&e.saved.bytes<=c.MAX_DOWNLOAD_BYTES&&c.HASH.test(e.saved.sha256||''),'SAFE_SAVED_BYTES');
  if(e.cdp.status!=='OK')k.check(e.saved.cdp_exact_equality==='UNAVAILABLE','NO_FALLBACK_EQUALITY');
  if(e.status==='DIAGNOSTIC_COMPLETE')k.check(e.phase==='DONE'&&e.database_unchanged&&e.authority==='VERIFIED'&&e.cleanup==='OWN_CAPTURE_DISPOSED_CONTEXTS_CLOSED'&&e.client?.disposed&&e.saved.content_inspection==='VERIFIED'&&e.saved.client_hash_equality&&e.saved.no_export_on_save&&interpretation(e.cdp,e.client,e.saved,e.binding,e.authority)===e.interpretation&&['CDP_UNAVAILABLE_CLIENT_AND_SAVE_VERIFIED_INSTRUMENTED','THREE_OBSERVATIONS_AGREE_INSTRUMENTED'].includes(e.interpretation),'COMPLETE_DIAGNOSTIC_ONLY');
  return e;
}
module.exports.validateEvidence=validateEvidence;
