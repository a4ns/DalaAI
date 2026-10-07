"""Hash-pinned offline C1 metrics. No DB, network, model or runtime endpoint.

Default input is the locally generated canonical file; --history accepts only
identical bytes from an explicitly supplied file. No Git objects are required. Traces are reproduced on
stdout with --trace, avoiding a second large published copy of the history.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path

from check_examples import summarize

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA = '5775d6f6aa8e1bbf8796e7ba36c9ada6f1edd6e7'
HISTORY_PATH = 'data/synthetic/v1/history.json'  # Historical provenance only.
GENERATED_PATH = 'data/synthetic/generated/v1/history.json'
GENERATOR_SHA = '8af3897f03aa2f41f0af07ec74ec2c807a4a535a'
HISTORY_SHA256 = '7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1'
DEFINITION_SHA = '2a65c80b94d92bd15112dd95d9498998431eb00c'
PERIODS = (
    ('full', '2026-06-30T19:00:00Z', '2026-09-30T19:00:00Z'),
    ('2026-07', '2026-06-30T19:00:00Z', '2026-07-31T19:00:00Z'),
    ('2026-08', '2026-07-31T19:00:00Z', '2026-08-31T19:00:00Z'),
    ('2026-09', '2026-08-31T19:00:00Z', '2026-09-30T19:00:00Z'),
)
STOCKS = {'awaiting_review', 'overdue_active'}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False) + '\n').encode()


def load_history(path=None):
    selected = Path(path) if path else ROOT / GENERATED_PATH
    if not selected.is_file():
        raise ValueError('canonical history missing; run python3 scripts/synthetic/generate.py --output ' + GENERATED_PATH + ' or pass --history <file>')
    raw = selected.read_bytes()
    if sha256(raw).hexdigest() != HISTORY_SHA256:
        raise ValueError('history hash mismatch; do not silently substitute a dataset')
    history = json.loads(raw)
    if history['metadata']['synthetic'] is not True or history['metadata']['as_of'] != PERIODS[0][2]:
        raise ValueError('unsupported C1 export profile')
    return history


def reduced(history, start, end):
    """Only complete pinned export; this is not a generic import/RBAC adapter."""
    return dict(marker='SYNTHETIC_METRIC_UNIT_ONLY', start=start, end=end,
                domain_as_of=history['metadata']['as_of'], snapshots_as_of=history['metadata']['as_of'],
                # The real read time satisfies the reduced-oracle input; it is
                # not a canonical source field or historical knowledge cutoff.
                # Deterministic output identifies capture by commit and hash.
                captured_at_real=datetime.now(timezone.utc).isoformat(), capture_complete=True, history_complete=True,
                allowed_section_ids=sorted(s['id'] for s in history['sections']),
                orders=history['orders'], submissions=history['submissions'], reviews=history['reviews'])


def exact_metric(metric):
    out = deepcopy(metric)
    out.pop('source_ids')
    out['excluded_from_eligible'] = 0
    out['exclusion_policy'] = 'eligible cohort only; missing values counted separately, outside-cohort records not silently dropped'
    if 'count' in out:
        out.update(status='ok', numerator=out['count'], denominator=None, eligible=out['count'], missing=0)
    if 'value' in out:
        n, d = out['numerator'], out['denominator']
        with localcontext() as context:
            context.prec = 40
            out['value_decimal_12_places'] = str((Decimal(n) / Decimal(d)).quantize(Decimal('.000000000001'))) if d else None
        del out['value']
        out['value_policy'] = 'exact numerator/denominator authoritative; decimal rounded half-even to 12 places'
    return out


def calculate(history):
    traces = {}
    periods = []
    for period_id, start, end in PERIODS:
        result = summarize(reduced(history, start, end))
        metrics = {}
        for name, metric in result.items():
            if name in STOCKS:
                continue
            trace_id = period_id + '/' + name
            ids = metric['source_ids']
            traces[trace_id] = ids
            metrics[name] = exact_metric(metric) | dict(
                trace_id=trace_id, source_ids_count=len(ids), source_ids_sha256=sha256(canonical(ids)).hexdigest(),
                source_ids_sample=ids[:2],
                source_table={'issued_orders':'orders','submitted_orders':'orders','submission_attempts':'submissions',
                              'closed_orders':'orders','rework_decisions':'reviews','human_score':'reviews',
                              'closed_on_time':'submissions','closed_with_rework':'orders','attempt_on_time':'submissions'}[name])
        periods.append(dict(period_id=period_id, start_inclusive=start, end_exclusive=end, metrics=metrics))
    full = summarize(reduced(history, PERIODS[0][1], PERIODS[0][2]))
    stocks = {}
    for name in sorted(STOCKS):
        ids = full[name]['source_ids']
        trace_id = 'as_of/' + name
        traces[trace_id] = ids
        stocks[name] = exact_metric(full[name]) | dict(trace_id=trace_id, source_ids_count=len(ids),
                                source_ids_sha256=sha256(canonical(ids)).hexdigest(), source_ids_sample=ids[:2], source_table='orders')
    output = dict(
        manifest_version='c3-c1-metrics/1', evidence_level='offline_synthetic_calculation',
        watermark='Синтетические данные — не история предприятия',
        source_commit=SOURCE_SHA, source_path=HISTORY_PATH, history_sha256=HISTORY_SHA256,
        source_commit_role='historical provenance only; no Git object required at runtime',
        generator_source_commit=GENERATOR_SHA, default_generated_path=GENERATED_PATH,
        source_schema_version=history['metadata']['schema_version'], definition_commit=DEFINITION_SHA,
        definition_path='docs/analytics/metric-definitions.md',
        display_timezone='Asia/Almaty', display_offset='+05:00',
        scope=dict(kind='entire_frozen_synthetic_export_not_a_user_authorization',
                   section_ids=sorted(s['id'] for s in history['sections'])),
        counts={name:len(history[name]) for name in ('orders','submissions','reviews','order_events','ai_assessments')},
        periods=periods, snapshot=dict(domain_as_of=history['metadata']['as_of'], metrics=stocks),
        trace=dict(canonicalization='UTF-8 sorted-key compact JSON plus final LF',
                   full_trace_sha256=sha256(canonical(traces)).hexdigest(),
                   reproduce='python3 docs/analytics/c1_metrics.py --trace all',
                   selection='--trace <trace_id> returns full eligible sorted UUID membership; human_score includes unscored IDs, filter final_score!=null for observed denominator; count denominator null means not a rate'),
        unsupported={
            'downtime':dict(value=None,status='unsupported_inputs',reason='No authoritative downtime intervals'),
            'repeat_fault_7d':dict(value=None,status='unsupported_inputs',reason='No validated repair/failure episodes and continuous seven-day follow-up'),
            'composite_rating':dict(value=None,status='unsupported_inputs',reason='No accepted complete component/cohort policy, difficulty/exposure or refusal adjudication'),
            'ai_quality':dict(value=None,status='no_assessment',reason='ai_assessments is empty; AI job state unknown'),
            'historical_month_end_stocks':dict(value=None,status='not_reconstructed',reason='Only export as_of snapshot used; month flows do not claim month-end stocks')},
        limits=['All scores and work facts are synthetic; no industrial, employee or model-quality claim',
                'Source IDs reproduce from pinned history; evaluator construction labels are never read',
                'No DB/API, live authorization, actual upload, deployment or phone test',
                'Missing input counts apply to this pinned complete profile, not arbitrary exports',
                'Human score partial means unscored closes are excluded from observed mean and counted'],
    )
    return output, traces


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path)
    parser.add_argument('--trace', help='all or a trace_id from the manifest')
    parser.add_argument('--check', action='store_true', help='compare calculated manifest with committed manifest')
    args = parser.parse_args()
    manifest, traces = calculate(load_history(args.history))
    if args.check:
        expected = json.loads(Path(__file__).with_name('c1-metrics-manifest.json').read_text())
        if manifest != expected:
            raise SystemExit('FAIL: committed metric manifest differs')
        print('PASS: exact pinned C1 metrics and trace hashes reproduce')
    elif args.trace:
        print(canonical(traces if args.trace == 'all' else traces[args.trace]).decode(), end='')
    else:
        print(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
