#!/usr/bin/env python3
"""Single unambiguous integration bundle, no edits to selected accepted baseline."""
import argparse
import os
from pathlib import Path
import sys
import unittest
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--baseline',default=str(root.parent/'dalaai-a3-workers'))
p.add_argument('--photos',default=str(root.parent/'dalaai-a2-photos'))
p.add_argument('--postgres',action='store_true')
a=p.parse_args()
if a.postgres and not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable DALA_TEST_DATABASE_URL required; no skipped green gate')
sys.path[:0]=[str(Path(a.baseline)/'backend'),str(root/'backend/tests'),str(Path(a.baseline)/'backend/tests')]
import app,app.ai,app.jobs
app.__path__.append(str(Path(a.photos)/'backend/app'))
app.ai.__path__.insert(0,str(root/'backend/app/ai'));app.jobs.__path__.insert(0,str(root/'backend/app/jobs'))
names=['test_provider_worker_postgres'] if a.postgres else [
    'test_model_adapter','test_model_process_budget','test_model_transport',
    'test_provider_worker_unit','test_camera_derivation','test_demo_policy']
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in names)
expected=8 if a.postgres else 90
if suite.countTestCases()!=expected:raise SystemExit(f'Expected {expected} tests, found {suite.countTestCases()}')
r=unittest.TextTestRunner(verbosity=2).run(suite)
if r.testsRun!=expected or r.skipped or not r.wasSuccessful():raise SystemExit(1)
