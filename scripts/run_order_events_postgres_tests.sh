#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit disposable PostgreSQL test database URL; this gate cannot skip}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE=${DALA_PERSISTENCE_ROOT:-$ROOT}
export PYTHONPATH="$ROOT/backend:$BASE/backend:$BASE/backend/tests${PYTHONPATH:+:$PYTHONPATH}"
export DALA_EVENTS_TEST_ROOT="$ROOT/backend/tests"
python -c 'import psycopg; print("PostgreSQL driver:",psycopg.__version__)'
python - <<'PYTEST'
import os,unittest
suite=unittest.defaultTestLoader.discover(os.environ['DALA_EVENTS_TEST_ROOT'],pattern='test_order_events_postgres.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun!=10 or result.skipped or not result.wasSuccessful():
    raise SystemExit('Order-events PostgreSQL gate requires all 10 cases to pass without skips')
PYTEST
