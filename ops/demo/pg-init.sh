#!/usr/bin/env sh
# Runs only during human-started first initialization of this isolated DB volume.
set -eu
DALA_RUNTIME_PASSWORD=$(cat /run/secrets/postgres_runtime_password)
case "$DALA_RUNTIME_PASSWORD" in
  ''|*[!A-Za-z0-9_-]*) echo 'Runtime password file format is invalid' >&2; exit 1;;
esac
[ ${#DALA_RUNTIME_PASSWORD} -ge 32 ] && [ ${#DALA_RUNTIME_PASSWORD} -le 128 ] || exit 1
export DALA_RUNTIME_PASSWORD
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv runtime_password DALA_RUNTIME_PASSWORD
CREATE ROLE naryadai_api LOGIN PASSWORD :'runtime_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
SQL
unset DALA_RUNTIME_PASSWORD
if [ -f /run/secrets/postgres_worker_password ]; then
  DALA_WORKER_PASSWORD=$(cat /run/secrets/postgres_worker_password)
  case "$DALA_WORKER_PASSWORD" in
    ''|*[!A-Za-z0-9_-]*) echo 'Worker password file format is invalid' >&2; exit 1;;
  esac
  [ ${#DALA_WORKER_PASSWORD} -ge 32 ] && [ ${#DALA_WORKER_PASSWORD} -le 128 ] || exit 1
  export DALA_WORKER_PASSWORD
  psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv worker_password DALA_WORKER_PASSWORD
CREATE ROLE naryadai_worker LOGIN PASSWORD :'worker_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
SQL
  unset DALA_WORKER_PASSWORD
fi
