'use strict';
// Advisory fixed labels only. No exception, DOM, response body, URL or headers
// are accepted or serialized. These diagnostics never promote acceptance.
const SUBSTEPS = Object.freeze([
  'NOT_STARTED', 'NAVIGATE_ANALYTICS', 'FILL_PERIOD_START', 'FILL_PERIOD_END',
  'WAIT_MATCHING_UI_RESPONSE', 'CHECK_RESPONSE_IDENTITY_STATUS',
  'CHECK_PROTECTED_HEADERS', 'CHECK_CACHE_PRIVATE', 'CHECK_CACHE_NO_STORE',
  'CHECK_VARY_COOKIE', 'CHECK_NOSNIFF', 'CHECK_SERVICE_WORKER_ABSENCE', 'PARSE_RESPONSE_JSON',
  'CHECK_RESPONSE_PERIOD', 'CHECK_HISTORICAL_PROVENANCE', 'CHECK_FACTS_SCHEMA',
  'CHECK_ORDER_COUNT', 'CHECK_API_DATABASE_IDENTITIES', 'CHECK_PHOTO_REFERENCES',
  'SELECT_OBSERVED_HISTORICAL_ORDER', 'WAIT_SYNTHETIC_WATERMARK',
  'WAIT_UNAVAILABLE_PHOTO_NOTICE', 'CHECK_UNAVAILABLE_PHOTO_COUNTS',
  'CHECK_PHYSICAL_EVIDENCE_DISCLOSURE', 'EXPAND_PROVENANCE_DISCLOSURE',
  'CHECK_PROVENANCE_HASHES', 'WAIT_PERIOD_METRICS_HEADING',
  'WAIT_EXECUTOR_METRICS_HEADING', 'CHECK_ISSUED_API_METRIC',
  'CHECK_ISSUED_UI_METRIC', 'RECORD_ANALYTICS_OBSERVATION',
  'OTHER_JOURNEY_STEP', 'UNCLASSIFIED_STEP',
]);
const STATUS = Object.freeze({ 200: 'HTTP_OK', 400: 'HTTP_BAD_REQUEST', 401: 'HTTP_UNAUTHENTICATED',
  403: 'HTTP_FORBIDDEN', 404: 'HTTP_NOT_FOUND', 422: 'HTTP_VALIDATION',
  429: 'HTTP_RATE_LIMITED', 500: 'HTTP_SERVER_ERROR', 502: 'HTTP_GATEWAY_ERROR',
  503: 'HTTP_UNAVAILABLE', 504: 'HTTP_GATEWAY_TIMEOUT' });
function createDiagnostics() { return { substep: 'NOT_STARTED', failure_category: 'NONE', analytics_response: 'NOT_OBSERVED' }; }
function checkpoint(state, label) { state.substep = SUBSTEPS.includes(label) ? label : 'UNCLASSIFIED_STEP'; }
function observeAnalyticsStatus(state, status) {
  state.analytics_response = Number.isInteger(status) && Object.hasOwn(STATUS, status) ? STATUS[status] : 'HTTP_OTHER_OR_UNAVAILABLE';
}
function failDiagnostic(state) { state.failure_category = 'ASSERTION_OR_OPERATION_FAILED'; }
module.exports = { SUBSTEPS, createDiagnostics, checkpoint, observeAnalyticsStatus, failDiagnostic };
