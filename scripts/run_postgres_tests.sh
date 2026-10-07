#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit disposable PostgreSQL test database URL; no skip is allowed in this gate}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
python -c 'import psycopg; print("PostgreSQL driver:", psycopg.__version__)'
python -m unittest discover -s "$ROOT/backend/tests" -p 'test_persistence_postgres.py' -v
