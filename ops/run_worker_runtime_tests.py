#!/usr/bin/env python3
"""Mandatory real PG gate: one frozen bootstrap case + three mounted worker cases.

Usage: DALA_TEST_DATABASE_URL=<disposable local owner DSN>
       DALA_ACCEPTANCE_DISPOSABLE=1 python ops/run_worker_runtime_tests.py

Use supplied API+worker test DSNs together, or create/clean two independently
named temporary restricted LOGIN fixtures using the existing accepted CI helper.
All application test data lives in random disposable schemas. This is never an
operator/production provisioning command. Missing setup exits2, no skipped green.
--collect only lists expected cases; it performs no database or role operation.
"""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATHS = [str(ROOT/'backend'), str(ROOT/'backend/tests'), str(ROOT/'ops/provision'), str(ROOT/'ops/provision/tests')]
EXPECTED_FLOWS = 3


def _local_dsn(value):
    from psycopg.conninfo import conninfo_to_dict
    parts = conninfo_to_dict(value)
    host = parts.get('host', '')
    if (not parts.get('dbname') or not host or ',' in host or parts.get('service') or parts.get('servicefile')
            or parts.get('hostaddr') not in (None, '', '127.0.0.1', '::1')
            or host not in ('localhost', '127.0.0.1', '::1') and not host.startswith('/')):
        raise ValueError('WORKER_GATE_REQUIRES_EXPLICIT_LOCAL_DISPOSABLE_DSN')


def _pins(environment):
    names = ('DALA_DEMO_MASTER_PIN', 'DALA_DEMO_EXECUTOR_PIN')
    if bool(environment.get(names[0])) != bool(environment.get(names[1])):
        raise ValueError('WORKER_GATE_REQUIRES_BOTH_TEST_PINS_OR_NEITHER')
    if all(environment.get(name) for name in names):
        return {name: environment[name] for name in names}
    values = []
    while len(values) < 2:
        value = ''.join(secrets.SystemRandom().sample('0123456789', 8))
        if value != '71426839' and value not in values:
            values.append(value)
    return dict(zip(names, values))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true')
    args = parser.parse_args(argv)
    if not args.collect and (not os.environ.get('DALA_TEST_DATABASE_URL') or os.environ.get('DALA_ACCEPTANCE_DISPOSABLE') != '1'):
        print('NOT_RUN: explicit local disposable DALA_TEST_DATABASE_URL and DALA_ACCEPTANCE_DISPOSABLE=1 required')
        return 2
    sys.path[:0] = PATHS
    from test_worker_runtime_postgres import WorkerRuntimePostgresTests
    from test_worker_capabilities import DisposableWorkerGate
    flows = unittest.defaultTestLoader.loadTestsFromTestCase(WorkerRuntimePostgresTests)
    bootstrap = unittest.defaultTestLoader.loadTestsFromTestCase(DisposableWorkerGate)
    if flows.countTestCases() != EXPECTED_FLOWS or bootstrap.countTestCases() != 1:
        print('FAIL: worker gate has an unexpected/empty test set')
        return 1
    if args.collect:
        print(json.dumps({'status': 'COLLECTED_ONLY_NOT_EXECUTED', 'bootstrap_cases': 1,
                          'worker_flow_cases': EXPECTED_FLOWS, 'database_access': False, 'role_creation': False}))
        return 0
    fixtures = []
    code = 1
    try:
        if any(os.environ.get(name) for name in ('PGSERVICE', 'PGSERVICEFILE', 'PGHOSTADDR')):
            raise ValueError('WORKER_GATE_AMBIENT_DATABASE_INDIRECTION_REFUSED')
        _local_dsn(os.environ['DALA_TEST_DATABASE_URL'])
        names = ('DALA_ACCEPTANCE_RUNTIME_DATABASE_URL', 'DALA_ACCEPTANCE_WORKER_DATABASE_URL')
        supplied = [bool(os.environ.get(name)) for name in names]
        if any(supplied) and not all(supplied):
            raise ValueError('WORKER_GATE_REQUIRES_BOTH_RESTRICTED_DSNS_OR_NEITHER')
        with ExitStack() as stack:
            environment = dict(os.environ, **_pins(os.environ))
            if all(supplied):
                for name in names:
                    _local_dsn(environment[name])
            else:
                from test_persistence_role import ApplicationRoleTests
                class APILoginFixture(ApplicationRoleTests):
                    pass
                class WorkerLoginFixture(ApplicationRoleTests):
                    pass
                # No inherited test methods run. Only the existing class fixture
                # creates a direct nonowner LOGIN with random in-memory secret.
                for name, fixture in zip(names, (APILoginFixture, WorkerLoginFixture)):
                    fixtures.append(fixture)
                    fixture.setUpClass()
                    environment[name] = fixture.runtime_dsn
            stack.enter_context(patch.dict(os.environ, environment, clear=True))
            # Invoke the existing frozen gate, including its local-DSN validation,
            # exact one-test/no-skip requirement and revoked-grant nonrepair check.
            from test_worker_capabilities import run_postgres_gate
            if run_postgres_gate() != 0:
                print('FAIL: prerequisite three-login bootstrap gate did not pass')
            else:
                result = unittest.TextTestRunner(verbosity=2).run(flows)
                if result.testsRun == EXPECTED_FLOWS and not result.skipped and result.wasSuccessful():
                    code = 0
    except Exception as error:
        print('FAIL: worker PostgreSQL gate setup/execution error (' + type(error).__name__ + ')')
    finally:
        for fixture in reversed(fixtures):
            fixture.doClassCleanups()
            if fixture.tearDown_exceptions:
                code = 1
                print('FAIL: disposable restricted-role fixture cleanup was not confirmed')
    if code == 0:
        print('PASS: one actual three-login bootstrap + three mounted rules-worker cases; zero skips; no provider calls')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
