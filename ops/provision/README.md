# Minimal synthetic demo provisioning candidate

Prepared for A5/operator setup and the C5 two-role browser rehearsal. **No hosting,
live database, real employee, new database access or account has been created by
this task.** Application/deployment URLs and secure credential handoff remain
operator prerequisites. C1 owns the separate historical 500+ order dataset.

This small fixture contains one synthetic section/equipment/work code/material,
two employees (`DALA-DEMO-MASTER`, `DALA-DEMO-EXECUTOR`) and their section membership.
It creates no order, submission, photo, assessment, session or notification.
Actual users must log in through the accepted session API; the lifecycle must be
performed through the real app, never seeded as a successful demonstration.

## Files and owners

- `prepare_demo_database.py`: plan-only by default; explicitly authorized owner
  may initialize one **new** schema with exact accepted migration hashes, grant
  the tested minimum profile to an already supplied restricted LOGIN, then run
  the actual application prerequisite validator
- `bootstrap_demo.py`: single first-start/safe-repeat entry point combining the
  reviewed initializer and minimal seed, with no database-role creation or
  credential generation; application PINs are explicitly supplied by the operator
- `database_profile.py`: reviewed acceptance profile, no role/credential creation
- `provision_synthetic_demo.py`: dry-run by default; adds only deterministic
  synthetic fixture IDs in one transaction, with actual Argon2id PIN hashes
- `C5_TWO_ROLE_RUNBOOK.md`: browser/device handoff, no claimed browser execution
- `tests/`: seven preparation checks plus four real PostgreSQL checks
- `run_demo_postgres_tests.sh`: non-skipping local-disposable CI gate for A5's
  existing pipeline; owner and runtime LOGIN must already be supplied

No backend domain module, contract, migration contents, root CI, historical seed,
frontend or browser automation is changed here. The accepted baseline is
`dfe9d8f7772b1a1c44f5a506c03e26c55fb5e1ca`. A future accepted migration needs an
explicit launcher update/review rather than globbing arbitrary SQL into a live DB.
Proposed integration path is `ops/provision/`; A5 separately owns `ops/demo/`
Compose/host packaging. These scripts do not touch those files.

## Operator setup, after authorization and hosting decisions

1. Obtain the exact accepted backend/image and the designated isolated demo DB
2. The operator supplies existing owner and restricted LOGIN identities through
   the approved private environment/secret mechanism. Do not put DSNs/PINs in
   chat transcripts, journals, screenshots, shell command arguments, source or
   artifacts. This package never creates a PostgreSQL role or saves credentials
3. Run both default plans and review the target schema/migration hashes/fixture
4. Only after confirming the isolated target, enable the explicit apply flags
5. Initialize a new schema, apply the fixture, then start the app with the
   **restricted runtime** DSN. Owner credentials must not enter the runtime
6. Verify actual HTTPS same-origin readiness/login through A5/C5 before claiming
   a deployed demo. No deployed endpoint is currently asserted by this package

Required private operator environment:

```text
DALA_DEMO_OWNER_DATABASE_URL       owner, setup only
DALA_DEMO_RUNTIME_DATABASE_URL     existing restricted LOGIN, same isolated DB
DALA_DEMO_MASTER_PIN               private 8–32 digit PIN
DALA_DEMO_EXECUTOR_PIN             distinct private 8–32 digit PIN
DALA_API_MODE=demo
DALA_DEMO_SEED_ALLOWED=1            explicit synthetic provisioning switch
```

Do not use the public PIN from acceptance tests. No default PIN or reusable
credential is printed, generated into a file, or embedded in the live fixture.
Use the approved secure mechanism to give each demo operator their own role's
PIN. This is isolated demo authentication, not production authentication.

Commands contain paths and a database **name**, not credentials:

```sh
# Preview only; no database connection
python ops/provision/bootstrap_demo.py \
  --backend <accepted-backend> --schema dalaai_demo
# Or preview each phase separately from this candidate's demo_ops directory:
python demo_ops/prepare_demo_database.py \
  --backend <accepted-backend> --schema dalaai_demo
python demo_ops/provision_synthetic_demo.py \
  --backend <accepted-backend> --schema dalaai_demo

# After target/permission/secure environment are confirmed by the operator
python ops/provision/bootstrap_demo.py \
  --backend <accepted-backend> --schema dalaai_demo \
  --expected-database <isolated-database-name> --apply
# The same combined command is safe to repeat with identical private inputs.
# Separate phase entry points are also available:
python demo_ops/prepare_demo_database.py \
  --backend <accepted-backend> --schema dalaai_demo \
  --expected-database <isolated-database-name> --apply
python demo_ops/provision_synthetic_demo.py \
  --backend <accepted-backend> --schema dalaai_demo \
  --expected-database <isolated-database-name> --apply
```

The launcher applies exactly 001, 002, `db/proposals/003_auth_rate_limits.sql`, 004.
It refuses a duplicate/moved 003, hash mismatch, wrong database, or an unmarked/
partial/foreign schema. First start writes a bundle-hashed schema comment in
`initializing` state and only changes it to `ready` after all four migrations,
scoped grants and actual runtime validation. First seed atomically changes `ready`
to `seeded` with all fixture rows; it checks this state after acquiring its
transaction lock. A repeat accepts only those exact ready/seeded markers and
successful current runtime validation; it does not replay migrations or grants.
Seeded repeats are verify-only and do not rewrite the marker. They refuse missing
references/accounts/memberships, so an operator-revoked scope or deleted account
is never restored. The first seed refuses unexpected preexisting fixture IDs. It does
not pretend four self-committing migrations are one transaction.
On partial failure it preserves the schema and reports confirmed migration names;
keep runtime disabled and inspect it. It never drops data to retry or adds a
silent migration/backfill. Adopting/upgrading an independently existing schema
is outside this tool.

Seeding is repeatable: identical existing fixture + matching supplied PINs yields
`ALREADY_PRESENT`. A changed PIN, role, label, identity or missing/extra membership causes
a conflict and rollback; the script never resets credentials or silently expands
existing access. Existing orders/history are never deleted or rewritten. An
unconfirmed commit remains unconfirmed; retry the same fixture only after checking
the target and result, using its idempotent comparison.

Runtime variables remain A5's actual interface:

```text
DALA_API_MODE=demo
DATABASE_URL=<restricted runtime DSN from private setup>
DALA_ALLOWED_ORIGIN=<one verified exact HTTPS origin>
DALA_DATABASE_SCHEMA=dalaai_demo
```

Use A5's accepted launch command/configuration (`app.main:app`, no untrusted proxy
headers or access logs). Do not disable Secure cookies, CSRF or origin checks to
make an HTTP/separate-origin setup appear to work. The public evidence journal
may contain commit/run IDs, fixture version, safe synthetic account codes, route
statuses and pass/fail/NOTRUN counts; it must contain no owner/runtime credential,
PIN, hash, cookie, CSRF token or raw login request.

## Verification status

Preparation checks and dry-run/schema-plan generation run locally. Real provision,
idempotency, safe conflict handling and actual two-role login checks are **NOTRUN
locally**, because no local PostgreSQL service/DSNs are available. A5 must run
`run_demo_postgres_tests.sh` with an existing temporary restricted LOGIN in its
single serialized pipeline before approving these new write helpers.

The already accepted actual app.main lifecycle passed at `dfe9d8f...`; it does not
automatically establish this separate provisioning script or a live deployment.
