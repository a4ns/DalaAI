# C-110: real composed browser/API/PostgreSQL core journey

Status at initial handoff: **browser/API/DB NOT_RUN** in C0's environment.
Source/parser tests are separate evidence. This is an executable Playwright
journey, not a completed runtime result. No successful business response is
mocked. The app must be the composed UI from frontend source
`2beb2244c4639c09004e4cdb5a7598d447ad68f6` and an A5-recorded backend source SHA.

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
| `DALA_E2E_FRONTEND_SHA` | Exactly `2beb2244c4639c09004e4cdb5a7598d447ad68f6` |
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
allowed disposable runner, before exporting real fixture/PIN/observer inputs:

```sh
# DALA_C110_PREFLIGHT_RECEIPT is a new absolute, non-secret output path.
node tests/e2e/c110_secrecy_preflight.cjs
```

The wrapper refuses inherited fixture/PIN-file/observer inputs and uses pinned
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
verification writes a public receipt with source SHA, relevant file hashes,
pinned version, expected/observed failure count, zero matches and output digest.
The receipt expires after 30 minutes. Core config and fixture loading verify it
before real input files are read. There is no boolean override. Both preflight and core enforce their exact checked
config, list/JSON reporters with step printing off, one worker/repeat, zero
retries, and an allowlist of context options. HAR/logger/storage-state/launch/
connect overrides and alternate configs/reporters are rejected before PIN use.

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
node --test tests/e2e/c110_contract.test.cjs tests/e2e/c110_preflight.test.cjs
python -B tests/e2e/c110_observe_test.py
node --check tests/e2e/c110_core.spec.cjs
node --check tests/e2e/c110_playwright.config.cjs
```

Parser fixtures are deliberately synthetic and never live acceptance results.
