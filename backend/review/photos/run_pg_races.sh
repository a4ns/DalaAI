#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Explicit disposable PostgreSQL DSN required; this gate cannot skip}"
: "${DALA_PHOTO_CANDIDATE:?Absolute complete candidate root containing backend required}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$DALA_PHOTO_CANDIDATE/backend:$DALA_PHOTO_CANDIDATE/backend/tests:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
python -c 'import psycopg, PIL, python_multipart; print("psycopg", psycopg.__version__, "Pillow", PIL.__version__, "python-multipart", python_multipart.__version__)'
python - <<'PY'
import unittest
import test_photo_pg_races as probes
suite = probes.load_tests(unittest.defaultTestLoader, None, None)
assert suite.countTestCases() == 4, "Expected the four independent PG race scenarios"
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != 4 or not result.wasSuccessful():
    raise SystemExit(1)
PY
