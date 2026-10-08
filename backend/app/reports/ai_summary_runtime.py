"""Optional host assembly; importing never reads secrets or makes a request.

The operator explicitly adds the report overlay after approving the combined
purpose. Existing closure-only startup and its durable budget are unchanged.
"""
from pathlib import Path
import os
import stat
from types import SimpleNamespace

from app.ai.demo_policy import INTERACTIVE_REPORTS_PURPOSE, load_interactive_demo_policy
from app.ai.model_adapter import DemoProjectContext, strict_json
from app.ai.model_budget import SqliteBudgetLedger
from app.ai.openai_runtime import OpenAIHTTPTransport, openai_demo_budget, openai_demo_settings
from app.reports.ai_summary import ReportModelAdapter
from app.worker_runtime import _read_file, _secret


def _private_ledger_path(value):
    path = Path(value)
    if not value or not path.is_absolute() or path.resolve() != path:
        raise ValueError('REPORT_BUDGET_PATH_INVALID')
    parent = path.parent.stat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
            or parent.st_mode & 0o077):
        raise ValueError('REPORT_BUDGET_DIRECTORY_INVALID')
    if path.exists():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o022):
            raise ValueError('REPORT_BUDGET_FILE_INVALID')
    return path


def build_report_model_adapter(environment, real_clock, *, runtime_mode):
    """Return factual fallback unless this process has the complete opt-in.

    No HTTP occurs here. The adapter claims/reserves only for an authenticated,
    scoped request after its own final eligibility checks. Load once at startup;
    changing host policy or secrets requires a deliberate process restart.
    """
    fallback = lambda reason='provider_not_configured': ReportModelAdapter(fallback_reason=reason)
    enabled = environment.get('DALA_AI_REPORT_MODEL_ENABLED', 'false')
    if enabled == 'false':
        return fallback()
    if enabled != 'true' or runtime_mode != 'demo':
        return fallback('provider_policy_unavailable')
    force_off = environment.get('DALA_MODEL_FORCE_OFF', 'false')
    if force_off == 'true':
        return fallback()
    if force_off != 'false':
        return fallback('provider_policy_unavailable')
    if not (environment.get('OPENAI_API_KEY') or environment.get('OPENAI_API_KEY_FILE')):
        return fallback()
    try:
        policy = strict_json(_read_file(environment.get('DALA_MODEL_APPROVAL_FILE', ''), 1048576),
                             cap=1048576)
        if type(policy) is not dict or policy.get('purpose') != INTERACTIVE_REPORTS_PURPOSE:
            return fallback('report_purpose_not_approved')
        settings, budget = openai_demo_settings(), openai_demo_budget()
        project = DemoProjectContext(environment.get('DALA_MODEL_PROJECT_ID', ''),
                                     environment.get('DALA_MODEL_INSTANCE_ID', ''))
        # Use the common policy validator before opening either secret or ledger.
        # This read-only policy view does not create a second budget implementation.
        approval = load_interactive_demo_policy(policy, settings=settings,
            ledger=SimpleNamespace(policy=budget), project_context=project, runtime_mode=runtime_mode)
        if approval.expires_at <= real_clock.now():
            return fallback('provider_policy_expired')
        key = _secret(environment, 'OPENAI_API_KEY', cap=4096)
        transport = OpenAIHTTPTransport(key)
        path = _private_ledger_path(environment.get('DALA_MODEL_BUDGET_PATH', ''))
        ledger = SqliteBudgetLedger(path, budget)
        return ReportModelAdapter.from_operator_policy(settings=settings, transport=transport,
            policy=policy, ledger=ledger, project_context=project, runtime_mode=runtime_mode,
            real_clock=real_clock)
    except Exception:
        # No paths, key bytes, policy contents or underlying provider errors escape.
        return fallback('provider_policy_unavailable')
