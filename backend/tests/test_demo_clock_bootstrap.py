"""Offline clock-bootstrap safety and orchestration checks; not a PostgreSQL pass."""
import argparse
from contextlib import ExitStack, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ops/provision'))
import enable_demo_clock as helper
from prepare_demo_database import bootstrap_marker, worker_migration_plan

INSTANCE = '00000000-0000-0000-0000-000000000013'


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.args = argparse.Namespace(backend=ROOT/'backend', schema='clock_test',
                                       expected_database='isolated', bootstrap=True)
        self.env = dict(zip(helper.DATABASE_VARIABLES, ('owner', 'api', 'worker')),
                        DALA_API_MODE='demo', DALA_DEMO_SEED_ALLOWED='1',
                        DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1',
                        DALA_DEMO_CLOCK_CAPABILITY_ALLOWED='1', DALA_DEMO_CLOCK_INSTANCE_ID=INSTANCE)

    def test_013_is_exact_optional_eighth_file_without_mutating_frozen_plan(self):
        plan = worker_migration_plan(ROOT/'backend')
        self.assertEqual(len(plan), 7)
        self.assertNotIn(helper.CLOCK_MIGRATION[0], [e['path'] for e in plan])
        self.assertEqual(helper.migration_plan(ROOT/'backend'),
                         dict(zip(('path', 'sha256'), helper.CLOCK_MIGRATION)))

    def test_changed_or_duplicate_migration_refuses_before_database(self):
        with TemporaryDirectory() as temp:
            backend = Path(temp)
            path = backend/helper.CLOCK_MIGRATION[0]
            path.parent.mkdir(parents=True)
            path.write_text('SELECT 1;')
            with self.assertRaisesRegex(ValueError, 'HASH_MISMATCH'):
                helper.migration_plan(backend)
            path.write_bytes((ROOT/'backend'/helper.CLOCK_MIGRATION[0]).read_bytes())
            (backend/'db/migrations').mkdir()
            (backend/'db/migrations/013_demo_business_clock.sql').touch()
            with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
                helper.migration_plan(backend)

    def test_minimal_and_history_fingerprints_remain_frozen(self):
        expected = {'minimal': '2db9177be2d0c012a8228727e7528820f309e89c379ffa43a23cdcc897075908',
                    'history': 'd8c286af83f43160efa6b80ec1d40740651f481b6c96447124f31382298afbe4'}
        for mode, fingerprint in expected.items():
            _, _, manifest = helper.worker_bootstrap.selected_fixture({'DALA_DEMO_FIXTURE_MODE': mode})
            self.assertEqual(helper.worker_bootstrap.capability_fingerprint(worker_migration_plan(ROOT/'backend'),
                owner_role='owner', api_role='api', worker_role='worker', fixture_manifest=manifest), fingerprint)

    def test_instance_is_canonical_and_changes_receipt(self):
        for value in (None, 13, '', 'not-uuid', INSTANCE.replace('-', ''), INSTANCE.upper().replace('013', 'ABC')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                helper.instance_uuid(value)
        base = dict(baseline_fingerprint='a'*64, instance_id=INSTANCE)
        fingerprint = helper.capability_fingerprint(**base)
        self.assertNotEqual(fingerprint, helper.capability_fingerprint(**dict(base, instance_id=INSTANCE[:-1]+'4')))
        self.assertNotEqual(fingerprint, helper.capability_fingerprint(**dict(base, baseline_fingerprint='b'*64)))

    def test_exact_permissions_and_no_role_or_wildcard_grants(self):
        statements = []
        db = SimpleNamespace(execute=lambda q: statements.append(q.as_string()))
        for role, profile in (('api', helper.API_PROFILE), ('worker', helper.WORKER_PROFILE)):
            helper.worker_bootstrap._grant_profile(db, schema='clock_test', role_name=role, profile=profile)
        self.assertEqual(statements, [
            'GRANT USAGE ON SCHEMA "clock_test" TO "api"',
            'GRANT SELECT ON "clock_test"."demo_clock_state" TO "api"',
            'GRANT SELECT ON "clock_test"."demo_clock_controls" TO "api"',
            'GRANT UPDATE ("version","real_anchor","domain_anchor","scale") ON "clock_test"."demo_clock_state" TO "api"',
            'GRANT INSERT ON "clock_test"."demo_clock_controls" TO "api"',
            'GRANT USAGE ON SCHEMA "clock_test" TO "worker"',
            'GRANT SELECT ON "clock_test"."demo_clock_state" TO "worker"'])

    def test_plan_has_no_database_access_and_no_secret_output(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'DALA_DEMO_OWNER_DATABASE_URL': 'never-log-me'}, clear=True), \
                patch('psycopg.connect', side_effect=AssertionError('DB access')), redirect_stdout(output):
            self.assertEqual(helper.main(['--backend', str(ROOT/'backend'), '--schema', 'clock_test']), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload['status'], 'PLAN_ONLY_NO_DATABASE_ACCESS')
        self.assertEqual(len(payload['migrations']), 8)
        self.assertNotIn('never-log-me', output.getvalue())

    def test_each_explicit_opt_in_is_required_before_database(self):
        for key in ('DALA_API_MODE', 'DALA_DEMO_SEED_ALLOWED', 'DALA_DEMO_WORKER_CAPABILITY_ALLOWED',
                    'DALA_DEMO_CLOCK_CAPABILITY_ALLOWED', 'DALA_DEMO_CLOCK_INSTANCE_ID'):
            with self.subTest(key=key), patch('psycopg.connect', side_effect=AssertionError('DB access')):
                with self.assertRaises(ValueError):
                    helper.apply_capabilities(self.args, {k: v for k, v in self.env.items() if k != key})
        self.args.bootstrap = False
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REQUIRED'):
            helper.apply_capabilities(self.args, self.env)

    def test_missing_runtime_contract_refuses_before_db(self):
        with patch('app.runtime.validate_database', lambda connect: None), \
                patch('psycopg.connect', side_effect=AssertionError('DB access')):
            with self.assertRaisesRegex(ValueError, 'CAPABILITY_AWARE_RUNTIME_REQUIRED'):
                helper.apply_capabilities(self.args, self.env)

    def test_repeat_requires_both_exact_completed_receipts(self):
        kwargs = dict(baseline_fingerprint='a'*64, fingerprint='b'*64)
        valid = (bootstrap_marker('seeded'), helper.worker_bootstrap.marker('complete', 'a'*64),
                 helper.marker('complete', 'b'*64))
        self.assertEqual(helper.repeat_action(*valid, **kwargs), 'verify_only')
        for index, replacement in ((0, None), (1, None), (2, None), (2, helper.marker('initializing', 'b'*64)),
                                   (2, helper.marker('complete', 'c'*64))):
            bad = list(valid)
            bad[index] = replacement
            with self.subTest(index=index, replacement=replacement), self.assertRaises(ValueError):
                helper.repeat_action(*bad, **kwargs)

    def harness(self, *, existing=True):
        stack = ExitStack()
        self.addCleanup(stack.close)
        baseline = helper.worker_bootstrap.capability_fingerprint(worker_migration_plan(ROOT/'backend'),
                    owner_role='owner', api_role='api', worker_role='worker')
        fingerprint = helper.capability_fingerprint(baseline_fingerprint=baseline, instance_id=INSTANCE)
        receipts = {'schema': bootstrap_marker('seeded'), 'worker': helper.worker_bootstrap.marker('complete', baseline),
                    'clock': helper.marker('complete', fingerprint)} if existing else None
        class DB:
            def __init__(self, role): self.role = role
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, q, params=None):
                if 'pg_try_advisory_lock' in q: row = {'ok': True}
                elif 'SELECT EXISTS' in q: row = {'bad': False}
                else: raise AssertionError('Unexpected database write/query: '+q)
                return SimpleNamespace(fetchone=lambda: row)
        def identity(connect):
            with connect() as db:
                return dict(database_name='isolated', server_address='127.0.0.1', server_port=5432,
                            role_name=db.role, session_role=db.role, rolsuper=False, rolcreatedb=False,
                            rolcreaterole=False, rolbypassrls=False)
        stack.enter_context(patch('psycopg.connect', side_effect=lambda role, **kw: DB(role)))
        stack.enter_context(patch('database_profile.identity', side_effect=identity))
        mocks = {}
        for name in ('_runtime_validators', '_validate_profiles', '_verify_singleton', '_install_clock', '_complete_clock'):
            mocks[name] = stack.enter_context(patch.object(helper, name))
        mocks['markers'] = stack.enter_context(patch.object(helper, '_read_markers', return_value=receipts))
        mocks['preflight'] = stack.enter_context(patch.object(helper.worker_bootstrap, 'preflight_apply'))
        mocks['baseline'] = stack.enter_context(patch.object(helper.worker_bootstrap, 'apply_capabilities',
                                                    return_value={'status': 'WORKER_CAPABILITIES_READY'}))
        return mocks

    def test_repeat_never_initializes_seeds_regrants_or_updates_markers(self):
        mocks = self.harness()
        result = helper.apply_capabilities(self.args, self.env)
        self.assertEqual(result['status'], 'DEMO_CLOCK_ALREADY_VERIFIED')
        for name in ('preflight', 'baseline', '_install_clock', '_complete_clock'):
            mocks[name].assert_not_called()
        mocks['_validate_profiles'].assert_called_once()
        mocks['_verify_singleton'].assert_called_once()

    def test_revoked_grant_repeat_fails_without_any_repair(self):
        mocks = self.harness()
        mocks['_validate_profiles'].side_effect = ValueError('revoked')
        with self.assertRaisesRegex(ValueError, 'revoked'):
            helper.apply_capabilities(self.args, self.env)
        for name in ('baseline', '_install_clock', '_complete_clock'):
            mocks[name].assert_not_called()

    def test_unmarked_existing_base_and_partial_clock_are_never_adopted(self):
        mocks = self.harness()
        for bad in (None, helper.marker('initializing', 'b'*64)):
            mocks['markers'].return_value['clock'] = bad
            with self.assertRaisesRegex(ValueError, 'MARKER_MISMATCH'):
                helper.apply_capabilities(self.args, self.env)
        mocks['baseline'].assert_not_called()
        mocks['_install_clock'].assert_not_called()

    def test_fresh_orders_baseline_install_validate_then_completion(self):
        mocks = self.harness(existing=False)
        parent = Mock()
        for name in ('baseline', '_install_clock', '_verify_singleton', '_validate_profiles', '_complete_clock'):
            parent.attach_mock(mocks[name], name)
        result = helper.apply_capabilities(self.args, self.env)
        self.assertEqual(result['status'], 'DEMO_CLOCK_READY')
        self.assertEqual([call[0] for call in parent.mock_calls],
                         ['baseline', '_install_clock', '_verify_singleton', '_validate_profiles', '_complete_clock'])
        self.assertEqual(result['clock_rows_seeded'], 1)

    def test_failed_fresh_validation_preserves_incomplete_state(self):
        mocks = self.harness(existing=False)
        mocks['_validate_profiles'].side_effect = ValueError('synthetic grant mismatch')
        with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE_SCHEMA_PRESERVED'):
            helper.apply_capabilities(self.args, self.env)
        mocks['_install_clock'].assert_called_once()
        mocks['_complete_clock'].assert_not_called()

    def test_concurrent_existing_base_cannot_become_clock_profile(self):
        mocks = self.harness(existing=False)
        mocks['baseline'].return_value = {'status': 'WORKER_CAPABILITIES_ALREADY_VERIFIED'}
        with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE_SCHEMA_PRESERVED'):
            helper.apply_capabilities(self.args, self.env)
        mocks['_install_clock'].assert_not_called()

    def test_pg_gate_missing_inputs_is_nonzero_not_skip_or_mock_success(self):
        spec = importlib.util.spec_from_file_location('clock_pg_gate',
                    ROOT/'ops/provision/tests/test_demo_clock_bootstrap_postgres.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), redirect_stdout(output), \
                patch('psycopg.connect', side_effect=AssertionError('DB access')):
            self.assertEqual(gate.run_postgres_gate(), 2)
        self.assertIn('NOT_RUN', output.getvalue())

    def test_pg_gate_rejects_remote_and_ambient_indirection_before_connect(self):
        spec = importlib.util.spec_from_file_location('clock_pg_gate',
                    ROOT/'ops/provision/tests/test_demo_clock_bootstrap_postgres.py')
        gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gate)
        environment = {name: 'dbname=isolated user=existing host=127.0.0.1' for name in gate.INPUTS[:3]}
        environment.update(DALA_ACCEPTANCE_DISPOSABLE='1', DALA_DEMO_MASTER_PIN='not-read', DALA_DEMO_EXECUTOR_PIN='not-read')
        gate.require_disposable_inputs(environment)
        for changes in ({gate.INPUTS[0]: 'dbname=isolated user=existing host=remote.example'},
                        {'PGSERVICE': 'ambient'}, {gate.INPUTS[0]: 'dbname=isolated host=localhost'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                gate.require_disposable_inputs(dict(environment, **changes))

    def test_cli_failure_never_echoes_dsn_or_raw_database_error(self):
        output = io.StringIO()
        with patch.object(helper, 'apply_capabilities', side_effect=RuntimeError('postgres://secret-token')), redirect_stdout(output):
            self.assertEqual(helper.main(['--backend', str(ROOT/'backend'), '--schema', 'clock_test', '--apply']), 1)
        self.assertNotIn('secret-token', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['code'], 'DEMO_CLOCK_BOOTSTRAP_FAILED')


if __name__ == '__main__':
    unittest.main()
