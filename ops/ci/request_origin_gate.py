#!/usr/bin/env python3
"""One source-bound anonymous WebKit request-Origin comparison."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BRANCH = 'refs/heads/validation/request-origin-browser-20261008'
BASELINE = '348b82683b95e4bd20ce2ecbbf980d761e72ae3a'
CASES = ('baseline_no_referrer_origin', 'candidate_post_origin', 'candidate_referrer_privacy',
         'candidate_cookie_csrf', 'same_origin_metadata', 'cross_origin_refused',
         'cross_origin_redirect_refused', 'same_origin_redirect_refused')
OWNED = ['ops/ci/request_origin_' + suffix for suffix in
         ('gate.py', 'probe.cjs', 'tests.py', 'contract.json', 'README.md')]
OWNED.append('.github/workflows/request-origin-browser.yml')


def environment():
    return {k: v for k, v in os.environ.items() if k in
            {'PATH', 'HOME', 'LANG', 'LC_ALL', 'PLAYWRIGHT_BROWSERS_PATH'}}


def command(argv, cwd, env, timeout=20):
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, timeout=timeout, check=False)


def require(condition, code):
    if not condition:
        raise ValueError('REQUEST_ORIGIN_' + code)


def verify_source(source):
    c = json.loads((HERE / 'request_origin_contract.json').read_text())
    require(c.get('accepted') is True and re.fullmatch('[a-f0-9]{40}', c.get('product_sha', '')), 'EXACT_ACCEPTED_SOURCE_REQUIRED')
    require(c.get('baseline_product_sha') == BASELINE and c.get('engine') == 'webkit'
            and c.get('playwright') == '1.63.0' and c.get('case_count') == 8, 'FIXED_CONTRACT_REQUIRED')
    env = environment()
    head = command(['git', 'rev-parse', 'HEAD'], source, env)
    require(head.returncode == 0 and head.stdout.decode().strip() == c['product_sha'], 'EXACT_SOURCE_REQUIRED')
    require(command(['git', 'diff', '--exit-code', 'HEAD', '--', 'frontend'], source, env).returncode == 0, 'DIRTY_SOURCE')
    extra = command(['git', 'ls-files', '--others', '--exclude-standard', '--', 'frontend'], source, env)
    require(extra.returncode == 0 and not extra.stdout.strip(), 'UNTRACKED_SOURCE')
    pins = c.get('source_sha256', {})
    require(set(pins) == {'frontend/src/shared/api/client.ts', 'frontend/package.json', 'frontend/package-lock.json'}, 'EXACT_SOURCE_FILES_REQUIRED')
    for relative, digest in pins.items():
        f = source / relative
        require(f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(source.resolve())
                and hashlib.sha256(f.read_bytes()).hexdigest() == digest, 'SOURCE_HASH_MISMATCH')
    require(pins['frontend/src/shared/api/client.ts'] == c.get('candidate_client_sha256'), 'CLIENT_BINDING_MISMATCH')
    script = HERE / 'request_origin_probe.cjs'
    require(not script.is_symlink() and hashlib.sha256(script.read_bytes()).hexdigest() == c.get('fixture_sha256'), 'AUTHOR_SOURCE_MISMATCH')
    package = json.loads((source / 'frontend/package.json').read_text())
    require(package.get('devDependencies', {}).get('@playwright/test') == '1.63.0', 'LOCKED_PLAYWRIGHT_REQUIRED')
    return c


def verify_harness():
    env = environment()
    require(os.environ.get('GITHUB_REF') == BRANCH, 'EXACT_BRANCH_REQUIRED')
    head = command(['git', 'rev-parse', 'HEAD'], ROOT, env)
    sha = head.stdout.decode().strip()
    require(head.returncode == 0 and re.fullmatch('[a-f0-9]{40}', sha)
            and os.environ.get('GITHUB_SHA') == sha, 'EXACT_HARNESS_REQUIRED')
    require(command(['git', 'diff', '--exit-code', 'HEAD', '--', *OWNED], ROOT, env).returncode == 0, 'HARNESS_CHANGED')
    extra = command(['git', 'ls-files', '--others', '--exclude-standard', '--', *OWNED], ROOT, env)
    require(extra.returncode == 0 and not extra.stdout.strip(), 'HARNESS_UNTRACKED')
    return sha


def projection(raw, c, returncode):
    require(isinstance(raw, dict) and raw.get('schemaVersion') == 1
            and raw.get('fixture') == 'anonymous_request_origin_v1' and raw.get('engine') == 'webkit'
            and raw.get('candidateClientSha256') == c['candidate_client_sha256'], 'OUTPUT_BINDING')
    result = raw.get('outcome')
    if result == 'blocked':
        require(returncode == 2 and raw.get('caseCount') == 0
                and raw.get('stage') in {'fixture_setup', 'browser_launch', 'browser_cases'}, 'BLOCKED_SHAPE')
        return {'status': 'BLOCKED', 'stage': raw['stage'], 'case_count': 0}
    require(raw.get('baselineProductSha') == BASELINE and raw.get('caseCount') == 8, 'BASELINE_OR_COUNT')
    rows = raw.get('cases')
    require(isinstance(rows, list) and len(rows) == 8 and all(isinstance(r, dict) for r in rows)
            and [r.get('id') for r in rows] == list(CASES), 'EXACT_CASE_MATRIX')
    require(rows[0].get('status') in {'pass', 'inconclusive'}
            and all(r.get('status') in {'pass', 'fail'} for r in rows[1:]), 'CASE_STATUS')
    candidate = all(r['status'] == 'pass' for r in rows[1:])
    baseline = rows[0]['status'] == 'pass'
    require(type(raw.get('candidatePass')) is bool and raw['candidatePass'] is candidate
            and type(raw.get('baselineReproduced')) is bool and raw['baselineReproduced'] is baseline, 'NO_RESULT_PROMOTION')
    expected = 'fail' if not candidate else 'pass' if baseline else 'inconclusive'
    require(result == expected and returncode == {'pass': 0, 'fail': 1, 'inconclusive': 2}[expected], 'EXIT_OR_RESULT_MISMATCH')
    origins = {'opaque_null', 'exact_origin', 'missing', 'unexpected'}
    require(raw.get('baselineOrigin') in origins and raw.get('candidateOrigin') in origins
            and type(raw.get('candidateReferrerOriginOnly')) is bool
            and raw.get('candidateFetchMetadata') in {'same-origin', 'missing_allowed_by_backend', 'unexpected'}
            and type(raw.get('downstreamHits')) is int and 0 <= raw['downstreamHits'] <= 3, 'CATEGORY_BOUNDS')
    if baseline:
        require(raw['baselineOrigin'] == 'opaque_null', 'BASELINE_CONTRADICTION')
    require((rows[1]['status'] == 'pass') == (raw['candidateOrigin'] == 'exact_origin')
            and (rows[2]['status'] == 'pass') == raw['candidateReferrerOriginOnly']
            and (rows[4]['status'] == 'pass') == (raw['candidateFetchMetadata'] != 'unexpected'), 'CASE_CONTRADICTION')
    if any(r['status'] == 'pass' for r in rows[5:]):
        require(raw['downstreamHits'] == 0, 'DESTINATION_CONTRADICTION')
    version = raw.get('browserVersion', '')
    return {'status': {'pass': 'PASS_ANONYMOUS_WEBKIT_TRANSPORT', 'fail': 'FAIL', 'inconclusive': 'INCONCLUSIVE'}[expected],
            'stage': 'completed', 'candidate_pass': candidate, 'baseline_reproduced': baseline,
            'baseline_origin': raw['baselineOrigin'], 'candidate_origin': raw['candidateOrigin'],
            'candidate_referrer_origin_only': raw['candidateReferrerOriginOnly'],
            'candidate_fetch_metadata': raw['candidateFetchMetadata'], 'downstream_hits': raw['downstreamHits'],
            'browser_version': version if isinstance(version, str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+){0,4}', version) else 'UNRECORDED',
            'case_count': 8, 'cases': [{'id': r['id'], 'status': r['status']} for r in rows]}


def dummy_safety_check(c):
    raw = {'schemaVersion': 1, 'fixture': 'anonymous_request_origin_v1', 'engine': 'webkit',
           'candidateClientSha256': c['candidate_client_sha256'], 'outcome': 'blocked', 'stage': 'browser_launch',
           'caseCount': 0, 'message': 'PRIVATE_CANARY', 'headers': {'cookie': 'PRIVATE_CANARY'}}
    require('PRIVATE_CANARY' not in json.dumps(projection(raw, c, 2)), 'DUMMY_OUTPUT_UNSAFE')


def official_webkit(source, env):
    frontend = source / 'frontend'
    for package in ('playwright', 'playwright-core'):
        require(json.loads((frontend / 'node_modules' / package / 'package.json').read_text()).get('version') == '1.63.0', 'INSTALLED_PACKAGE_MISMATCH')
    module = frontend / 'node_modules/playwright'
    result = command(['node', '-e', 'process.stdout.write(require(process.argv[1]).webkit.executablePath())', str(module)], frontend, env)
    browser = Path(result.stdout.decode())
    base = Path(env.get('PLAYWRIGHT_BROWSERS_PATH', ''))
    require(result.returncode == 0 and base.is_absolute() and browser.is_absolute()
            and browser.resolve().is_relative_to(base.resolve()) and browser.is_file()
            and os.access(browser, os.X_OK), 'OFFICIAL_WEBKIT_REQUIRED')
    return module


def execute(source, module, env, c):
    with tempfile.TemporaryDirectory(prefix='ro-', dir='/tmp') as private:
        require(Path(private).stat().st_mode & 0o777 == 0o700, 'PRIVATE_DIRECTORY_MODE')
        child = subprocess.Popen(['node', str(HERE / 'request_origin_probe.cjs'), 'webkit', str(module),
                                  str(source / 'frontend/src/shared/api/client.ts')], cwd=private,
                                 env={**env, 'TMPDIR': private, 'HOME': private}, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, _ = child.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            try:
                # The pinned Playwright SIGTERM handler closes its browser;
                # a second signal forces that browser's separate process group.
                for _ in range(2):
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        child.communicate(timeout=5)
                    except subprocess.TimeoutExpired:
                        continue
                    break
            finally:
                # Reap the owned group even when the Node parent exited first.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate(timeout=5)
            return {'status': 'INCONCLUSIVE', 'stage': 'outer_timeout',
                    'reason_code': 'REQUEST_ORIGIN_OUTER_TIMEOUT', 'cleanup': 'UNVERIFIED'}
        require(len(stdout) <= 32768 and child.returncode in (0, 1, 2), 'PROCESS_OR_OUTPUT_BOUND')
        try:
            raw = json.loads(stdout)
        except Exception:
            return {'status': 'INCONCLUSIVE', 'stage': 'output_unavailable',
                    'reason_code': 'REQUEST_ORIGIN_OUTPUT_UNAVAILABLE', 'cleanup': 'UNVERIFIED'}
        result = projection(raw, c, child.returncode)
        # The unchanged fixture closes its browser and both servers in finally.
        # A normal single-result process exit completes that path; a caught
        # setup/finalizer error does not prove browser cleanup.
        result['cleanup'] = 'UNVERIFIED' if result['status'] == 'BLOCKED' else 'FIXTURE_FINALIZER_COMPLETED'
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--check-inputs', action='store_true')
    args = parser.parse_args()
    summary = {'schema_version': 1, 'status': 'BLOCKED', 'scope': 'ANONYMOUS_LOOPBACK_WEBKIT_TRANSPORT_ONLY',
               'observed_at': datetime.now(timezone.utc).isoformat(), 'engine': 'webkit',
               'application_authentication': 'NOT_RUN', 'hosted_https': 'NOT_RUN', 'physical_iphone': 'NOT_RUN',
               'C_gates': 'NOT_INVOKED_OR_MODIFIED', 'provider_calls': 'NOT_RUN', 'deployment_performed': False}
    try:
        source = args.source.resolve()
        c = verify_source(source)
        dummy_safety_check(c)
        if args.check_inputs:
            print('PASS: exact public fixture, candidate source and dummy-output boundary')
            return 0
        harness = verify_harness()
        summary.update(product_sha=c['product_sha'], baseline_product_sha=BASELINE,
                       fixture_sha256=c['fixture_sha256'], candidate_client_sha256=c['candidate_client_sha256'],
                       harness_sha=harness, dummy_output_safety='PASS')
        env = environment()
        summary.update(execute(source, official_webkit(source, env), env, c))
        require(verify_source(source) == c and verify_harness() == harness, 'SOURCE_CHANGED_DURING_RUN')
    except ValueError as error:
        code = str(error)
        summary.update(status='BLOCKED', reason_code=code if re.fullmatch('REQUEST_ORIGIN_[A-Z_]+', code) else 'REQUEST_ORIGIN_INVALID_OUTPUT')
    except Exception:
        summary.update(status='BLOCKED', reason_code='REQUEST_ORIGIN_UNEXPECTED_RUNNER_FAILURE')
    if args.check_inputs:
        print('BLOCKED: reviewed source contract unavailable')
        return 2
    (ROOT / 'request-origin-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'PASS_ANONYMOUS_WEBKIT_TRANSPORT' else 1 if summary['status'] == 'FAIL' else 2


if __name__ == '__main__':
    raise SystemExit(main())
