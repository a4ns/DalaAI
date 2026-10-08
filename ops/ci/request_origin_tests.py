import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import unittest
from unittest.mock import Mock, patch

import request_origin_gate as gate

C = json.loads((Path(__file__).parent / 'request_origin_contract.json').read_text())


def example():
    return {'schemaVersion': 1, 'fixture': 'anonymous_request_origin_v1', 'engine': 'webkit',
            'candidateClientSha256': C['candidate_client_sha256'], 'baselineProductSha': gate.BASELINE,
            'caseCount': 8, 'cases': [{'id': key, 'status': 'pass'} for key in gate.CASES],
            'candidatePass': True, 'baselineReproduced': True, 'outcome': 'pass',
            'baselineOrigin': 'opaque_null', 'candidateOrigin': 'exact_origin',
            'candidateReferrerOriginOnly': True, 'candidateFetchMetadata': 'same-origin',
            'downstreamHits': 0, 'browserVersion': '26.0'}


class RequestOriginSafety(unittest.TestCase):
    def test_exact_eight_cases(self):
        value = gate.projection(example(), C, 0)
        self.assertEqual(value['status'], 'PASS_ANONYMOUS_WEBKIT_TRANSPORT')
        self.assertEqual(len(value['cases']), 8)

    def test_baseline_variation_remains_inconclusive_with_candidate_pass(self):
        raw = example()
        raw.update(outcome='inconclusive', baselineReproduced=False, baselineOrigin='exact_origin')
        raw['cases'][0]['status'] = 'inconclusive'
        value = gate.projection(raw, C, 2)
        self.assertEqual(value['status'], 'INCONCLUSIVE')
        self.assertTrue(value['candidate_pass'])

    def test_candidate_referrer_failure_is_failure(self):
        raw = example()
        raw.update(outcome='fail', candidatePass=False, candidateReferrerOriginOnly=False)
        raw['cases'][2]['status'] = 'fail'
        self.assertEqual(gate.projection(raw, C, 1)['status'], 'FAIL')

    def test_launch_block_cannot_be_promoted(self):
        raw = {'schemaVersion': 1, 'fixture': 'anonymous_request_origin_v1', 'engine': 'webkit',
               'candidateClientSha256': C['candidate_client_sha256'], 'outcome': 'blocked',
               'stage': 'browser_launch', 'caseCount': 0, 'error': 'PRIVATE_CANARY'}
        self.assertEqual(gate.projection(raw, C, 2), {'status': 'BLOCKED', 'stage': 'browser_launch', 'case_count': 0})
        with self.assertRaises(ValueError):
            gate.projection(raw, C, 0)

    def test_incomplete_duplicate_skipped_or_extra_cases_rejected(self):
        mutations = [lambda d: d['cases'].pop(), lambda d: d['cases'].append(d['cases'][0]),
                     lambda d: d['cases'][1].update(id=gate.CASES[0]),
                     lambda d: d['cases'][1].update(status='skipped'), lambda d: d.update(caseCount=7)]
        for mutate in mutations:
            raw = example()
            mutate(raw)
            with self.assertRaises(ValueError):
                gate.projection(raw, C, 0)

    def test_wrong_source_engine_exit_or_contradictory_evidence_rejected(self):
        mutations = [lambda d: d.update(candidateClientSha256='0'*64), lambda d: d.update(engine='chromium'),
                     lambda d: d.update(baselineProductSha='0'*40), lambda d: d.update(candidatePass=False),
                     lambda d: d.update(downstreamHits=1), lambda d: d.update(candidateOrigin='missing'),
                     lambda d: d.update(baselineOrigin='exact_origin'), lambda d: d.update(candidateFetchMetadata='unexpected')]
        for mutate in mutations:
            raw = example()
            mutate(raw)
            with self.assertRaises(ValueError):
                gate.projection(raw, C, 0)
        with self.assertRaises(ValueError):
            gate.projection(example(), C, 1)

    def test_raw_headers_paths_and_extras_never_publish(self):
        raw = example()
        raw.update(browserVersion='PRIVATE_CANARY', evidence='PRIVATE_CANARY', headers={'Origin': 'PRIVATE_CANARY'})
        raw['cases'][0]['error'] = 'PRIVATE_CANARY'
        self.assertNotIn('PRIVATE_CANARY', json.dumps(gate.projection(raw, C, 0)))
        gate.dummy_safety_check(C)

    def test_environment_drops_credentials_and_launch_overrides(self):
        values = {key: 'PRIVATE_CANARY' for key in ('OPENAI_API_KEY', 'PGPASSWORD', 'NODE_OPTIONS', 'LD_PRELOAD',
                  'LD_LIBRARY_PATH', 'HTTP_PROXY', 'HTTPS_PROXY', 'DALA_E2E_MASTER_PIN_FILE', 'TMPDIR',
                  'PLAYWRIGHT_WEBKIT_EXECUTABLE_PATH', 'PWDEBUG', 'DISPLAY')}
        with patch.dict(os.environ, values):
            self.assertNotIn('PRIVATE_CANARY', json.dumps(gate.environment()))

    def test_author_source_is_unchanged(self):
        script = Path(__file__).parent / 'request_origin_probe.cjs'
        self.assertEqual(hashlib.sha256(script.read_bytes()).hexdigest(), C['fixture_sha256'])

    def test_outer_timeout_kills_group_and_cleans_private_parent(self):
        child = Mock(pid=12345, returncode=-15)
        child.communicate.side_effect = [subprocess.TimeoutExpired('probe', 90), subprocess.TimeoutExpired('probe', 5), (b'', b''), (b'', b'')]
        with patch.object(gate.subprocess, 'Popen', return_value=child) as launch, patch.object(gate.os, 'killpg') as kill:
            result = gate.execute(Path('/fixed/source'), Path('/fixed/module'), {}, C)
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertEqual(result['cleanup'], 'UNVERIFIED')
        self.assertEqual([call.args for call in kill.call_args_list], [(12345, signal.SIGTERM), (12345, signal.SIGTERM), (12345, signal.SIGKILL)])
        private = Path(launch.call_args.kwargs['cwd'])
        self.assertFalse(private.exists())
        self.assertTrue(str(private).startswith('/tmp/ro-'))
        self.assertEqual(launch.call_args.kwargs['env'], {'TMPDIR': str(private), 'HOME': str(private)})
        self.assertTrue(launch.call_args.kwargs['start_new_session'])

    def test_missing_output_is_inconclusive_and_raw_error_discarded(self):
        child = Mock(pid=12345, returncode=2)
        child.communicate.return_value = (b'', b'PRIVATE_CANARY')
        with patch.object(gate.subprocess, 'Popen', return_value=child):
            result = gate.execute(Path('/fixed/source'), Path('/fixed/module'), {}, C)
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertNotIn('PRIVATE_CANARY', json.dumps(result))

    def test_normal_result_requires_completed_fixture_finalizer(self):
        child = Mock(pid=12345, returncode=0)
        child.communicate.return_value = (json.dumps(example()).encode(), b'')
        with patch.object(gate.subprocess, 'Popen', return_value=child):
            result = gate.execute(Path('/fixed/source'), Path('/fixed/module'), {}, C)
        self.assertEqual(result['status'], 'PASS_ANONYMOUS_WEBKIT_TRANSPORT')
        self.assertEqual(result['cleanup'], 'FIXTURE_FINALIZER_COMPLETED')


if __name__ == '__main__':
    unittest.main()
