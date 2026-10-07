# One-command isolated demo stack

This increment packages the reviewed Russian frontend, real FastAPI API,
PostgreSQL, private photo storage and Caddy on one origin. It covers login,
create/accept/start, actual photo staging/submission and human CLOSE with current
physical evidence. The full overlay adds a separate restricted worker, durable
rules assessments, notification queues, Web Push subscription routes and an
optional bounded model path. Provider acceptance and actual phone delivery remain
separate checks. No host
has been selected and nothing is deployed by publishing this package.

## Local/disposable start

Requires Docker Compose and Python3. From the repository root:

```sh
./ops/demo/run.sh
```

Default bind is loopback only, HTTP8080 and HTTPS8443, hostname localhost. The
script creates private local inputs only if absent, then builds and starts the
stack. Existing volumes without their original secret files stop the launcher;
there is no automatic reset or password rotation. Local browser trust must be
configured normally; never bypass a certificate warning. CI uses an explicitly
trusted ephemeral localhost CA and does not change an existing user trust store.

For the human-selected VPS after DNS, ports and costs are approved:

```sh
DALA_DOMAIN=demo.example.org DALA_BIND_ADDRESS=0.0.0.0 \
DALA_HTTP_PORT=80 DALA_HTTPS_PORT=443 ./ops/demo/run.sh
```

Choose the real domain before first preparation. Changing stored configuration
requires an explicit operator edit; rerunning never silently overwrites it.
Caddy handles TLS and serves the exact built frontend. Only Caddy exposes ports;
PostgreSQL/API stay on an internal network. Source API ignores spoofed forwarding
headers; login source quotas conservatively share the proxy address in this
bounded demo. A future trusted-proxy policy needs separate verification.

## Secrets and persistence

ops/demo/.local is UID-owned0700 and ignored by Git and Docker build context.
Its exclusively created0444 files are readable only through that private parent
on the host and only by the Docker services to which each file is explicitly
mounted. This supports the API's different UID without exposing owner secrets to
it. Values are never printed. Human-started first DB initialization creates the
separate nonowner naryadai_api LOGIN; the API never gets the owner DSN or PIN files.
The owner setup container applies exact reviewed SQL and seeds two scoped accounts:
DALA-DEMO-MASTER and DALA-DEMO-EXECUTOR. Their distinct private PINs stay in
.local/master_pin and .local/executor_pin for the operator. Do not copy them into
Git, public logs or screenshots. Seed repeat refuses changed/revoked/deleted
identities rather than restoring them.

Volumes preserve PostgreSQL, Caddy TLS state and private photos. API runs UID10001
with a read-only root, one worker and a writable private photo volume. The
photo-directory initializer only sets that named volume's root ownership/mode.
The starting API memory envelope is1536MiB; worst-case mixed-load capacity remains
unmeasured. Keep the private photo volume outside every static file root.

The default launcher adds `compose.workers.yaml`, a distinct worker LOGIN, exact
001/002/003/004/005/011/012 bootstrap and a durable model-budget volume. The worker
reads the same photo volume read-only. AI and notification capabilities are
enabled; absent VAPID configuration pauses notification consumption and preserves
pending jobs. Rules assessment remains active without an OpenAI key. The base
`compose.yaml` alone is the older worker-free four-migration profile used by the
separate manual C-110 browser gate. Existing baseline schemas are not upgraded or
reset by the full launcher: retain them and arrange an explicit reviewed forward
upgrade or choose a fresh isolated instance before running the full profile.

Setup creates one named DalaAI model policy and prints its disclosure. Once the
operator supplies `OPENAI_API_KEY` to the launcher environment, the model worker
selects the approved demo path automatically; no key keeps rules fallback.
`DALA_MODEL_FORCE_OFF=true` is the explicit override. The $50 total/$10 night
ledger persists on `model_budget`; restarting must never delete it. The policy
expires at 2026-10-08 18:59 UTC. Private-key file mounting is supported by the
worker's `OPENAI_API_KEY_FILE` when the operator supplies an explicit Compose
mount/override; never set both key sources. No key is generated or committed.

Текст результата и выбранные фото демонстрационного наряда отправляются в OpenAI
для проверки соответствия и сравнения до/после. Синтетичность содержимого загрузок
не подтверждена автоматически. Модель рекомендует; решение принимает мастер.

Web Push remains off until human VAPID setup and browser permission/subscription.
Supply `DALA_WEB_PUSH_ENABLED=true`, the matching public/private keys and subject
to both API and worker through the operator environment. The private key is never
passed to Caddy or the frontend. Telegram remains an optional separately enabled
adapter; this default Compose lane is Web Push only.

Stop without deleting data:

```sh
docker compose --env-file ops/demo/.local/env --env-file ops/demo/.local/workers.env \
  -f ops/demo/compose.yaml -f ops/demo/compose.workers.yaml down
```

## Morning checks

The15-minute setup target assumes Docker, DNS and the selected host are already
ready; first image downloads can take longer. Review the selected managed-host
alternative/costs separately. Verify trusted HTTPS, /healthz and /readyz; log in
as both supplied demo accounts, then follow ops/provision/C5_TWO_ROLE_RUNBOOK.md.
A10-minute two-physical-Android check still requires real devices and explicit
camera/notification permissions. CI Android emulation does not replace it.

Current source assembly: B product2a12798c19a26b33aabd9ffd572b99586f80e2f1 plus
only five reviewed harness files from9f37c2951cbffb88db8a254beff033f7e31ed6d9.
Mobile CI separates13 synthetic Pixel9 rendering cases from C-110's real composed
API scenarios. An absent/unaccepted C-110 contract is BLOCKED, never a green core
result. The separate full Compose HTTPS smoke waits for the actual rules worker
verdict; it still labels live model, browser and phone push outside that scope.

Official image/config references checked2026-10-07:
- https://hub.docker.com/_/caddy (2.11.7-alpine)
- https://hub.docker.com/_/node (24.21.0-bookworm-slim)
- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy
