"""Regression for GitHub expression contexts; YAML parsing alone cannot catch this."""
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[3] / '.github/workflows/mobile-e2e.yml'


class WorkflowContextTests(unittest.TestCase):
    def test_runner_context_not_used_in_job_env(self):
        text = WORKFLOW.read_text()
        blocks = re.findall(r'^    env:\n((?:^      .*\n)+)', text, flags=re.MULTILINE)
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertNotIn('runner.', block)

    def test_browser_paths_are_assigned_at_step_runtime(self):
        text = WORKFLOW.read_text()
        self.assertEqual(text.count('name: Set isolated browser installation path'), 2)
        self.assertEqual(text.count('"$RUNNER_TEMP" >> "$GITHUB_ENV"'), 2)


if __name__ == '__main__':
    unittest.main()
