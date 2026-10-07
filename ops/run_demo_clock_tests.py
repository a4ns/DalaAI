"""Mandatory6 durable+8 bootstrap+4 mounted clock cases; disposable PostgreSQL only."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests'),str(ROOT/'ops/provision'),str(ROOT/'ops/provision/tests'),str(ROOT/'ops')]
from run_worker_runtime_tests import _local_dsn,_pins


def run(suite,count,label):
    assert suite.countTestCases()==count
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or result.testsRun!=count:
        raise RuntimeError(label+' gate failed')
    print(f'PASS: {label}, {count} actual PostgreSQL cases, zero skips')


def main():
    if os.environ.get('DALA_ACCEPTANCE_DISPOSABLE')!='1' or not os.environ.get('DALA_TEST_DATABASE_URL'):
        print('NOT_RUN: explicit local disposable database required');return 2
    fixtures=[]
    try:
        _local_dsn(os.environ['DALA_TEST_DATABASE_URL'])
        if any(os.environ.get(k) for k in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR')):
            raise ValueError('Ambient database indirection refused')
        from test_persistence_role import ApplicationRoleTests
        class APILogin(ApplicationRoleTests):pass
        class WorkerLogin(ApplicationRoleTests):pass
        environment=dict(os.environ,**_pins({}),DALA_DEMO_CLOCK_TEST_DISPOSABLE='true')
        for name,fixture in zip(('DALA_ACCEPTANCE_RUNTIME_DATABASE_URL','DALA_ACCEPTANCE_WORKER_DATABASE_URL'),(APILogin,WorkerLogin)):
            fixtures.append(fixture);fixture.setUpClass();environment[name]=fixture.runtime_dsn
        with patch.dict(os.environ,environment,clear=True):
            from test_demo_clock_postgres import PostgresClockTests
            from test_demo_clock_bootstrap_postgres import DisposableClockBootstrapTests
            from test_demo_clock_runtime_postgres import load_tests
            run(unittest.defaultTestLoader.loadTestsFromTestCase(PostgresClockTests),6,'durable clock')
            run(unittest.defaultTestLoader.loadTestsFromTestCase(DisposableClockBootstrapTests),8,'three-login clock bootstrap')
            run(load_tests(None,None,None),4,'mounted API and worker clock')
    except Exception as error:
        print('FAIL: clock gate ('+type(error).__name__+')');return 1
    finally:
        for fixture in reversed(fixtures):
            fixture.doClassCleanups()
            if fixture.tearDown_exceptions:raise SystemExit('FAIL: clock role fixture cleanup')
    return 0


if __name__=='__main__':raise SystemExit(main())
