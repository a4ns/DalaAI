"""Four frozen provisioning PG cases plus explicit photo capability/repeat."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
import json

ROOT=Path(__file__).resolve().parents[1]
if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests'),str(ROOT/'ops/provision'),str(ROOT/'ops/provision/tests')]
from test_persistence_role import ApplicationRoleTests
ApplicationRoleTests.setUpClass()
try:
    os.environ.update(DALA_ACCEPTANCE_RUNTIME_DATABASE_URL=ApplicationRoleTests.runtime_dsn,
                      DALA_DEMO_TEST_BACKEND=str(ROOT/'backend'),DALA_ACCEPTANCE_DISPOSABLE='1')
    import test_demo_postgres as author
    class PhotoCapabilityTests(author.DemoPostgresTests):
        def test_explicit_photo_first_and_repeat(self):
            environment=dict(os.environ,DALA_DEMO_PHOTO_CAPABILITY_ALLOWED='1',
                DALA_DEMO_MASTER_PIN=author.PINS['master'],DALA_DEMO_EXECUTOR_PIN=author.PINS['executor'])
            command=[sys.executable,str(ROOT/'ops/provision/enable_photo_capability.py'),'--backend',str(self.backend),
                '--schema',self.schema,'--expected-database',self.database,'--bootstrap','--apply']
            for expected in ('PHOTO_CAPABILITY_VALIDATED','PHOTO_CAPABILITY_ALREADY_VALID'):
                result=subprocess.run(command,env=environment,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,'Photo capability helper failed')
                body=json.loads(result.stdout);self.assertEqual(body['status'],expected)
                self.assertFalse(body['roles_created']);self.assertFalse(body['storage_directory_created'])
            from app.runtime import validate_database
            validate_database(lambda:self.connect(runtime=True),photo_enabled=True)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(author.DemoPostgresTests)
    assert suite.countTestCases()==4
    suite.addTest(PhotoCapabilityTests('test_explicit_photo_first_and_repeat'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun!=5 or not result.wasSuccessful():raise SystemExit(1)
    print('PASS: four frozen provisioning and one photo capability PostgreSQL checks, zero skips')
finally:
    ApplicationRoleTests.doClassCleanups()
