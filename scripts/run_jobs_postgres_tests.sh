#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit disposable PostgreSQL test database URL; this gate must not skip}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend:$ROOT/backend/tests${PYTHONPATH:+:$PYTHONPATH}"
python - "$ROOT" <<'PY'
import sys
import unittest
from pathlib import Path
root = Path(sys.argv[1])
suite = unittest.defaultTestLoader.discover(str(root/'backend/tests'),pattern='test_jobs_postgres.py')
expected = 18
count = suite.countTestCases()
if count != expected:
    raise SystemExit(f'Mandatory jobs gate expected {expected} cases, found {count}')
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun != expected or result.skipped or not result.wasSuccessful():
    raise SystemExit('Jobs PostgreSQL gate failed, skipped or incomplete')
PY
