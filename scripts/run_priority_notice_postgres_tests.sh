#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set explicit disposable PostgreSQL URL; priority-notice gate cannot skip}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend:$ROOT/backend/tests${PYTHONPATH:+:$PYTHONPATH}"
python - "$ROOT" <<'PY'
import sys,unittest
from pathlib import Path
suite=unittest.defaultTestLoader.discover(str(Path(sys.argv[1])/'backend/tests'),pattern='test_priority_notice_postgres.py')
expected=14
if suite.countTestCases()!=expected:raise SystemExit('Wrong priority-notice gate test count')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun!=expected or result.skipped or not result.wasSuccessful():
    raise SystemExit('Priority notice PostgreSQL gate failed, skipped or incomplete')
PY
