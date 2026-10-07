import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_synthetic as runner


class SyntheticEvidenceTests(unittest.TestCase):
    def setUp(self):
        rows = [{"projectName": "android-emulation-pixel-9", "expectedStatus": "passed", "status": "expected",
                 "results": [{"status": "passed", "retry": 0}]} for _ in range(13)]
        self.data = {"errors": [], "suites": [{"suites": [{"specs": [{"tests": [row]} for row in rows]}]}]}

    def test_all_thirteen_pass(self):
        self.assertEqual(runner.verify_report(self.data)["tests_passed"], 13)

    def test_skip_fails(self):
        self.data["suites"][0]["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "skipped"
        with self.assertRaises(ValueError):
            runner.verify_report(self.data)

    def test_incomplete_count_fails(self):
        self.data["suites"][0]["suites"][0]["specs"].pop()
        with self.assertRaises(ValueError):
            runner.verify_report(self.data)

    def test_wrong_project_fails(self):
        self.data["suites"][0]["suites"][0]["specs"][0]["tests"][0]["projectName"] = "independent-source"
        with self.assertRaises(ValueError):
            runner.verify_report(self.data)

    def test_top_level_error_fails(self):
        self.data["errors"] = [{"message": "private raw failure"}]
        with self.assertRaises(ValueError):
            runner.verify_report(self.data)


if __name__ == "__main__":
    unittest.main()

class SyntheticPairSafetyTests(unittest.TestCase):
    def test_git_blob_hash_is_exact(self):
        import hashlib
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'input'
            path.write_bytes(b'hello\n')
            self.assertEqual(runner.blob_id(path), hashlib.sha1(b'blob 6\0hello\n').hexdigest())

    def test_symlink_is_rejected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'link'
            path.symlink_to(Path(temp) / 'other')
            with self.assertRaises(ValueError):
                runner.blob_id(path)

    def test_exact_five_paths_only(self):
        self.assertEqual(len(runner.HARNESS_FILES), 5)
        self.assertTrue(all(p == 'frontend/playwright.config.ts' or p.startswith('frontend/tests/')
                            for p in runner.HARNESS_FILES))
        self.assertTrue(all(len(x) == 40 for x in runner.HARNESS_FILES.values()))

    def test_old_desktop_project_is_rejected(self):
        data = {"errors": [], "suites": [{"specs": [{"tests": [{
            "projectName": "chromium-390", "expectedStatus": "passed", "status": "expected",
            "results": [{"status": "passed", "retry": 0}]}]} for _ in range(13)]}]}
        with self.assertRaises(ValueError):
            runner.verify_report(data)
