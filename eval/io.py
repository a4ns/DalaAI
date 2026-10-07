"""Small strict JSON helpers shared by predictor and offline scorer."""
import hashlib
import json
from pathlib import Path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line, object_pairs_hook=_pairs)
            if type(row) is not dict:
                raise ValueError('JSONL object required')
            rows.append(row)
    return rows


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_jsonl(path: Path, rows) -> None:
    path.write_text(''.join(json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n'
                            for row in rows), encoding='utf-8')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
