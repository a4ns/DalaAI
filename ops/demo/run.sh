#!/usr/bin/env bash
# Execute manually on the chosen host; never provisions a host or deploys itself.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
DOMAIN=${DALA_DOMAIN:-localhost}
if docker volume inspect dalaai-demo_postgres_data >/dev/null 2>&1 && [ ! -f "$ROOT/ops/demo/.local/env" ]; then
  echo 'Database volume already exists. Restore its matching private configuration; no reset will run.' >&2
  exit 1
fi
MODE_ARGS=()
if [ "${DALA_DEMO_FIXTURE_MODE+x}" = x ]; then MODE_ARGS=(--fixture-mode "$DALA_DEMO_FIXTURE_MODE"); fi
CLOCK_ARGS=()
if [ "${DALA_DEMO_CLOCK_ENABLED+x}" = x ]; then CLOCK_ARGS=(--demo-clock "$DALA_DEMO_CLOCK_ENABLED"); fi
python3 "$ROOT/ops/demo/prepare.py" --workers "${CLOCK_ARGS[@]}" "${MODE_ARGS[@]}" --directory "$ROOT/ops/demo/.local" --domain "$DOMAIN" \
  --bind "${DALA_BIND_ADDRESS:-127.0.0.1}" --http-port "${DALA_HTTP_PORT:-8080}" --https-port "${DALA_HTTPS_PORT:-8443}"
export DALA_DEMO_FIXTURE_MODE
DALA_DEMO_FIXTURE_MODE=$(cat "$ROOT/ops/demo/.local/fixture_mode")
export DALA_DEMO_CLOCK_ENABLED DALA_DEMO_CLOCK_INSTANCE_ID
DALA_DEMO_CLOCK_ENABLED=$(cat "$ROOT/ops/demo/.local/clock_mode")
DALA_DEMO_CLOCK_INSTANCE_ID=''
if [ "$DALA_DEMO_CLOCK_ENABLED" = true ]; then DALA_DEMO_CLOCK_INSTANCE_ID=$(cat "$ROOT/ops/demo/.local/clock_instance"); fi
COMPOSE=(docker compose --env-file "$ROOT/ops/demo/.local/env" --env-file "$ROOT/ops/demo/.local/workers.env" -f "$ROOT/ops/demo/compose.yaml" -f "$ROOT/ops/demo/compose.workers.yaml")
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up --build --detach --wait --wait-timeout 180
printf '%s\n' 'Containers started. Run the documented HTTPS and two-role checks; this is not a device acceptance result.'
