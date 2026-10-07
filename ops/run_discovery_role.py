"""Run all 13 unchanged author discovery cases through the restricted login."""

import os
from pathlib import Path
import sys
import unittest

if not os.environ.get("DALA_TEST_DATABASE_URL"):
    raise SystemExit("NOT_RUN: disposable PostgreSQL DSN required")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
import test_discovery_postgres as author
from test_persistence_role import ApplicationRoleTests


class RuntimeFixtureView:
    """Expose the runtime connection to services; keep fixture helpers owner-bound."""
    def __init__(self, fixture):
        self.fixture = fixture

    def connect(self):
        return self.fixture.runtime_connect()

    def __getattr__(self, name):
        return getattr(self.fixture, name)


class RestrictedDiscoveryTests(author.DiscoveryPostgresTests):
    @classmethod
    def setUpClass(cls):
        ApplicationRoleTests.setUpClass()
        cls.addClassCleanup(ApplicationRoleTests.doClassCleanups)

    def setUp(self):
        fixture = ApplicationRoleTests("test_runtime_login_is_nonowner_and_nonprivileged")
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        fixture.test_runtime_login_is_nonowner_and_nonprivileged()
        self.fixture = RuntimeFixtureView(fixture)
        self.service = author.DiscoveryService(
            self.fixture.connect, domain_clock=self.fixture.domain, real_clock=self.fixture.real,
            dictionary_policy=author.WorkloadPolicy(author.POLICY_NAME),
        )


suite = unittest.defaultTestLoader.loadTestsFromTestCase(RestrictedDiscoveryTests)
if suite.countTestCases() != 13:
    raise SystemExit("Expected all 13 discovery cases")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != 13 or not result.wasSuccessful():
    raise SystemExit("FAIL: restricted-role discovery must execute all 13 cases without skips")
print("PASS: 13 restricted-role discovery cases, zero skips")
