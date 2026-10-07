#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit disposable PostgreSQL test DSN; no skip is allowed in this gate}"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export PYTHONPATH="$ROOT/backend:$ROOT/backend/tests${DALA_PERSISTENCE_ROOT:+:$DALA_PERSISTENCE_ROOT/backend:$DALA_PERSISTENCE_ROOT/backend/tests}${PYTHONPATH:+:$PYTHONPATH}"
python -c 'import psycopg, PIL, python_multipart; print("Driver:", psycopg.__version__, "Pillow:", PIL.__version__, "multipart:", python_multipart.__version__)'
python -m unittest discover -s "$ROOT/backend/tests" -p 'test_photos_postgres.py' -v
