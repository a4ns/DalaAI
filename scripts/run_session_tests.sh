#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit disposable PostgreSQL test DSN; no skip allowed in this gate}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
python -c 'import psycopg, argon2; from importlib.metadata import version; print("psycopg", psycopg.__version__, "argon2-cffi", version("argon2-cffi"))'
python -m unittest discover -s "$ROOT/backend/tests" -p 'test_sessions_*.py' -v
