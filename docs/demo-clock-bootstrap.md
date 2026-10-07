# Optional fresh-demo clock bootstrap

Source-only, opt-in profile. This is not a deployment, reset, schema upgrade, role
creation, credential creator, or permission-repair tool. Do not run it against a
live or previously initialized minimal/history schema to add clock capability.
The existing four/seven-migration bundles and minimal/history receipts remain
unchanged. A5 owns runtime assembly, capability-aware validators, and CI.

## Entry point and explicit selection

`enable_demo_clock.apply_capabilities(args, environment)` expects `args.backend`
(`Path`), `args.schema`, `args.expected_database`, and `args.bootstrap=True`.
The CLI is `python ops/provision/enable_demo_clock.py --backend backend --schema
<new_isolated_schema> --expected-database <isolated_database> --bootstrap --apply`.
Without `--apply`, the CLI only prints the pinned eight-file plan and clock grant
profiles; it never opens a database or reads/prints credentials.

The authorized operator must separately supply:

- `DALA_API_MODE=demo`, `DALA_DEMO_SEED_ALLOWED=1`,
  `DALA_DEMO_WORKER_CAPABILITY_ALLOWED=1`, `DALA_DEMO_CLOCK_CAPABILITY_ALLOWED=1`
- A fixed, canonical `DALA_DEMO_CLOCK_INSTANCE_ID` UUID; API and worker must use
  this same UUID and the same database/schema. Do not generate a new ID on restart
- The existing owner/API/worker LOGINs through `DALA_DEMO_OWNER_DATABASE_URL`,
  `DALA_DEMO_RUNTIME_DATABASE_URL`, `DALA_DEMO_WORKER_DATABASE_URL`. The helper
  creates no LOGIN, credential, persistent access token, provider key, or account
  role. Runtime identities must be distinct, direct, restricted logins
- Fresh bootstrap only: the existing private demo PIN inputs required by the
  reviewed worker fixture helper. These are never returned/logged by this helper
- Optional `DALA_DEMO_FIXTURE_MODE=history`; default remains `minimal`. Both are
  fresh-profile choices. Changing an existing profile is refused

Services must remain stopped during bootstrap and after any failure. Successful
provisioning does not start services or enable routes. Mounting the clock and
allowlisting only the existing synthetic master are separate A5 runtime steps.

## Exact behavior and permissions

An absent schema invokes the unchanged full-worker bootstrap once. Only its
fresh-success result can proceed. Pinned optional proposal 013, one clock row,
clock grants, and an `initializing` clock-table receipt commit in one transaction.
All initial anchors use one materialized PostgreSQL real-time sample: version 0,
scale 1, synthetic true, seven-day domain horizon. Capability-aware API/worker
validators must pass before the separate clock receipt becomes `complete`.

- API: SELECT state/controls, UPDATE only state `version`, `real_anchor`,
  `domain_anchor`, `scale`, and INSERT controls
- Worker: SELECT state only
- Neither receives state INSERT, audit mutation, DELETE, TRUNCATE, ownership,
  identity/horizon edits, or grant options through this extension

On repeat, the exact full-worker receipt and exact clock receipt must match the
chosen fixture, existing identities, pinned migration, and instance. The helper
verifies exactly one synthetic row and enabled API/worker validators. It never
calls a seed, migration, GRANT, receipt rewrite, or repair on repeat. Private PIN
inputs are unnecessary for a completed repeat. Current clock scale/version/time
and existing history/accounts/scopes remain intact.

Any existing schema without that completed clock receipt is refused, including
foreign, base-only, partially initialized, interrupted, or mismatched profiles.
Missing/revoked/excess permissions are validation failures, not permission to
repair them. Failures preserve committed state for operator inspection. A crash
after base initialization or before the completed clock receipt is deliberately
not automatically resumable. No reset/drop/cleanup path exists in the helper.

This is business time only. Authentication/session and staged-photo TTLs,
leases/backoff, request and provider timeouts, monotonic admission, budget and
approval expiry all continue using real clocks. Acceleration cannot extend them.

## Reproduction and evidence

Use the existing locked development dependencies:

```sh
PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_demo_clock_bootstrap.py' -v
python -m compileall -q ops/provision/enable_demo_clock.py backend/tests/test_demo_clock_bootstrap.py ops/provision/tests/test_demo_clock_bootstrap_postgres.py
```

Mandatory actual-PG gate (no mocks replace its database behavior):

```sh
PYTHONPATH=backend python ops/provision/tests/test_demo_clock_bootstrap_postgres.py
```

The gate requires `DALA_ACCEPTANCE_DISPOSABLE=1`, three existing local LOGIN DSNs
(`DALA_TEST_DATABASE_URL`, `DALA_ACCEPTANCE_RUNTIME_DATABASE_URL`,
`DALA_ACCEPTANCE_WORKER_DATABASE_URL`), and the private demo PIN inputs. DSNs must
name the local host/socket, database, and user; remote/service indirection is
refused. It creates and cleans up only uniquely named synthetic test schemas.
Eight cases cover fresh anchors, persisted control/repeat, real denied SQL,
revoked grants without repair, base-only adoption refusal, interrupted receipt,
wrong instance/excess privilege, and fresh 540-order history preservation.
Missing inputs return **2 / NOT_RUN**, never skip/green. Any test failure or skip
fails the gate. A5 must run this with its mounted capability-aware validators.

Local source checks: 18 passed at initial delivery. Actual PostgreSQL: **NOT_RUN**;
no installed PostgreSQL binary or authorized disposable DSNs were available.
This does not establish mounted runtime, full aggregate, hosted HTTPS, physical
phones, external notification delivery, or security-clock runtime regression.
