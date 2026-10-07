"""Non-mutating Python/TOML/YAML syntax checks; not Docker runtime validation."""

import ast
import tomllib
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
for directory in ("backend/app", "backend/tests", "ops"):
    for path in sorted((root / directory).rglob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
for path in (root / "backend").glob("*.toml"):
    tomllib.loads(path.read_text(encoding="utf-8"))
for path in [root / "ops/compose.yaml", *sorted((root / ".github/workflows").glob("*.yml"))]:
    with path.open(encoding="utf-8") as stream:
        if not isinstance(yaml.safe_load(stream), dict):
            raise ValueError(f"Expected a mapping: {path}")
print("PASS: Python, TOML and YAML syntax")
