# C112: isolated read-only historical analytics acceptance

Source-only handoff. This package does **not** claim a browser, TLS, database,
physical Android or preflight execution in C0. A5 owns all actual execution.
It never selects or changes C110's exact-one lifecycle test or existing gate.

## Frozen target and scenario

- Frontend: `bbe897514e58a4b8f8b6d4f580e5273e34cb5c75` (reviewed executor before-photo product, per
  [C0092 binding maintenance](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6051803090))
- Harness base: `4d38c71164a56b0eeefa9eb0430eb9100bcd7a3d`
- Exactly one test: `C112 real history analytics and protected reports`
- Exactly one project: `c112-android-chromium`; Playwright `1.63.0`, Chromium,
  Pixel 7 emulation, two independent contexts, ru-RU / Asia/Almaty
- Exact origin: `https://localhost:18443`; trusted TLS is mandatory
- Read-only business journey; only the two login POSTs are allowed. Any business
  mutation, cross-origin request, or WebSocket attempt fails the network gate

A fresh canonical history fixture has 540 orders, 568 submissions, 444 historical
photo references, no actual photo rows, and 17 disabled historical actors. The
live master sees four sections; the live executor sees the manifest's first
section. Users and section/dictionary IDs come from the actual
`ops/provision/history_demo.py::public_manifest()` object, not guessed IDs or
C110's minimal manifest. Do not supply the enclosing CLI `{status, fixture}`.
The manifest reader rejects extra fields, links and files over 16 KiB.

The UI is explicitly filled with **2026-07-01T05:00** and
**2026-10-01T05:00** in UTC+5, the canonical minute-only `datetime-local` form.
Both normalized field values are asserted after filling and before requesting
analytics. These map to the unchanged canonical API interval
`[2026-07-01T00:00:00Z, 2026-10-01T00:00:00Z)`. Local midnight would be a
different interval and is deliberately not used. Period metrics and whole-snapshot
historical provenance are separate assertions.

## What the one journey requires

1. Restricted real PostgreSQL read-only corroboration of the fresh fixture
2. Real UI login of the manifest master and executor in separate secure sessions
3. Master opens the navigation **button** “Аналитика и отчёты”, fills the explicit
   dates, loads a real `/api/v1/analytics/shift` response and sees matching
   540/568/444/444 synthetic/unavailable-photo provenance and the issued metric
4. A separately fetched protected shift report agrees with analytics; scoped DOM
   assertions use the “Выбранный отчёт” region
5. Select an order ID returned by the real facts/options, with historical photo
   references; its protected order report matches that exact observed fact and
   displays its own scoped unavailable-evidence counts. The exact-name combobox
   is scoped to the analytics region and must be unique; both `selectOption`'s
   returned ID and the actual field value must match the observed ID before fetch
6. Executor has no analytics UI and receives 403/FORBIDDEN, protected response
   headers and no report data from all three report/analytics paths
7. An independent second PostgreSQL observation has the same business-row digest,
   counts, identities and scopes. Auth session creation is intentionally excluded
   from the business-data digest; the journey is business-read-only, not login-free

The real spec never calls route.fulfill, setContent, a business mutation API,
setup/bootstrap, DB writes or a substitute server. Chromium receives an explicit
allowlisted environment, never inherited PIN/DSN/PG/preload/proxy variables.
Artifacts contain safe synthetic projections and hashes, not PINs, cookies, CSRF,
DSNs, storage paths, raw login responses or driver errors. Screenshot/video/trace,
HAR, debug capture and custom reporters are forbidden.

## A5 inputs and commands

The fresh preflight accepts only source/public execution inputs:

- `DALA_E2E_FRONTEND_SHA` = the exact reviewed frontend above
- `DALA_C112_RUN_ID` = unique `c112-` prefixed lowercase slug, 13–63 characters
- `DALA_C112_PREFLIGHT_RECEIPT` = new absolute receipt filename; existing files
  are not overwritten; no C110 receipt is accepted
- Optional `DALA_C112_PLAYWRIGHT_PACKAGE` = absolute directory of the already
  installed, locked `@playwright/test` 1.63.0 package

Run **without** PIN-file, fixture, observer-DSN or inherited PG inputs:

```sh
node tests/e2e/c112_secrecy_preflight.cjs
```

This launches only a disposable local dummy DOM. Exactly one unexpected
`C112_DUMMY_FAILURE_EXPECTED` failure must occur. Its stdout, stderr and every
bounded artifact are scanned for generated dummy PIN/DSN/cookie/CSRF sentinels.
Only then is a fresh, source-hash-bound, frontend-bound and run-ID-bound C112
receipt written. A normal pass, zero tests, skip, missing failure or sentinel
exposure is not proof. The receipt expires after 30 minutes. Every executable
C112 runtime source, gate, observer and package/lockfile is bound to the clean
committed harness HEAD. Run it again after source/HEAD changes with a fresh path.

Only after that successful proof, A5 supplies these actual-run inputs:

- `DALA_C112_AUTHORIZED=operator-provisioned-synthetic-only`
- `DALA_C112_WORKERS_DISABLED=ai,delivery,providers`; A independently verifies
  the actual disabled inventory, rather than treating this declaration as proof
- `DALA_E2E_BASE_URL=https://localhost:18443`
- `DALA_E2E_BACKEND_SHA` = exact backend source SHA verified by A
- `DALA_E2E_FIXTURE_FILE` = absolute path to the public history manifest object
- Existing `DALA_E2E_MASTER_PIN_FILE` and `DALA_E2E_EXECUTOR_PIN_FILE` = distinct
  private paths authorized for A's runner only; no values on the command line
- `DALA_C112_OBSERVER_DATABASE_URL` and `DALA_C112_DATABASE_SCHEMA` = A's
  explicit isolated observer inputs; no host/socket/passfile/service fallback
- Optional `DALA_C112_PYTHON` = A's trusted, source-bound observer adapter

```sh
node tests/e2e/node_modules/@playwright/test/cli.js test --config=tests/e2e/c112_playwright.config.cjs
node tests/e2e/c112_gate.cjs tests/e2e/c112_artifacts/$DALA_C112_RUN_ID/playwright.json tests/e2e/c112_artifacts/$DALA_C112_RUN_ID/evidence.json
```

If the locked package is installed elsewhere, use that package's `cli.js` and set
`DALA_C112_PLAYWRIGHT_PACKAGE` consistently; do not use an install-on-demand CLI.
No package, runner, workflow or Compose files are changed by C112.

The observer adapter is invoked twice with this exact public argument shape:

```text
DALA_C112_PYTHON tests/e2e/c112_observe.py <manifest-master-UUID> <manifest-executor-UUID>
```

A owns binding any adapter/container mount to the accepted C112 source and
project, its TLS trust, the actual built app SHAs, secret injection and process
inventory. The old one-UUID C110 adapter is not compatible without a separate
A-owned C112 seam. The observer needs SELECT on orders, order_events,
submissions, reviews, photos, material_writeoffs, ai_assessments,
operation_receipts, and safe employee/employee_sections columns. It never queries
password hashes or session secrets. The accepted observer architecture reuses C110's existing restricted runtime
LOGIN with an enforced repeatable-read READ ONLY transaction and before/after
business-data corroboration. Superuser/CREATEDB/CREATEROLE/BYPASSRLS/schema-CREATE
roles are rejected. This is **not** a SELECT-only role or a claim that the login
cannot write in another transaction. No new role, grants or credentials are
required or authorized. A binds the wrapper and supplies only its existing
approved runtime secret.

Output is isolated under `tests/e2e/c112_artifacts/<run-id>/`. Reusing an artifact
run ID is rejected. The gate requires the exact attached evidence bytes, one
unretried passing test, every step, current proof/source/run/app identities,
actual protected API/DB observations and unchanged business state. A stale,
C110, empty, skipped, flaky, partial, mock-only or expected-failure run cannot
promote the result. The final JSON gate receipt is the outcome; merely starting
Playwright or seeing a green source test is insufficient.

## Source-only checks

```sh
node --test tests/e2e/c112_*.test.cjs
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/e2e -p 'c112_*test.py' -v
```

These use isolated mocks and the offline public-manifest function. They do not
read private files, connect to PostgreSQL, launch browsers or issue an execution
receipt. C110 lifecycle, physical Android, native camera, push delivery, model
provider, live closure and report export remain separate NOT_RUN gates.

## Failure localization without private diagnostics

`evidence.diagnostics` adds only three fixed-label fields: `substep`,
`failure_category`, and `analytics_response`. The latter is a category such as
`NOT_OBSERVED`, `HTTP_OK`, `HTTP_VALIDATION` or `HTTP_UNAVAILABLE`, never a raw
status/body/URL. Checkpoints distinguish navigation, period inputs, matching
response, each protected-header requirement, JSON/period/provenance/count/DB
checks, unavailable-photo notice, disclosure expansion and issued metric.
No exception text, DOM text, request data or response headers are copied.

An empty `observations` list alone does not mean no API response: the original
stage records its complete API/UI observation only after every assertion passes.
The fixed diagnostics are advisory and cannot make a failed gate pass. Their
helper is source-bound and exercised by the mandatory dummy-failure preflight.
The diagnostic-source change requires a new receipt on the exact accepted HEAD.
The date-fill and semantic order-selector corrections change source-bound files:
A5 must generate a fresh preflight receipt for the exact newly accepted HEAD
before the actual rerun.

## Final target compatibility and historical evidence

Read-only comparison of `9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c` with the final
target verified that `AnalyticsView.tsx`, `Reports.tsx`, the period model,
analytics protocol, order store, login fields and existing lifecycle selectors
are unchanged. The navigation button, canonical date fields, exact scoped
`Наряд для отчёта` combobox and report/provenance regions remain compatible.
The existing minute-only fills and unique-selection/value checks stay intact.

`AnalyticsScreen` appends download controls after the existing view. They only
subscribe on mount; fetching requires «Подготовить PDF/XLSX» and saving requires
a further explicit gesture. C112 never invokes either. Their auth/session/report
guards and cancellation lifecycle do not modify the JSON report flow when idle.
The shared API additions preserve the old JSON analytics/report request paths.

App keeps the session-keyed Workspace mounted inside a visibility wrapper and
adds a separate master-only demo-clock mount. Its controller starts idle and
attach only subscribes; neither mount nor tab switching performs clock GET/POST.
Reads and CAS controls require explicit buttons, which C112 never clicks.
Workspace/analytics state and session-epoch cleanup remain in place. This source
review does not establish runtime behavior or download/demo-clock acceptance.

A0 reported the historical 9a1d6109 C112 full PASS on main
`347119c47b9a0ec70cd30cbc8bce2a2774a439e0`,
[run 37712740639, job 113102167252](https://github.com/a4ns/DalaAI/actions/runs/37712740639/job/113102167252).
That result remains attached only to 9a1d6109. The final faef5d3d browser/API/DB
run is **NOT_RUN in C0** and needs A's fresh runtime acceptance.

Only the final exact target is accepted. Old/unknown/shortened selections,
old report/evidence identities and old frontend/source/hash/run-bound receipts
fail closed. This contract change invalidates its bound file hash; A must create
a fresh preflight on the final accepted committed harness HEAD, with a new C112
run ID and receipt. No old PASS or proof may be relabeled. Test/project/stage
counts, periods, fixture counts, timeouts, security and separate gates are unchanged.
