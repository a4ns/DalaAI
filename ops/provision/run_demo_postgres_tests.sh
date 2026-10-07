#!/usr/bin/env sh
set -eu
: "${DALA_TEST_DATABASE_URL:?Set an explicit local disposable owner DSN}"
: "${DALA_ACCEPTANCE_RUNTIME_DATABASE_URL:?A5 must supply an existing restricted LOGIN DSN}"
: "${DALA_DEMO_TEST_BACKEND:?Set the exact accepted backend path}"
[ "${DALA_ACCEPTANCE_DISPOSABLE:-}" = 1 ] || { echo 'NOTRUN: disposable database acknowledgement required'; exit 2; }
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python -m unittest discover -s "$HERE/tests" -p test_demo_postgres.py -v
