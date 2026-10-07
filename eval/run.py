"""Freeze-verified two-stage offline evaluation. No real provider calls are supported."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import platform
import subprocess
import sys
from uuid import uuid4

from .dataset import DATA, verify_dataset
from .io import read_jsonl, sha256, write_json
from .metrics import score

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def run(output: Path, split: str = 'all', allow_dirty: bool = False) -> dict:
    manifest = verify_dataset()
    code_sha = git('rev-parse', 'HEAD')
    dirty = bool(git('status', '--porcelain', '--untracked-files=all', '--', 'backend/app/ai', 'eval'))
    if dirty and not allow_dirty:
        raise ValueError('commit implementation and frozen fixtures before recording exact-SHA evidence')
    output = output.resolve()
    if not output.is_relative_to((ROOT / 'eval' / 'runs').resolve()):
        raise ValueError('run output must be below eval/runs')
    if output.exists():
        raise ValueError('run output already exists; evidence is append-only')
    output.mkdir(parents=True)
    splits = ('dev', 'holdout') if split == 'all' else (split,)
    results = {}
    for name in splits:
        entry = manifest['splits'][name]
        prediction_path = output / (name + '.predictions.jsonl')
        # Child gets exactly the input path and output path, never labels or case notes.
        subprocess.run([sys.executable, '-m', 'eval.predict', '--inputs',
                        str(DATA / entry['inputs']['path']), '--output', str(prediction_path)],
                       cwd=ROOT, check=True)
        # Expected decisions are read only after inference has finished.
        labels = read_jsonl(DATA / entry['labels']['path'])
        results[name] = score(labels, read_jsonl(prediction_path))
        results[name]['prediction_sha256'] = sha256(prediction_path)
    report = {
        'schema_version': '1', 'run_id': 'closure-eval-' + str(uuid4()),
        'executed_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'code_sha': code_sha, 'working_tree_dirty': dirty,
        'evidence_level': 'synthetic_local_rules_unit', 'python': platform.python_version(),
        'dataset_version': manifest['dataset_version'], 'dataset_manifest_sha256': sha256(DATA / 'manifest.json'),
        'dataset_hashes': manifest['splits'], 'dataset_seed': None,
        'config': {'mode': 'rules_fallback', 'entrypoint': 'app.ai.rules.assess_rules',
                   'prompt': None, 'threshold_tuning': False, 'retries': 0},
        'rules_baseline': {'status': 'MEASURED', 'splits': results},
        'model_enabled': {'status': 'NOT_RUN', 'model': None, 'model_version': None,
                          'reason': 'No real adapter, approved provider or spending budget; synthetic seam is not a model'},
        'cost': {'usd': None, 'status': 'NOT_MEASURED', 'paid_provider_calls': 0},
        'production_acceptance': 'NOT_EVALUATED; final decision belongs to master',
        'limits': ['Hand-authored synthetic fixtures, not enterprise validation or a random sample',
                   'Holdout frozen before first evaluation; backend rules were visible to the independent label author',
                   'No image bytes or visual/repair quality evaluated',
                   'No HTTP, database, real device, model or notification evidence',
                   'Zero observed critical false accepts cannot establish zero future risk'],
    }
    write_json(output / 'report.json', report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', choices=('dev', 'holdout', 'all'), default='all')
    parser.add_argument('--allow-dirty', action='store_true', help='Diagnostic only; report marks evidence dirty')
    args = parser.parse_args()
    report = run(args.output, args.split, args.allow_dirty)
    print('code_sha=' + report['code_sha'])
    for name, result in report['rules_baseline']['splits'].items():
        print(name, result['fixture_gate_expectations'], result['mandatory_gates']['accuracy_all_episodes'],
              'critical_false_accept=', result['critical_false_accept_rate'])
    print('model_enabled=NOT_RUN; cost_usd=null')
    if any(r['fixture_gate_expectations'] != 'PASS' for r in report['rules_baseline']['splits'].values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
