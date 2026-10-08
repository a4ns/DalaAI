# Isolated body-reader diagnostic: A5 execution handoff

Source candidate only. Root/sole reviewer cleared the design; actual source and
separate CI wiring must be reviewed before browser/private-fixture execution.
Product, C113 acceptance sources, original red evidence and shared CI are untouched.

The diagnostic studies one master GUI SHIFT_PDF Prepare GET in the equivalent
C113 clock/report prelude. An instance-only same-reader observer preserves native
fetch/read Promise, Response, reader and chunk identities; no clone, tee, second
consumer, retry, substitute response or extra master export GET. Extra observer
reactions/copying change timing. Results are instrumented diagnostic evidence only.
Rejection observers also mark selected native promises handled for the host's
unhandled-rejection reporting. The original promises still reject with the same
values for the application, but this instrumentation can suppress an otherwise
unhandledrejection notification; it is not event-observation-neutral.

The Node route guard associates exactly one canonical main-frame fetch Request
with the browser one-shot private nonce arm. No nonce or credential is added to the
network or public evidence. The independent executor 403 request is role-isolation
verification, never a replay of the master's authorized body.

## Source-only checks

    node --test tests/e2e/body_capture_probe/*.test.cjs
    node --test tests/e2e/c113_*.test.cjs

These do not launch browsers, read operator fixtures/PINs, connect to PostgreSQL,
call providers or issue a privacy receipt. Node synthetic Response/ReadableStream
objects are specifically labelled source tests.

## New proof, then new private run

A5 supplies an already installed locked @playwright/test 1.63.0, a Chromium browser
and the reviewed isolated synthetic history/clock stack. No install-on-demand.

Public source binding inputs:

- DALA_BCP_PRODUCT_SHA=064a7a3785a95d61d7150e7785ff17db892bc110
- DALA_E2E_FRONTEND_SHA=1594a930de4b9f15d11dd35bbc59e5b4b0b1d964
- DALA_BCP_RUN_ID=fresh bcp- slug matching the strict contract
- DALA_BCP_PREFLIGHT_RECEIPT=new absolute filename; never overwritten
- DALA_BCP_PLAYWRIGHT_PACKAGE=absolute installed @playwright/test package directory
- PLAYWRIGHT_BROWSERS_PATH=optional explicit absolute existing browser directory;
  preserved for the Node preflight driver, never added to Chromium's launch env

Run with no PIN/fixture/observer/authorization/PG inputs:

    node tests/e2e/body_capture_probe/secrecy_preflight.cjs

The dummy browser page intercepts only its own fixed HTTPS dummy document and uses
synthetic Response streams. It exercises the actual reader tap with secret-shaped
bytes and a rejected native read, private login/bridge/Save/inspector/auth failure
boundaries, then deliberately fails once. All bounded output is scanned for PIN,
DSN/cookie/CSRF/body and private-nonce canaries, including escaped/encoded forms.
No dummy output is uploaded or echoed; it is deleted. This receipt is new, bound to
clean committed probe HEAD/all runtime files/imports/package lock/product trees,
and clean staged/working frontend/backend source (including non-ignored untracked files),
unique run, exact frontend/product and Playwright, with a 30-minute TTL. C113
receipts cannot authorize the new probe.

Only after that proof, supply:

- DALA_BCP_AUTHORIZED=operator-provisioned-synthetic-only
- DALA_BCP_WORKERS_DISABLED=ai,delivery,providers (independently verified by A5)
- DALA_E2E_BASE_URL=https://localhost:18443 with trusted TLS, no certificate bypass
- DALA_E2E_BACKEND_SHA=064a7a3785a95d61d7150e7785ff17db892bc110
- DALA_E2E_FIXTURE_FILE=existing bounded public history manifest
- DALA_E2E_MASTER_PIN_FILE and DALA_E2E_EXECUTOR_PIN_FILE=distinct existing private inputs
- DALA_BCP_OBSERVER_DATABASE_URL and DALA_BCP_DATABASE_SCHEMA=isolated restricted
  runtime LOGIN and non-public schema, used only through the original READ ONLY observer
- DALA_BCP_PYTHON=reviewed A5 source-bound observer wrapper when required
- DALA_BCP_INSPECT_PYTHON=trusted stdlib-only Python (default python)
- DALA_BCP_SAFE_RESULT=new absolute JSON destination for fixed public evidence

    node tests/e2e/body_capture_probe/execute.cjs

Use execute.cjs rather than exposing raw Playwright CLI output. The actual spec
claims `<receipt>.execution-claim` exclusively before reading private inputs, so
that receipt/run cannot be executed twice. A failure requires a fresh reviewed run,
proof and isolated stack; no in-run retry or compensating clock mutation.

A5 alone owns build verification, observer wrapper source/mounts, disabled service
inventory, runtime source SHA, TLS/DB provision and isolated validation-branch CI.
This author does not publish, deploy, run private fixtures, create credentials,
change grants or call model providers.

## What may be published

Only DALA_BCP_SAFE_RESULT, after execute.cjs has validated its exact schema and
bindings. The private temporary directory contains raw stdout/stderr/report, the
real saved PDF, and expected inspector values; it is deleted in finally on every
outcome. Do not upload that directory, PDFs or raw browser artifacts. PIN inputs,
DSN, cookie, CSRF, nonce, response content and arbitrary exceptions never enter the
safe projection. Browser environment is filtered and traces/HAR/screenshots/video
are disabled. A5 must also clean the disposable stack and any external browser
profile directories its runner creates.

The tap retains at most one declared-length byte buffer <=8 MiB, no chunk list or
raw-byte bridge. EOF and declared size must agree; incomplete/duplicate/overflow/
timeout observations are NOT_COMPARABLE. Crypto may hold a bounded internal copy;
Chromium's internal/network memory is not claimed to be 8 MiB. In particular,
Playwright response.body() can allocate before returning; its bound relies on the
unchanged server export cap and is not an independent Chromium-memory guarantee.

The original one-time CDP read and exact Request failure fields remain separate.
A later actual Save plus tap-hash/content/auth success cannot turn that read into
success: CDP-to-saved literal equality remains UNAVAILABLE when CDP failed.
All-three agreement requires actual CDP bytes equal saved bytes. The unchanged
inspector validates actual saved content; hash equality alone is insufficient.

Execution states are DIAGNOSTIC_COMPLETE, INCONCLUSIVE or BLOCKED. A green
Playwright/CI diagnostic process is not a C113 PASS. Every output carries
c113_acceptance=NOT_ESTABLISHED and points back to red run 37726366034. No result
proves an uninstrumented Chromium cause or reliable production behavior.

## Response-type regression

The first isolated instrumented run (`37733049935`, job `113166320498`) reached
matching CDP/client/saved PDF bytes and content inspection, then remained BLOCKED
before final authority/database corroboration. Source inspection reproduced a
helper TypeError: APIRequestContext returns APIResponse without fromServiceWorker.
The corrected helper explicitly accepts that type only at the executor denial
call; page Response still requires the method and an exact false result. Exact
origin/path/403/cache/Vary/nosniff and FORBIDDEN/no-report-fields checks remain.
A new source-bound dummy proof is required; this source repair does not promote
the incomplete earlier run or establish C113 acceptance.
