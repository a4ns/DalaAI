#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set the disposable PostgreSQL owner DSN for fixtures; no skip is allowed}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
python -m unittest discover -s "$ROOT/backend/tests" -p 'test_persistence_role.py' -v
