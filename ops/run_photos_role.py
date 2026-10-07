"""All twenty photo PG cases with a real restricted application login."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/tests')]
import test_photos_postgres as author
from test_persistence_role import ApplicationRoleTests

class RuntimeFixtureView:
    def __init__(self,fixture):self.fixture=fixture
    def connect(self):return self.fixture.runtime_connect()
    def __getattr__(self,name):return getattr(self.fixture,name)

class RestrictedPhotoTests(author.PhotoPostgresTests):
    @classmethod
    def setUpClass(cls):
        # One unchanged author probe reads driver types on the base fixture.
        author.fixtures.PostgresCommandTests.setUpClass()
        ApplicationRoleTests.setUpClass()
        cls.addClassCleanup(ApplicationRoleTests.doClassCleanups)
    def setUp(self):
        fixture=ApplicationRoleTests('test_runtime_login_is_nonowner_and_nonprivileged')
        self.addCleanup(fixture.doCleanups);fixture.setUp()
        with fixture.connect() as db:
            db.execute(fixture.sql.SQL('GRANT INSERT ON photos TO {}').format(fixture.sql.Identifier(fixture.runtime_role)))
        fixture.test_runtime_login_is_nonowner_and_nonprivileged()
        self.fixture=RuntimeFixtureView(fixture)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=author.PrivateFileStore(self.root)
        self.service=self.new_service()
suite=unittest.defaultTestLoader.loadTestsFromTestCase(RestrictedPhotoTests)
assert suite.countTestCases()==20
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun!=20 or not result.wasSuccessful():raise SystemExit(1)
print('PASS: twenty restricted-login photo cases, zero skips')
