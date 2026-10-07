"""Mandatory actual PostgreSQL gate. Missing local disposable inputs is NOT_RUN/2.

Creates only unique synthetic test schemas using three EXISTING LOGINs. No role,
password, service, provider or production setup. Tests never skip or pass mocks
as database evidence. Cleanup is limited to each test's own random namespace.
"""
import argparse
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'ops/provision')]
import enable_demo_clock as helper
from provision_synthetic_demo import IDENTITY

INPUTS = ('DALA_TEST_DATABASE_URL', 'DALA_ACCEPTANCE_RUNTIME_DATABASE_URL',
          'DALA_ACCEPTANCE_WORKER_DATABASE_URL', 'DALA_DEMO_MASTER_PIN', 'DALA_DEMO_EXECUTOR_PIN')


def require_disposable_inputs(environment):
    if environment.get('DALA_ACCEPTANCE_DISPOSABLE') != '1' or any(not environment.get(key) for key in INPUTS):
        raise ValueError('NOT_RUN: local disposable opt-in, three existing LOGIN DSNs and private test PINs required')
    if any(environment.get(key) for key in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR')):
        raise ValueError('NOT_RUN: ambient PostgreSQL service/hostaddr indirection refused')
    from psycopg.conninfo import conninfo_to_dict
    for name in INPUTS[:3]:
        parts = conninfo_to_dict(environment[name])
        host = parts.get('host', '')
        if (not parts.get('dbname') or not parts.get('user') or not host or ',' in host
                or parts.get('service') or parts.get('servicefile')
                or parts.get('hostaddr') not in (None, '', '127.0.0.1', '::1')
                or host not in ('localhost', '127.0.0.1', '::1') and not host.startswith('/')):
            raise ValueError('NOT_RUN: each DSN must explicitly name a local disposable database and existing user')


class DisposableClockBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_disposable_inputs(os.environ)
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        cls.pg, cls.sql, cls.dict_row = psycopg, sql, staticmethod(dict_row)

    def setUp(self):
        self.schema = 'clock_bootstrap_gate_' + uuid4().hex
        self.instance = str(uuid4())
        with self.pg.connect(os.environ[INPUTS[0]], autocommit=True) as db:
            self.database = db.execute('SELECT current_database()').fetchone()[0]
        self.env = dict(os.environ, DALA_API_MODE='demo', DALA_DEMO_SEED_ALLOWED='1',
                        DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1', DALA_DEMO_CLOCK_CAPABILITY_ALLOWED='1',
                        DALA_DEMO_CLOCK_INSTANCE_ID=self.instance, DALA_DEMO_FIXTURE_MODE='minimal',
                        **dict(zip(helper.DATABASE_VARIABLES, (os.environ[k] for k in INPUTS[:3]))))
        self.args = argparse.Namespace(backend=ROOT/'backend', schema=self.schema,
                                       expected_database=self.database, bootstrap=True)
        self.addCleanup(self.drop_own_schema)

    def connect(self, role=0):
        return self.pg.connect(os.environ[INPUTS[role]], autocommit=True, row_factory=self.dict_row,
                options=f'-c search_path={self.schema} -c statement_timeout=10000 -c lock_timeout=5000')

    def drop_own_schema(self):
        with self.pg.connect(os.environ[INPUTS[0]], autocommit=True) as db:
            db.execute(self.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(self.sql.Identifier(self.schema)))

    def bootstrap(self):
        result = helper.apply_capabilities(self.args, self.env)
        self.assertEqual(result['status'], 'DEMO_CLOCK_READY')
        return result

    def snapshot(self):
        with self.connect() as db:
            actors = db.execute('SELECT * FROM employees ORDER BY id').fetchall()
            # Compare identity/PIN-hash stability without printing private hashes
            # in unittest assertion diffs if the candidate is broken.
            actor_digest = sha256(json.dumps(actors, sort_keys=True, default=str).encode()).hexdigest()
            return {
                'state': db.execute('SELECT * FROM demo_clock_state ORDER BY instance_id').fetchall(),
                'audit': db.execute('SELECT * FROM demo_clock_controls ORDER BY instance_id,version').fetchall(),
                'receipts': helper._read_markers(db, self.schema),
                'actor_digest': actor_digest, 'actor_count': len(actors),
                'scopes': db.execute('SELECT * FROM employee_sections ORDER BY employee_id,section_id').fetchall(),
                'orders': db.execute('SELECT count(*) AS n FROM orders').fetchone()['n'],
            }

    def test_fresh_one_db_anchor_and_control_then_repeat_preserves_every_receipt(self):
        self.bootstrap()
        first = self.snapshot()
        self.assertEqual(len(first['state']), 1)
        row = first['state'][0]
        self.assertEqual((str(row['instance_id']), row['synthetic'], row['version'], row['scale']),
                         (self.instance, True, 0, 1))
        self.assertEqual(row['real_anchor'], row['domain_anchor'])
        self.assertEqual(row['domain_anchor'], row['domain_start'])
        self.assertEqual(row['domain_limit'] - row['domain_start'], timedelta(days=7))
        from app.demo_clock.clock import DemoClockSettings
        from app.demo_clock.postgres import PostgresDemoBusinessClock
        settings = DemoClockSettings(enabled=True, mode='demo', isolated_demo=True)
        clock = PostgresDemoBusinessClock(lambda: self.connect(1), settings=settings, instance_id=self.instance)
        clock.apply({'instance_id': self.instance, 'expected_version': 0, 'action': 'set_scale', 'scale': 0},
                    authorize=lambda: IDENTITY['master'])
        reader = PostgresDemoBusinessClock(lambda: self.connect(2), settings=settings, instance_id=self.instance)
        self.assertEqual(reader.capture().revision, 1)
        before = self.snapshot()
        # An already accepted receipt can be verified without operator PIN input.
        for name in INPUTS[3:]:
            self.env.pop(name, None)
        self.assertEqual(helper.apply_capabilities(self.args, self.env)['status'], 'DEMO_CLOCK_ALREADY_VERIFIED')
        self.assertEqual(self.snapshot(), before)

    def test_actual_denied_identity_audit_and_worker_writes(self):
        self.bootstrap()
        denied = {
            1: ('INSERT INTO demo_clock_state SELECT * FROM demo_clock_state WHERE false',
                'UPDATE demo_clock_state SET instance_id=instance_id WHERE false',
                'UPDATE demo_clock_controls SET actor_id=actor_id WHERE false',
                'DELETE FROM demo_clock_controls WHERE false', 'TRUNCATE demo_clock_controls'),
            2: ('SELECT * FROM demo_clock_controls LIMIT 0',
                'UPDATE demo_clock_state SET scale=scale WHERE false',
                'INSERT INTO demo_clock_controls SELECT * FROM demo_clock_controls WHERE false',
                'DELETE FROM demo_clock_state WHERE false', 'TRUNCATE demo_clock_state'),
        }
        for role, statements in denied.items():
            with self.connect(role) as db:
                for statement in statements:
                    with self.subTest(role=role, statement=statement), self.assertRaises(self.pg.errors.InsufficientPrivilege):
                        db.execute(statement)

    def test_missing_api_control_grant_refuses_repeat_without_repair(self):
        self.bootstrap()
        with self.connect(1) as api:
            role = api.execute('SELECT current_user AS name').fetchone()['name']
        with self.connect() as db:
            db.execute(self.sql.SQL('REVOKE UPDATE (scale) ON {} FROM {}').format(
                self.sql.Identifier(self.schema, 'demo_clock_state'), self.sql.Identifier(role)))
        before = self.snapshot()
        with self.assertRaises(Exception):
            helper.apply_capabilities(self.args, self.env)
        self.assertEqual(self.snapshot(), before)
        with self.connect(1) as api:
            self.assertFalse(api.execute("SELECT has_column_privilege('demo_clock_state','scale','UPDATE') AS ok").fetchone()['ok'])

    def test_missing_worker_read_refuses_repeat_without_repair(self):
        self.bootstrap()
        with self.connect(2) as worker:
            role = worker.execute('SELECT current_user AS name').fetchone()['name']
        with self.connect() as db:
            db.execute(self.sql.SQL('REVOKE SELECT ON {} FROM {}').format(
                self.sql.Identifier(self.schema, 'demo_clock_state'), self.sql.Identifier(role)))
        before = self.snapshot()
        with self.assertRaises(Exception):
            helper.apply_capabilities(self.args, self.env)
        self.assertEqual(self.snapshot(), before)
        with self.connect(2) as worker:
            self.assertFalse(worker.execute("SELECT has_table_privilege('demo_clock_state','SELECT') AS ok").fetchone()['ok'])

    def test_existing_base_has_no_clock_adoption(self):
        baseline = helper.worker_bootstrap.apply_capabilities(self.args, self.env)
        self.assertEqual(baseline['status'], 'WORKER_CAPABILITIES_READY')
        with self.assertRaisesRegex(ValueError, 'MARKER_MISMATCH'):
            helper.apply_capabilities(self.args, self.env)
        with self.connect() as db:
            self.assertIsNone(db.execute("SELECT to_regclass('demo_clock_state') AS name").fetchone()['name'])
            self.assertEqual(db.execute('SELECT count(*) AS n FROM employees').fetchone()['n'], 2)

    def test_initializing_marker_blocks_retry_without_seed_or_grants(self):
        with patch.object(helper, '_complete_clock', side_effect=RuntimeError('synthetic final receipt failure')):
            with self.assertRaisesRegex(RuntimeError, 'INCOMPLETE_SCHEMA_PRESERVED'):
                helper.apply_capabilities(self.args, self.env)
        before = self.snapshot()
        self.assertIn('initializing', before['receipts']['clock'])
        with self.assertRaisesRegex(ValueError, 'MARKER_MISMATCH'):
            helper.apply_capabilities(self.args, self.env)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_instance_and_excess_grant_fail_closed_without_changes(self):
        self.bootstrap()
        before = self.snapshot()
        self.env['DALA_DEMO_CLOCK_INSTANCE_ID'] = str(uuid4())
        with self.assertRaisesRegex(ValueError, 'MARKER_MISMATCH'):
            helper.apply_capabilities(self.args, self.env)
        self.assertEqual(self.snapshot(), before)
        self.env['DALA_DEMO_CLOCK_INSTANCE_ID'] = self.instance
        with self.connect(1) as api:
            role = api.execute('SELECT current_user AS name').fetchone()['name']
        with self.connect() as db:
            db.execute(self.sql.SQL('GRANT UPDATE ON {} TO {}').format(
                self.sql.Identifier(self.schema, 'demo_clock_state'), self.sql.Identifier(role)))
        with self.assertRaises(Exception):
            helper.apply_capabilities(self.args, self.env)
        self.assertEqual(self.snapshot(), before)
        with self.connect(1) as api:
            self.assertTrue(api.execute("SELECT has_column_privilege('demo_clock_state','instance_id','UPDATE') AS ok").fetchone()['ok'])

    def test_fresh_history_profile_keeps_540_orders_and_verifies_without_reseed(self):
        self.env['DALA_DEMO_FIXTURE_MODE'] = 'history'
        self.bootstrap()
        before = self.snapshot()
        self.assertEqual(before['orders'], 540)
        self.assertEqual(before['actor_count'], 19)
        self.assertEqual(helper.apply_capabilities(self.args, self.env)['status'], 'DEMO_CLOCK_ALREADY_VERIFIED')
        self.assertEqual(self.snapshot(), before)


def run_postgres_gate():
    try:
        require_disposable_inputs(os.environ)
    except Exception:
        # DSN parser/provider errors can contain credentials. Never print them.
        print('NOT_RUN: explicit local disposable database, three existing LOGINs and private test PINs required')
        return 2
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DisposableClockBootstrapTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun == 8 and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(run_postgres_gate())
