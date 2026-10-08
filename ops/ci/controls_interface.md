# C113 isolated clock controls and download acceptance seam

Source-ready binding: C1130d2ac5e95dcd99b11b144b7871152ed9c0033697 against
frontendfaef5d3d8b4c640fae013dbfa78074382e512e8f. Actual C113 execution is
pending for this diagnostic source. Final C110/C112 acceptance remains separate evidence.

A5 reserved `.github/workflows/controls-mobile-e2e.yml` and new `ops/ci/controls_*`
paths. C owns `tests/e2e/c113_*`. The final B source bindings and actual C110/C112
regressions take priority before this additional acceptance.

The approved fresh bootstrap is unchanged:

```text
ops/demo/prepare.py --workers --fixture-mode history --demo-clock true
```

Use a new owned private fixture and the accepted base/full-profile Compose files
plus a C113-only overlay. Start only API/web and required init/observer services;
keep worker/budget services inactive, worker flags off and provider inputs absent.
Validate declared and actual service inventory and retain the internal unpublished
PostgreSQL topology. This exercises the existing master clock controls, with CAS,
real authentication and real TTL unchanged. Never adopt or reset an existing stack.

C113 must supply its own exact-source/frontend/run-bound dummy-failure proof,
config, strict evidence gate and observer, including any clock-table projection.
Run that independent proof before preparing actual fixture PINs/database inputs.
Reuse only the existing authorized runtime input for the fixed read-only observer;
no new grants or identity and no private fields in browser environment or output.
Do not extend C112's read-only scenario or use its receipt for new C113 source.

Downloads must originate from the real mounted API and be validated as actual
PDF/XLSX files under the C-owned acceptance contract. Keep files inside this
invocation's temporary artifacts; do not publish raw private reports, browser
state, request/response diagnostics or credential values. Any public evidence
must be an explicit reviewed safe projection. Synthetic buffers/injected save
ports from B's source tests are separate evidence and cannot pass this gate.

Use normal localhost TLS validation and only fresh disposable browser trust.
Delete only the owned stack, raw browser artifacts, downloads and private fixture
on completion. No physical-device, provider, worker, production or deployment
claim follows from this additional Android-emulation job.


## Exact execution

The distinct title is `C113 real protected downloads and demo clock`, project
`c113-android-chromium`. Twenty C/package blobs are pinned; C's own proof binds
15 executable/package inputs. Eight steps require three permitted UI clock POSTs,
one denied executor POST, four completed saved/inspected files and unchanged
business rows. The approved clock changes are excluded from that business digest.

```sh
python -m pip install -r backend/requirements.lock -r backend/requirements-dev.lock
npm ci --prefix tests/e2e --ignore-scripts
python -m unittest discover -s ops/ci/controls_tests -v
python ops/ci/controls_runner.py --check-inputs
node --test tests/e2e/c113_*.test.cjs
python -m unittest discover -s tests/e2e -p 'c113_*test.py' -v
node tests/e2e/node_modules/@playwright/test/cli.js install --with-deps chromium
python ops/ci/controls_runner.py --report controls-ci-summary.json
```

The workflow supplies the exact frontend reference checkout, official Node/Python
and Chromium, NSS tooling and Docker Compose. Its install step has a10-minute
limit and cannot promote an incomplete install. Local source checks do not prove
Docker or browser execution.

The runner reads the fresh clock instance exactly as the supported launcher does,
then requires that same canonical UUID in API/setup/disabled-worker configuration.
C verifies initial version0/scale1 through the actual API. The bootstrap samples
real DB time and supplies a168-hour horizon; real security clocks are unchanged.

`DALA_C113_PYTHON` is an observer-only adapter, bound to `c113_observe.py` and
the manifest's two actor IDs. `DALA_C113_INSPECT_PYTHON` is the explicit resolved
host interpreter; C supplies only PATH/LANG/PYTHONDONTWRITEBYTECODE to that child.
A matching credential-free stdlib import probe runs before fixture credentials.
The inspector is frozen C source using bounded ZIP/XML and a fixed ReportLab
subset; no pypdf or generic arbitrary-PDF validation is claimed.

C's strict gate reads and hashes all four saved files while they still exist.
Only after its success are the safe evidence and gate receipt copied to public
outputs. Raw downloads/reports/assertion output stay private and are deleted with
the owned artifact tree. The public JSON summary distinguishes actual Chromium
file saving under Android emulation from physical devices or native viewer apps.
The separate executor observer receives no owner input; the file inspector
receives no observer/PIN environment. Cleanup failure fails the workflow.

The first43cd9ca runtime result remains FAIL after four stages/six clock observations. The accepted diagnostic source adds fixed report/download/transport/inspector phases without changing predicates. CI projects only those fixed categories plus eight fixed saved/expected-file presence booleans before cleanup; no paths, headers, sizes, contents or raw errors are published. A fresh proof/run on this source is required.

On e548c948, C113 attempt 1 passed all eight stages and four file inspections;
the deliberate same-head attempt 2 failed at SHIFT_PDF / READ_RESPONSE_BYTES.
Both observations remain preserved. Repeatability and the underlying cause are
unresolved; diagnostic changes do not constitute an application fix.

The new C-owned source observes only the exact request identity, before and after
one response-body call bounded to 20 seconds. It reports fixed request terminal
states and a failure-present boolean, bounded scoped UI states and a fixed body
exception category. CI double-allowlists those fields and drops raw extras.
Listeners are removed in finally. Visible readiness, request completion or a
timeout cannot pass the gate: exact response/saved byte equality and all file
inspections remain mandatory. The workflow and product remain unchanged, and
the new integrated source must create its own fresh failure-output proof.
