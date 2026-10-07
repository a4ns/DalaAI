#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set explicit disposable PostgreSQL URL; no skips allowed in delivery gate}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend:$ROOT/backend/tests${PYTHONPATH:+:$PYTHONPATH}"
python - "$ROOT" <<'PY'
import sys,unittest
from pathlib import Path
suite=unittest.defaultTestLoader.discover(str(Path(sys.argv[1])/'backend/tests'),pattern='test_delivery_postgres.py')
expected=20
if suite.countTestCases()!=expected:raise SystemExit('Wrong mandatory delivery test count')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun!=expected or result.skipped or not result.wasSuccessful():
    raise SystemExit('Delivery PostgreSQL gate failed, skipped or incomplete')
PY
