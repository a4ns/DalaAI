# Real composed-app mobile CI (C-110 integration)

This is an Android **browser-emulation** gate on the standard GitHub Ubuntu runner.
It uses the accepted `ops/demo` Dockerfiles, real PostgreSQL, the mounted
`app.main:app`, the composed frontend, and C-110-owned scenarios. It does not
substitute API responses or duplicate the team's test scenarios.

## Current source-preparation state

- Infrastructure fixture/safety tests run locally
- Real Compose/browser execution is **NOT RUN** in the preparation environment:
  Docker is unavailable there
- `scenarios.json` deliberately has `accepted: false` until the actual C-110
  package, configuration, test IDs and expected count are handed over
- A missing package, zero tests, skipped test, expected failure, retry, missing
  mandatory ID, duplicate mandatory ID, or unexpected count fails the gate
- The existing synthetic frontend suite is a separate evidence level

Do not publish a green full-cycle/demo claim from this workflow. Even a successful
core result leaves physical Android, actual provider-to-browser notification
delivery, camera permissions, and hardware behavior as separate acceptance gates.
The output always reports `full_cycle_green: false`, `real_android_device:
NOT_RUN`, and `real_webpush_provider_delivery: NOT_RUN`.

## Inputs and ownership

A5 supplies the accepted backend, migrations, `ops/provision`, `ops/demo`, and the
unmodified accepted frontend. This package changes only `ops/ci/**` and
`.github/workflows/mobile-e2e.yml`. It changes no B frontend or C scenarios.

C-110 supplies:

1. `tests/e2e/package.json` and `package-lock.json`, with exact `@playwright/test`
2. Exported `tests/e2e/playwright.config.ts`, project `android-chromium`
3. Actual test files and fixtures in `tests/e2e/**`
4. Required public IDs in test titles, such as `C-110-HERO`, plus exact test count
5. Acceptance of the runtime interface below, or a coordinated adapter change

The config may retain C-owned fixtures/global setup, but cannot start a mock
`webServer`, use an alternative browser binary, supply custom launch arguments,
or rely on project dependencies that this focused gate would otherwise omit.
Required scenarios must use two independent browser contexts configured from
Playwright's project `use` settings; creating an unconfigured context does not
inherit Android emulation automatically. C-110 must assert actual secure context,
mobile user agent/touch/viewport, separate cookie jars, and real HTTP results.

After source handoff, the integrator sets `accepted: true`, the exact project,
`required_test_ids`, `expected_test_count`, and `required_source_files` in
`scenarios.json`. Do not reduce those expectations to make an incomplete run pass.

## Runtime interface

Only the child Playwright process receives:

- `DALA_E2E_BASE_URL=https://localhost:18443`
- `DALA_E2E_FIXTURE_FILE`: public synthetic fixture manifest JSON, generated from
  `ops/provision/provision_synthetic_demo.py:public_manifest()`
- `DALA_E2E_MASTER_PIN_FILE`, `DALA_E2E_EXECUTOR_PIN_FILE`: transient private files
- `HOME`: a newly created disposable browser-only home/NSS trust DB
- `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE`: one-day localhost-only CA file
- `PLAYWRIGHT_BROWSERS_PATH`: installed official matching Chromium path

Employee codes are `DALA-DEMO-MASTER` / `DALA-DEMO-EXECUTOR`; IDs, dictionaries and
scope come from the fixture manifest. PINs are randomly generated for each
isolated database. No application sessions are preseeded. Tests must log in over
real HTTP and must never print PINs, session/CSRF values, cookies, or headers.

No OpenAI key reaches the composed app. Rules fallback must be asserted honestly;
no paid model or real notification-provider calls are authorized by this gate.
The test runner does not fake worker output, provider receipts, or notification
success. If a required runtime worker/capability is absent, report/fix the failure
in its owned source; never skip that scenario.

## Reproduction after all inputs are accepted

Run at repository root on a disposable Linux host with local Docker Compose,
Node 24.21.0, Python 3.12, OpenSSL and Ubuntu `libnss3-tools`:

```sh
python -m unittest discover -s ops/ci/tests -v
node --test ops/ci/tests/test_reporter.cjs
python ops/ci/run_mobile.py --check-inputs
npm ci --prefix tests/e2e --ignore-scripts
node tests/e2e/node_modules/@playwright/test/cli.js install --with-deps chromium
python ops/ci/run_mobile.py --report mobile-ci-summary.json
```

The normal test requires installed C-110 packages; it never implicitly installs
an unpinned package. The official Playwright browser is tied to that exact version.
The GitHub workflow executes the same sequence. It uses ordinary public-repo CI,
read-only repository token permissions and no deployment/provider secrets.

## TLS, secrets and cleanup

The accepted app requires an exact HTTPS Origin and retains its normal Secure
cookies and CSRF checks. CI therefore uses a real TLS endpoint with a fresh
one-day root/leaf chain constrained to localhost/127.0.0.1. Only the new disposable
Chromium home trusts that root; Python and Node test clients use an explicit CA
bundle. There is no `ignoreHTTPSErrors`, certificate-warning bypass, insecure-origin
flag, tunnel, public certificate request, or system/existing-browser trust change.

The CI Compose overlay preserves A5's services and Dockerfiles, changing only
private test inputs, fixed loopback origin and Caddy's CI certificate. DB/API stay
unpublished. HTTP port18080 has no application listener; HTTPS18443 is bound only
to127.0.0.1. A random `dalaai-ci-<id>` project owns fresh volumes; cleanup removes
only those disposable containers/volumes, never the `dalaai-demo` project.

All secret fixture files stay under a fresh0700 directory outside the checkout.
File-backed Compose secrets are0444 there so nonroot container UID10001 can read
only explicitly mounted files; the0700 parent prevents other host users from
traversing to them. All browser output stays in that private temporary directory
and is removed. Traces, videos, screenshots and raw error bodies are not published.
Only a bounded ID/status/count summary can enter the public artifact/log.

## Evidence and official references

The run binds evidence to the checkout's exact SHA and fails on tracked source
changes. The artifact contains source SHA, stage, test counts, required IDs and
explicit untested levels. It is not an industrial-data or physical-device claim.

- [Playwright CI](https://playwright.dev/docs/ci)
- [Playwright device emulation](https://playwright.dev/docs/emulation)
- [Chromium Linux NSS certificate management](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/cert_management.md)
- [Compose secret file ownership limitations](https://docs.docker.com/reference/compose-file/services/#secrets)
- [setup-node v7 immutable release](https://github.com/actions/setup-node/releases/tag/v7.0.0)

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
typechecks B's tests and executes all13 `android-emulation-pixel-9` browser cases
with no skip/retry allowance. This is equivalent to B's
`npm run test:ui -- --project=android-emulation-pixel-9`, invoked directly through
its identical installed Playwright CLI to capture only the JSON report. The
wrapper unsets inherited `UI_TEST_NO_SERVER`, `UI_REVIEW_ROOT` and
`PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`; it uses B's dedicated strict loopback Vite
server. The safe report records both source SHAs and the workflow SHA, discarding
raw assertion/log/attachment content.

The accepted Playwright1.63 Pixel9 descriptor is Android14,360×732,touch/mobile,
DPR3. The B shell test asserts Android user agent, touch support,DPR3 and360px
inner width during actual execution. This establishes real rendering of synthetic
fixtures under Android browser emulation. It does not prove actual backend/DB
effects, a physical Android device, camera/push permission UX or real notification
delivery. The separate required C-110 core remains fail-closed.

The original desktop390px delta is preserved as a frozen earlier artifact; this
replacement delta moves only the separate synthetic job to the accepted Pixel9
pair. It does not edit B product/harness source or the C-110 tests.
