#!/usr/bin/env python3
"""Actual managed image against disposable PostgreSQL and verified loopback TLS.

No hosting, provider calls, browser trust-store changes, raw logs or secrets in
public output. Base DB/bootstrap and the existing HTTPS/photo/export smoke are
reused unchanged. Only this unique disposable project is removed afterwards.
"""
from contextlib import redirect_stdout
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from uuid import uuid4

from fixtures import prepare_private, prepare_tls, write_private

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
ORIGIN = 'https://localhost'
PROJECT = re.compile(r'dalaai-managed-ci-[a-f0-9]{16}')


class GateFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise GateFailure(code)


def clean_environment():
    keep = {'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'CI', 'SYSTEMROOT', 'COMSPEC'}
    result = {key: value for key, value in os.environ.items() if key in keep}
    result['DOCKER_HOST'] = 'unix:///var/run/docker.sock'
    result['DOCKER_CONTEXT'] = 'default'
    return result


def command(argv, *, env, timeout=300, code='COMMAND_FAILED', output=False):
    # Spool privately instead of retaining unbounded build logs or printing them.
    with tempfile.TemporaryFile() as capture:
        try:
            result = subprocess.run(argv, cwd=ROOT, env=env, stdout=capture,
                                    stderr=capture, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            raise GateFailure(code + '_TIMEOUT') from None
        require(result.returncode == 0, code)
        if not output:
            return None
        size = capture.tell()
        require(size <= 2_000_000, 'BOUNDED_COMMAND_OUTPUT_EXCEEDED')
        capture.seek(0)
        return capture.read().decode('utf-8')


def compose_command(project, private):
    require(PROJECT.fullmatch(project), 'INVALID_DISPOSABLE_PROJECT')
    return ['docker', 'compose', '--project-name', project, '--project-directory', str(ROOT / 'ops/demo'),
            '--env-file', str(private / 'env'), '--env-file', str(private / 'workers.env'),
            '-f', str(ROOT / 'ops/demo/compose.yaml'), '-f', str(ROOT / 'ops/demo/compose.workers.yaml'),
            '-f', str(HERE / 'managed_compose.yaml')]


def source_sha(env):
    sha = command(['git', 'rev-parse', 'HEAD'], env=env, output=True, code='SOURCE_SHA_UNAVAILABLE').strip()
    require(re.fullmatch(r'[a-f0-9]{40}', sha), 'SOURCE_SHA_INVALID')
    require(not os.environ.get('GITHUB_SHA') or sha == os.environ['GITHUB_SHA'], 'CHECKOUT_SHA_MISMATCH')
    scopes = ['backend', 'frontend', 'ops', 'scripts/synthetic', '.github/workflows/managed-image-validation.yml']
    command(['git', 'diff', '--quiet', 'HEAD', '--', *scopes], env=env, code='SOURCE_WORKTREE_DIFFERS')
    untracked = command(['git', 'ls-files', '--others', '--exclude-standard', '--', *scopes], env=env,
                        output=True, code='SOURCE_INVENTORY_FAILED')
    require(not untracked.strip(), 'SOURCE_INPUTS_UNTRACKED')
    return sha


def verify_config(config, image):
    services = config['services']
    managed, edge = services['managed'], services['tls-edge']
    require(managed['image'] == image and services['prepare']['image'] == image, 'IMAGE_IDENTITY_MISMATCH')
    require(managed['build']['dockerfile'] == 'ops/managed/Dockerfile', 'WRONG_MANAGED_DOCKERFILE')
    require('command' not in managed and 'entrypoint' not in managed, 'MANAGED_ENTRYPOINT_OVERRIDDEN')
    require(not managed.get('ports') and config['networks']['backend'].get('internal') is True, 'MANAGED_NETWORK_BOUNDARY')
    require(set(managed['networks']) == {'backend'}, 'MANAGED_EGRESS_NOT_ISOLATED')
    ports = edge.get('ports', [])
    require(len(ports) == 1 and ports[0].get('host_ip') == '127.0.0.1'
            and int(ports[0]['published']) == 443 and ports[0]['target'] == 443, 'TLS_NOT_LOOPBACK_ONLY')
    env = managed['environment']
    require(env['DALA_WORKER_NOTIFY_ENABLED'] == 'true' and env['DALA_WEB_PUSH_ENABLED'] == 'false'
            and env['DALA_MODEL_FORCE_OFF'] == 'true', 'CAPABILITY_OR_PROVIDER_FLAGS_MISMATCH')
    require(not env.get('OPENAI_API_KEY') and not env.get('OPENAI_API_KEY_FILE'), 'PROVIDER_KEY_MUST_BE_ABSENT')
    require(not any('OWNER' in key or 'PIN' in key for key in env), 'OWNER_OR_PIN_IN_RUNTIME')
    for name in ('api', 'worker', 'web', 'photo-directory', 'budget-directory'):
        require(services[name].get('profiles') == ['normal-demo-not-run'], 'NORMAL_COMPOSE_RUNTIME_NOT_DISABLED')


def opener(ca):
    context = ssl.create_default_context(cafile=str(ca))
    require(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname, 'TLS_VERIFICATION_DISABLED')
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))


def wait_ready(ca):
    client = opener(ca)
    until = time.monotonic() + 180
    while time.monotonic() < until:
        try:
            with client.open(ORIGIN + '/readyz', timeout=5) as response:
                if response.status == 200 and json.loads(response.read()) == {'status': 'ready'}:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise GateFailure('TRUSTED_HTTPS_READINESS_FAILED')


def auth_boundary(ca, private):
    client = opener(ca)
    def request(path, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(ORIGIN + path, data=data,
              headers={'Content-Type': 'application/json', 'Origin': ORIGIN} | (headers or {}))
        try:
            with client.open(req, timeout=10) as response:
                return response.status, response.headers
        except urllib.error.HTTPError as error:
            return error.code, error.headers
    require(request('/api/v1/me')[0] == 401, 'ANONYMOUS_API_NOT_DENIED')
    body = {'employee_code': 'DALA-DEMO-MASTER', 'pin': (private / 'master_pin').read_text().strip()}
    require(request('/api/v1/auth/login', body, {'Origin': 'https://invalid.example'})[0] == 403,
            'CROSS_ORIGIN_LOGIN_NOT_DENIED')
    status, headers = request('/api/v1/auth/login', body)
    require(status == 200, 'COOKIE_BOUNDARY_LOGIN_FAILED')
    from http.cookies import SimpleCookie
    cookie = SimpleCookie(); cookie.load(headers.get('Set-Cookie', ''))
    require(len(cookie) == 1, 'COOKIE_COUNT_INVALID')
    morsel = next(iter(cookie.values()))
    require(bool(morsel['secure']) and bool(morsel['httponly']) and morsel['samesite'].lower() == 'strict'
            and morsel['path'] == '/' and not morsel['domain'], 'SECURE_COOKIE_FLAGS_INVALID')
    require(request('/api/v1/auth/logout', {}, {'Cookie': morsel.key + '=' + morsel.value})[0] == 403,
            'MISSING_CSRF_NOT_DENIED')


def validate_smoke(data, sha):
    required = {'source_sha': sha, 'status': 'PASS_COMPOSE_PHOTO_CYCLE',
                'AI_worker': 'PASS_PERSISTED_RULES_FALLBACK',
                'clock': 'PASS_SHARED_PAUSE_ADVANCE_CAS_MASTER_ONLY',
                'history': 'PASS_540_CANONICAL_ORDERS_VISIBLE_WITH_MISSING_EVIDENCE_DISCLOSURE',
                'exports': 'PASS_ACTUAL_CONTAINER_PDF_XLSX_MASTER_ONLY'}
    require(all(data.get(key) == value for key, value in required.items()), 'ACTUAL_SMOKE_INCOMPLETE')
    return required


def validate_snapshot(data):
    require(set(data) == {'processes', 'counts', 'physical_photo_count', 'photo_digest', 'record_digest', 'budget'}, 'OBSERVER_SHAPE_INVALID')
    require(data['processes'] == {'api_uid': 10001, 'worker_uid': 10001, 'edge_uid': 10002,
                                'api_loopback_only': True, 'child_secret_scopes': 'PASS'}, 'PROCESS_BOUNDARY_INVALID')
    require(set(data['counts']) == {'orders', 'photos', 'submissions', 'ai_assessments', 'operation_receipts'}
            and all(type(value) is int and value >= 0 for value in data['counts'].values()), 'OBSERVER_COUNTS_INVALID')
    require(data['counts']['orders'] >= 541 and data['physical_photo_count'] >= 1
            and re.fullmatch(r'[a-f0-9]{64}', data['photo_digest'])
            and re.fullmatch(r'[a-f0-9]{64}', data['record_digest']), 'PERSISTED_HISTORY_PHOTO_MISSING')
    require(data['budget'] == {'calls_reserved': 1, 'outcome': 'cancelled', 'actual_billed_cost': None,
                              'reserved_upper_bound_microusd': 100}, 'OFFLINE_BUDGET_RESERVATION_INVALID')
    return data


def run(report):
    for tool in ('docker', 'openssl', 'certutil'):
        if not shutil.which(tool):
            report.update(status='NOT_RUN', stage='runner_tools', blocker='REQUIRED_LOCAL_TOOL_MISSING')
            return
    require(os.environ.get('DALA_MANAGED_DISPOSABLE') == '1', 'EXPLICIT_DISPOSABLE_OPT_IN_REQUIRED')
    env = clean_environment()
    report['source_sha'] = source_sha(env)
    command(['docker', 'info', '--format', '{{.OSType}}'], env=env, code='LOCAL_DOCKER_UNAVAILABLE')
    project = 'dalaai-managed-ci-' + uuid4().hex[:16]
    image = project + ':candidate'
    with tempfile.TemporaryDirectory(prefix='dalaai-managed-ci-') as temp:
        private = Path(temp) / 'private'
        prepare_private(private, credentials=False)
        prepare_tls(private)
        spec = importlib.util.spec_from_file_location('managed_original_prepare', ROOT / 'ops/demo/prepare.py')
        fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        with redirect_stdout(io.StringIO()):
            fixture.prepare(private, 'localhost', '127.0.0.1', 80, 443, workers=True,
                            fixture_mode='history', demo_clock=True)
        write_private(private / 'managed.env', 'DATABASE_URL=' + (private / 'runtime_dsn').read_text().strip()
                      + '\nDALA_WORKER_DATABASE_URL=' + (private / 'worker_dsn').read_text().strip() + '\n')
        env.update(DALA_MANAGED_PRIVATE=str(private), DALA_MANAGED_ROOT=str(ROOT), DALA_MANAGED_IMAGE=image,
                   DALA_MODEL_INSTANCE_ID=(private / 'model_instance').read_text().strip(),
                   DALA_DEMO_CLOCK_INSTANCE_ID=(private / 'clock_instance').read_text().strip(),
                   DALA_DEMO_CLOCK_ENABLED='true', DALA_DEMO_FIXTURE_MODE='history')
        compose = compose_command(project, private)
        started = False
        try:
            report['stage'] = 'compose_configuration'
            config = json.loads(command(compose + ['config', '--format', 'json'], env=env, output=True,
                                        code='COMPOSE_CONFIG_INVALID'))
            verify_config(config, image)
            report['stage'] = 'actual_managed_image_build'
            command(compose + ['build', 'managed'], env=env, timeout=900, code='MANAGED_IMAGE_BUILD_FAILED')
            image_id = command(['docker', 'image', 'inspect', '--format', '{{.Id}}', image], env=env,
                               output=True, code='IMAGE_INSPECT_FAILED').strip()
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', image_id), 'IMAGE_DIGEST_INVALID')
            report['image_id'] = image_id
            report['stage'] = 'actual_caddy_validate'
            started = True
            command(compose + ['run', '--rm', '--no-deps', '-e', 'DALA_PUBLIC_HOST=localhost', 'managed',
                    'caddy', 'validate', '--config', '/service/ops/managed/Caddyfile', '--adapter', 'caddyfile'],
                    env=env, code='IMAGE_CADDY_VALIDATE_FAILED')
            report['stage'] = 'actual_full_profile_startup'
            command(compose + ['up', '--no-build', '--detach', '--wait', '--wait-timeout', '240',
                               'managed', 'tls-edge'], env=env, timeout=420, code='MANAGED_STACK_START_FAILED')
            wait_ready(private / 'tls/root.crt')
            container = command(compose + ['ps', '-q', 'managed'], env=env, output=True, code='CONTAINER_MISSING').strip()
            require(re.fullmatch(r'[a-f0-9]{64}', container), 'CONTAINER_ID_INVALID')
            running_image = command(['docker', 'inspect', '--format', '{{.Image}}', container], env=env,
                                    output=True, code='CONTAINER_IMAGE_INSPECT_FAILED').strip()
            require(running_image == image_id, 'RUNNING_IMAGE_DIFFERS_FROM_BUILT')
            report['stage'] = 'actual_cookie_origin_csrf'
            auth_boundary(private / 'tls/root.crt', private)
            report['auth_boundary'] = 'PASS_TRUSTED_TLS_SECURE_COOKIE_ORIGIN_CSRF'
            report['stage'] = 'existing_photo_rules_clock_history_exports_smoke'
            smoke_file = private / 'smoke.json'
            command([sys.executable, str(ROOT / 'ops/demo/smoke_https.py'), '--base-url', ORIGIN,
                     '--ca-file', str(private / 'tls/root.crt'), '--secrets', str(private), '--report', str(smoke_file),
                     '--source-sha', report['source_sha'], '--expect-rules-worker', '--fixture-mode', 'history',
                     '--expect-demo-clock', 'true'], env=env, timeout=240, code='EXISTING_SMOKE_FAILED')
            report['smoke'] = validate_smoke(json.loads(smoke_file.read_text()), report['source_sha'])
            report['stage'] = 'actual_image_processes_and_persistence'
            probe = compose + ['exec', '-T', '--user', '0:0', 'managed', 'python', '/ci/managed_observe.py']
            before = validate_snapshot(json.loads(command(probe + ['--initialize-budget'], env=env, output=True,
                                                           code='INITIAL_OBSERVER_FAILED')))
            command(compose + ['restart', '--timeout', '90', 'managed'], env=env, timeout=150, code='RESTART_FAILED')
            wait_ready(private / 'tls/root.crt')
            after = validate_snapshot(json.loads(command(probe, env=env, output=True, code='RESTART_OBSERVER_FAILED')))
            require(before == after, 'PERSISTED_STATE_CHANGED_ON_RESTART')
            report.update(persistence='PASS_DB_PHOTO_OFFLINE_BUDGET_RESERVATION',
                          process_boundary=after['processes'], counts=after['counts'],
                          physical_photo_count=after['physical_photo_count'],
                          offline_ledger='SEPARATE_CI_POLICY_ONE_CANCELLED_RESERVATION_NO_PROVIDER_CALL_NO_BILLED_COST',
                          status='PASS', stage='completed')
        finally:
            if started:
                try:
                    command(compose + ['down', '--volumes', '--remove-orphans', '--timeout', '90'],
                            env=env, timeout=180, code='DISPOSABLE_CLEANUP_FAILED')
                    report['cleanup'] = 'PASS_OWN_DISPOSABLE_PROJECT_REMOVED'
                except Exception:
                    report.update(cleanup='FAIL', status='FAIL', blocker='DISPOSABLE_CLEANUP_FAILED')
            try:
                command(['docker', 'image', 'rm', image], env=env, code='IMAGE_CLEANUP_FAILED')
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=Path('managed-image-summary.json'))
    args = parser.parse_args()
    require(not args.report.exists(), 'REPORT_MUST_BE_FRESH')
    report = {'status': 'FAIL', 'scope': 'ACTUAL_MANAGED_IMAGE_DISPOSABLE_TLS_POSTGRES',
              'source_sha': None, 'stage': 'preflight', 'provider_calls': 'NOT_RUN_DISABLED',
              'hosted_render': 'NOT_RUN', 'real_android': 'NOT_RUN', 'mixed_load_capacity': 'NOT_RUN'}
    try:
        run(report)
    except GateFailure as error:
        report['blocker'] = str(error)
    except Exception:
        report['blocker'] = 'UNEXPECTED_GATE_ERROR'
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, sort_keys=True))
    return 0 if report['status'] == 'PASS' else 2 if report['status'] == 'NOT_RUN' else 1


if __name__ == '__main__':
    raise SystemExit(main())
