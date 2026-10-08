# Render operator card: isolated DalaAI demo

**The managed image passed disposable CI; no hosted deployment was performed. Humans choose the platform and approve resources in the morning.**

The full first-run launcher, restricted API/worker profiles, history and optional clock are integrated. [Exact image validation at 2d1a407](https://github.com/a4ns/DalaAI/actions/runs/37712260125/job/113100631476) exercised them together. Keep start approval false until the operator has validated the chosen hosted database, persistent disk, credentials and HTTPS origin.

The example is deliberately named `render.yaml.example`, has automatic deploys and previews off, and starts with `DALA_MANAGED_START_APPROVED=false`. Importing/syncing a Blueprint can still create **paid** resources; the start flag is an application gate, not a spending safeguard. Review the current [Render pricing](https://render.com/pricing) before approving any resources.

## What this runs

One paid Render web service contains three separate processes: Caddy serves the built frontend and proxies `/api/*`; FastAPI listens only on `127.0.0.1:8000`; a separate `python -m app.worker_runtime` consumes durable jobs. PostgreSQL is a separate private managed database. API and worker use different restricted database LOGINs; the owner identity is never configured on the web service.

Photos and the model-budget ledger share a persistent disk at `/var/lib/naryadai`, outside Caddy's `/srv` document root. This is deliberately one instance: Render disks cannot be shared between services, are unavailable to build/pre-deploy/one-off jobs, and prevent zero-downtime deploys. Do not split the worker into a second service with an empty independent disk. [Disk constraints](https://render.com/docs/disks)

This bounded synthetic-demo profile treats API and worker as **one security principal**: both require UID 10001 for the current private-file adapter. The worker can write photos, and same-UID processes are not a secret-isolation boundary. Its distinct SQL role limits normal operations, not compromise of a sibling. Caddy runs as UID 10002 with no database/model keys in its environment. The fixed supervisor retains root solely for directory initialization and cross-UID lifecycle control; no application child runs as root. This is not a production multi-tenant isolation design.

## Prerequisites before the 15-minute clock

- Human approval of provider, region, recurring compute/storage charges and data location; account/billing/repository access already working
- Approved exact release SHA containing the frontend, worker runtime, provision helpers, accepted model/push dependencies and the current migration map and successful exact-release checks
- Paid web compute `1c-2g` (2 GB), a 2 GB persistent disk, paid PostgreSQL 17 `0.5c-1g` with 5 GB storage, and an existing private administrative execution environment in the same workspace/region; reuse existing resources only by verified identity
- Existing owner, API and worker LOGINs with operator-managed credentials. API and worker are direct, distinct, non-owner roles; no broad grants or elevated inherited memberships
- One chosen HTTPS hostname, verified domain/TLS if custom, and two synthetic demo-account PINs supplied privately to the provisioning environment only
- Exact candidate image built and checked, or budget extra time for build queues/image downloads; baseline image tags mirror `ops/demo`, not digest-qualified deployment evidence

The example's PostgreSQL `ipAllowList: []` disables public connectivity. Copy **internal** host details from Render and use the same database for both restricted DSNs; never inject `fromDatabase.connectionString` into the API, because that uses the database's primary owner identity. Same-region services use Render's [private network](https://render.com/docs/private-network). Isolation from other same-workspace services is a separate platform setting, not implied by this file.

**15 minutes is an active operator checklist after those prerequisites, not a signup, provisioning, build, DNS or successful-launch guarantee. Stop at a failed gate.**

## 0–4 min: approve configuration and first-run database gate

1. Review `render.yaml.example`; choose verified names/region and remove the database stanza if the approved database already exists. Keep one instance, no autoscaling, no previews and no automatic deploys. Selecting/importing the example or creating the resources requires the human's spending decision. [Blueprint reference](https://render.com/docs/blueprint-spec)
2. In the separate private administrative environment, supply `DALA_API_MODE=demo`, `DALA_DEMO_SEED_ALLOWED=1`, `DALA_DEMO_WORKER_CAPABILITY_ALLOWED=1`, the three existing identities through `DALA_DEMO_OWNER_DATABASE_URL`, `DALA_DEMO_RUNTIME_DATABASE_URL`, `DALA_DEMO_WORKER_DATABASE_URL`, and the private `DALA_DEMO_MASTER_PIN` / `DALA_DEMO_EXECUTOR_PIN`. Choose `DALA_DEMO_FIXTURE_MODE=history` before first initialization for 540 canonical historical orders, or keep the default `minimal`.
3. **Choose clock-off or clock-enabled before any bootstrap command.** For clock-off, use `enable_worker_capabilities.py`. For a fresh clock-enabled schema, use `enable_demo_clock.py` instead, with explicit `DALA_DEMO_CLOCK_CAPABILITY_ALLOWED=1` and one fixed `DALA_DEMO_CLOCK_INSTANCE_ID`. Do not run the worker helper first and then try to add the clock. See [the exact clock bootstrap contract](../../docs/demo-clock-bootstrap.md).
   The clock-off command from the accepted repository is:
   `python ops/provision/enable_worker_capabilities.py --backend backend --schema dalaai_demo --expected-database naryadai --bootstrap --apply`
   For the chosen clock-enabled profile, replace that helper name with `enable_demo_clock.py` and keep the same CLI arguments. Use `--backend /service` only inside the built image. The full helper applies exactly 001/002/003/004/005/011/012; the clock wrapper additionally applies 013 and its separate completion barrier. Both validate the matching restricted profiles and selected fixture. A repeat verifies the same completed profile; it never repairs grants, resets PINs or replays a partial schema. The older four-migration initializer is insufficient.
4. Keep `DALA_WORKER_AI_ENABLED=true`, `DALA_WORKER_NOTIFY_ENABLED=true`, `DALA_WORKER_CHANNEL=web_push`, `DALA_NOTIFICATION_CAPABILITY=true`, `DALA_PUSH_CAPABILITY=true` and `DALA_DELIVERY_CHANNEL=web_push`. Provider activation is separate: `DALA_WEB_PUSH_ENABLED=false` pauses notification consumption while preserving pending jobs and the provisioned role profile. Without an OpenAI key, rules assessment still consumes AI jobs. Do not apply a `--no-notify` role profile to this runtime.
5. If clock capability was selected and successfully initialized, API and worker must both receive `DALA_DEMO_CLOCK_ENABLED=true` and the same fixed instance ID. Existing clock-off schemas are not automatically upgraded.

Use a pre-existing trusted private administration service/shell; if one must be created, approve its additional cost and complete that setup before timing. Do not put owner credentials on the public web service to make a one-off job convenient: [one-off jobs inherit their base service's environment](https://render.com/docs/one-off-jobs). Keep the application stopped during first initialization. Repeat startup checks never mean reset or seed replay.

## 4–7 min: operator secrets and persistent mount

In the web service's private Environment settings, set `DATABASE_URL` to the API role and `DALA_WORKER_DATABASE_URL` to the worker role. Use URL-encoded passwords where needed, preserve approved connection/TLS options, and never print either DSN. Set `DALA_ALLOWED_ORIGIN=https://<chosen-host>` exactly, lowercase, no path/trailing slash/explicit port. Set the nonsensitive values from the example. Do not configure owner/PIN/bootstrap variables there. This profile uses direct secret environment values for the two DSNs, not `_FILE` aliases. [Secret configuration](https://render.com/docs/configure-environment-variables)

Verify the persistent mount is exactly `/var/lib/naryadai`, root-owned. Startup rejects a missing real mount and symlinked child directories, then creates/repairs only fixed `photos` and `budget` directory metadata to UID 10001/0700. It neither recurses through nor deletes existing data. If a platform ownership/mount check fails, inspect and repair it explicitly; do not remove the mount check. Photo capacity is 1 GiB; the disk remainder holds the ledger and headroom. Budget persistence must survive every restart/rollback.

## 7–11 min: start only the approved release

After the schema/role gates pass, the operator changes `DALA_MANAGED_START_APPROVED` to `true` and manually deploys the approved exact commit. Dockerfile: `ops/managed/Dockerfile`; context: repository root; command: `python ops/managed/supervise.py`. No migrations run in the image build or application startup.

Startup validates the worker with `--check`, without claiming jobs/provider calls, before launching all three processes. Unexpected exit of any child stops the container. SIGTERM allows75 seconds for children within Render's90-second shutdown window. `/healthz` is API liveness; `/readyz` checks the mounted API's database/schema/role prerequisites. Render probes `/readyz`. A live worker PID and initial check do not prove ongoing queue progress or device delivery; verify an actual job separately. [Health checks](https://render.com/docs/health-checks)

## 11–15 min: HTTPS and persistence acceptance

- Open the chosen HTTPS origin. Confirm frontend and API use the same origin and `/api/v1/me` returns401 without login
- Log in as each demo role. Inspect `Set-Cookie`: Secure, HttpOnly, SameSite=Strict, Path=/, no Domain attribute. Test wrong Origin/missing CSRF denial and a cross-role object denial
- Upload a synthetic photo and complete the accepted two-role flow. Observe an actual durable AI job reach a rules-fallback assessment, then the master's decision. Rules-only is the default and must be labeled
- Confirm `/readyz` returns200, then restart once and verify the photo, session/domain data, pending jobs and budget ledger persist. Record commit, image/deployment ID, results and time without credentials

Render terminates TLS; Caddy receives internal HTTP and does not perform scheme-based redirects. FastAPI ignores all proxy headers. Caddy permits the chosen Host and normalizes Host only for `/healthz` and `/readyz` probes. It never rewrites Origin. Secure cookies are explicit; do not weaken them to fix login. Proxy headers are not client identity: login source-based limiting sees the shared loopback proxy, which can make failed-login throttling affect all demo users. Test that small-demo availability limit and avoid repeated bad PIN attempts. Do not enable wildcard forwarded-header trust as a workaround.

## Optional features, after the baseline

**Grounded report model:** off by default, independently of the existing closure worker. The [explicit report opt-in guide](../../docs/reports/model-runtime.md) requires a separate combined-purpose policy and the same durable ledger/project/instance. Only `DALA_AI_REPORT_MODEL_ENABLED=true` forwards those reviewed model inputs to the API; Caddy remains excluded. This source option has no live provider acceptance.

**OpenAI:** no key is configured in this source template, so the canonical runtime uses rules fallback. The reviewed interactive-demo policy authorizes one named demo project/instance and automatically selects current verified before/after photos from persisted server records. It does **not** require a manual content hash or selection map for every new order/photo. The operator prepares that one expiring policy with the accepted `scripts/prepare_interactive_demo_policy.py`, makes the processing disclosure visible, and points the accepted runtime at the named project/instance and durable ledger. Canonical worker names are `DALA_MODEL_APPROVAL_FILE`, `DALA_MODEL_PROJECT_ID`, `DALA_MODEL_INSTANCE_ID` and `DALA_MODEL_BUDGET_PATH`. The worker passes `DemoProjectContext` into `ProviderAssessmentWorker` and uses `CameraAssetsFactory(verifier.read)` without a selection file. This canonical activation path is integrated; actual provider calls remain unverified. Policy files may live under `/etc/secrets` and must be readable by UID 10001. Once the accepted host configuration is complete, `OPENAI_API_KEY` or exclusive `OPENAI_API_KEY_FILE` is the only enable-time input: no key means rules fallback, and a key selects the authorized model path automatically. No morning `DALA_WORKER_OPENAI_ENABLED` toggle is required. The supervisor rejects that obsolete flag and a per-photo selection-map variable; remove any inherited copies from the service settings. A key file must be a regular readable `/etc/secrets/<name>` file. Strict fixture replay is optional, never a new consent requirement for the approved interactive scope. Preserve the reviewed $50 lifetime/$10 overnight budget (night cutoff 2026-10-08 04:00Z, default policy expiry 2026-10-08 18:59Z); never reset the ledger to recover from an error. No live call or model-quality result was established here.

**Web Push:** default off. Requires accepted 005/012, API subscription routes/public configuration, matching API job channel and a reviewed notification worker role profile. The full managed profile already pairs the API and worker on `web_push`; provider-disabled operation keeps jobs pending. Configure the existing VAPID public/private pair and subject through approved secret handling, enable `DALA_WEB_PUSH_ENABLED`, `DALA_WORKER_NOTIFY_ENABLED`, `DALA_WORKER_CHANNEL=web_push`, and re-run the role/worker checks. The current API PushSettings validates the public/private pair, so this profile passes the private key to API and worker only, never Caddy or the frontend. This is the same application trust boundary; the subject must be the operator’s real approved mailto contact. Do not enable with an unreviewed runtime assembly. Delivery proof requires a human-consenting actual phone; provider acceptance is not display/sound/vibration. Telegram is deliberately disabled in this managed profile.

## Limits, rollback and retention

A measured 20 MP decoder consumed about 401 MiB alone. Do not choose a 512 MB/free service. Keep at least 1 GiB available for the backend workload; this candidate selects 2 GB for the combined service, one API process and one sequential worker, but **mixed photo/login/AI load has not been measured here**. Monitor memory/CPU/disk, serialize large demo uploads and increase paid capacity only after approval. Photo quota exhaustion fails closed; no automatic cleanup or data reset exists. Do not promise sustained load or upload timings before measurement.

For code rollback, stop new traffic/jobs, choose an earlier **schema-compatible** accepted image/commit and retain the same database, disk and secrets. Never downgrade migrations, delete a volume, reset a seed or erase ambiguous delivery attempts/spend to make a rollback green. Otherwise use a reviewed forward fix. Disk-backed deploys cause a short outage; plan one before the demo, not during judging.

Before destructive recovery, capture a coordinated DB backup plus private-photo and ledger copy while writes are stopped; preserve command receipts and delivery audit. A disk snapshot restored alone may disagree with newer DB rows and spend reservations. Render's disk snapshots are whole-disk restore points; restoring loses subsequent changes. Paid PostgreSQL has a separate [recovery/backup workflow](https://render.com/docs/postgresql-backups). Verify the actual retention window and recovery copy before cutover. Keep the original resources until recovery is verified and an owner explicitly approves disposal; deleting/suspending the app is not a data-retention policy.

## Evidence and remaining gates

[Run 37712260125, job 113100631476](https://github.com/a4ns/DalaAI/actions/runs/37712260125/job/113100631476) passed on exact source `2d1a40796881eace63378c9ef83886b0a0bda95d`, image `sha256:b439d19433736f2f2cf8d5d2b24d977cbd92973c0fc5e5e1a930edd14e1446ac`. It built the actual managed Dockerfile and ran the unchanged supervisor with a disposable PostgreSQL database and verified loopback TLS.

The combined history + clock + real photo + separate rules worker + human close + four PDF/XLSX exports passed. Actual API/worker UID 10001 and Caddy UID 10002, child environment boundaries and API loopback binding passed. A container restart preserved DB identities, physical photo hashes and one separate offline/cancelled budget reservation; that reservation is not a provider call or billed cost. Final counts were 541 orders, 569 submissions, one rules assessment and one physical photo. All 39 managed/harness source tests and owned cleanup passed.

Still NOT_RUN: official Render schema/API validation, account/resource creation, hosted PostgreSQL and disk behavior, public DNS/TLS deployment, mixed-load memory, live OpenAI/Web Push, native downloads and physical Android. The CI loopback certificate and test-only localhost flag are not a public deployment configuration. The copied managed Caddy binary has no low-port file capability because its listener is restricted to ports at or above 1024.
Suggested local image/config gates after integration, without deploying:
`docker build -f ops/managed/Dockerfile -t dalaai-managed:<approved-sha> .`
`docker run --rm -e PORT=10000 -e DALA_PUBLIC_HOST=demo.example.com --entrypoint caddy dalaai-managed:<approved-sha> validate --config /service/ops/managed/Caddyfile --adapter caddyfile`

Provider references checked 2026-10-07; official docs and account-visible pricing win if they change. The template is a reviewed starting point, not evidence of successful hosting.
