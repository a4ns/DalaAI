"""Run unchanged reviewed probes against a checked copy of the integrated backend."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main() -> None:
    if not os.environ.get("DALA_TEST_DATABASE_URL"):
        raise SystemExit("NOT_RUN: disposable PostgreSQL DSN required")
    root = Path(__file__).resolve().parents[1]
    review = root / "backend/review/discovery"
    manifest = json.loads((review / "REVIEWED_INPUTS.json").read_text())
    for path, expected in manifest["source_hashes"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Reviewed discovery source changed: {path}")
    for path, expected in manifest["probe_hashes"].items():
        if hashlib.sha256((review / path).read_bytes()).hexdigest() != expected:
            raise SystemExit(f"Reviewed discovery probe changed: {path}")
    with tempfile.TemporaryDirectory(prefix="dalaai-discovery-review-") as directory:
        scratch = Path(directory)
        shutil.copyfile(review / "run_postgres_gate.sh", scratch / "run_postgres_gate.sh")
        shutil.copytree(review / "probes", scratch / "probes")
        for name in ("app", "db"):
            shutil.copytree(root / "backend" / name, scratch / "snapshot/backend" / name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        support = scratch / "snapshot/test-support"
        support.mkdir(parents=True)
        for name in ("test_persistence_canonical.py", "test_persistence_postgres.py"):
            shutil.copyfile(root / "backend/tests" / name, support / name)
        if not (scratch / "snapshot/backend/db/migrations/004_immutable_reference_keys.sql").is_file():
            raise SystemExit("Required identity hardening migration missing from reviewer schema")
        subprocess.run(["bash", "run_postgres_gate.sh"], cwd=scratch, check=True)


if __name__ == "__main__":
    main()
