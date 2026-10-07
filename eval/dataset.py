"""Offline scoring-only dataset integrity. The runtime predictor never imports this."""
from pathlib import Path
from .io import read_json, read_jsonl, sha256

DATA = Path(__file__).resolve().parent / 'data' / 'v1'


def verify_dataset(root: Path = DATA) -> dict:
    manifest = read_json(root / 'manifest.json')
    if manifest['dataset_version'] != 'closure-eval-v1':
        raise ValueError('unsupported dataset version')
    seen_ids, fingerprints = set(), set()
    for split in ('dev', 'holdout'):
        entry = manifest['splits'][split]
        paths = {kind: root / entry[kind]['path'] for kind in ('inputs', 'labels')}
        for kind, path in paths.items():
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('dataset path outside root')
            if sha256(path) != entry[kind]['sha256']:
                raise ValueError('frozen dataset hash mismatch')
        inputs, labels = read_jsonl(paths['inputs']), read_jsonl(paths['labels'])
        input_ids = [row['case_id'] for row in inputs]
        label_ids = [row['case_id'] for row in labels]
        if len(input_ids) != entry['n'] or len(label_ids) != entry['n'] or set(input_ids) != set(label_ids):
            raise ValueError('dataset labels/input mismatch')
        if len(set(input_ids)) != len(input_ids) or len(set(label_ids)) != len(label_ids):
            raise ValueError('duplicate dataset case_id')
        if seen_ids.intersection(input_ids):
            raise ValueError('dev/holdout overlap')
        seen_ids.update(input_ids)
        # Compare content with identity values normalized, not just unique IDs.
        from hashlib import sha256 as digest
        import json
        from uuid import UUID
        for row in inputs:
            identities = {}
            def neutral(value):
                if isinstance(value, dict):
                    return {key: neutral(item) for key, item in sorted(value.items()) if key != 'case_id'}
                if isinstance(value, list):
                    return [neutral(item) for item in value]
                if isinstance(value, str):
                    try:
                        UUID(value)
                    except ValueError:
                        return value
                    return identities.setdefault(value, 'IDENTITY_' + str(len(identities)))
                return value
            fingerprint = digest(json.dumps(neutral(row), sort_keys=True).encode()).hexdigest()
            if fingerprint in fingerprints:
                raise ValueError('duplicate input across splits')
            fingerprints.add(fingerprint)
    return manifest
