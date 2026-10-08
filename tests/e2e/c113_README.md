# C113: protected GUI downloads and explicit demo-clock acceptance

Source-only handoff. No browser, database, TLS, real PIN input or secrecy
preflight was executed by C0. A owns actual execution on a separate disposable
synthetic history + clock stack. C110 and C112 receipts/gates are not reused or
changed. No shared runner, workflow, dependency, contract or product edits.

## Fixed identities and minimal A interface

- Base: `347119c47b9a0ec70cd30cbc8bce2a2774a439e0`
- Frozen frontend: `8081a2984b2f27b909fa2b86cd9f10ffd01d1e11`
- Binding maintenance: [C0092](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6051803090); fresh runtime evidence is required
- Exactly one test: `C113 real protected downloads and demo clock`
- Exactly one project: `c113-android-chromium`
- Locked `@playwright/test` 1.63.0; Chromium Pixel 7 emulation; two separate
  sessions; ru-RU / Asia/Almaty; trusted `https://localhost:18443`
- Fresh canonical history `ops/provision/history_demo.py::public_manifest()`
  object, not CLI wrapper: 540 orders / 568 submissions / 444 unavailable
  historical after-photo references / 17 disabled historical actors. Existing
  live master has four sections; existing executor has its one manifest section.
- A enables an existing durable `postgres_shared` demo clock: version 0,
  scale 1, domain time after 2026-10-01T00:00:00Z, at least 120 seconds before
  its horizon. The live master is the explicit permitted clock operator; the
  executor is excluded. A verifies disabled AI/delivery/provider workers.
- No fresh credentials, grants, accounts, destructive reset, real data,
  provider access or installation are requested. Existing restricted runtime
  LOGIN is used only in a repeatable-read READ ONLY observer transaction.

Source/public preflight inputs:

- `DALA_E2E_FRONTEND_SHA` = exact frozen frontend above
- `DALA_C113_RUN_ID` = fresh `c113-` lowercase slug, 13–63 characters total
- `DALA_C113_PREFLIGHT_RECEIPT` = new absolute receipt filename, no overwrite
- Optional `DALA_C113_PLAYWRIGHT_PACKAGE` = absolute path to already installed
  locked `@playwright/test` 1.63.0

Run without PIN-file, public fixture-file, observer DSN or inherited PG inputs:

```sh
node tests/e2e/c113_secrecy_preflight.cjs
```

This actually launches a dummy browser page in A CI. It requires exactly one
unexpected `C113_DUMMY_FAILURE_EXPECTED` failure and scans bounded stdout,
stderr and artifacts for generated dummy PIN/DSN/cookie/CSRF sentinels, including
escaped and encoded forms. The actual login boundary and the generic operation
boundary used by clock/download/parser/denial paths are exercised. A pass, no
failure, skip, retry or sentinel exposure cannot issue a receipt. No raw child
output is echoed. The proof is bound to the clean committed harness HEAD, all
C113 runtime sources, shared package/lockfiles, exact frontend and unique run ID;
it expires after 30 real minutes. Any accepted source/HEAD change needs a new
receipt at a new path, even if C110/C112 already passed.

Only after successful fresh proof, A supplies:

- `DALA_C113_AUTHORIZED=operator-provisioned-synthetic-only`
- `DALA_C113_WORKERS_DISABLED=ai,delivery,providers` (A independently verifies)
- `DALA_E2E_BASE_URL=https://localhost:18443`
- `DALA_E2E_BACKEND_SHA` = exact A-verified backend source SHA
- `DALA_E2E_FIXTURE_FILE` = bounded public history manifest absolute path
- Existing distinct `DALA_E2E_MASTER_PIN_FILE` and
  `DALA_E2E_EXECUTOR_PIN_FILE`, private paths only; never values in command lines
- `DALA_C113_OBSERVER_DATABASE_URL` and `DALA_C113_DATABASE_SCHEMA` = isolated
  explicit observer inputs; no libpq environment/socket/passfile fallback
- Optional `DALA_C113_PYTHON` = A-owned trusted observer wrapper
- Optional `DALA_C113_INSPECT_PYTHON` = trusted stdlib Python (default `python`)

```sh
node tests/e2e/node_modules/@playwright/test/cli.js test --config=tests/e2e/c113_playwright.config.cjs
node tests/e2e/c113_gate.cjs tests/e2e/c113_artifacts/$DALA_C113_RUN_ID/playwright.json tests/e2e/c113_artifacts/$DALA_C113_RUN_ID/evidence.json
```

For an alternate installed locked package, use its `cli.js` and set
`DALA_C113_PLAYWRIGHT_PACKAGE` consistently. Never install on demand.

Observer argv is exactly:

```text
DALA_C113_PYTHON tests/e2e/c113_observe.py <master-UUID> <executor-UUID>
```

It requires safe employee/scope columns and SELECT on orders, order_events,
submissions, reviews, photos, material_writeoffs, ai_assessments and
operation_receipts. No password/session table is read. The existing role must
not be superuser/CREATEDB/CREATEROLE/BYPASSRLS/schema-CREATE. This proves the
transaction is read-only, not that the login is globally SELECT-only. A owns
source-bound wrapper/mounts, build SHAs, exact isolated schema, trust and inventory.

Inspector argv is separate, with no DB/credential environment:

```text
DALA_C113_INSPECT_PYTHON tests/e2e/c113_inspect_download.py <saved-file> <pdf|xlsx> <safe-expected-json>
```

The spec supplies only PATH, LANG and PYTHONDONTWRITEBYTECODE. This subprocess
has a 15-second deadline and a 16 KiB fixed-output bound. The standalone inspector
is Python-stdlib-only; no new dependency or host package is needed.

## Exact single journey

1. Independent read-only PostgreSQL corroboration of the fresh history manifest
2. Actual GUI login in two independent secure sessions; private browser env,
   no TLS bypass, no trace/HAR/video/screenshots, fixed reporters and no retries
3. Master navigation button “Демо-время”, explicit first read, pause, delayed
   explicit read proving frozen domain time, +60 seconds while paused, resume
   1×, delayed explicit read proving resumed progress. Exactly three real GUI
   POSTs, checked against the planned action/instance/expected_version before
   network dispatch; same instance, versions 0→1→2→3. UI shows each returned
   snapshot, never a guessed ticking browser clock. Real time stays unmodified.
4. Explicit UTC+5 minute-form historical interval
   `2026-07-01T05:00` to `2026-10-01T05:00`, mapping to the canonical UTC interval.
   Real analytics IDs must match the DB; an actual returned historical order
   with unavailable photo references is selected, not an invented fixture ID.
5. Open protected shift report. For each PDF then XLSX: click Prepare, wait for
   the real protected binary response and Save button, require no download yet,
   arm browser download event, click Save, await completion, save actual bytes.
6. Exact-name semantic order combobox selects/asserts the observed ID; open that
   protected order report, then repeat the two-gesture PDF/XLSX cycles.
7. Executor has neither UI area and receives 403/FORBIDDEN for clock GET/POST
   and all four exact export URLs. POST uses its own valid session/CSRF. A later
   master read verifies the denied POST changed neither version nor mapping.
8. Independent second business snapshot has identical row digest/counts/IDs/
   scopes. Auth sessions and the authorized clock changes are not in that
   business digest. Exact network counts require 2 login POSTs, 3 permitted
   master clock POSTs, 1 denied executor POST and 4 GUI export GETs.

A missing/ambiguous clock response fails immediately: no POST replay, remount,
reset, compensating mutation or attempt to infer original success from a GET.
Fresh stack rerun after a failed cycle belongs to A; do not reuse a run ID or
pretend a partially changed clock is fresh. C113 does not force a failure or
perform the separate 409/unknown-response product tests.

## File checks and honest limits

Each response must have fixed MIME/filename, private no-store/Vary Cookie,
nosniff, sandbox CSP and bounded Content-Length. The browser-saved file must
be nonempty and ≤8 MiB, equal byte-for-byte to that exact Prepare response,
with matching SHA-256. Save must not cause another export fetch. The gate
re-reads all four saved files and rechecks their hashes; retaining only a green
Playwright summary is insufficient.

The independent inspector checks actual bytes against report kind, selected
order ID/number, canonical period, synthetic watermark, unavailable historical
counts and shift issued count. PDF validation is a narrow ReportLab-generated
subset: traditional xref/object offsets, page tree, referenced content/font/
ToUnicode streams, exact allowlisted Catalog/Pages/Page/font-resource dictionary
shapes, bounded decompression, allowed text/drawing operators and
page count, fixed dark fill palette, positive known font sizes and identity text
matrices at visible A4 page coordinates, without crop/rotation/unit overrides. Invisible/white/zero-size/off-page text
and orphan form text fail. XLSX
validation bounds archive entries/expansion, verifies ZIP integrity, actual
workbook sheet relationships and ordered cell coordinates, and rejects path
traversal, duplicates, formulas, external links and malformed/entity XML.
This is not a generic hostile-file validator, raster layout QA, a physical
Android test or native Microsoft Excel/PDF-viewer acceptance.

Outputs live only under `tests/e2e/c113_artifacts/<run-id>/`: report, attached
safe evidence, four `saved-<shift|order>.<pdf|xlsx>` files and small synthetic
expected-value files. Never upload operator inputs. No raw requests, cookies,
CSRF, login/driver exceptions or private paths go into evidence. Partial failures
remain failures; source tests and previous C110/C112 results cannot promote them.
The existing C110 lifecycle, C112 analytics, physical device/native applications,
photo/push/provider/live closure and actual security-clock expiry checks remain
separate NOT_RUN gates in this package.

## Source-only checks

```sh
node --test tests/e2e/c113_*.test.cjs
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/e2e -p 'c113_*test.py' -v
```

These test dummy contracts/gates and offline generated files with existing locked
renderer dependencies. They never read operator input, launch browsers, connect
to a database or create an execution receipt. A owns final browser/DB validation.

## Failure localization (A0-0085)

`download_diagnostic` emits only fixed target/substep/HTTP-status/encoding/
Content-Length/inspector-stage categories. It distinguishes report opening,
Prepare response, each fixed header check, declared size, actual response bytes,
Save gesture, browser completion, saved-byte equality, inspector process and
content validation. A missing completed download row does not mean no response
or saved bytes existed. Content-Encoding is classified (identity/gzip/zstd/br/
other) without retaining headers; declared length is only a bounded category.
All acceptance predicates remain unchanged, including declared/actual size checks.

The inspector's failure output is exactly a fixed status/code/stage object. The
runner accepts only its allowlisted stages from bounded stdout; malformed,
extra-field or unrecognized output becomes `PROCESS_FAILED`. It never copies
child exception text, stderr, paths, content, arbitrary headers or raw output.
The mandatory dummy-failure preflight exercises these sanitizers with private-
shaped sentinels. Diagnosis is advisory and cannot promote failed evidence.
This source change requires a fresh exact-integrated-HEAD C113 proof.

### Original response-body boundary (A0-0091–0093)

The same-head deliberate repeat reached `READ_RESPONSE_BYTES` after successful
200/protected-header/identity-encoding/bounded-length checks, then failed before
Save or inspection. The earlier full PASS is retained; the repeat is an unresolved
intermittent result, not a reliable all-green claim.

Request-finished/failed listeners are registered before Prepare. A weak identity
map captures early terminal events, and observations bind only to the exact
matched `response.request()`. Evidence records `FINISHED`, `FAILED` or
`NOT_OBSERVED` plus a failure-present boolean, never the failure text or URL.
Listeners are removed on every download outcome.

The original single `response.body()` call has a 20-second real-time bound.
Before and after it, an independently bounded one-second probe observes only
fixed scoped Save-button/alert/loading/expired states. A failure is classified
only as timeout, body-protocol-failure, body-unavailable, target-closed or other;
raw exception text is never serialized. The original failure is rethrown into
the existing private boundary. No unbounded `response.finished()` wait, GET
retry, alternate body, blob substitution or inferred transfer success is used.
Byte equality, saved-file/content checks and every acceptance gate are unchanged.
All added paths participate in the fresh dummy-failure secrecy proof.
