#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Explicit disposable PostgreSQL DSN required; this gate cannot skip}"
: "${DALA_SESSION_CANDIDATE:?Absolute candidate root containing backend required}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$DALA_SESSION_CANDIDATE/backend:$DALA_SESSION_CANDIDATE/backend/tests:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
python -c 'import psycopg, argon2; from importlib.metadata import version; print("psycopg", psycopg.__version__, "argon2-cffi", version("argon2-cffi"))'
python - <<'PY'
import unittest
import test_session_pg_adversarial as probes
suite = probes.load_tests(unittest.defaultTestLoader, None, None)
assert suite.countTestCases() == 4, "Expected the four independent PG scenarios"
result = unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != 4 or not result.wasSuccessful():
    raise SystemExit(1)
PY
