"""Four mandatory real mounted physical-evidence CLOSE checks."""
import os
from pathlib import Path
import sys
import unittest
if not os.environ.get('DALA_TEST_DATABASE_URL'):raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
r=Path(__file__).resolve().parents[1];sys.path[:0]=[str(r/'backend'),str(r/'backend/tests')]
from test_photo_closure_postgres import PhotoClosureTests
suite=unittest.defaultTestLoader.loadTestsFromTestCase(PhotoClosureTests)
assert suite.countTestCases()==4
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun!=4 or not result.wasSuccessful():raise SystemExit(1)
print('PASS: four real mounted photo CLOSE integrity cases, zero skips')
