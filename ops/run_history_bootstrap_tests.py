"""Three real-PG checks for explicit fixture mode and completion barriers."""
import argparse
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
if os.environ.get('DALA_ACCEPTANCE_DISPOSABLE')!='1' or not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit local disposable database required')
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests'),str(ROOT/'ops/provision'),str(ROOT/'ops')]
from run_worker_runtime_tests import _local_dsn, _pins
from test_persistence_role import ApplicationRoleTests
from prepare_demo_database import bootstrap_marker
import enable_worker_capabilities as helper
from psycopg.rows import dict_row

_local_dsn(os.environ['DALA_TEST_DATABASE_URL'])
if any(os.environ.get(k) for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR')):
    raise SystemExit('BLOCKED: ambient database indirection refused')

class APIFixture(ApplicationRoleTests):pass
class WorkerFixture(ApplicationRoleTests):pass

class HistoryBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.schema='history_bootstrap_'+uuid4().hex
        self.addCleanup(self.cleanup_schema)
        self.environment=dict(os.environ,**_pins({}),DALA_API_MODE='demo',DALA_DEMO_SEED_ALLOWED='1',
            DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1',DALA_DEMO_FIXTURE_MODE='history',
            DALA_DEMO_OWNER_DATABASE_URL=os.environ['DALA_TEST_DATABASE_URL'],
            DALA_DEMO_RUNTIME_DATABASE_URL=APIFixture.runtime_dsn,
            DALA_DEMO_WORKER_DATABASE_URL=WorkerFixture.runtime_dsn)
        with APIFixture.pg.connect(os.environ['DALA_TEST_DATABASE_URL'],autocommit=True) as db:
            database=db.execute('SELECT current_database()').fetchone()[0]
        self.args=argparse.Namespace(backend=ROOT/'backend',schema=self.schema,
                                    expected_database=database,bootstrap=True)

    def owner(self):
        return APIFixture.pg.connect(os.environ['DALA_TEST_DATABASE_URL'],autocommit=True,
            options=f'-c search_path={self.schema}',row_factory=dict_row)

    def cleanup_schema(self):
        with APIFixture.pg.connect(os.environ['DALA_TEST_DATABASE_URL'],autocommit=True) as db:
            db.execute(APIFixture.sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(APIFixture.sql.Identifier(self.schema)))

    def test_history_complete_repeat_and_opposite_mode_are_fenced(self):
        first=helper.apply_capabilities(self.args,self.environment)
        self.assertEqual(first['fixture_mode'],'history')
        self.assertEqual(first['status'],'WORKER_CAPABILITIES_READY')
        with self.owner() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM orders').fetchone()['n'],540)
            self.assertEqual(db.execute('SELECT count(*) AS n FROM employees').fetchone()['n'],19)
            self.assertTrue(db.execute("SELECT obj_description('delivery_dispatches'::regclass,'pg_class') AS marker").fetchone()['marker'].startswith(helper.MARKER_PREFIX+'complete '))
        repeat=helper.apply_capabilities(self.args,self.environment)
        self.assertEqual(repeat['seed']['status'],'ALREADY_PRESENT')
        self.assertFalse(repeat['migrations_replayed']);self.assertFalse(repeat['grants_replayed'])
        with self.assertRaisesRegex(ValueError,'WORKER_EXISTING_CAPABILITY_MARKER_MISMATCH'):
            helper.apply_capabilities(self.args,dict(self.environment,DALA_DEMO_FIXTURE_MODE='minimal'))
        with self.owner() as db:self.assertEqual(db.execute('SELECT count(*) AS n FROM orders').fetchone()['n'],540)

    def test_minimal_profile_keeps_its_previous_receipt_and_rejects_history_adoption(self):
        environment=dict(self.environment,DALA_DEMO_FIXTURE_MODE='minimal')
        first=helper.apply_capabilities(self.args,environment)
        self.assertEqual(first['fixture_mode'],'minimal')
        self.assertEqual(helper.apply_capabilities(self.args,environment)['status'],'WORKER_CAPABILITIES_ALREADY_VERIFIED')
        with self.assertRaisesRegex(ValueError,'WORKER_EXISTING_CAPABILITY_MARKER_MISMATCH'):
            helper.apply_capabilities(self.args,self.environment)
        with self.owner() as db:
            self.assertEqual(db.execute('SELECT count(*) AS n FROM orders').fetchone()['n'],0)
            self.assertEqual(db.execute('SELECT count(*) AS n FROM employee_sections').fetchone()['n'],2)

    def test_seed_failure_never_marks_history_profile_complete_or_retries_as_minimal(self):
        with patch('history_demo.apply_fixture',side_effect=RuntimeError('synthetic seed failure')):
            with self.assertRaisesRegex(RuntimeError,'WORKER_BOOTSTRAP_INCOMPLETE_SCHEMA_PRESERVED'):
                helper.apply_capabilities(self.args,self.environment)
        with self.owner() as db:
            marker=db.execute("SELECT obj_description('delivery_dispatches'::regclass,'pg_class') AS marker").fetchone()['marker']
            self.assertTrue(marker.startswith(helper.MARKER_PREFIX+'initializing '))
            self.assertEqual(db.execute('SELECT count(*) AS n FROM employees').fetchone()['n'],0)
        for mode in ('history','minimal'):
            with self.assertRaisesRegex(ValueError,'WORKER_EXISTING_CAPABILITY_MARKER_MISMATCH'):
                helper.apply_capabilities(self.args,dict(self.environment,DALA_DEMO_FIXTURE_MODE=mode))

fixtures=[]
try:
    for fixture in (APIFixture,WorkerFixture):
        fixtures.append(fixture);fixture.setUpClass()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(HistoryBootstrapTests)
    assert suite.countTestCases()==3
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun!=3 or not result.wasSuccessful():raise SystemExit(1)
    print('PASS: three actual mode-bound bootstrap cases, zero skips')
finally:
    for fixture in reversed(fixtures):
        fixture.doClassCleanups()
        if fixture.tearDown_exceptions:raise SystemExit('FAIL: disposable bootstrap-role cleanup not confirmed')
