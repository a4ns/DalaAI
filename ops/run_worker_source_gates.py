"""Run every frozen worker/provider PostgreSQL source gate without skips."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'backend/tests'), str(ROOT/'backend/review/workers')]
gates = [('test_jobs_postgres',18), ('test_delivery_postgres',20),
         ('test_reconcile_postgres',14), ('test_priority_notice_postgres',14),
         ('test_push_postgres',9), ('test_provider_worker_postgres',8)]
for name, expected in gates:
    suite = unittest.defaultTestLoader.loadTestsFromName(name)
    if suite.countTestCases() != expected:
        raise SystemExit('FAIL: frozen PostgreSQL gate count differs: '+name)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun != expected or not result.wasSuccessful():
        raise SystemExit('FAIL: incomplete PostgreSQL gate: '+name)
    print(f'PASS: {name}, {expected} actual PostgreSQL cases, zero skips')
import test_independent_workers_postgres as review
review.MIGRATIONS = ROOT/'backend/db/migrations'
review.fixture.MIGRATIONS = review.MIGRATIONS
suite = review.load_tests(unittest.defaultTestLoader,None,None)
assert suite.countTestCases() == 7
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != 7 or not result.wasSuccessful():
    raise SystemExit('FAIL: independent PostgreSQL worker gate')
print('PASS: seven independent PostgreSQL cases; 90 combined, zero skips, no live sends')
