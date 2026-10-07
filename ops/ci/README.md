# Real composed-app Android-emulation CI

This workflow has two deliberately separate jobs:

1. `mobile-core`: C-110's actual composed browser/API/PostgreSQL manual journey
2. `b-synthetic-rendering`: the independently pinned B synthetic Pixel 9 UI suite

Neither job can mark the complete demo/release green. Physical Android, native
camera, live push delivery, model/rules worker execution, throttled upload SLA
and report export remain separate gates. No deployment is performed.

## C-110 accepted source and build provenance

`scenarios.json` accepts exact C source
`23a135348a0e8ad9a140a36ca60e8440704b7893` and frontend
`ca320bf692c01d89dd79496fe18d1bc2742052df`. C includes the bounded resume/Back
render waits and version-2 frontend/source-bound receipt. Missing or altered
source still blocks before private execution. Do not lower counts or silently
skip a missing input.

The active integration uses C's unchanged config
`tests/e2e/c110_playwright.config.cjs`, project `c110-android-chromium`, and C's own
`c110_gate.cjs`. Exactly one test named `C110 real composed master executor
lifecycle` must pass, with all six asserted stages, 11 committed UI commands and
13 persisted events. It uses two independent Pixel 7 Android-emulated contexts.
No successful business request is mocked. The earlier generic CI Playwright
wrapper/reporter is retained as frozen infrastructure history and is not used to
run C-110; C correctly rejects alternate configurations and reporters.

Before execution, CI verifies every accepted C source blob from the manifest and
checks that all non-harness frontend inputs in the built checkout match the exact
accepted frontend reference checkout. C separately binds its runtime proof to its
actual committed harness HEAD and file hashes. The report records the integrated
source SHA, the accepted C source SHA and the reviewed frontend source SHA.

The normal checkout must be clean, with no untracked source inputs. The workflow
provides `.ci-c110-frontend-reference` at the exact frontend SHA listed in the
contract. It never copies that checkout over the integration source or backend.

## Credentials and mandatory failure-output preflight

Only official matching Playwright 1.63 Chromium is installed. The runner creates a
new browser-only HOME/NSS database and one-day localhost-only TLS certificate
chain. No existing browser/profile/system trust store is changed. Hostname checks
remain on for the browser, Node and Python clients; no `ignoreHTTPSErrors`, browser
warning bypass, insecure-origin flag, tunnel or public certificate request exists.

Before even generating real synthetic PIN/database credentials or supplying any
fixture/PIN/observer fields to C, the runner
executes `c110_secrecy_preflight.cjs` in that allowed disposable environment. This
must observe exactly one intentional dummy failure, scan every bounded output,
find zero sentinels, and produce a fresh source/hash/version-bound receipt. That
intentional failure is never a core pass. Missing/stale proof stops credential
reads. The source-bound preflight is repeated on every run and every source change.

After the preflight, the real C process receives:

- Exact HTTPS origin `https://localhost:18443`
- The public fixture OBJECT from `public_manifest()`, with no dry-run wrapper
- Random private master/executor PIN file paths; no sessions/orders/photos seeded
- Exact frontend/backend source identities and a unique non-secret run ID
- C's accepted synthetic-only authorization marker and verified worker-disabled state
- Existing restricted runtime PostgreSQL credentials for read-only observation
- Per-process CA paths; never debug/protocol/HAR/auth capture or `PG*` overrides

The source/provisioning identities remain `DALA-DEMO-MASTER` and
`DALA-DEMO-EXECUTOR`. The private fixture directory is 0700. Assigned Compose
secret files are 0444 within it so the nonroot container UID can read its own
explicit mounts. Other host users cannot traverse the 0700 parent. Secret values,
raw runner errors, raw Playwright reports and credential-bearing diagnostics are
never printed or uploaded.

## Actual runtime, worker exclusion and observer

A5 owns the real `ops/demo` Dockerfiles/runtime/provisioning. The CI overlay adds
only test inputs, a loopback trusted HTTPS endpoint and a CI-only PostgreSQL bind
`127.0.0.1:15432`. The API is never exposed directly; the ordinary demo Compose
remains unchanged. The observer uses existing `naryadai_api` direct LOGIN and
C's read-only repeatable-read transaction, not an owner credential or new grant.

CI inspects the resolved Compose model before setting C's worker-disabled marker.
The five core services must exist. Any extra worker service must be profile-gated
and cannot be a dependency of a core service. Enabled worker flags/provider keys
fail. The command starts only `api web` and their approved dependencies, with no
inherited `COMPOSE_PROFILES`. The actual started service inventory is checked
again. Workers/provider delivery are therefore not merely declared disabled.

The manual journey queues AI jobs but expects no assessment because workers are
disabled. This gate does not exercise or claim rules fallback. The absent model
key and manual-core evidence are distinct from the separate no-key rules-worker
gate that A5 owns.

A random `dalaai-ci-<id>` project owns fresh database/photo volumes. Teardown only
removes that disposable project's containers/volumes. It never operates on the
human's `dalaai-demo` project. C artifacts must use a fresh directory created by
this invocation, then are removed. Both Playwright and C's evidence gate must
succeed; the gate is still invoked when Playwright fails or evidence is absent.
Only C's bound allowlisted synthetic projection can be published, after an extra
check against the known ephemeral credential values. Raw output is discarded.

## Reproduction on the disposable runner

After all accepted sources are integrated and the frontend reference checkout is
present at the exact recorded SHA:

```sh
python -m unittest discover -s ops/ci/tests -v
node --test ops/ci/tests/test_reporter.cjs
python ops/ci/run_mobile.py --check-inputs
npm ci --prefix tests/e2e --ignore-scripts
python -m pip install -r backend/requirements.lock
node tests/e2e/node_modules/@playwright/test/cli.js install --with-deps chromium
# Ubuntu also requires openssl and libnss3-tools from its official repositories.
python ops/ci/run_mobile.py --report mobile-ci-summary.json
```

A local Docker daemon is required; remote Docker contexts are rejected. The
source-preparation environment has no Docker, so local unit/parser/certificate
checks are not represented as an actual composed-app run.

## Official references

- [Playwright CI](https://playwright.dev/docs/ci)
- [Playwright device emulation](https://playwright.dev/docs/emulation)
- [Chromium Linux NSS certificate management](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/cert_management.md)
- [Compose secret file ownership limitations](https://docs.docker.com/reference/compose-file/services/#secrets)
- [GitHub expression context availability](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)

## Independent B synthetic Android-emulation job

`b-synthetic-rendering` runs independently of the blocked/unblocked C-110 core.
It uses two immutable accepted inputs:

- Product: `2a12798c19a26b33aabd9ffd572b99586f80e2f1`
- Harness: `9f37c2951cbffb88db8a254beff033f7e31ed6d9`

The job checks them out into separate disposable directories, verifies their
HEADs, then copies only five accepted harness files into the product checkout.
Each copied file is checked against its fixed Git blob ID. Every other product
source file remains at the exact product SHA. An unexpected dirty/untracked source
file fails rather than being overwritten. This is explicitly two-SHA evidence,
not a claim that the product commit already contains the later harness.

After installing the product lockfile and matching official Chromium, the job
typechecks B's tests and executes all 13 `android-emulation-pixel-9` browser cases
with no skip/retry allowance. This is equivalent to B's
`npm run test:ui -- --project=android-emulation-pixel-9`, invoked directly through
its identical installed Playwright CLI to capture only the JSON report. The
wrapper unsets inherited `UI_TEST_NO_SERVER`, `UI_REVIEW_ROOT` and
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`; it uses B's dedicated strict loopback Vite
server. The safe report records both source SHAs and the workflow SHA, discarding
raw assertion/log/attachment content.

The accepted Playwright 1.63 Pixel 9 descriptor is Android 14, 360×732, touch/mobile,
DPR 3. The B shell test asserts Android user agent, touch support,DPR 3 and 360px
inner width during actual execution. This establishes real rendering of synthetic
fixtures under Android browser emulation. It does not prove actual backend/DB
effects, a physical Android device, camera/push permission UX or real notification
delivery. The separate required C-110 core remains fail-closed.

The original desktop390px delta is preserved as a frozen earlier artifact; this
replacement delta moves only the separate synthetic job to the accepted Pixel 9
pair. It does not edit B product/harness source or the C-110 tests.
