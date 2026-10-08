# C-110: real composed browser/API/PostgreSQL core journey

Current final product target: **browser/API/DB rerun NOT_RUN** in C0's environment.
Source/parser tests are separate evidence. This is an executable Playwright
journey, not a completed runtime result. No successful business response is
mocked. For the next C110 manual-core gate, the final frontend is pinned
**only** to `8081a2984b2f27b909fa2b86cd9f10ffd01d1e11`, per
[C0092 binding maintenance](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6051803090).

A5 builds/binds that exact candidate and records its exact backend source SHA.
The previous `9a1d6109` / `3ef269b` / `ca320bf` / `2beb2244` baselines, intermediate `45a65ae`, shortened
SHAs and unknown candidates are rejected. Earlier baseline evidence is not relabeled.

Historical ca320bf manual-core PASS was reported by A0 on exact main
`ab632c0cf411b7670c1a03fe7aa97419950019a2` in
[this CI job](https://github.com/a4ns/DalaAI/actions/runs/37697793713/job/113053699040).
Historical optional-UI 3ef269b manual-core PASS was later reported by A0 on
`3d4312b815fd7ca60baa176dc1e3449f9ca3a34f` in
[this dedicated CI job](https://github.com/a4ns/DalaAI/actions/runs/37701307143/job/113065128591).
Those results cover only their recorded older targets. A0 subsequently reported
9a1d6109 manual-core PASS on main `2471afde` in
[run 37710664244, job 113095586907](https://github.com/a4ns/DalaAI/actions/runs/37710664244/job/113095586907),
bound to harness `d674d8a1cc261760c89b04b555123ca775f3c845`.
No historical result covers faef5d3d. A5 must run fresh preflight and core for
the current exact product; source review does not establish aggregate success.

## Stable A5 integration seam

Authoritative coordination:
- [A0-0035](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046581967)
- [A0-0036](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046630968)

A5 owns provisioning, CI/bootstrap, trusted ephemeral CA, server startup and
teardown. C110 owns only the test configuration and journey. It never creates
roles, grants permissions, applies migrations, seeds orders or starts a server.
No private PIN files are opened by source/unit checks. Only A5's authorized test
execution reads operator-supplied PIN files. C0 must not run that step locally.

Configuration: `tests/e2e/c110_playwright.config.cjs`
Project: `c110-android-chromium`
Spec: `tests/e2e/c110_core.spec.cjs`
Mandatory test title: `C110 real composed master executor lifecycle`
Mandatory test count: **exactly 1**, containing **6 mandatory asserted stages**.
One worker, zero retries. No `.skip`, expected-failure or empty-suite success.

Required inputs:

| Variable | Meaning |
| --- | --- |
| `DALA_E2E_BASE_URL` | Exactly `https://localhost:18443` |
| `DALA_E2E_FIXTURE_FILE` | Public fixture object from A0-0036, without dry-run wrapper |
| `DALA_E2E_MASTER_PIN_FILE` | Operator-private file for the synthetic master |
| `DALA_E2E_EXECUTOR_PIN_FILE` | Operator-private file for the synthetic executor |
| `DALA_E2E_FRONTEND_SHA` | Exactly `8081a2984b2f27b909fa2b86cd9f10ffd01d1e11`, required for preflight, core and evidence gate |
| `DALA_E2E_BACKEND_SHA` | Exact 40-hex source SHA used to build the running backend |
| `DALA_C110_RUN_ID` | Unique non-secret lowercase identifier, 8–64 chars, digits/hyphens allowed |
| `DALA_C110_PREFLIGHT_RECEIPT` | New absolute public receipt path written by the mandatory executable preflight below |
| `DALA_C110_AUTHORIZED` | `operator-provisioned-synthetic-only` |
| `DALA_C110_WORKERS_DISABLED` | `ai,delivery,providers`, only after A5 confirms all three are disabled |
| `DALA_C110_OBSERVER_DATABASE_URL` | Existing restricted loopback PostgreSQL LOGIN URI supplied by A5, explicit authentication, no credential-file fallback |
| `DALA_C110_DATABASE_SCHEMA` | Existing isolated non-public schema used by that runtime |
| `DALA_C110_PYTHON` | Optional interpreter with the backend's existing `psycopg` dependency |
| `DALA_C110_PLAYWRIGHT_PACKAGE` | Optional absolute B-owned installed `@playwright/test` package directory; otherwise the local pinned dependency |

`DEBUG`, `PWDEBUG`, and `NODE_OPTIONS` must be unset. The DB observer also
rejects inherited nonempty `PG*` variables to prevent libpq service/auth/file
overrides; A5 must provide only the explicit observer URI in its subprocess. A5 must not enable protocol,
API, network-body, HAR or auth tracing. The config rejects those debug/preload
environments and disables trace/video/screenshots. The test creates clean
contexts without storage-state/HAR/recording options. Never log environment
values, raw login bodies, PINs, DSNs, session cookies or CSRF values.

### Mandatory executable failure-output preflight

Trace-off and a bare operator boolean are **not proof of secrecy**. In A5's
allowed disposable runner, after selecting `DALA_E2E_FRONTEND_SHA` and before
exporting real fixture/PIN/observer inputs:

```sh
# DALA_C110_PREFLIGHT_RECEIPT is a new absolute, non-secret output path.
node tests/e2e/c110_secrecy_preflight.cjs
```

The wrapper preserves only the public frontend SHA from `DALA_E2E_*`; it
refuses inherited fixture/PIN-file/observer inputs and uses pinned
Playwright 1.63.0. Its separate project `c110-secrecy-preflight` contains exactly
one intentionally failed test `C110 dummy credential failure output`. A disabled
dummy-DOM PIN input exercises the **same 5-second fill timeout and shared generic
login-error boundary** used by the real journey. Additional dummy DSN, session
and CSRF values exercise lower-layer error suppression. No app/server/real login
or private fixture file is used. The intentional dummy result must have exit 1,
one unexpected failure with the exact marker, no skips/retries/runner errors.
It can never count as the core test's PASS.

The wrapper captures and scans stdout, stderr and every small text/JSON artifact
in its newly created private temporary directory, including base64 JSON
attachment strings. Sentinel matches, truncated/oversized output, symlinks,
unknown compressed/binary artifacts, missing reports or wrong counts all block
success. Raw dummy artifacts are discarded, never echoed. Only successful
verification writes a public receipt with harness and selected frontend SHAs, relevant file hashes,
pinned version, expected/observed failure count, zero matches and output digest.
The receipt expires after 30 minutes. Core config and fixture loading verify it
before real input files are read. There is no boolean override. Both preflight and core enforce their exact checked
config, list/JSON reporters with step printing off, one worker/repeat, zero
retries, and an allowlist of context options. HAR/logger/storage-state/launch/
connect overrides and alternate configs/reporters are rejected before PIN use.

Changing either the harness source or pinned frontend identity invalidates
the receipt. The gate requires the same selected SHA in its environment,
Playwright report metadata and journey evidence; old or mismatched source identities
are rejected rather than relabeling an older run. A5 still owns build/source matching proof.

Then A5 can supply the real synthetic fixture/PIN/observer inputs and run the
core suite. Any source/config/helper change or missing/stale receipt requires
repeating the preflight. Its actual execution remains NOT_RUN in C0's environment.
A5 must retain normal secure masking of runner outputs and publish only reviewed
allowlisted artifacts. A blocked preflight is a credential-execution blocker.

The browser and Node API client must trust A5's test certificate normally. A5
uses a disposable HOME/NSS profile and per-process CA bundle, never an existing
profile/system trust store. There is no `ignoreHTTPSErrors`, warning bypass,
public host, tunnel, deployment or browser-security workaround.

### Public fixture object (no credentials)

- `fixture_version`: `dalaai-live-vertical-demo-v1`
- `data_classification`: `synthetic demo only`
- `section`, `equipment`, `work_code`, `material`: each `{id, code, label}`
- `users`: `{id, employee_code, role, section_ids, on_shift}` entries
- Master: `DALA-DEMO-MASTER`, `8d27067c-4e86-50a2-87c4-f1012f53a2bb`
- Executor: `DALA-DEMO-EXECUTOR`, `37baa480-be02-54bc-837c-6c0b2a00ec12`
- Section: `6907df3e-d9e3-53e2-aa91-c874b453d960`
- Equipment: `2348bd85-4627-542e-8638-1a7297e4e6c5`
- Work code: `e7c29005-c026-5017-adcc-2292434500b8`
- Material: `92444401-f0ee-56f3-b49b-3d329f50f54d`

Source identities are separately supplied in the two `DALA_E2E_*_SHA` fields.
The evidence explicitly calls their origin **operator build provenance**, not
an independently measured runtime commit. A5 must attach build/source matching
proof. C110 independently records its actual committed harness HEAD and refuses
tracked test-source modifications. No pre-seeded order/session/photo is used.

## Authorized A5 execution

The package lock preserves the exact Playwright 1.63.0 dependency entries and
integrities from the reviewed B lock, without adding root/frontend packages.
Install only through A5's allowed dependency/bootstrap path. Then:

```sh
npm --prefix tests/e2e run test:e2e
node tests/e2e/c110_gate.cjs tests/e2e/c110_artifacts/playwright.json <c110_evidence-attachment-json>
```

A5 must propagate both nonzero exit codes and run the gate even after Playwright
failure. Missing report/evidence is not PASS. The gate binds the evidence file
to the exact Playwright JSON attachment, requires one pass, no skipped/filtered
mandatory test, no retries/flaky/expected failure, all six stages, the real DB
projection and all 11 committed command receipts. Do not upload unreviewed raw
runner logs. The public artifact is the allowlisted `c110_evidence` projection.

## What actually runs

Two separate Chromium contexts use Playwright's **Pixel 7 Android emulation**
with touch/mobile mode, RU locale, UTC+5 and blocked service workers. Browser
version, UA, viewport and scale are recorded. All requests are same-origin;
external requests are aborted, never fulfilled with fake success.

1. Log in as the two operator-created synthetic users; check real `/me` roles
   and independent protected session cookies
2. Master creates an unplanned order through the actual composed RU form
3. Executor queues, accepts, starts, pauses with reason and resumes through UI
4. Executor submits incomplete evidence; UI blocks close; master requests rework
5. Executor starts again, adds work code/material and uploads generated PNG
   bytes through the real picker/API; DB attachment and protected returned bytes
   are verified; absent AI assessment stays absent
6. Master closes manually without score; null is preserved; executor sees closed;
   master opens history; all 13 events match actual API and PostgreSQL

A bounded test-lifetime request ledger also requires exactly the 11 intended
order/command POSTs; extra create operations or hidden retries fail.
Every successful UI command is correlated with its real response, both session
GETs, PostgreSQL status/version and exactly one committed receipt. The observer
uses a read-only repeatable-read transaction, restricted direct LOGIN, bounded
queries only for the newly created synthetic order, no credential-file fallback
and generic error output. It cannot create/update/delete any business record.
There is no fixed sleep or frozen clock. Deadlines are genuinely future times.

## Explicitly separate gates

This is the **manual core cycle**, not the full model/fallback demonstration.
AI/rules-worker verdicts, provider calls, physical Android, native camera,
push delivery, throttled-mobile 10-second photo SLA and report export are all
`NOT_RUN`. The PNG is synthetic pixels, not a camera capture or proof of repair.
UI incomplete-close blocking does not substitute for A's backend negative tests.
No restart/race/offline/idempotent retry claim is made by this happy/core journey.

## Safe source checks (no browser, DB, private files or login)

```sh
node --test tests/e2e/c110_contract.test.cjs tests/e2e/c110_preflight.test.cjs tests/e2e/c110_resume_source.test.cjs
python -B tests/e2e/c110_observe_test.py
node --check tests/e2e/c110_core.spec.cjs
node --check tests/e2e/c110_playwright.config.cjs
```

Parser fixtures are deliberately synthetic and never live acceptance results.

## Source-reviewed resume sequencing correction

[B0-0042](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6047298409)
identified a race opportunity in the old baseline and exact repinned UI: pause mode persists;
Back reappears only after resumed `in_progress` renders, and result fields appear
only after Back is clicked. C110 now unconditionally waits for Back (10 seconds),
clicks it, then waits for the work-result field (10 seconds). The source regression
rejects the former instantaneous visibility probe and a missing result wait.
The original defect was source-proven, **not an observed browser failure**.
Historical manual-core reruns later passed on their exact older targets. The
current product still requires A5's fresh preflight and full core rerun.

## Optional-UI selector compatibility (source-only)

Compared exact `ca320bf692c01d89dd79496fe18d1bc2742052df` with
`3ef269bba80dbd6eafaff0d5e557da21f2d96244` before repinning. Login, creation,
executor action/result/photo controls, review controls and history selectors are
unchanged. The retained pause-mode Back predicate and bounded wait/click/wait
correction remain applicable. The added result-analysis disclosure is read-only;
its unknown assessment copy does not claim a model or rules verdict.

`PushPreferences` mount constructs/subscribes to an inert controller. Config
lookup, service-worker registration and permission/subscription actions require
explicit push buttons, which this core test never clicks. Service workers stay
blocked; native push/provider delivery remains NOT_RUN. This source compatibility
review did not itself establish a runtime pass; its later exact runtime result
is recorded separately above.

## Historical analytics-UI product compatibility (source-only)

Compared exact `3ef269bba80dbd6eafaff0d5e557da21f2d96244` with
`9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c`. Master/executor screens, photo controls,
review controls, panel history, push mount and disclosure are byte-unchanged.
The master gains «Аналитика и отчёты». C110 stays in «Наряды» until it opens
«Обзор смены», whose controls and visibility remain compatible.

The hidden analytics mount only constructs a controller and subscribes to session
changes; its initial state is idle. Facts/reports are requested by explicit
analytics actions, which C110 never invokes. Existing core API request handling
is preserved; analytics-only validators and response limits are additive.

That checkpoint bound only the manual core to 9a1d6109. The separate C112 journey
owns analytics/report browser acceptance. It did not accept later download-control
candidates or infer any analytics, download or new-product runtime PASS.

## Final faef5d3d compatibility review (source-only)

Compared immutable `9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c` with
`faef5d3d8b4c640fae013dbfa78074382e512e8f` before changing the exact pin.
Master/executor screens, executor modes and result disclosure, photo/review
controls, panel/history, order store, push mount and dependency lockfiles are
byte-unchanged. The existing login, default «Наряды», «Обзор смены» and all
C110 control labels remain compatible. Resume still waits for Back, clicks it,
then waits for the result field with the same bounded waits.

App preserves the session-keyed Workspace lifetime inside a visibility wrapper.
Its draft, photo, executor and analytics controllers stay mounted across tabs;
the session epoch still clears the workspace on identity changes. The new
master-only demo-clock controller starts idle and attach only subscribes to
session changes. Clock GET requires the explicit access/refresh button and POST
requires an explicit control action after a ready snapshot. C110 never opens or
operates that tab. No clock request, time freeze or mutation is implied by mount.
Download preparation and save are also explicit controls outside this journey.
The shared API additions leave existing JSON and business-command paths intact.

Only this target is accepted by fixture selection, reporter metadata, evidence
and proof validation. Old 9a1d6109, unknown/shortened SHAs and stale or mismatched
proofs are rejected. Changing the bound contract invalidates the old file hash
and the new committed harness HEAD requires a fresh target/source-bound preflight.
The exact-one test, six stages, command/event counts, timeouts, security controls
and separate NOT_RUN gates are unchanged. No browser was launched for this
review; A owns fresh runtime acceptance on the final built target.

Source-only checks for this delta: 19 Node tests and 4 Python observer tests PASS,
plus all C110 JavaScript syntax checks and `git diff --check`. No executable
preflight receipt or runtime acceptance artifact was produced in C0.
