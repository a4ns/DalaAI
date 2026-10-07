'use strict';
// Non-secret, fail-closed integration contract. No file containing credentials is read.
const { deflateSync } = require('node:zlib');
const FRONTEND_SHA = 'ca320bf692c01d89dd79496fe18d1bc2742052df';
const TITLE = 'C110 real composed master executor lifecycle';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function check(ok, code) { if (!ok) throw new Error(`C110 BLOCKED: ${code}`); }
const fs = require('node:fs');
function selectedFrontendSha(env = process.env) {
  check(env.DALA_E2E_FRONTEND_SHA === FRONTEND_SHA, 'explicit reviewed frontend SHA required');
  return env.DALA_E2E_FRONTEND_SHA;
}
function fixtureFromEnv(env = process.env, readPublicFile = file => fs.readFileSync(file, 'utf8'), verifyProof = require('./c110_preflight_proof.cjs').requireProof) {
  check(env.DALA_C110_AUTHORIZED === 'operator-provisioned-synthetic-only', 'operator fixture authorization required');
  check(!env.DEBUG && !env.PWDEBUG && !env.NODE_OPTIONS, 'debug/preload capture must be disabled');
  verifyProof(env);
  const frontendSha = selectedFrontendSha(env);
  let publicFixture;
  try { publicFixture = JSON.parse(readPublicFile(env.DALA_E2E_FIXTURE_FILE)); } catch { check(false, 'public synthetic fixture JSON required'); }
  check(publicFixture?.fixture_version === 'dalaai-live-vertical-demo-v1' && publicFixture.data_classification === 'synthetic demo only', 'accepted synthetic fixture version required');
  check(Array.isArray(publicFixture.users), 'fixture users required');
  const f = { schema_version: 1, synthetic: true, frontend_sha: frontendSha,
    backend_sha: env.DALA_E2E_BACKEND_SHA, run_id: env.DALA_C110_RUN_ID,
    origin: env.DALA_E2E_BASE_URL };
  check(/^[0-9a-f]{40}$/.test(f.backend_sha || ''), 'exact backend SHA required');
  check(/^[a-z0-9][a-z0-9-]{7,63}$/.test(f.run_id || ''), 'unique non-secret run ID required');
  check(env.DALA_C110_WORKERS_DISABLED === 'ai,delivery,providers', 'AI/provider/delivery workers must be disabled');
  let origin;
  try { origin = new URL(f.origin); } catch { check(false, 'loopback HTTPS origin required'); }
  check(origin.origin === 'https://localhost:18443', 'accepted loopback HTTPS origin required');
  check(!origin.username && !origin.password && origin.pathname === '/' && !origin.search && !origin.hash, 'origin must contain no credentials/path/query');
  f.origin = origin.origin;
  const acceptedUsers = { master: ['8d27067c-4e86-50a2-87c4-f1012f53a2bb', 'DALA-DEMO-MASTER'], executor: ['37baa480-be02-54bc-837c-6c0b2a00ec12', 'DALA-DEMO-EXECUTOR'] };
  const acceptedDicts = { section: '6907df3e-d9e3-53e2-aa91-c874b453d960', equipment: '2348bd85-4627-542e-8638-1a7297e4e6c5', work_code: 'e7c29005-c026-5017-adcc-2292434500b8', material: '92444401-f0ee-56f3-b49b-3d329f50f54d' };
  for (const [key, id] of Object.entries(acceptedDicts)) {
    check(publicFixture[key]?.id === id, `${key} accepted fixture UUID required`);
    f[`${key}_id`] = id;
  }
  for (const role of ['master', 'executor']) {
    const users = publicFixture.users.filter(user => user.role === role);
    check(users.length === 1, `exactly one synthetic ${role} required`);
    f[role] = users[0];
    check(f[role].id === acceptedUsers[role][0] && f[role].employee_code === acceptedUsers[role][1], `${role} accepted identity required`);
    check(Array.isArray(f[role].section_ids) && f[role].section_ids.includes(f.section_id) && (role !== 'executor' || f[role].on_shift === true), `${role} fixture scope and shift required`);
    check(typeof env[`DALA_E2E_${role.toUpperCase()}_PIN_FILE`] === 'string' && env[`DALA_E2E_${role.toUpperCase()}_PIN_FILE`].length > 0, `${role} operator PIN path missing`);
  }
  check(/^[a-z_][a-z0-9_]{0,62}$/.test(env.DALA_C110_DATABASE_SCHEMA || '') && env.DALA_C110_DATABASE_SCHEMA !== 'public', 'isolated schema required');
  check(Boolean(env.DALA_C110_OBSERVER_DATABASE_URL), 'restricted DB observer environment missing');
  return f;
}
function readOperatorPin(role, env = process.env, readPrivateFile = file => fs.readFileSync(file, 'utf8')) {
  check(env.DALA_C110_AUTHORIZED === 'operator-provisioned-synthetic-only' && ['master', 'executor'].includes(role), 'authorized A5 runner required');
  require('./c110_preflight_proof.cjs').requireProof(env);
  // Called only by the authorized A5 test runner, never source/unit checks here.
  try {
    const pin = readPrivateFile(env[`DALA_E2E_${role.toUpperCase()}_PIN_FILE`]).trim();
    check(/^[0-9]{4,64}$/.test(pin), 'operator PIN format');
    return pin;
  } catch { throw new Error('C110 BLOCKED: operator PIN input unavailable; details suppressed'); }
}
function validateEffectiveRunner(config, project, configFile, reportFile) {
  check(config.configFile === configFile, 'the reviewed C110 config must be used');
  check(config.workers === 1 && project.retries === 0 && project.repeatEach === 1, 'one worker, zero retries and one repeat required');
  const reporters = config.reporter;
  check(reporters?.length === 2 && reporters[0][0] === 'list' && reporters[1][0] === 'json' &&
    JSON.stringify(reporters[0][1]) === JSON.stringify({ printSteps: false }) &&
    JSON.stringify(reporters[1][1]) === JSON.stringify({ outputFile: reportFile }),
    'effective reporters must match the preflight protection profile');
  const allowed = { browserName: 'chromium', ignoreHTTPSErrors: false, trace: 'off', video: 'off', screenshot: 'off', serviceWorkers: 'block' };
  check(project.use && Object.keys(project.use).length === Object.keys(allowed).length &&
    Object.entries(allowed).every(([key, value]) => project.use[key] === value),
    'only reviewed context options allowed; no HAR/logger/auth/launch/connect overrides');
}
function crc32(bytes) {
  let n = 0xffffffff;
  for (const byte of bytes) { n ^= byte; for (let k = 0; k < 8; k++) n = (n >>> 1) ^ (n & 1 ? 0xedb88320 : 0); }
  return (n ^ 0xffffffff) >>> 0;
}
function syntheticPng() {
  const width = 64, height = 64;
  const header = Buffer.alloc(13); header.writeUInt32BE(width, 0); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = 2;
  const rows = Buffer.alloc(height * (1 + width * 3));
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = y * (width * 3 + 1) + 1 + x * 3;
    rows[i] = x * 4; rows[i + 1] = y * 4; rows[i + 2] = (x + y) % 2 ? 180 : 50;
  }
  const chunk = (name, data) => { const type = Buffer.from(name); const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(Buffer.concat([type, data]))); return Buffer.concat([len, type, data, crc]); };
  return Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header), chunk('IDAT', deflateSync(rows)), chunk('IEND', Buffer.alloc(0))]);
}
function dueLocal(now = Date.now()) { return new Date(now + (2 + 5) * 3600_000).toISOString().slice(0, 16); }
module.exports = { FRONTEND_SHA, selectedFrontendSha, TITLE, UUID, check, fixtureFromEnv, readOperatorPin, validateEffectiveRunner, syntheticPng, dueLocal };
