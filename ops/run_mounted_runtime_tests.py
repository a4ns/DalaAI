"""Mandatory eleven-case actual-entrypoint PostgreSQL gate."""
import os
from pathlib import Path
import sys
import unittest
if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
from test_runtime_postgres import MountedRuntimeTests
suite=unittest.defaultTestLoader.loadTestsFromTestCase(MountedRuntimeTests)
if suite.countTestCases()!=11:
    raise SystemExit('Expected eleven mounted runtime PostgreSQL checks')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun!=11 or not result.wasSuccessful():
    raise SystemExit('FAIL: all mounted runtime cases must execute without skips')
print('PASS: eleven actual app.main PostgreSQL checks, zero skips')
