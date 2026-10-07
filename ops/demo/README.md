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

For a **fresh** historical demo, select the profile before first initialization:

```sh
DALA_DEMO_FIXTURE_MODE=history ./ops/demo/run.sh
```

The private configuration preserves that choice on repeats. The historical
profile exposes540 canonical July–September synthetic orders to the live master
across four sections; the live executor stays in one section. All17 historical
actors remain disabled. Historical photo placeholders remain missing physical
evidence, with that disclosure in the reports. New live orders use real uploads,
worker assessments and human decisions on the same API/database. The default
profile remains `minimal`. Switching an existing profile is refused; there is
no automatic import, scope change, reset or repair on a running/minimal instance.

Default bind is loopback only, HTTP8080 and HTTPS8443, hostname localhost. The
script creates private local inputs only if absent, then builds and starts the
stack. Existing volumes without their original secret files stop the launcher;
there is no automatic reset or password rotation. Local browser trust must be
configured normally; never bypass a certificate warning. CI uses an explicitly
trusted ephemeral localhost CA and does not change an existing user trust store.
The human-run preparation creates private demo PIN files; bootstrap receives
them as operator inputs. No assistant step here creates a live account or host.

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

Current source assembly: exact B analytics product9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c.
C-110 is strictly rebound atd674d8a1cc261760c89b04b555123ca775f3c845; every new integration head must pass a
fresh secrecy preflight and actual Android-emulated browser/API/PostgreSQL run.
The separate13-case synthetic Pixel9 job retains its explicitly historical B
source pins. The full Compose HTTPS smoke verifies the actual rules worker,
physical photo and master closure, plus protected PDF/XLSX exports. In history
mode it also checks540 orders,568 attempts and444 missing historical photo rows.
Live model, device push, physical phones and mixed-load capacity are separate
checks; no overnight deployment is performed.

Official image/config references checked2026-10-07:
- https://hub.docker.com/_/caddy (2.11.7-alpine)
- https://hub.docker.com/_/node (24.21.0-bookworm-slim)
- https://caddyserver.com/docs/caddyfile/directives/reverse_proxy

## Optional shared business clock

Before first initialization only, run
`DALA_DEMO_CLOCK_ENABLED=true ops/demo/run.sh`. The launcher persists one UUID
and the choice beside its private configuration. API and worker share the same
PostgreSQL mapping; normal repeats preserve it. An already initialized profile
cannot gain this capability or switch back to wall time silently. Use the
operator-approved fresh schema/profile; no reset or database deletion is offered.

The existing synthetic master alone can GET/POST `/api/v1/demo/clock`; executor
and other identities cannot control it. Use the same cookie, exact Origin and
session CSRF header. POST includes `instance_id`, `expected_version`, and either
`action: set_scale` with integer `scale`0–60 or `action: advance` with `seconds`1–3600.
Zero pauses business time,1 resumes. Stale or repeated control returns409; GET
before deciding on another action. No rewind/reset exists. The seven-business-day
horizon is fixed. Clock controls do not change session/photo TTL, lease/backoff,
provider timeout or OpenAI budget/approval clocks. The UI should display the
returned Russian synthetic-time label whenever consuming this optional clock.

The separate optional Compose gate tests pause/advance/CAS and the real
photo/rules/human-close cycle. Physical devices and real provider timing remain
outside those checks. Render operators use `enable_demo_clock.py` on a fresh
schema and forward identical `DALA_DEMO_CLOCK_ENABLED=true` and
`DALA_DEMO_CLOCK_INSTANCE_ID` to API/worker; the managed supervisor allows only
these non-secret settings, no owner credentials.
