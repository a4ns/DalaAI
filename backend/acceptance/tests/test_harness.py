"""Harness safety/unit checks. Passing these NEVER certifies the real API gate."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from vertical_acceptance.fixtures import command, create_order_command, submission_payload
from vertical_acceptance.support import file_inventory, require_local_dsn, route_inventory, schema_name


class HarnessSelfTests(unittest.TestCase):
    def test_only_owned_schema_names_accepted(self):
        self.assertEqual(schema_name("vertical_acceptance_" + "a" * 32), "vertical_acceptance_" + "a" * 32)
        for value in ("public", "a6_test_123", "vertical_acceptance_x", "vertical_acceptance_" + "a" * 32 + ";DROP SCHEMA public"):
            with self.assertRaises(ValueError):
                schema_name(value)

    def test_dsn_policy_allows_only_explicit_local_database(self):
        for host in ("localhost", "127.0.0.1", "::1", "/tmp/postgresql"):
            result = require_local_dsn("unused", lambda _: {"host": host, "dbname": "synthetic"})
            self.assertEqual(result["host"], host)
        for parsed in ({"host": "remote.example", "dbname": "test"}, {"dbname": "test"},
                       {"host": "localhost,remote", "dbname": "test"}, {"host": "localhost"},
                       {"host": "localhost", "dbname": "test", "hostaddr": "203.0.113.1"},
                       {"host": "localhost", "dbname": "test", "service": "external"}):
            with self.assertRaises(ValueError):
                require_local_dsn("unused", lambda _: parsed)

    def test_inventory_changes_when_source_changes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "app").mkdir()
            file = root / "app/example.py"
            file.write_text("x = 1\n")
            before = file_inventory(root)
            self.assertEqual(before, file_inventory(root))
            file.write_text("x = 2\n")
            self.assertNotEqual(before["tree_sha256"], file_inventory(root)["tree_sha256"])

    def test_route_inventory_keeps_methods_distinct(self):
        app = SimpleNamespace(routes=[SimpleNamespace(path="/api/v1/orders", methods={"GET", "POST"}),
                                      SimpleNamespace(path="/mount")])
        self.assertEqual(route_inventory(app), {("GET", "/api/v1/orders"), ("POST", "/api/v1/orders")})

    def test_commands_are_synthetic_no_fake_photo_evidence(self):
        created = create_order_command()
        self.assertEqual(created["payload"]["type"], "planned")
        self.assertEqual(created["expected_version"], 0)
        self.assertEqual(created["payload"]["before_photo_ids"], [])
        self.assertEqual(submission_payload()["after_photo_ids"], [])
        self.assertNotEqual(command("accept", 1)["operation_id"], command("accept", 1)["operation_id"])


if __name__ == "__main__":
    unittest.main()
