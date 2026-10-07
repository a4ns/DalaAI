# Explicit mounted demo runtime

The ASGI entry point is app.main:app. DALA_API_MODE=health (the default) preserves
health-only startup. DALA_API_MODE=demo mounts nine accepted session/order/dictionary
operations only when DATABASE_URL and one exact DALA_ALLOWED_ORIGIN=https://host
are supplied. DALA_DATABASE_SCHEMA defaults to public and accepts one simple
lowercase PostgreSQL identifier. Configuration and driver errors never print DSNs.

The demo role must be a distinct restricted LOGIN, neither object owner nor a
member of any object-owner role, without superuser, database/role creation,
BYPASSRLS or schema CREATE. Schema setup is a separate owner operation. Apply
001_vertical_slice.sql, 002_trusted_evidence.sql, the accepted session candidate
003_auth_rate_limits.sql (currently under db/proposals), and
004_immutable_reference_keys.sql. Never apply 002 to populated submissions without
its separately reviewed backfill. Startup does not apply migrations or create
roles, PINs, seed data or sessions.

The runtime permission profile is the union of the exercised command/discovery
role and the session role. Exact grants are exercised by the disposable real-PG
CI, not provisioned against a deployed service. Startup checks required columns,
enabled receipt/audit/identity/evidence guards, expected INSERT and column UPDATE,
order sequence access, and refuses sensitive auth/file-validation UPDATE grants.
A failed prerequisite raises a generic RuntimePrerequisiteError with a fixed code.
Readiness repeats these checks; liveness remains process-only. Requests cannot
use domain routes before a successful application lifespan startup.

The runtime uses wall UTC, Secure HttpOnly same-origin cookies, explicit dictionary
workload policy and durable synthetic delivery intents. No scheduler loop, delivery
provider, AI worker, network model call, public file mount or fabricated assessment
is started. Until private blob integrity verification is integrated, every
submitted photo is unknown at the runtime CLOSE boundary even if file_valid=true
in PostgreSQL. Planned no-photo completion remains available; required-photo
closure fails closed with no successful receipt or review.

Use the pinned image or installed dependencies to run uvicorn app.main:app with
--no-proxy-headers and --no-access-log. Supply runtime settings through your
approved local environment; never commit a DSN/PIN. The existing make dev Compose
profile remains health-only with its own disposable database owner. Do not enable
demo mode against that owner connection. An HTTPS same-origin ingress and any
trusted proxy-address mapping are separate deployment work. The image deliberately
ignores forwarded headers until an explicit trusted ingress is configured.

Evidence boundaries: eight focused PostgreSQL tests execute this actual factory,
including real lifespan, scoped role, readiness failure and unverified-blob close.
The separate frozen v1 harness still proves test-owned component assembly. Actual
mounted lifecycle evidence is a distinct gate; in-process HTTPS-origin ASGI checks
do not establish deployed TLS, browser/Android, notifications or photo performance.
