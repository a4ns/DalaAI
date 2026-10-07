import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_mobile as runner


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.contract = {"required_test_ids": ["C-110-HERO", "C-110-REWORK"], "expected_test_count": 2}
        self.data = {"status": "passed", "errors": 0, "discovered": 2, "results": [
            {"ids": ["C-110-HERO"], "status": "passed", "expected_status": "passed", "retry": 0},
            {"ids": ["C-110-REWORK"], "status": "passed", "expected_status": "passed", "retry": 0},
        ]}

    def test_exact_core_pass(self):
        self.assertEqual(runner.verify_results(self.data, self.contract)["tests_passed"], 2)

    def test_skip_is_failure(self):
        self.data["results"][1]["status"] = "skipped"
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_expected_failure_is_failure(self):
        self.data["results"][1]["status"] = "failed"
        self.data["results"][1]["expected_status"] = "failed"
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_retry_or_flake_is_failure(self):
        self.data["results"][1]["retry"] = 1
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_missing_test_is_failure(self):
        self.data["results"].pop()
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_missing_id_is_failure(self):
        self.data["results"][1]["ids"] = []
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_duplicate_id_is_failure(self):
        self.data["results"][0]["ids"].append("C-110-REWORK")
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_suite_error_is_failure(self):
        self.data["errors"] = 1
        with self.assertRaises(runner.GateError):
            runner.verify_results(self.data, self.contract)

    def test_production_project_cannot_be_cleaned(self):
        with self.assertRaises(runner.GateError):
            runner.compose_command("dalaai-demo")
        self.assertIn("dalaai-ci-1234567890abcdef", runner.compose_command("dalaai-ci-1234567890abcdef"))

    def test_source_path_cannot_escape(self):
        with self.assertRaises(runner.GateError):
            runner.owned_source("../../outside")


if __name__ == "__main__":
    unittest.main()
