'use strict';
const fs = require('node:fs'), path = require('node:path');
const c = require('../c113_contract.cjs');
const PRODUCT_SHA = '064a7a3785a95d61d7150e7785ff17db892bc110';
const FRONTEND_SHA = '1594a930de4b9f15d11dd35bbc59e5b4b0b1d964';
const TITLE = 'Isolated original response reader diagnostic';
const DUMMY_TITLE = 'Body probe dummy private output failure';
const PROJECT = 'body-probe-android-chromium';
const EXACT_URL = 'https://localhost:18443/api/v1/reports/shift.pdf?' + new URLSearchParams(c.PERIOD);
function check(value, code) { if (!value) throw new Error(`BODY_PROBE_BLOCKED:${code}`); }
function runId(env = process.env) { check(/^bcp-[a-z0-9-]{8,58}$/.test(env.DALA_BCP_RUN_ID || ''), 'RUN_ID'); return env.DALA_BCP_RUN_ID; }
function validatePublic(env = process.env) {
  check(!env.DEBUG && !env.PWDEBUG && !env.NODE_OPTIONS, 'CAPTURE_OVERRIDE');
  check(env.DALA_BCP_PRODUCT_SHA === PRODUCT_SHA && env.DALA_E2E_FRONTEND_SHA === FRONTEND_SHA, 'PRODUCT_BINDING');
  return runId(env);
}
function privateOutput(env = process.env) { check(path.isAbsolute(env.DALA_BCP_PRIVATE_OUTPUT || ''), 'PRIVATE_OUTPUT'); return env.DALA_BCP_PRIVATE_OUTPUT; }
function runnerUse(env = process.env) { return c.runnerUse(env); }
function validateRunner(config, project, configPath, reportPath) {
  check(config.configFile === configPath && config.workers === 1 && config.forbidOnly && project.retries === 0 && project.repeatEach === 1, 'RUNNER');
  check(c.stable(config.reporter) === c.stable([['list', { printSteps: false }], ['json', { outputFile: reportPath }]]) && c.stable(project.use) === c.stable(runnerUse()), 'CAPTURE_POLICY');
}
function readJson(file, max) { const s = fs.lstatSync(file); check(s.isFile() && !s.isSymbolicLink() && s.size <= max, 'BOUNDED_INPUT'); return JSON.parse(fs.readFileSync(file, 'utf8')); }
function fixture(env = process.env) {
  const proof = require('./proof.cjs').requireProof(env); validatePublic(env);
  check(env.DALA_BCP_AUTHORIZED === 'operator-provisioned-synthetic-only' && env.DALA_BCP_WORKERS_DISABLED === 'ai,delivery,providers', 'ISOLATION');
  check(env.DALA_E2E_BASE_URL === 'https://localhost:18443' && env.DALA_E2E_BACKEND_SHA === PRODUCT_SHA, 'BUILD_ORIGIN');
  const pins = ['MASTER', 'EXECUTOR'].map(role => env[`DALA_E2E_${role}_PIN_FILE`]);
  check(pins.every(p => path.isAbsolute(p || '')) && pins[0] !== pins[1] && path.isAbsolute(env.DALA_E2E_FIXTURE_FILE || '') && !pins.includes(env.DALA_E2E_FIXTURE_FILE), 'INPUT_PATHS');
  check(/^[a-z_][a-z0-9_]{0,62}$/.test(env.DALA_BCP_DATABASE_SCHEMA || '') && !['public', 'information_schema'].includes(env.DALA_BCP_DATABASE_SCHEMA) && !env.DALA_BCP_DATABASE_SCHEMA.startsWith('pg_') && Boolean(env.DALA_BCP_OBSERVER_DATABASE_URL), 'OBSERVER');
  const manifest = readJson(env.DALA_E2E_FIXTURE_FILE, 16384), identities = c.validateManifest(manifest);
  return { ...identities, manifest, proof, origin: env.DALA_E2E_BASE_URL };
}
function claimExecution(env = process.env) {
  const proof = require('./proof.cjs').requireProof(env);
  try { fs.writeFileSync(env.DALA_BCP_PREFLIGHT_RECEIPT + '.execution-claim', JSON.stringify({run_id:runId(env),source_sha:proof.source_sha}) + '\n', {flag:'wx',mode:0o600}); }
  catch { throw new Error('BODY_PROBE_BLOCKED:FRESH_SINGLE_EXECUTION_REQUIRED'); }
}
function readPin(role, env = process.env) {
  require('./proof.cjs').requireProof(env);
  check(env.DALA_BCP_AUTHORIZED === 'operator-provisioned-synthetic-only' && ['master', 'executor'].includes(role), 'PIN_AUTHORITY');
  try { const file = env[`DALA_E2E_${role.toUpperCase()}_PIN_FILE`], s = fs.lstatSync(file); check(s.isFile() && !s.isSymbolicLink() && s.size <= 128, 'PIN_INPUT');
    const pin = fs.readFileSync(file, 'utf8').trim(); check(/^[0-9]{8,32}$/.test(pin), 'PIN_SHAPE'); return pin;
  } catch { throw new Error('BODY_PROBE_BLOCKED:PRIVATE_PIN_UNAVAILABLE'); }
}
function observerEnv(env = process.env) {
  const result = Object.fromEntries(['PATH', 'HOME', 'LANG', 'PYTHONDONTWRITEBYTECODE', 'DALA_BCP_OBSERVER_DATABASE_URL', 'DALA_BCP_DATABASE_SCHEMA'].filter(k => env[k]).map(k => [k, env[k]]));
  result.DALA_C113_AUTHORIZED = 'operator-provisioned-synthetic-only';
  result.DALA_C113_OBSERVER_DATABASE_URL = result.DALA_BCP_OBSERVER_DATABASE_URL; result.DALA_C113_DATABASE_SCHEMA = result.DALA_BCP_DATABASE_SCHEMA;
  delete result.DALA_BCP_OBSERVER_DATABASE_URL; delete result.DALA_BCP_DATABASE_SCHEMA; return result;
}
module.exports = { PRODUCT_SHA, FRONTEND_SHA, TITLE, DUMMY_TITLE, PROJECT, EXACT_URL, check, runId, validatePublic, privateOutput, runnerUse, validateRunner, fixture, claimExecution, readPin, observerEnv };
