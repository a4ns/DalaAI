"""Input-only subprocess. No imports or access to evaluator labels/manifest.

Only the repository's deterministic rules can execute. There is deliberately no
provider selection, external plugin loading, credentials or network operation.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
from time import perf_counter_ns
from uuid import NAMESPACE_URL, uuid5

from .io import read_jsonl, write_jsonl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.ai.models import ClosureInput, EvidenceContext, Material, PhotoEvidence  # noqa: E402
from app.ai.rules import assess_rules  # noqa: E402

INPUT_KEYS = {'case_id', 'closure', 'context'}
CLOSURE_KEYS = {'order_id', 'submission_id', 'assignment_revision', 'order_type',
                'problem_description', 'work_description', 'work_code_id', 'materials', 'after_photo_ids'}
CONTEXT_KEYS = {'current_order_id', 'current_submission_id', 'current_assignment_revision',
                'current_status', 'submission_completeness', 'missing_evidence',
                'work_code_ids', 'material_ids', 'photos'}
PHOTO_KEYS = {'id', 'order_id', 'submission_id', 'assignment_revision', 'purpose', 'file_valid'}


def typed_input(row: dict) -> tuple[ClosureInput, EvidenceContext]:
    """Exact allowlist prevents expected labels/notes reaching a detector payload."""
    if set(row) != INPUT_KEYS or not isinstance(row['case_id'], str):
        raise ValueError('input envelope fields invalid')
    data, context = row['closure'], row['context']
    if type(data) is not dict or set(data) != CLOSURE_KEYS:
        raise ValueError('closure fields invalid')
    if type(context) is not dict or set(context) != CONTEXT_KEYS:
        raise ValueError('context fields invalid')
    if any(type(m) is not dict or set(m) != {'material_id', 'quantity'} for m in data['materials']):
        raise ValueError('material fields invalid')
    if any(type(p) is not dict or set(p) != PHOTO_KEYS for p in context['photos']):
        raise ValueError('photo fields invalid')
    closure = ClosureInput(**{**data,
        'materials': tuple(Material(m['material_id'], Decimal(m['quantity'])) for m in data['materials']),
        'after_photo_ids': tuple(data['after_photo_ids'])})
    evidence = EvidenceContext(**{**context,
        'missing_evidence': tuple(context['missing_evidence']),
        'work_code_ids': None if context['work_code_ids'] is None else frozenset(context['work_code_ids']),
        'material_ids': None if context['material_ids'] is None else frozenset(context['material_ids']),
        'photos': tuple(PhotoEvidence(**p) for p in context['photos'])})
    return closure, evidence


def predict_one(row: dict, detector=assess_rules) -> dict:
    started = perf_counter_ns()
    result = {'case_id': row.get('case_id'), 'gate_decision': 'invalid',
              'semantic_decision': 'invalid', 'fallback': None, 'mode': None,
              'error_type': None, 'gates': [], 'score': None, 'model': None}
    try:
        data, context = typed_input(row)
        assessment, report = detector(data, context,
            assessment_id=str(uuid5(NAMESPACE_URL, 'dalaai-eval-assessment/' + row['case_id'])),
            created_at=datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc))
        wire = assessment.to_wire()
        if wire['mode'] != 'rules_fallback' or wire['score'] is not None or wire['model'] is not None:
            raise ValueError('unexpected rules output')
        if not report.gates or any(g.status not in ('pass', 'fail', 'unknown') for g in report.gates):
            raise ValueError('invalid gate report')
        result.update(gate_decision='gate_permit' if report.closure_permitted else 'gate_block',
                      semantic_decision='abstain', fallback=True, mode=wire['mode'],
                      fallback_reason=wire['fallback_reason'], recommendation=wire['recommendation'],
                      stale=wire['stale'], gates=[{'code': g.code, 'status': g.status} for g in report.gates])
    except Exception as error:
        # Keep one failed episode in the denominator. Never leak raw payload/error text.
        result['error_type'] = type(error).__name__
    result['latency_ms'] = (perf_counter_ns() - started) / 1_000_000
    return result


def predict_file(inputs: Path, output: Path) -> None:
    rows = read_jsonl(inputs)
    ids = [r.get('case_id') for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate input case_id')
    write_jsonl(output, (predict_one(row) for row in rows))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    predict_file(args.inputs, args.output)


if __name__ == '__main__':
    main()
