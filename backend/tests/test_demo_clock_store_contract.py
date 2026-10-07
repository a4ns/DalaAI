"""Pure shared-row validation/assembly tests; not PostgreSQL transaction proof."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from app.core.auth_boundary import SystemRealClock
from app.demo_clock.clock import DemoClockSettings, DemoClockUnavailable
from app.demo_clock.postgres import build_domain_clock, PostgresDemoBusinessClock
from app.demo_clock.http import create_demo_clock_router

T0 = datetime(2026, 10, 7, tzinfo=timezone.utc)
INSTANCE = "00000000-0000-0000-0000-000000000002"


class StoreContractTests(unittest.TestCase):
    def setUp(self):
        self.connect = Mock(side_effect=AssertionError("Pure tests must not open PostgreSQL"))
        self.settings = DemoClockSettings(enabled=True, mode="demo", isolated_demo=True)
        self.clock = PostgresDemoBusinessClock(self.connect, settings=self.settings, instance_id=INSTANCE)
        self.row = {"instance_id": INSTANCE, "version": 7, "scale": 30,
            "real_anchor": T0, "domain_anchor": T0, "domain_start": T0,
            "domain_limit": T0 + timedelta(days=7), "synthetic": True}

    def test_default_is_wall_clock_without_db_or_instance_parsing(self):
        clock = build_domain_clock(DemoClockSettings(), connect=self.connect, instance_id="not-parsed")
        self.assertIsInstance(clock, SystemRealClock)
        self.assertIsNotNone(clock.now().tzinfo)
        self.connect.assert_not_called()

    def test_explicit_enabled_assembly_requires_existing_shared_instance(self):
        with self.assertRaises(ValueError):
            build_domain_clock(self.settings, instance_id=INSTANCE)
        with self.assertRaises(ValueError):
            build_domain_clock(self.settings, connect=self.connect, instance_id="bad")
        self.assertIsInstance(build_domain_clock(self.settings, connect=self.connect, instance_id=INSTANCE), PostgresDemoBusinessClock)
        self.connect.assert_not_called()

    def test_restored_mapping_has_persisted_identity_version_and_anchor(self):
        first = self.clock._snapshot(self.row, T0 + timedelta(seconds=10))
        second = PostgresDemoBusinessClock(self.connect, settings=self.settings, instance_id=INSTANCE)._snapshot(self.row, T0 + timedelta(seconds=10))
        self.assertEqual(first, second)
        self.assertEqual(first.business_now, T0 + timedelta(minutes=5))
        self.assertEqual(first.storage, "postgres_shared")
        self.assertEqual(first.revision, 7)

    def test_corrupt_bounds_naive_timestamp_horizon_or_rewind_fail_closed(self):
        for key, value in (("scale", 61), ("scale", True), ("version", -1), ("version", True),
                           ("domain_limit", T0 + timedelta(days=9)), ("domain_anchor", T0 - timedelta(seconds=1))):
            with self.subTest(key=key, value=value), self.assertRaises(DemoClockUnavailable):
                self.clock._snapshot(dict(self.row, **{key: value}), T0)
        for when in (T0-timedelta(seconds=1), T0+timedelta(days=8)):
            with self.assertRaises(DemoClockUnavailable):
                self.clock._snapshot(self.row, when)
        with self.assertRaises(ValueError):
            self.clock._snapshot(self.row, datetime(2026, 10, 7))

    def test_body_deadline_configuration_is_finite_and_bounded(self):
        for value in (0, -1, 11, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                create_demo_clock_router(Mock(), body_deadline_seconds=value)


if __name__ == "__main__":
    unittest.main()
