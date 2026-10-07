# Canonical migration map — 2026-10-07

A5 is the sole integration writer. This map reserves filenames and specifies the
reviewed source paths; a reservation is not execution evidence. Never copy stale
shared migrations/services out of a worker's dependency snapshot.

| ID | Canonical source path | Dependency / activation |
|---|---|---|
|001|backend/db/migrations/001_vertical_slice.sql|Core schema, accepted and exercised|
|002|backend/db/migrations/002_trusted_evidence.sql|After001; refuses populated submissions without explicit backfill|
|003|backend/db/proposals/003_auth_rate_limits.sql|Accepted sessions; explicit launcher applies these exact bytes once; do not duplicate in migrations|
|004|backend/db/migrations/004_immutable_reference_keys.sql|Required protected row-lock key grants; accepted and exercised|
|005|backend/db/proposals/005_web_push_subscriptions.sql|Reserved/frozen WebPush source; apply once before API subscription/worker WebPush capability|
|011|backend/db/migrations/011_durable_job_leases.sql|Frozen AI lease fencing; required before AI worker capability|
|012|backend/db/migrations/012_delivery_dispatch_attempts.sql|Frozen dispatch intent/result audit and lease fence; required before notification worker AND priority-notice command hook|

There is no013 migration in the priority-notice delta. Its helper and service hook
read012's dispatch audit across all scheduling revisions of the current assignment.
The later optional demo-clock reservation is backend/db/proposals/013_demo_business_clock.sql; it stays outside core activation. Photo storage uses001/002
and private physical storage; it adds no SQL migration.

New frozen SQL hashes, pending their own integration/runtime evidence:
-005:152c4bada41b8ca7eddd25d8aa06a2cfe0b9b0bed578555fa70a0f265e064477
-011:e517a44d247b20f00133f93627ddf43109d5a8a610e39273ef74ffcde6c11495
-012:14351dc30aaec1fd517d5db47644961dbf1982a54ce7af4cb1b0a98def0b49e1

Owner bootstrap, API startup and dedicated worker startup must agree on the exact
schema/capabilities before activation. The old four-file bootstrap is not a valid
initializer for an enabled012-dependent priority hook. API and worker roles stay
separate. WebPush requires005; notify needs012; AI needs011. Missing provider keys
pause the consuming lane and preserve pending work, without removing schema gates.
No migration or role is applied merely by publishing this map.
