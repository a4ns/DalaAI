"""Optional report host wiring. Local placeholder secrets; never provider I/O."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.ai.demo_policy import build_interactive_demo_policy
from app.ai.model_budget import SqliteBudgetLedger, BudgetBlocked
from app.ai.openai_runtime import openai_demo_budget
from app.reports.ai_summary_runtime import build_report_model_adapter


class ReportModelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = SimpleNamespace(now=lambda: datetime(2026,10,8,6,tzinfo=timezone.utc))
        self.policy = self.root/'combined.json'
        self.ledger = self.root/'openai.sqlite3'
        self.env = {'DALA_AI_REPORT_MODEL_ENABLED':'true', 'OPENAI_API_KEY':'local-fixture-only',
            'DALA_MODEL_APPROVAL_FILE':str(self.policy), 'DALA_MODEL_BUDGET_PATH':str(self.ledger),
            'DALA_MODEL_PROJECT_ID':'DalaAI', 'DALA_MODEL_INSTANCE_ID':'host-test'}
        self.write_policy()

    def write_policy(self, **options):
        options.setdefault('include_grounded_reports', True)
        self.policy.write_text(json.dumps(build_interactive_demo_policy(
            project_id='DalaAI',instance_id='host-test',**options)))

    def build(self, env=None, mode='demo'):
        return build_report_model_adapter(self.env if env is None else env,
            self.clock,runtime_mode=mode)

    def assert_fallback(self, adapter, reason):
        self.assertIsNone(adapter.transport)
        self.assertEqual(adapter.fallback_reason,reason)

    def test_default_and_force_off_do_not_read_any_secret_policy_or_ledger(self):
        variants=[{},self.env|{'DALA_AI_REPORT_MODEL_ENABLED':'false'},
                  self.env|{'DALA_MODEL_FORCE_OFF':'true'},
                  {k:v for k,v in self.env.items() if k!='OPENAI_API_KEY'}]
        with patch('app.reports.ai_summary_runtime._read_file',side_effect=AssertionError()), \
                patch('app.reports.ai_summary_runtime._secret',side_effect=AssertionError()), \
                patch('app.reports.ai_summary_runtime.SqliteBudgetLedger',side_effect=AssertionError()):
            for env in variants:
                with self.subTest(env=tuple(env)):
                    self.assert_fallback(self.build(env),'provider_not_configured')
        self.assertFalse(self.ledger.exists())

    def test_closure_only_policy_denies_reports_before_key_or_ledger_read(self):
        self.write_policy(include_grounded_reports=False)
        original=self.policy.read_bytes()
        with patch('app.reports.ai_summary_runtime._secret',side_effect=AssertionError()):
            self.assert_fallback(self.build(),'report_purpose_not_approved')
        self.assertEqual(self.policy.read_bytes(),original)
        self.assertFalse(self.ledger.exists())

    def test_expired_or_changed_binding_does_not_open_key_or_ledger(self):
        with patch('app.reports.ai_summary_runtime._secret',side_effect=AssertionError()) as secret:
            self.write_policy(expires_at=datetime(2026,10,8,5,tzinfo=timezone.utc))
            self.assert_fallback(self.build(),'provider_policy_expired')
            self.write_policy()
            for changed in ({'DALA_MODEL_PROJECT_ID':'Other'}, {'DALA_MODEL_INSTANCE_ID':'other'},
                            {'DALA_AI_REPORT_MODEL_ENABLED':'yes'}, {'DALA_MODEL_FORCE_OFF':'yes'}):
                self.assert_fallback(self.build(self.env|changed),'provider_policy_unavailable')
            self.assert_fallback(self.build(mode='health'),'provider_policy_unavailable')
            secret.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_policy_read_is_single_bounded_no_follow_and_invalid_json_is_fixed(self):
        from app.worker_runtime import _read_file
        with patch('app.reports.ai_summary_runtime._read_file',wraps=_read_file) as reader:
            adapter=self.build()
        self.assertIsNotNone(adapter.transport)
        reader.assert_called_once_with(str(self.policy),1048576)
        link=self.root/'link.json';link.symlink_to(self.policy)
        self.assert_fallback(self.build(self.env|{'DALA_MODEL_APPROVAL_FILE':str(link)}),
                             'provider_policy_unavailable')
        for raw in ('{"purpose":1,"purpose":2}', 'x'*1048577):
            self.policy.write_text(raw)
            self.assert_fallback(self.build(),'provider_policy_unavailable')

    def test_key_file_is_exclusive_regular_and_bounded(self):
        key=self.root/'key';key.write_text('local-fixture-file\n')
        env={k:v for k,v in self.env.items() if k!='OPENAI_API_KEY'}|{'OPENAI_API_KEY_FILE':str(key)}
        self.assertIsNotNone(self.build(env).transport)
        self.assert_fallback(self.build(env|{'OPENAI_API_KEY':'duplicate'}),'provider_policy_unavailable')
        link=self.root/'key-link';link.symlink_to(key)
        self.assert_fallback(self.build(env|{'OPENAI_API_KEY_FILE':str(link)}),'provider_policy_unavailable')
        key.write_text('x'*4097)
        self.assert_fallback(self.build(env),'provider_policy_unavailable')

    def test_api_and_closure_share_existing_counters_concurrency_and_approval(self):
        from app.worker_runtime import build_model_adapter
        closure,_,_=build_model_adapter(self.env,self.clock,runtime_mode='demo')
        token=closure.ledger.reserve(now=self.clock.now().timestamp())
        before=closure.ledger.counters()
        report=self.build()
        self.assertIsNotNone(report.transport)
        self.assertEqual(report.ledger.path,closure.ledger.path)
        self.assertEqual(report.approval.approval_id,closure.approval.approval_id)
        self.assertEqual(report.ledger.counters(),before)
        with self.assertRaises(BudgetBlocked):
            report.ledger.reserve(now=self.clock.now().timestamp())
        closure.ledger.finish(token,'cancelled')
        self.assertEqual(report.ledger.counters()['calls_reserved'],1)
        self.assertEqual(self.build().ledger.counters(),report.ledger.counters())

    def test_ledger_requires_private_existing_parent_and_never_follows_link(self):
        adapter=self.build()
        before=adapter.ledger.counters()
        link=self.root/'ledger-link';link.symlink_to(self.ledger)
        for value in (str(link),str(self.root/'missing'/'ledger'),':memory:','relative.sqlite'):
            self.assert_fallback(self.build(self.env|{'DALA_MODEL_BUDGET_PATH':value}),
                                 'provider_policy_unavailable')
        self.root.chmod(0o755)
        try:self.assert_fallback(self.build(),'provider_policy_unavailable')
        finally:self.root.chmod(0o700)
        self.assertEqual(SqliteBudgetLedger(self.ledger,openai_demo_budget()).counters(),before)

    def test_constructor_is_inert_and_loader_runs_after_database_gate(self):
        from fastapi import APIRouter
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.runtime import RuntimeSettings
        captured=[]
        def capture(service):
            captured.append(service)
            return APIRouter()
        settings=RuntimeSettings(mode='demo',database_url='unused',allowed_origin='https://test.example')
        with patch('app.reports.ai_summary_routes.create_ai_summary_router',side_effect=capture), \
                patch('app.main.validate_database') as validate, \
                patch.dict(os.environ,self.env,clear=True), \
                patch('app.core.auth_boundary.SystemRealClock',return_value=self.clock), \
                patch('app.reports.ai_summary_runtime._read_file',wraps=__import__('app.worker_runtime',fromlist=['_read_file'])._read_file) as read:
            app=create_app(settings=settings,connect=lambda:None)
            read.assert_not_called();validate.assert_not_called()
            self.assertIsNone(captured[0].adapter.transport)
            with TestClient(app):
                validate.assert_called_once()
                self.assertTrue(app.state.runtime_ready)
                self.assertIsNotNone(captured[0].adapter.transport)
            self.assertFalse(app.state.runtime_ready)
        self.assertEqual(captured[0].adapter.ledger.counters()['calls_reserved'],0)

    def test_database_failure_cannot_read_or_activate_report_profile(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.runtime import RuntimeSettings
        settings=RuntimeSettings(mode='demo',database_url='unused',allowed_origin='https://test.example')
        with patch('app.main.validate_database',side_effect=ValueError('fixture')), \
                patch('app.reports.ai_summary_runtime.build_report_model_adapter') as loader:
            app=create_app(settings=settings,connect=lambda:None)
            with self.assertRaises(ValueError):
                with TestClient(app):pass
            loader.assert_not_called()
            self.assertFalse(app.state.runtime_ready)


if __name__=='__main__':unittest.main()
