#!/usr/bin/env bash
set -euo pipefail
: "${DALA_TEST_DATABASE_URL:?NOT_RUN: isolated PostgreSQL test DSN is required}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$ROOT/snapshot/backend:$ROOT/snapshot/test-support:$ROOT/probes${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY'
import psycopg
import unittest
import test_independent_discovery_postgres as probes
suite=probes.load_tests(unittest.defaultTestLoader, None, None)
expected=suite.countTestCases()
assert expected == 7, f'Unexpected test count: {expected}'
result=unittest.TextTestRunner(verbosity=2).run(suite)
if result.skipped or result.testsRun != expected or not result.wasSuccessful():
    raise SystemExit('FAIL: all seven independent discovery PostgreSQL cases must execute and pass, with no skip')
print('PASS: all seven independent discovery PostgreSQL cases executed, zero skips')
PY
