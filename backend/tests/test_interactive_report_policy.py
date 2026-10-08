"""Explicit report-purpose authorization; local policy files and SQLite only."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from app.ai.demo_policy import (build_interactive_demo_policy, load_interactive_demo_policy,
    INTERACTIVE_PURPOSE, INTERACTIVE_REPORTS_PURPOSE, PROCESSING_DISCLOSURE,
    REPORTS_PROCESSING_DISCLOSURE)
from app.ai.model_adapter import DemoProjectContext
from app.ai.model_budget import SqliteBudgetLedger
from app.ai.models import InputValidationError
from app.ai.openai_runtime import openai_demo_budget, openai_demo_settings


class InteractiveReportPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = openai_demo_settings()
        self.project = DemoProjectContext('DalaAI', 'report-policy-test')
        self.ledger = SqliteBudgetLedger(self.root / 'budget.sqlite3', openai_demo_budget())

    def policy(self, **options):
        return build_interactive_demo_policy(project_id=self.project.project_id,
            instance_id=self.project.instance_id, settings=self.settings, **options)

    def load(self, policy):
        return load_interactive_demo_policy(policy, settings=self.settings, ledger=self.ledger,
            project_context=self.project, runtime_mode='demo')

    def test_default_stays_closure_only_and_explicit_extension_changes_only_purpose_disclosure(self):
        legacy = self.policy()
        self.assertEqual(legacy, self.policy(include_grounded_reports=False))
        self.assertEqual(legacy['purpose'], INTERACTIVE_PURPOSE)
        self.assertEqual(legacy['processing_disclosure'], PROCESSING_DISCLOSURE)
        combined = self.policy(include_grounded_reports=True)
        self.assertEqual(combined['purpose'], INTERACTIVE_REPORTS_PURPOSE)
        self.assertEqual(combined['processing_disclosure'], REPORTS_PROCESSING_DISCLOSURE)
        self.assertEqual({key for key in combined if combined[key] != legacy[key]},
                         {'purpose', 'processing_disclosure'})

    def test_purpose_cannot_be_relabelled_without_the_matching_disclosure(self):
        legacy = self.policy()
        combined = self.policy(include_grounded_reports=True)
        for altered in (dict(legacy, purpose=INTERACTIVE_REPORTS_PURPOSE),
                        dict(combined, purpose=INTERACTIVE_PURPOSE),
                        dict(combined, purpose='all_requests'),
                        dict(combined, authenticated_submissions_only=False)):
            with self.subTest(altered=altered['purpose']):
                with self.assertRaises(InputValidationError):
                    self.load(altered)

    def test_extension_uses_existing_budget_without_reset_or_new_approval(self):
        now = datetime(2026, 10, 8, 5, tzinfo=timezone.utc).timestamp()
        token = self.ledger.reserve(now=now)
        self.ledger.finish(token, 'valid')
        before = self.ledger.counters()
        legacy = self.load(self.policy())
        combined = self.load(self.policy(include_grounded_reports=True))
        self.assertEqual(legacy.approval_id, combined.approval_id)
        self.assertEqual(legacy.expires_at, combined.expires_at)
        self.assertEqual(self.ledger.counters(), before)
        self.assertEqual(before['calls_reserved'], 1)

    def test_opt_in_requires_an_actual_boolean(self):
        for value in (1, 0, 'true', None):
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                self.policy(include_grounded_reports=value)

    def test_operator_cli_never_upgrades_existing_closure_file(self):
        repo = Path(__file__).resolve().parents[2]
        output = self.root / 'policy.json'
        command = [sys.executable, str(repo / 'scripts/prepare_interactive_demo_policy.py'),
            '--backend', str(repo / 'backend'), '--project-id', self.project.project_id,
            '--instance-id', self.project.instance_id, '--output', str(output),
            '--confirm-owner-authorized-demo-processing']
        first = subprocess.run(command, capture_output=True, check=False)
        self.assertEqual(first.returncode, 0)
        original = output.read_bytes()
        self.assertEqual(json.loads(original)['purpose'], INTERACTIVE_PURPOSE)
        rejected = subprocess.run(command + ['--include-grounded-reports'], capture_output=True, check=False)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(output.read_bytes(), original)
        new_output = self.root / 'combined-policy.json'
        command[command.index(str(output))] = str(new_output)
        created = subprocess.run(command + ['--include-grounded-reports'], capture_output=True, check=False)
        self.assertEqual(created.returncode, 0)
        combined = json.loads(new_output.read_bytes())
        self.assertEqual(combined['purpose'], INTERACTIVE_REPORTS_PURPOSE)
        self.assertIn(REPORTS_PROCESSING_DISCLOSURE.encode(), created.stdout)
        self.load(combined)


if __name__ == '__main__':
    unittest.main()
