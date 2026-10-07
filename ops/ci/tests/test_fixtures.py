import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fixtures


class FixturesTests(unittest.TestCase):
    def test_private_fresh_distinct_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            fixtures.prepare_private(root)
            master = (root / "master_pin").read_text().strip()
            executor = (root / "executor_pin").read_text().strip()
            self.assertEqual(len(master), 16)
            self.assertTrue(master.isdecimal())
            self.assertNotEqual(master, executor)
            self.assertGreaterEqual(len(set(master)), 3)
            self.assertGreaterEqual(len(set(executor)), 3)
            for path in root.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600 if path.name == ".fixture-owner" else 0o444)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertIn("@db:5432/naryadai", (root / "runtime_dsn").read_text())

    def test_credentials_can_be_delayed_until_after_dummy_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            fixtures.prepare_private(root, credentials=False)
            self.assertEqual({path.name for path in root.iterdir()}, {".fixture-owner"})
            fixtures.prepare_credentials(root)
            self.assertTrue((root / "master_pin").exists())
            with self.assertRaises(ValueError):
                fixtures.prepare_credentials(root)

    def test_existing_directory_not_touched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sentinel = root / "preserve"
            sentinel.write_text("existing user fixture")
            with self.assertRaises(ValueError):
                fixtures.prepare_private(root)
            self.assertEqual(sentinel.read_text(), "existing user fixture")

    def test_existing_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "secret"
            fixtures.write_private(path, "first")
            with self.assertRaises(FileExistsError):
                fixtures.write_private(path, "second")
            self.assertEqual(path.read_text(), "first")

    def test_tool_failure_never_discloses_output(self):
        with patch.object(fixtures.subprocess, "run") as run:
            run.return_value.returncode = 2
            run.return_value.stdout = b"pretend-secret-credential"
            with self.assertRaisesRegex(RuntimeError, "Fixture tool failed: openssl") as error:
                fixtures.run_private(["openssl", "pretend-secret-argument"])
            self.assertNotIn("pretend-secret", str(error.exception))

    def test_tls_does_not_use_global_trust(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "private"
            fixtures.prepare_private(root)
            with patch.object(fixtures, "run_private") as run:
                fixtures.prepare_tls(root)
            calls = [call.args[0] for call in run.call_args_list]
            certificate_calls = [call for call in calls if call[0] == "certutil"]
            self.assertEqual(len(certificate_calls), 2)
            for command in certificate_calls:
                self.assertIn(f"sql:{root}/browser-home/.pki/nssdb", command)
            config = (root / "tls" / "root.cnf").read_text()
            self.assertIn("nameConstraints = critical", config)
            self.assertIn("permitted;DNS:localhost", config)
            self.assertNotIn("sudo", " ".join(" ".join(x) for x in calls))


if __name__ == "__main__":
    unittest.main()
