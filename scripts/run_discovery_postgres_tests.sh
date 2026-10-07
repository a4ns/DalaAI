#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit disposable PostgreSQL test database URL; this gate never silently skips}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BASE=${DALA_PERSISTENCE_ROOT:-$ROOT}
# For the isolated handoff only, point DALA_PERSISTENCE_ROOT at the frozen
# persistence candidate. In the integrated repository ROOT already contains it.
export PYTHONPATH="$ROOT/backend:$BASE/backend:$BASE/backend/tests${PYTHONPATH:+:$PYTHONPATH}"
python -c 'import psycopg; print("PostgreSQL driver:", psycopg.__version__)'
export DALA_DISCOVERY_TEST_ROOT="$ROOT/backend/tests"
python - <<'PYTEST'
import os,sys,unittest
suite=unittest.defaultTestLoader.discover(os.environ['DALA_DISCOVERY_TEST_ROOT'],pattern='test_discovery_postgres.py')
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.testsRun != 13 or result.skipped or not result.wasSuccessful():
    raise SystemExit('Discovery PostgreSQL gate requires all 13 cases executed successfully without skips')
PYTEST
