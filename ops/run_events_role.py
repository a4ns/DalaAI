"""Run all 10 unchanged author order_events cases through the restricted login."""

import os
from pathlib import Path
import sys
import unittest

if not os.environ.get("DALA_TEST_DATABASE_URL"):
    raise SystemExit("NOT_RUN: disposable PostgreSQL DSN required")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "backend/tests")]
import test_order_events_postgres as author
from test_persistence_role import ApplicationRoleTests


class RuntimeFixtureView:
    """Expose the runtime connection to services; keep fixture helpers owner-bound."""
    def __init__(self, fixture):
        self.fixture = fixture

    def connect(self):
        return self.fixture.runtime_connect()

    def __getattr__(self, name):
        return getattr(self.fixture, name)


class RestrictedOrderEventsTests(author.OrderEventsPostgresTests):
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
        self.service = author.OrderEventService(self.fixture.connect, real_clock=self.fixture.real)


suite = unittest.defaultTestLoader.loadTestsFromTestCase(RestrictedOrderEventsTests)
if suite.countTestCases() != 10:
    raise SystemExit("Expected all 10 order_events cases")
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != 10 or not result.wasSuccessful():
    raise SystemExit("FAIL: restricted-role order_events must execute all 10 cases without skips")
print("PASS: 10 restricted-role order_events cases, zero skips")
