# One application dataset: canonical history plus two live demo accounts

This is an **explicit fresh-database operator option**, not a migration of an
existing live/minimal fixture. The default minimal mode remains unchanged. Source
and disposable tests do not imply permission to initialize a real demo account,
grant access, create credentials, run a provider or deploy a service.

## Exact fixture

- Unmodified C107 loader `2836cec1c5351544c286e72503ad4b5b7590d847`
- Unmodified generator `8af3897f03aa2f41f0af07ec74ec2c807a4a535a`
- Canonical export SHA-256
  `7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`
- 540 synthetic orders issued July 1–September 30, 2026; source dates, UUIDs,
  canonical 17-actor mapping and import/photo provenance are unchanged
- All 17 historical actors are inactive, off-shift, and retain the public
  non-authenticating disabled sentinel. Their scopes are never expanded
- Two separate live accounts use the existing stable IDs/codes:
  `DALA-DEMO-MASTER` has all four canonical sections; `DALA-DEMO-EXECUTOR`
  has only `SYN-SECTION-001`. Both are active/on-shift, without a brigade
- Human/operator-provided distinct private PINs use the existing Argon2id profile
- No new live order, photo, session, AI assessment or notification is seeded

The master can read the 540 historical orders through the normal scoped API and
issue a new order in section 001 to the live executor. The executor initially has
an empty order list, cannot open another historical executor's orders, and uses
the real accept → start → submit → master review flow on the new order. The
historical actors are not selectable active executors. Use planned work for a
photo-free rehearsal; unplanned work still requires actual valid after-photo
evidence for closure.

Historical photo metadata is **not image evidence**. This bridge never creates
photo records or `file_valid` claims. The C111 report reader's exact canonical
provenance exception is a separate required integration for historical reports.

## A5 bootstrap seam and startup order

The reviewed launcher should accept `DALA_DEMO_FIXTURE_MODE=minimal|history`,
defaulting to `minimal`, validate it before writes, and bind that choice into its
initialization/completion fingerprint. The mode is not inferred from existing
rows, supplied PINs, or a failed attempt. The history code itself does not grant
privileges, apply migrations, generate credentials or start services.

For history mode, keep services stopped while the operator-owned setup runs:

1. Validate explicit isolated target, existing owner/API/worker LOGINs and
   operator-supplied PINs before the first write
2. Create a new schema and apply the exact accepted seven migrations and grants
   using the existing worker-capability bootstrap
3. Once runtime validation passes and the schema has the standard `ready`
   marker, call `history_demo.apply_fixture(owner, expected_database, pins)`
   instead of the minimal fixture
4. The bridge verifies pinned source hashes and requires every table empty;
   it commits a history-specific `initializing` schema receipt
5. C107 imports its exact canonical history in **its own transaction**
6. The bridge creates the two live accounts and their 5 memberships, the
   history-specific complete receipt on `sections`, and the standard `seeded`
   schema marker **together in one final transaction**
7. Only after that succeeds may the launcher mark its profile complete and
   start the API/worker/web with their separate restricted identities

The existing setup service must receive the mode consistently on first start
and repeat. A5 owns the actual one-command Compose dispatch and verifies it on
the assembled commit. Do not claim a shell/Compose command supports this option
until that dispatch has been integrated and tested.

Required image inputs: `ops/provision/history_demo.py` plus existing provision
helpers and exact `scripts/synthetic/load_demo.py` and `generate.py`. At the
normal repository layout the source root is inferred from the module location;
an embedding launcher can supply `source_root` explicitly if its image differs.
The source hashes are checked before executing either pinned module. There is
no Git fetch/network fallback or evaluator-truth export into the database.

Offline plan, with no database connection or secret access:

```sh
python ops/provision/history_demo.py
```

This script intentionally has no apply CLI. Only the explicitly authorized,
profile-bound bootstrap owns creation of the live accounts. PINs/DSNs must never
appear in shell arguments, source, output, screenshots or evidence artifacts.

## Repeat and failure behavior

The same fixture lock serializes history and minimal seed attempts. Successful
history repeats require the exact standard `seeded` schema marker **and** exact
history completion receipt. They verify the live PINs/identity/memberships,
17 historical actors' locked state and immutable creation provenance for the
540 imported orders. Newer live orders, events, sessions and worker data are
allowed; they are not compared to an old snapshot or rewritten. No import,
grants, migration replay, reactivation, credential reset, scope restoration or
business-data change occurs on repeat.

An existing minimal fixture, unmarked/preimported schema, foreign schema,
missing actor/scope, changed PIN or incomplete receipt fails closed. The import
and final live-account transaction are deliberately **not advertised as one
atomic transaction**. A failure after initialization keeps the history-specific
initializing receipt and any committed import for operator inspection. The
launcher must keep all services stopped. Do not reset, adopt, retry as minimal,
delete data or replay grants automatically; choose a separately authorized new
isolated schema or have the operator investigate the preserved one.

## Looking at historical analytics

Use the master account and retain the visible synthetic-data watermark. The
report API's default maximum is 31 days, so use adjacent UTC monthly ranges:

- July: `[2026-07-01T00:00:00Z, 2026-08-01T00:00:00Z)`
- August: `[2026-08-01T00:00:00Z, 2026-09-01T00:00:00Z)`
- September: `[2026-09-01T00:00:00Z, 2026-10-01T00:00:00Z)`

The three `issued_orders` totals must sum to 540. Today's shift correctly does
not count the old history as newly issued work. A new live order uses the real
application/domain clock; history is never shifted forward to make a dashboard
look populated. The list endpoint can paginate all 540 under the same master
session. C111 must be mounted to claim `/api/v1/reports/shift` and
`/api/v1/analytics/shift` acceptance.

## Verification and ownership

```sh
python -m unittest discover -s ops/provision/tests -p test_history_demo_inputs.py -v
# Explicit disposable local owner/runtime inputs from the existing A5 runner:
# DALA_TEST_DATABASE_URL, DALA_ACCEPTANCE_RUNTIME_DATABASE_URL,
# DALA_DEMO_TEST_BACKEND, DALA_ACCEPTANCE_DISPOSABLE=1
DALA_HISTORY_DEMO_DISPOSABLE=1 python ops/provision/tests/test_history_demo_postgres.py
# After accepted C111 is mounted: 10 total cases, zero skips required
DALA_HISTORY_DEMO_DISPOSABLE=1 python ops/provision/tests/test_history_demo_postgres.py --with-reports
```

Seven offline tests cover source/identity pins, scope contract, unchanged minimal
default, receipt binding, refusal of changed source, input preflight and secret-free
offline plan. Nine real PostgreSQL tests cover import/verify-only repeat, minimal
profile refusal, PIN/revoked membership/deleted identity refusal, historical actor
mutation refusal, interrupted import/wrong target, seven-migration schema import,
preservation of an import committed before a final-stage failure, disabled identity
guard refusal, and actual `app.main` two-session discovery/lifecycle/repeat. The tenth opt-in
case checks the real mounted reports/analytics with monthly windows and executor
denial. All gate tests fail on missing inputs or connection errors; no mock,
skip, missing route or offline plan is PostgreSQL/report/deployment evidence.

This package only owns this helper, its two tests and this document. A5 owns
launcher/profile/Compose integration and publication. The designated security
reviewer owns independent review. No C107/C111/domain/auth/contract file is
modified by this package.
