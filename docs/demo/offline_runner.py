#!/usr/bin/env python3
"""One-command synthetic evidence assembly. No app, network, Git or provider calls."""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'offline_sources.json'
ROOT = HERE.parents[1]
PRODUCT_GATES = ('live_api', 'database', 'browser_render', 'real_model',
                 'photo_bytes', 'push_delivery', 'physical_android', 'deployment')
SCORE = '''import json,sys
from pathlib import Path
from eval.dataset import verify_dataset,DATA
from eval.io import read_jsonl
from eval.metrics import score
out=Path(sys.argv[1]); manifest=verify_dataset(); results={}
for split in ('dev','holdout'):
    labels=read_jsonl(DATA/manifest['splits'][split]['labels']['path'])
    results[split]=score(labels,read_jsonl(out/(split+'.predictions.jsonl')))
report={'evidence_level':'offline_synthetic_rules_only','dataset_version':manifest['dataset_version'],
        'splits':results,'model_enabled':'NOT_RUN','cost_usd':None,'paid_provider_calls':0,
        'code_provenance':'See offline-summary.json package SHAs and per-file hashes; no assembled Git SHA'}
(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\\n')
if any(r['fixture_gate_expectations']!='PASS' for r in results.values()):raise SystemExit(1)
print('PASS: 24 dev and 24 holdout synthetic rule episodes; real model NOT_RUN')
'''


class Blocked(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def checked_file(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise Blocked('unsafe source path')
    candidate = root / path
    if any(part.is_symlink() for part in (candidate, *candidate.parents)):
        raise Blocked('symlink source path: ' + relative)
    if not candidate.is_file():
        raise Blocked('missing required source: ' + relative)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise Blocked('source escaped root')
    return candidate


def verify_sources(root, manifest):
    if manifest.get('schema_version') != 1 or set(manifest.get('packages', {})) != {'C1', 'C2', 'C3', 'C4'}:
        raise Blocked('required C1/C2/C3/C4 source manifest missing or invalid')
    files = {}
    for package, spec in manifest['packages'].items():
        if not re.fullmatch('[0-9a-f]{40}', spec.get('source_sha', '')) or not spec.get('files'):
            raise Blocked('invalid package provenance: ' + package)
        for relative, expected in spec['files'].items():
            if relative in files:
                raise Blocked('duplicate source ownership: ' + relative)
            raw = checked_file(root, relative).read_bytes()
            if digest(raw) != expected:
                raise Blocked('source hash mismatch: ' + relative)
            files[relative] = raw
    return files


def clean_log(text, roots):
    for root, label in sorted(roots, key=lambda item: len(str(item[0])), reverse=True):
        text = text.replace(str(root), label)
    return text.replace(sys.executable, 'python3')


def unit_count(text):
    counts = re.findall(r'Ran (\d+) tests? in ', text)
    if len(counts) != 1 or int(counts[0]) == 0 or not re.search(r'\nOK\s*$', text) or 'skipped=' in text:
        raise ValueError('unit suite did not report one complete, unskipped OK result')
    return int(counts[0])


class InertHTML(HTMLParser):
    # Exact static stylesheet from the pinned C4 renderer; no arbitrary CSS accepted.
    SAFE_STYLE_SHA256 = '5e11cc4e8f0759da89e6617d6a57404da333753792a50d539b8aef38a0c9e1af'
    ALLOWED_TAGS = {'html', 'head', 'body', 'title', 'meta', 'style', 'header', 'footer',
                    'main', 'section', 'article', 'h1', 'h2', 'h3', 'p', 'pre', 'code',
                    'strong', 'em', 'b', 'i', 'br', 'ul', 'ol', 'li', 'table', 'thead',
                    'tbody', 'tr', 'td', 'th', 'caption', 'div', 'span'}
    ALLOWED_ATTRS = {'lang', 'charset', 'name', 'content', 'class', 'id', 'colspan', 'rowspan'}

    def __init__(self):
        super().__init__()
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        if tag not in self.ALLOWED_TAGS or any(k.lower() not in self.ALLOWED_ATTRS for k, _ in attrs):
            raise ValueError('active/external report content')
        if tag == 'meta':
            values = dict(attrs)
            if values != {'charset': 'utf-8'} and values != {'charset': 'UTF-8'} and not (
                    set(values) == {'name', 'content'} and values['name'] == 'viewport'):
                raise ValueError('unexpected report meta')
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def close(self):
        super().close()
        if self.in_style:
            raise ValueError('unclosed report style')

    def handle_data(self, text):
        if self.in_style and digest(text.encode('utf-8')) != self.SAFE_STYLE_SHA256:
            raise ValueError('active/external report style')


def verify_outputs(output):
    history = json.loads((output / 'c1/history.json').read_text())
    metrics = json.loads((output / 'c3/metrics.json').read_text())
    reports = json.loads((output / 'c4/manifest.json').read_text())
    evaluation = json.loads((output / 'c2/report.json').read_text())
    q = metrics['periods'][0]['metrics']; r = reports['full_period_totals']
    pairs = [('issued_orders', 'issued_order_count'), ('submitted_orders', 'submitted_order_count'),
             ('submission_attempts', 'submitted_submission_count'), ('closed_orders', 'closed_order_count'),
             ('rework_decisions', 'rework_review_count')]
    if any(q[a]['count'] != r[b] for a, b in pairs):
        raise ValueError('C3/C4 count disagreement')
    if any(q['human_score'][key] != r['human_score'][key] for key in ('numerator', 'denominator')):
        raise ValueError('C3/C4 human-score disagreement')
    if q['human_score']['missing'] != r['human_score']['unscored_count']:
        raise ValueError('C3/C4 null-score disagreement')
    if any(q['closed_on_time'][key] != r['on_time'][key] for key in ('numerator', 'denominator')):
        raise ValueError('C3/C4 on-time disagreement')
    for name, expected in reports['artifacts'].items():
        raw = checked_file(output / 'c4', name).read_bytes()
        if digest(raw) != expected['sha256'] or len(raw) != expected['bytes']:
            raise ValueError('C4 generated artifact digest mismatch')
        if name.endswith('.html'):
            parser = InertHTML()
            parser.feed(raw.decode('utf-8'))
            parser.close()
    if len(history['orders']) != 540 or history['ai_assessments'] != []:
        raise ValueError('unexpected canonical synthetic history')
    for split in evaluation['splits'].values():
        if split['fixture_gate_expectations'] != 'PASS' or split['mandatory_gates']['n_expected'] != 24:
            raise ValueError('incomplete C2 evaluation')
    return {'orders': len(history['orders']), 'submissions': len(history['submissions']),
            'synthetic_eval_episodes': 48, 'human_score_sum': r['human_score']['numerator'],
            'human_scored': r['human_score']['denominator'], 'human_unscored': r['human_score']['unscored_count'],
            'on_time': r['on_time'], 'c3_c4_cross_check': 'PASS', 'html_inert_markup_check': 'PASS',
            'visual_browser_check': 'NOT_RUN'}


def run(root, output, manifest_path=MANIFEST, timeout=120):
    if sys.version_info < (3, 12):
        raise Blocked('Python 3.12 or newer is required')
    root, output = root.resolve(), output.absolute()
    # Never overwrite existing evidence or traverse an existing output symlink.
    if output.exists() or output.is_symlink():
        raise Blocked('output directory already exists; choose a new path')
    if not output.parent.is_dir() or any(p.is_symlink() for p in (output.parent, *output.parents)):
        raise Blocked('output parent must exist and must not be a symlink')
    output.mkdir()
    summary = {'schema_version': 1, 'evidence_level': 'OFFLINE_SYNTHETIC_ONLY',
               'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'BLOCKED',
               'runner_sha256': digest(Path(__file__).read_bytes()),
               'python': sys.version.split()[0], 'git_required': False,
               'network_or_credentials_used': False, 'stages': [],
               'product_gates': {gate: 'NOT_RUN' for gate in PRODUCT_GATES}}
    status = 2
    try:
        if not manifest_path.is_file():
            raise Blocked('source manifest is missing')
        manifest = json.loads(manifest_path.read_text())
        summary['sources_manifest_sha256'] = digest(manifest_path.read_bytes())
        files = verify_sources(root, manifest)
        summary['packages'] = manifest['packages']
        summary['verified_source_files'] = len(files)
        for name in ('logs', 'c1', 'c2', 'c3', 'c4'):
            (output / name).mkdir()
        with tempfile.TemporaryDirectory(prefix='.offline-sources-', dir=output) as directory:
            work = Path(directory)
            for relative, raw in files.items():
                path = work / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            scratch = work / 'tmp'; scratch.mkdir()
            history = output / 'c1/history.json'
            env = {'PATH': '', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1',
                   'TMPDIR': str(scratch), 'C3_HISTORY_PATH': str(history), 'C4_HISTORY': str(history)}
            roots = [(work, '<WORK>'), (output, '<OUTPUT>'), (root, '<SOURCE>')]

            def stage(name, args, *, units=False, stdout_file=None):
                entry = {'id': name, 'status': 'FAIL', 'command': clean_log('python3 -B -s ' + ' '.join(args), roots)}
                summary['stages'].append(entry)
                command = [sys.executable, '-B', '-s', *args]
                try:
                    result = subprocess.run(command, cwd=work, env=env, text=True, capture_output=True, timeout=timeout)
                except subprocess.TimeoutExpired:
                    entry['reason'] = 'stage timeout'; raise ValueError('stage timeout: ' + name) from None
                log = clean_log(result.stdout + result.stderr, roots)
                (output / 'logs' / (name + '.txt')).write_text(log)
                entry.update(exit_code=result.returncode, log='logs/' + name + '.txt')
                if result.returncode:
                    raise ValueError('stage failed: ' + name)
                if units:
                    entry['tests_passed'] = unit_count(log)
                if stdout_file:
                    (output / stdout_file).write_text(result.stdout)
                entry['status'] = 'PASS'

            stage('c1-generate', ['scripts/synthetic/generate.py', '--output', str(history)])
            stage('c1-validate', ['scripts/synthetic/validate.py', str(history), '--manifest', str(history.with_name('history.manifest.json'))])
            stage('c1-tests', ['-m', 'unittest', 'discover', '-s', 'scripts/synthetic', '-p', 'test_*.py', '-v'], units=True)
            stage('c2-tests', ['-m', 'unittest', 'discover', '-s', 'eval/tests', '-p', 'test_*.py', '-v'], units=True)
            for split in ('dev', 'holdout'):
                stage('c2-predict-' + split, ['-m', 'eval.predict', '--inputs', 'eval/data/v1/inputs/' + split + '.jsonl',
                                             '--output', str(output / 'c2' / (split + '.predictions.jsonl'))])
            stage('c2-score', ['-c', SCORE, str(output / 'c2')])
            stage('c3-oracle', ['docs/analytics/check_examples.py'], units=True)
            stage('c3-check', ['docs/analytics/c1_metrics.py', '--history', str(history), '--check'])
            stage('c3-export', ['docs/analytics/c1_metrics.py', '--history', str(history)], stdout_file='c3/metrics.json')
            stage('c3-tests', ['-m', 'unittest', 'discover', '-s', 'docs/analytics', '-p', 'test_c1_metrics.py', '-v'], units=True)
            stage('c4-tests', ['-m', 'unittest', 'discover', '-s', 'docs/reports', '-p', 'test_*.py', '-v'], units=True)
            stage('c4-reports', ['docs/reports/c4_c1_history_report.py', '--history', str(history),
                                 '--output-dir', str(output / 'c4'), '--code-sha', manifest['packages']['C4']['source_sha']])
            try:
                if verify_sources(work, manifest) != files:
                    raise ValueError('copied source bytes changed')
            except Blocked:
                raise ValueError('copied source bytes changed after execution') from None
        try:
            if verify_sources(root, manifest) != files:
                raise ValueError('input source bytes changed')
        except Blocked:
            raise ValueError('input source bytes changed after execution') from None
        summary['counts'] = verify_outputs(output)
        summary['unit_tests_passed'] = sum(s.get('tests_passed', 0) for s in summary['stages'])
        summary.update(status='PASS', scope='Offline artifacts and synthetic tests only; not live MVP')
        status = 0
    except Blocked as error:
        summary['reason'] = str(error)
    except (OSError, ValueError, KeyError, TypeError) as error:
        summary.update(status='FAIL', reason=clean_log(str(error), [(output, '<OUTPUT>'), (root, '<SOURCE>')]))
        status = 1
    summary['finished_at'] = datetime.now(timezone.utc).isoformat()
    summary['artifacts'] = {p.relative_to(output).as_posix(): {'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size}
                            for p in sorted(output.rglob('*')) if p.is_file() and not p.is_symlink()}
    write_json(output / 'offline-summary.json', summary)
    (output / 'README.txt').write_text('OFFLINE SYNTHETIC ONLY. See offline-summary.json for exact inputs and results.\n'
        'C1 history, C2 mandatory rules evaluation, C3 arithmetic and C4 inert HTML reports.\n'
        'No application, DB, browser, model, phone, delivery or deployment acceptance.\n')
    return status, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True, help='New directory; parent must already exist')
    parser.add_argument('--source-root', type=Path, default=ROOT, help='Local source tree containing the four pinned public packages')
    args = parser.parse_args(argv)
    try:
        status, summary = run(args.source_root, args.output_dir)
        print(json.dumps({'status': summary['status'], 'evidence_level': summary['evidence_level'],
                          'unit_tests_passed': summary.get('unit_tests_passed'),
                          'reason': summary.get('reason'), 'product_gates': summary['product_gates']}, sort_keys=True))
        return status
    except Blocked as error:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(error), 'existing_evidence_modified': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
