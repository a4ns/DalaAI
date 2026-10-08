# Canonical migration map — 2026-10-08

A5 is the sole integration writer. This map reserves filenames and specifies the
reviewed source paths; a reservation is not execution evidence. Never copy stale
shared migrations/services out of a worker's dependency snapshot.

| ID | Canonical source path | Dependency / activation |
|---|---|---|
|001|backend/db/migrations/001_vertical_slice.sql|Core schema, accepted and exercised|
|002|backend/db/migrations/002_trusted_evidence.sql|After001; refuses populated submissions without explicit backfill|
|003|backend/db/proposals/003_auth_rate_limits.sql|Accepted sessions; explicit launcher applies these exact bytes once; do not duplicate in migrations|
|004|backend/db/migrations/004_immutable_reference_keys.sql|Required protected row-lock key grants; accepted and exercised|
|005|backend/db/proposals/005_web_push_subscriptions.sql|Validated Web Push capability; full launcher applies once before API/worker activation|
|011|backend/db/migrations/011_durable_job_leases.sql|Validated AI lease fencing; required before AI worker capability|
|012|backend/db/migrations/012_delivery_dispatch_attempts.sql|Validated dispatch audit/lease fence; required before notification worker AND priority-notice command hook|
|013|backend/db/proposals/013_demo_business_clock.sql|Optional fresh-demo clock wrapper only; same instance and enabled capability on API/worker|

There is no013 migration in the priority-notice delta. Its helper and service hook
read012's dispatch audit across all scheduling revisions of the current assignment.
Optional 013 remains outside default clock-off activation. Photo storage uses001/002
and private physical storage; it adds no SQL migration.

Pinned SQL hashes:
-005:152c4bada41b8ca7eddd25d8aa06a2cfe0b9b0bed578555fa70a0f265e064477
-011:e517a44d247b20f00133f93627ddf43109d5a8a610e39273ef74ffcde6c11495
-012:14351dc30aaec1fd517d5db47644961dbf1982a54ce7af4cb1b0a98def0b49e1
-013:dd37cbfcb25497f67f9390e3b9171b763d7022caa26ee5ef775c34d697c86158

Owner bootstrap, API startup and dedicated worker startup must agree on the exact
schema/capabilities before activation. The old four-file bootstrap is not a valid
initializer for an enabled012-dependent priority hook. API and worker roles stay
separate. WebPush requires005; notify needs012; AI needs011. Missing Web Push keys
pause notification consumption and preserve pending delivery jobs, without removing
schema gates. Missing OpenAI keys keep AI jobs active through rules fallback.
No migration or role is applied merely by publishing this map.

The full seven-file worker profile and optional eight-file clock profile have
actual PostgreSQL and runtime evidence. [Managed-image CI at 2d1a407](https://github.com/a4ns/DalaAI/actions/runs/37712260125/job/113100631476)
ran a fresh history+clock setup, the actual API/worker/photo/report flow, and
container restart persistence. [Clock PostgreSQL gates at 2b6e8ab](https://github.com/a4ns/DalaAI/actions/runs/37704403122)
ran the required 6+8+4 cases. These runs do not apply migrations to a hosted or
existing database; the operator must still validate the exact target/profile.
