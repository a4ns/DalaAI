# Render operator card: isolated DalaAI demo

**Source-only proposal. No account, resource, secret, payment, deployment or live provider call was made. Humans choose the platform in the morning. Do not apply this overnight.**

**Launch dependency pending:** A5’s full first-run bundle and `ops/provision/enable_worker_capabilities.py` are not yet implemented/accepted at this checkpoint. Keep start approval false until they are integrated and verified. This package does not supply or substitute that launcher.

The example is deliberately named `render.yaml.example`, has automatic deploys and previews off, and starts with `DALA_MANAGED_START_APPROVED=false`. Importing/syncing a Blueprint can still create **paid** resources; the start flag is an application gate, not a spending safeguard. Review the current [Render pricing](https://render.com/pricing) before approving any resources.

## What this runs

One paid Render web service contains three separate processes: Caddy serves the built frontend and proxies `/api/*`; FastAPI listens only on `127.0.0.1:8000`; a separate `python -m app.worker_runtime` consumes durable jobs. PostgreSQL is a separate private managed database. API and worker use different restricted database LOGINs; the owner identity is never configured on the web service.

Photos and the model-budget ledger share a persistent disk at `/var/lib/naryadai`, outside Caddy's `/srv` document root. This is deliberately one instance: Render disks cannot be shared between services, are unavailable to build/pre-deploy/one-off jobs, and prevent zero-downtime deploys. Do not split the worker into a second service with an empty independent disk. [Disk constraints](https://render.com/docs/disks)

This bounded synthetic-demo profile treats API and worker as **one security principal**: both require UID 10001 for the current private-file adapter. The worker can write photos, and same-UID processes are not a secret-isolation boundary. Its distinct SQL role limits normal operations, not compromise of a sibling. Caddy runs as UID 10002 with no database/model keys in its environment. The fixed supervisor retains root solely for directory initialization and cross-UID lifecycle control; no application child runs as root. This is not a production multi-tenant isolation design.

## Prerequisites before the 15-minute clock

- Human approval of provider, region, recurring compute/storage charges and data location; account/billing/repository access already working
- Approved exact release SHA containing the frontend, worker runtime, provision helpers, accepted model/push dependencies and A5's current migration map; current main alone may not contain every dependency
- Paid web compute `1c-2g` (2 GB), a 2 GB persistent disk, paid PostgreSQL 17 `0.5c-1g` with 5 GB storage, and an existing private administrative execution environment in the same workspace/region; reuse existing resources only by verified identity
- Existing owner, API and worker LOGINs with operator-managed credentials. API and worker are direct, distinct, non-owner roles; no broad grants or elevated inherited memberships
- One chosen HTTPS hostname, verified domain/TLS if custom, and two synthetic demo-account PINs supplied privately to the provisioning environment only
- Exact candidate image built and checked, or budget extra time for build queues/image downloads; baseline image tags mirror `ops/demo`, not digest-qualified deployment evidence

The example's PostgreSQL `ipAllowList: []` disables public connectivity. Copy **internal** host details from Render and use the same database for both restricted DSNs; never inject `fromDatabase.connectionString` into the API, because that uses the database's primary owner identity. Same-region services use Render's [private network](https://render.com/docs/private-network). Isolation from other same-workspace services is a separate platform setting, not implied by this file.

**15 minutes is an active operator checklist after those prerequisites, not a signup, provisioning, build, DNS or successful-launch guarantee. Stop at a failed gate.**

## 0–4 min: approve configuration and first-run database gate

1. Review `render.yaml.example`; choose verified names/region and remove the database stanza if the approved database already exists. Keep one instance, no autoscaling, no previews and no automatic deploys. Selecting/importing the example or creating the resources requires the human's spending decision. [Blueprint reference](https://render.com/docs/blueprint-spec)
2. In the separate approved private administrative environment, apply the **accepted A5 first-run migration/provisioning bundle**, then validate API and worker grants. The planned worker capability helper is `ops/provision/enable_worker_capabilities.py`; its command is intentionally not prescribed before acceptance. See `ops/MIGRATION_MAP.md`, `ops/provision/README.md` and `docs/worker-runtime.md` at the exact release SHA. This is intentionally not a runtime/pre-deploy hook.
3. The photo-aware bootstrap interface is:
   `python ops/provision/enable_photo_capability.py --backend /service --schema dalaai_demo --expected-database naryadai --bootstrap --apply`
   It requires `DALA_API_MODE=demo`, `DALA_DEMO_SEED_ALLOWED=1`, `DALA_DEMO_PHOTO_CAPABILITY_ALLOWED=1`, operator-supplied owner/runtime DSNs and the two demo PINs. It must belong to the reviewed full bundle. **An old bootstrap containing only 001–004 does not prepare an enabled worker/priority-notice runtime.** Required accepted additions are 011 (AI leases), 012 (delivery audit/priority hook), and 005 before Web Push. If the release's migration map/helper lacks these gates, leave start approval false and stop; do not manually replay SQL into an existing/partially initialized schema.
4. Render the dedicated worker profile for this default rules-only lane:
   `PYTHONPATH=/service python ops/provision/worker_profile.py --schema dalaai_demo --worker-role <existing_worker_role> --api-role <existing_api_role> --no-notify`
   This prints a review-only SQL proposal. The authorized operator applies it to the existing role using the accepted administrative workflow. Do not give the API those grants. Role creation and owner credential entry are operator prerequisites, not performed by this package.

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

**OpenAI:** no key is configured in this source template, so the canonical runtime uses rules fallback. The reviewed interactive-demo policy authorizes one named demo project/instance and automatically selects current verified before/after photos from persisted server records. It does **not** require a manual content hash or selection map for every new order/photo. The operator prepares that one expiring policy with the accepted `scripts/prepare_interactive_demo_policy.py`, makes the processing disclosure visible, and points the accepted runtime at the named project/instance and durable ledger. Canonical worker names are `DALA_MODEL_APPROVAL_FILE`, `DALA_MODEL_PROJECT_ID`, `DALA_MODEL_INSTANCE_ID` and `DALA_MODEL_BUDGET_PATH`. The worker passes `DemoProjectContext` into `ProviderAssessmentWorker` and uses `CameraAssetsFactory(verifier.read)` without a selection file. This activation is pending A5's matching runtime assembly; the old per-payload loader is not a substitute. Policy files may live under `/etc/secrets` and must be readable by UID 10001. Once the accepted host configuration is complete, `OPENAI_API_KEY` or exclusive `OPENAI_API_KEY_FILE` is the only enable-time input: no key means rules fallback, and a key selects the authorized model path automatically. No morning `DALA_WORKER_OPENAI_ENABLED` toggle is required. The supervisor rejects that obsolete flag and a per-photo selection-map variable; remove any inherited copies from the service settings. A key file must be a regular readable `/etc/secrets/<name>` file. Strict fixture replay is optional, never a new consent requirement for the approved interactive scope. Preserve the reviewed $50 lifetime/$10 overnight budget (night cutoff 2026-10-08 04:00Z, default policy expiry 2026-10-08 18:59Z); never reset the ledger to recover from an error. No live call or model-quality result was established here.

**Web Push:** default off. Requires accepted 005/012, API subscription routes/public configuration, matching API job channel and a reviewed notification worker role profile. The baseline API's `synthetic` channel cannot be delivered merely by changing the worker. Configure the existing VAPID public/private pair and subject through approved secret handling, enable `DALA_WEB_PUSH_ENABLED`, `DALA_WORKER_NOTIFY_ENABLED`, `DALA_WORKER_CHANNEL=web_push`, and re-run the role/worker checks. The current API PushSettings validates the public/private pair, so this profile passes the private key to API and worker only, never Caddy or the frontend. This is the same application trust boundary; the subject must be the operator’s real approved mailto contact. Do not enable with an unreviewed runtime assembly. Delivery proof requires a human-consenting actual phone; provider acceptance is not display/sound/vibration. Telegram is deliberately disabled in this managed profile.

## Limits, rollback and retention

A measured 20 MP decoder consumed about 401 MiB alone. Do not choose a 512 MB/free service. Keep at least 1 GiB available for the backend workload; this candidate selects 2 GB for the combined service, one API process and one sequential worker, but **mixed photo/login/AI load has not been measured here**. Monitor memory/CPU/disk, serialize large demo uploads and increase paid capacity only after approval. Photo quota exhaustion fails closed; no automatic cleanup or data reset exists. Do not promise sustained load or upload timings before measurement.

For code rollback, stop new traffic/jobs, choose an earlier **schema-compatible** accepted image/commit and retain the same database, disk and secrets. Never downgrade migrations, delete a volume, reset a seed or erase ambiguous delivery attempts/spend to make a rollback green. Otherwise use a reviewed forward fix. Disk-backed deploys cause a short outage; plan one before the demo, not during judging.

Before destructive recovery, capture a coordinated DB backup plus private-photo and ledger copy while writes are stopped; preserve command receipts and delivery audit. A disk snapshot restored alone may disagree with newer DB rows and spend reservations. Render's disk snapshots are whole-disk restore points; restoring loses subsequent changes. Paid PostgreSQL has a separate [recovery/backup workflow](https://render.com/docs/postgresql-backups). Verify the actual retention window and recovery copy before cutover. Keep the original resources until recovery is verified and an owner explicitly approves disposal; deleting/suspending the app is not a data-retention policy.

## Evidence and remaining gates

Local `python -m unittest discover -s ops/managed/tests -v`:19 tests PASS (environment isolation, no-approval refusal, mount/symlink denial, subprocess shutdown, YAML parse/invariants). Python AST syntax PASS. These are not container/provider acceptance.

NOT_RUN: Docker image build/context behavior, Caddy adapt/validate, official Render schema/API validation, hosted mount/UID behavior, migrations against Render PostgreSQL, TLS/cookies, live queue processing, mixed-load memory, restart persistence, live OpenAI/Web Push and real Android acceptance. They remain release gates. No root Compose files or existing runtime modules were changed.

Suggested local image/config gates after integration, without deploying:
`docker build -f ops/managed/Dockerfile -t dalaai-managed:<approved-sha> .`
`docker run --rm -e PORT=10000 -e DALA_PUBLIC_HOST=demo.example.com --entrypoint caddy dalaai-managed:<approved-sha> validate --config /service/ops/managed/Caddyfile --adapter caddyfile`

Provider references checked 2026-10-07; official docs and account-visible pricing win if they change. The template is a reviewed starting point, not evidence of successful hosting.
