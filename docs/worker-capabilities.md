# Explicit worker-capable bootstrap delta

This is source only. No schema, role, key, grant, hosted service or provider call was created/executed during preparation. It supplements the frozen runtime `b3b37312…` without changing that artifact. A5 alone integrates shared startup/Compose and publishes.

## Exact migration path

`prepare_demo_database.worker_migration_plan(backend)` explicitly verifies these seven frozen file hashes, in order:

1. `db/migrations/001_vertical_slice.sql`
2. `db/migrations/002_trusted_evidence.sql`
3. `db/proposals/003_auth_rate_limits.sql`
4. `db/migrations/004_immutable_reference_keys.sql`
5. `db/proposals/005_web_push_subscriptions.sql`
6. `db/migrations/011_durable_job_leases.sql`
7. `db/migrations/012_delivery_dispatch_attempts.sql`

There is no glob, migration renumbering, relocated/duplicated 003 or 005, schema adoption or replay. The existing `MIGRATIONS`, `migration_plan`, `bootstrap_marker` and `apply_fresh` four-file behavior remain unchanged.

The new path is `ops/provision/enable_worker_capabilities.py`. Its default is a JSON plan with no database access:

`python ops/provision/enable_worker_capabilities.py --backend backend --schema dalaai_demo --bootstrap`

An authorized operator may apply the reviewed source to a fresh isolated schema using `--apply --expected-database NAME`. Required operator inputs are:

- Actual `DALA_API_MODE=demo`
- `DALA_DEMO_SEED_ALLOWED=1`
- `DALA_DEMO_WORKER_CAPABILITY_ALLOWED=1`
- Existing `DALA_DEMO_OWNER_DATABASE_URL`, `DALA_DEMO_RUNTIME_DATABASE_URL` (API), and `DALA_DEMO_WORKER_DATABASE_URL`
- Existing operator-supplied `DALA_DEMO_MASTER_PIN` and `DALA_DEMO_EXECUTOR_PIN`

No role/credential creation, key generation or DSN discovery occurs. The three directly authenticated roles must be distinct, in the explicitly named same database. API/worker roles cannot be elevated or members of elevated/owner roles. A session advisory lock serializes this exact schema bootstrap across migration commits.

## Durable first-start/repeat behavior

A fresh schema is marked `initializing` before any migration. Each original migration retains its own explicit transaction boundaries; a partial failure is preserved and cannot be mistaken for ready. Exact API and worker grants are applied only on the fresh path. Both actual restricted logins are validated before a completion marker is committed.

The completion marker on `delivery_dispatches` binds all seven migration hashes, the owner/API/worker role identities and exact grant profiles. The schema then receives the existing baseline `ready` marker so the existing guarded synthetic fixture can run; the fixture changes it to `seeded` in the same transaction as its rows. Thus the old marker continues to describe the old baseline and the separate capability marker describes the extension.

On repeat, both exact completion markers are required. The helper validates existing capabilities and performs the fixture's existing non-repairing verification. It does not replay migrations/grants, restore a removed scope, recreate a deleted account, replace a PIN or adopt another role. A revoked/missing grant or changed role/profile fails closed. A previous partial schema, old four-file schema without the capability marker, or foreign schema is refused; inspection/forward recovery is an operator decision, not a hidden reset.

## Required runtime pairing for the full profile

This helper always provisions AI + notification + Web Push capabilities. Its plan/result explicitly reports `DALA_WORKER_AI_ENABLED=true`, `DALA_WORKER_NOTIFY_ENABLED=true`, and `DALA_WORKER_CHANNEL=web_push`. A5 must set those in both Compose and the managed worker template. The general runtime's conservative notification default is false and intentionally fails exact-profile validation if left unchanged against this full role.

Provider activation is separate: `DALA_WEB_PUSH_ENABLED=false` keeps the configured notification lane paused with no reconciliation/claims while preserving the granted capability scope. Set it true only with the authorized existing VAPID configuration. This is no relaxation of grant validation and does not turn missing provider keys into notification failures. The older managed template's notify=false must be revised before its preflight can pass this bootstrap.

## API versus worker grants

The worker keeps its separately reviewed exact column-level profile. No PIN hash or CSRF access, human status/review write, photo validity/path/owner write, audit mutation, sequence privilege or DDL capability is added.

The API receives its accepted baseline profile plus:

- Photo INSERT
- Push SELECT and INSERT; UPDATE only `session_hash`, `endpoint_hash`, `endpoint`, `p256dh`, `auth`, `expires_at`, `generation`, `active`, `updated_at`, `last_error_code`
- SELECT only `lease_token, job_id` from `delivery_dispatches`
- SELECT only `lease_token, outcome` from `delivery_dispatch_results`
- Delivery-job UPDATE only `state`, `attempts`, `next_attempt_at`, `lease_until`, `last_error_code`, covering accepted invalidation/priority-notice behavior
- Only the actual orders-number sequence's USAGE/SELECT

There is no `GRANT ALL`, `SELECT ON ALL TABLES`, sequence wildcard, API dispatch-history mutation or worker-assessment insertion by the API. Existing full-row order persistence retains its accepted orders UPDATE permission.

A5's API validator integration signature is `validate_database(connect, *, photo_enabled=False, push_enabled=False, notification_enabled=False)`. The helper passes true for its installed capabilities when those explicit parameters exist, then independently checks exact extension privileges and required guards. A5 must mount push routes only with push capability and the 012-dependent priority hook only with notification capability. Old four-file startup cannot silently enable either.

## One mandatory disposable PostgreSQL gate

Offline:

`PYTHONPATH=backend python -m unittest discover -s ops/provision/tests -p test_worker_capabilities.py -v`

Mandatory real PostgreSQL:

`PYTHONPATH=backend python ops/provision/tests/test_worker_capabilities.py --postgres-disposable`

The gate requires `DALA_ACCEPTANCE_DISPOSABLE=1`, explicit local disposable `DALA_TEST_DATABASE_URL`, `DALA_ACCEPTANCE_RUNTIME_DATABASE_URL`, `DALA_ACCEPTANCE_WORKER_DATABASE_URL`, and operator-supplied test PINs. It creates only a random `worker_gate_…` namespace, runs the seven-file source path using the existing logins, verifies repeats/actual priority-hook reads and negative permissions, revokes one worker grant inside that namespace and verifies the helper refuses to restore it. It removes only its own random test namespace. It creates no role or credential.

The gate is intentionally not run by ordinary discovery and missing setup exits 2 with `NOT_RUN`. Current status: NOT_RUN because no explicit three-role disposable setup is supplied. Offline mock/catalog tests cannot certify real grants or transactions. A5 must run this gate and the assembled API→worker path before marking the package ready.
