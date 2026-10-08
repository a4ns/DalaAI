'use strict';
// C113 is a read-only history journey, independent of C110's lifecycle gate.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const FRONTEND_SHA = 'c219957c0ea8abe8c1c3291c66117074de380946';
const TITLE = 'C113 real protected downloads and demo clock';
const PROJECT = 'c113-android-chromium';
const HISTORY_SHA256 = '7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1';
const HISTORY_SOURCE = '8af3897f03aa2f41f0af07ec74ec2c807a4a535a';
const PERIOD = { start: '2026-07-01T00:00:00Z', end: '2026-10-01T00:00:00Z' };
// datetime-local normalizes zero seconds away; fill its canonical minute form.
const LOCAL_PERIOD = { start: '2026-07-01T05:00', end: '2026-10-01T05:00' };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[0-9a-f]{40}$/;
const HASH = /^[0-9a-f]{64}$/;
const REQUIRED_STEPS = ['fresh history database corroborated', 'separate authenticated mobile sessions',
  'master explicitly reads pauses advances and resumes demo clock', 'master selects canonical historical reports',
  'master saves protected shift PDF and XLSX', 'master saves protected order PDF and XLSX',
  'executor cannot access clock or exports', 'business database unchanged'];
const ADVANCE_SECONDS = 60;
const MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024;
function check(ok, code) { if (!ok) throw new Error(`C113 BLOCKED: ${code}`); }
function stable(value) { return JSON.stringify(value, function (_, v) { return v && typeof v === 'object' && !Array.isArray(v) ? Object.fromEntries(Object.keys(v).sort().map(k => [k, v[k]])) : v; }); }
function digest(value) { return createHash('sha256').update(stable(value)).digest('hex'); }
function selectedFrontendSha(env = process.env) { check(env.DALA_E2E_FRONTEND_SHA === FRONTEND_SHA, 'REVIEWED_FRONTEND_REQUIRED'); return FRONTEND_SHA; }
function runId(env = process.env) { check(/^c113-[a-z0-9][a-z0-9-]{7,57}$/.test(env.DALA_C113_RUN_ID || ''), 'DISTINCT_C113_RUN_ID_REQUIRED'); return env.DALA_C113_RUN_ID; }
function artifactDir(env = process.env) { return path.join(__dirname, 'c113_artifacts', runId(env)); }
function browserEnvironment(env = process.env) {
  // Playwright otherwise passes every Node environment variable to Chromium.
  return Object.fromEntries(['PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR', 'DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR'].filter(k => env[k]).map(k => [k, env[k]]));
}
function validateManifest(m) {
  const keys = ['fixture_version','fixture_mode','synthetic','history_sha256','history_orders','history_period_utc','historical_actor_count','historical_actor_state','historical_photos','watermark','users','live_path','live_orders_seeded','sessions_seeded','photos_seeded','credentials','repeat'];
  check(m && stable(Object.keys(m).sort()) === stable(keys.sort()), 'EXACT_PUBLIC_MANIFEST_KEYS_REQUIRED');
  check(m.credentials === 'Operator-supplied distinct private PINs; no generated or printed credentials' && m.repeat === 'verify_only_no_import_no_scope_repair_no_pin_reset', 'PUBLIC_MANIFEST_DISCLOSURE_REQUIRED');
  check(m?.fixture_version === 'dalaai-canonical-history-live-demo-v1' && m.fixture_mode === 'history' && m.synthetic === true, 'HISTORY_PUBLIC_MANIFEST_REQUIRED');
  check(m.history_sha256 === HISTORY_SHA256 && m.history_orders === 540 && stable(m.history_period_utc) === stable(Object.values(PERIOD)), 'CANONICAL_HISTORY_REQUIRED');
  check(m.historical_actor_count === 17 && m.historical_actor_state === 'disabled_no_login' && m.historical_photos === 'metadata_only_no_image_bytes_no_file_valid_claim', 'HISTORICAL_RESTRICTIONS_REQUIRED');
  check(m.watermark === 'Синтетические данные — не история предприятия' && m.live_orders_seeded === 0 && m.photos_seeded === 0 && m.sessions_seeded === 0, 'FRESH_SYNTHETIC_MANIFEST_REQUIRED');
  check(Array.isArray(m.users) && m.users.length === 2, 'TWO_LIVE_IDENTITIES_REQUIRED');
  const result = {};
  for (const role of ['master', 'executor']) {
    const users = m.users.filter(u => u.role === role);
    check(users.length === 1, 'UNIQUE_ROLE_REQUIRED');
    const u = users[0];
    check(stable(Object.keys(u).sort()) === stable(['id','employee_code','role','section_ids','on_shift'].sort()), 'PUBLIC_USER_FIELDS_ONLY');
    check(UUID.test(u.id) && u.employee_code === `DALA-DEMO-${role.toUpperCase()}` && u.on_shift === true && Array.isArray(u.section_ids) && u.section_ids.every(id => UUID.test(id)) && new Set(u.section_ids).size === u.section_ids.length && u.section_ids.length === (role === 'master' ? 4 : 1), 'MANIFEST_SCOPE_REQUIRED');
    result[role] = u;
  }
  check(result.master.id !== result.executor.id && result.master.section_ids.includes(result.executor.section_ids[0]), 'MANIFEST_IDENTITIES_DISTINCT');
  check(m.live_path && stable(Object.keys(m.live_path).sort()) === stable(['section_id','equipment_id','executor_id','work_code_id','material_id'].sort()) && ['section_id','equipment_id','executor_id','work_code_id','material_id'].every(k => UUID.test(m.live_path[k])) && m.live_path.section_id === result.executor.section_ids[0] && m.live_path.executor_id === result.executor.id, 'LIVE_PATH_BINDING_REQUIRED');
  return result;
}
function fixtureFromEnv(env = process.env, read = file => { const stat = fs.lstatSync(file); check(stat.isFile() && !stat.isSymbolicLink() && stat.size <= 16_384, 'BOUNDED_PUBLIC_MANIFEST_REQUIRED'); return fs.readFileSync(file, 'utf8'); }, verify = require('./c113_preflight_proof.cjs').requireProof) {
  check(env.DALA_C113_AUTHORIZED === 'operator-provisioned-synthetic-only' && env.DALA_C113_WORKERS_DISABLED === 'ai,delivery,providers', 'ISOLATED_AUTHORIZATION_REQUIRED');
  check(!env.DEBUG && !env.PWDEBUG && !env.NODE_OPTIONS, 'CAPTURE_OVERRIDE_FORBIDDEN');
  const proof = verify(env), frontend_sha = selectedFrontendSha(env), run_id = runId(env);
  check(SHA.test(env.DALA_E2E_BACKEND_SHA || ''), 'EXACT_BACKEND_REQUIRED');
  check(env.DALA_E2E_BASE_URL === 'https://localhost:18443', 'EXACT_TRUSTED_LOOPBACK_ORIGIN_REQUIRED');
  const privatePaths = ['DALA_E2E_MASTER_PIN_FILE','DALA_E2E_EXECUTOR_PIN_FILE'].map(k => env[k]);
  check(privatePaths.every(p => typeof p === 'string' && path.isAbsolute(p)) && privatePaths[0] !== privatePaths[1], 'DISTINCT_OPERATOR_PIN_PATHS_REQUIRED');
  check(path.isAbsolute(env.DALA_E2E_FIXTURE_FILE || '') && !privatePaths.includes(env.DALA_E2E_FIXTURE_FILE), 'PUBLIC_MANIFEST_PATH_REQUIRED');
  let manifest; try { manifest = JSON.parse(read(env.DALA_E2E_FIXTURE_FILE)); } catch { check(false, 'PUBLIC_MANIFEST_UNAVAILABLE'); }
  const identities = validateManifest(manifest);
  check(/^[a-z_][a-z0-9_]{0,62}$/.test(env.DALA_C113_DATABASE_SCHEMA || '') && env.DALA_C113_DATABASE_SCHEMA !== 'public' && !env.DALA_C113_DATABASE_SCHEMA.startsWith('pg_') && env.DALA_C113_DATABASE_SCHEMA !== 'information_schema', 'ISOLATED_SCHEMA_REQUIRED');
  check(Boolean(env.DALA_C113_OBSERVER_DATABASE_URL), 'RESTRICTED_OBSERVER_REQUIRED');
  return { ...identities, manifest, manifest_sha256: digest(manifest), proof, frontend_sha, backend_sha: env.DALA_E2E_BACKEND_SHA, run_id, origin: env.DALA_E2E_BASE_URL };
}
function readOperatorPin(role, env = process.env) {
  check(env.DALA_C113_AUTHORIZED === 'operator-provisioned-synthetic-only' && ['master','executor'].includes(role), 'AUTHORIZED_RUNNER_REQUIRED');
  require('./c113_preflight_proof.cjs').requireProof(env);
  try { const pin = fs.readFileSync(env[`DALA_E2E_${role.toUpperCase()}_PIN_FILE`], 'utf8').trim(); check(/^[0-9]{8,32}$/.test(pin), 'PIN_FORMAT'); return pin; }
  catch { throw new Error('C113 BLOCKED: operator PIN unavailable; details suppressed'); }
}
function runnerUse(env = process.env) { return { browserName: 'chromium', ignoreHTTPSErrors: false, trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block', launchOptions: { env: browserEnvironment(env) } }; }
function validateEffectiveRunner(config, project, configFile, reportFile) {
  check(config.configFile === configFile && config.workers === 1 && project.retries === 0 && project.repeatEach === 1 && config.forbidOnly === true, 'REVIEWED_SINGLE_RUN_REQUIRED');
  check(stable(config.reporter) === stable([['list', { printSteps: false }], ['json', { outputFile: reportFile }]]), 'REVIEWED_REPORTERS_REQUIRED');
  check(stable(project.use) === stable(runnerUse()), 'REVIEWED_CAPTURE_AND_BROWSER_ENV_REQUIRED');
}
function historicalCounts(p, orders = 540, submissions = 568, photos = 444) {
  const h = p?.historical_evidence;
  check(p?.synthetic === true && p.coverage === 'consistent_snapshot' && p.history_complete === true && /^runtime-postgres:[0-9a-f-]{36}$/.test(p.source_ref || '') && Number.isFinite(Date.parse(p.domain_as_of)) && Number.isFinite(Date.parse(p.captured_at_real)), 'ACTUAL_RUNTIME_PROVENANCE_REQUIRED');
  check(h?.status === 'synthetic_historical_evidence_unavailable' && h.historical_order_count === orders && h.historical_submission_count === submissions && h.historical_after_photo_reference_count === photos && h.missing_after_photo_row_count === photos, 'HISTORICAL_COUNTS_REQUIRED');
  check(h.physical_evidence_verified === false && h.historical_completeness_is_verified_evidence === false && h.source_commit === HISTORY_SOURCE && h.history_sha256 === HISTORY_SHA256 && h.loader_version === '1.1.0' && HASH.test(h.identity_mapping_sha256 || ''), 'UNAVAILABLE_PHOTO_PROVENANCE_REQUIRED');
  return h;
}
module.exports = { FRONTEND_SHA,TITLE,PROJECT,HISTORY_SHA256,HISTORY_SOURCE,PERIOD,LOCAL_PERIOD,UUID,SHA,HASH,REQUIRED_STEPS,ADVANCE_SECONDS,MAX_DOWNLOAD_BYTES,check,stable,digest,selectedFrontendSha,runId,artifactDir,browserEnvironment,validateManifest,fixtureFromEnv,readOperatorPin,runnerUse,validateEffectiveRunner,historicalCounts };
