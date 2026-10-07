"""Mandatory real PostgreSQL gate: absent DSN, wrong count or skips fail closed."""
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: DALA_TEST_DATABASE_URL is required for Web Push PostgreSQL gate')
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
suite=unittest.defaultTestLoader.discover(str(ROOT/'backend/tests'),pattern='test_push_postgres.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun!=9 or result.skipped or not result.wasSuccessful():
    raise SystemExit('FAIL: Web Push PostgreSQL gate requires 9 passing tests and zero skips')
print('PASS: 9 real PostgreSQL Web Push tests, zero skips; no external sends')
