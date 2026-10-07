#!/usr/bin/env bash
# Execute manually on the chosen host; never provisions a host or deploys itself.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "$0")/../.." && pwd)
DOMAIN=${DALA_DOMAIN:-localhost}
if docker volume inspect dalaai-demo_postgres_data >/dev/null 2>&1 && [ ! -f "$ROOT/ops/demo/.local/env" ]; then
  echo 'Database volume already exists. Restore its matching private configuration; no reset will run.' >&2
  exit 1
fi
python3 "$ROOT/ops/demo/prepare.py" --directory "$ROOT/ops/demo/.local" --domain "$DOMAIN" \
  --bind "${DALA_BIND_ADDRESS:-127.0.0.1}" --http-port "${DALA_HTTP_PORT:-8080}" --https-port "${DALA_HTTPS_PORT:-8443}"
docker compose --env-file "$ROOT/ops/demo/.local/env" -f "$ROOT/ops/demo/compose.yaml" config --quiet
docker compose --env-file "$ROOT/ops/demo/.local/env" -f "$ROOT/ops/demo/compose.yaml" up --build --detach --wait --wait-timeout 180
printf '%s\n' 'Containers started. Run the documented HTTPS and two-role checks; this is not a device acceptance result.'
