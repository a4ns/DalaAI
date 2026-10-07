"""Pinned C1 historical export -> offline C4 report facts; no application access."""
import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path

import c4_report_examples as report

SOURCE_COMMIT = '8af3897f03aa2f41f0af07ec74ec2c807a4a535a'
HISTORICAL_EXPORT_COMMIT = '5775d6f6aa8e1bbf8796e7ba36c9ada6f1edd6e7'
SOURCE_PATH = 'data/synthetic/generated/v1/history.json'
SOURCE_HASH = '7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1'
FULL_START = '2026-06-30T19:00:00Z'
DEMO_START = '2026-09-26T19:00:00Z'
END = '2026-09-30T19:00:00Z'
DEMO_ORDER = 'a6ee1c96-9473-5998-bd83-476b161be6eb'
ROOT = Path(__file__).resolve().parents[2]


SOURCE_COUNTS = dict(ai_assessments=0,brigades=3,employees=17,equipment=25,
    material_writeoffs=568,materials=40,order_events=3510,orders=540,photos=444,
    reviews=568,sections=4,submissions=568,work_codes=20)


def history_file(path=None):
    """Explicit CLI path, test environment path, then public generator default."""
    return Path(path or os.environ.get('C4_HISTORY') or ROOT/SOURCE_PATH)


def load_history(path=None):
    selected=history_file(path)
    try:
        raw=selected.read_bytes()
    except FileNotFoundError:
        raise ValueError('history file missing; run public C1 generator, pass --history, or set C4_HISTORY') from None
    history=decode_history(raw)
    # This is the fixed profile of the exact pinned bytes, not an extra input file.
    manifest=dict(history_sha256=SOURCE_HASH,synthetic=True,counts=SOURCE_COUNTS.copy())
    return history,manifest


def decode_history(raw):
    report.require(hashlib.sha256(raw).hexdigest() == SOURCE_HASH, 'source.history_hash_mismatch')
    data = json.loads(raw, parse_float=Decimal)
    metadata = data['metadata']
    report.require(metadata['synthetic'] is True and metadata['purpose'] == 'offline_historical_export', 'source.synthetic_only')
    report.require(metadata['as_of'] == END, 'source.as_of')
    report.require(metadata['window']['start_inclusive'] == FULL_START and metadata['window']['end_exclusive'] == END, 'source.window')
    report.require(data['ai_assessments'] == [], 'source.ai_absence_changed')
    report.require(all(p['artifact_available'] is False for p in data['photos']), 'source.photo_placeholder_changed')
    return data


def adapt(history, manifest, *, start=DEMO_START, end=END):
    """Map a verified immutable full export; never infer completeness from pages.

    Call load_history/decode_history first. This helper is intentionally not a
    general-purpose importer, historical snapshot reconstructor or schema validator.
    """
    report.require(manifest['history_sha256'] == SOURCE_HASH and manifest['synthetic'] is True, 'manifest.source_mismatch')
    for table, count in manifest['counts'].items():
        report.require(len(history[table]) == count, 'manifest.count_mismatch')
    report.require(report.timestamp(FULL_START) <= report.timestamp(start) < report.timestamp(end) <= report.timestamp(END), 'period.outside_source')
    orders = copy.deepcopy(history['orders'])
    submissions = copy.deepcopy(history['submissions'])
    sub_ids = {s['id'] for s in submissions}
    report.require(all(r['submission_id'] in sub_ids for r in history['reviews']), 'source.orphan_review')
    report.require(all(a['submission_id'] in sub_ids for a in history['ai_assessments']), 'source.orphan_assessment')
    for order in orders:
        order['domain_now'] = history['metadata']['as_of']
        order['is_overdue'] = order['status'] in report.LIVE and report.timestamp(order['due_at']) < report.timestamp(END)
    for sub in submissions:
        sub['reviews'] = copy.deepcopy([r for r in history['reviews'] if r['submission_id'] == sub['id']])
        sub['assessments'] = copy.deepcopy([a for a in history['ai_assessments'] if a['submission_id'] == sub['id']])
    facts = dict(schema_version='c4-report-facts/1', synthetic=True,
        source_base_sha=SOURCE_COMMIT, contract_sha256=history['metadata']['core_contract_sha256'],
        coverage=dict(kind='frozen_complete_synthetic',scope_section_ids=[s['id'] for s in history['sections']],as_of=END),
        period=dict(start=start,end=end,display_offset='+05:00'),
        orders=orders, submissions=submissions, materials=copy.deepcopy(history['materials']))
    report.validate(facts)
    return facts


def compact_totals(facts):
    """Exact numerator/denominator plus ID-list hashes for independent C3 check."""
    result = report.summary(facts)
    reviews = {r['id']:r for s in facts['submissions'] for r in s['reviews']}
    totals = {k.removesuffix('_ids')+'_count':len(v) for k,v in result.items() if k.endswith('_ids')}
    totals['human_score'] = dict(cohort_count=result['human_scores']['cohort_count'],
        scored_count=result['human_scores']['scored_count'], unscored_count=result['human_scores']['unscored_count'],
        numerator=sum(reviews[i]['final_score'] for i in result['human_scores']['scored_review_ids']),
        denominator=result['human_scores']['scored_count'], mean=result['human_scores']['mean'])
    totals['on_time'] = {k:result['timeliness'][k] for k in ('numerator','denominator')}
    totals['source_id_sha256'] = {k:hashlib.sha256(json.dumps(v,separators=(',',':')).encode()).hexdigest() for k,v in result.items() if k.endswith('_ids')}
    return totals


def json_bytes(data):
    # Current pinned C1 quantities are JSON integers; no precision-losing conversion.
    def encode(value):
        if isinstance(value,Decimal):
            return str(value)
        raise TypeError(type(value).__name__)
    return (json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,default=encode)+'\n').encode('utf-8')


def build_samples(output_dir, *, history_path=None, code_sha=None):
    if code_sha is not None:
        report.require(len(code_sha)==40 and all(c in "0123456789abcdef" for c in code_sha), "code_sha.invalid")
    history, source_manifest = load_history(history_path)
    facts = adapt(history,source_manifest)
    full = adapt(history,source_manifest,start=FULL_START)
    order = next(o for o in facts['orders'] if o['id']==DEMO_ORDER)
    order_subs = [s for s in facts['submissions'] if s['order_id']==DEMO_ORDER]
    photo_ids = {p for s in order_subs for p in s['payload']['after_photo_ids']}
    event_trace = [e for e in history['order_events'] if e['order_id']==DEMO_ORDER]
    material_ids = {m['material_id'] for s in order_subs for m in s['payload']['materials']}
    actor_ids = {order['created_by'],order['assignment']['executor_id']} | {s['submitted_by'] for s in order_subs}
    sample = dict(synthetic=True, source_commit=SOURCE_COMMIT, source_history_sha256=SOURCE_HASH,
        period=facts['period'], coverage=facts['coverage'],
        order=dict(order=order, submissions=order_subs,
                   materials=[m for m in facts['materials'] if m['id'] in material_ids],
                   actors=[a for a in history['employees'] if a['id'] in actor_ids],
                   photo_placeholders=[p for p in history['photos'] if p['id'] in photo_ids],
                   order_events=event_trace), shift_summary=report.summary(facts))
    generated_at=datetime.now(timezone.utc).isoformat()
    # Existing renderer preserves source IDs, long text, modes, nulls and units.
    order_html=report.render_order(facts,DEMO_ORDER)
    shift_html=report.render_shift(facts)
    # Add conspicuous C1 provenance/placeholder disclosure to both existing reports.
    disclosure='<p>Источник C1: '+SOURCE_COMMIT+'; history SHA-256: '+SOURCE_HASH+'</p><p>Фото: только синтетические метаданные; image bytes отсутствуют. AI assessments отсутствуют; job state неизвестен. Scope: все четыре вымышленных участка, без проверки прав приложения.</p>'
    order_html=order_html.replace('</h1>','</h1>'+disclosure,1)
    shift_html=shift_html.replace('</h1>','</h1>'+disclosure,1)
    payloads={'order-521.html':order_html.encode(), 'period-september-27-30.html':shift_html.encode(),
              'report-source-trace.json':json_bytes(sample)}
    build=dict(synthetic=True, evidence_level='offline_report_from_pinned_synthetic_history',
        generated_at_real_utc=generated_at,
        report_code_sha=code_sha,
        report_code_sha_status='caller_supplied_provenance' if code_sha else 'not_supplied_source_archive_supported',
        report_source_sha256={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('c4_c1_history_report.py','c4_report_examples.py')},
        historical_export_commit=HISTORICAL_EXPORT_COMMIT,
        source_commit=SOURCE_COMMIT, source_path=SOURCE_PATH, source_history_sha256=SOURCE_HASH,
        source_counts=source_manifest['counts'], input_as_of=END, selected_order_id=DEMO_ORDER,
        sample_period=facts['period'], sample_totals=compact_totals(facts), full_period=dict(start=FULL_START,end=END),
        full_period_totals=compact_totals(full),
        artifacts={name:dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)) for name,data in payloads.items()},
        not_run=['DB import','HTTP/report API','runtime authorization','real model','image bytes','phone','visual browser/PDF/print'])
    output_dir.mkdir(parents=True,exist_ok=True)
    for name,data in payloads.items():
        (output_dir/name).write_bytes(data)
    (output_dir/'manifest.json').write_bytes(json_bytes(build))
    return build


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--history',type=Path,help='Exact-hash C1 generated history; default data/synthetic/generated/v1/history.json')
    parser.add_argument('--code-sha',help='Optional explicit code provenance; no Git lookup is performed')
    args=parser.parse_args()
    result=build_samples(args.output_dir,history_path=args.history,code_sha=args.code_sha)
    print(json.dumps({'result':'PASS_OFFLINE_SYNTHETIC_ONLY','sample_totals':result['sample_totals'],'full_period_totals':result['full_period_totals']},ensure_ascii=False))
