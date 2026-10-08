# C113 isolated clock controls and download acceptance seam

Source-ready binding: C113 `a06bc57af3f7045bfccad4506debcbe7dd2e4aa4` against
frontend `8e8087103821b6334ba8d5de0a40c91ee58276f9`. Actual C113 execution is
pending for this reviewed combined UI product. Final C110/C112 acceptance remains separate evidence.

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

Historical faef results remain preserved: both 34df71ec attempts passed, while
final docs-only f2f88e9 failed at the original SHIFT_PDF body capture with UI READY,
request FAILED and BODY_UNAVAILABLE, before Save or inspection. The reviewed
frontend source race is not established as the cause of that actual failure.
The current product/reference change requires a fresh C113 proof and gate; the
single original body capture, request/UI diagnostics, byte-equality oracle and
independent inspections are unchanged.

The current combined UI product `a880371589aa1dd117dde9e80936c687d146f919` is pinned through
source `87e69aaaab604250ee93dcb4dca34b68eca74599`. Earlier product results and
original C113 capture failures remain historical evidence. A fresh suite-specific
proof and actual gate are required; this reference update changes no journey,
observer, capture oracle or acceptance predicate. Mounted synthetic viewport
checks are a separate gate and do not establish new AI/API acceptance.

The current JSON-read compatibility product `8081a2984b2f27b909fa2b86cd9f10ffd01d1e11` is bound to
source `beee17544119794009cf96c3cb3a69838bc2a738`. The d48 C112 JSON-read and
C113 clock-prelude failures remain preserved; this source correction is not proof
of their cause. Fresh independent privacy proofs and unchanged actual gates must
establish this candidate's results. The a880 synthetic viewport PASS remains
historical, and the separate public JSON experiment does not substitute for C acceptance.

The current quiet-polling, optional report-model and failure-cleanup product
`6fa27276f14ef31757cb0da5ee9d7acc15789111` is bound to source
`5e97b71c6701e2ae1bf83547dce563a02c693389`. The optional model remains off by default.
Fresh independent privacy proofs and unchanged actual gates must establish this
candidate's results. The 06877 C110/C112 passes and C113 SHIFT_XLSX body-capture
failure remain preserved, along with the earlier d48 failures. Prior a880 viewport
and 8081 interaction evidence is historical; new quiet-polling geometry and public
reader experiments are separate evidence and do not replace these actual gates.

The reviewed executor before-photo product
`bbe897514e58a4b8f8b6d4f580e5273e34cb5c75` is bound to C source
`09e78cd2f5190e31f5d3e3dd32531bc9e3c7b2cc`. Fresh independent privacy proofs
and unchanged actual gates are required for this candidate. The 5947 C110/C112
passes and C113 SHIFT_XLSX body-capture failure remain historical evidence.
Before-photo mounted browser checks use synthetic intercepted HTTP and Android
emulation; they do not establish stored-photo backend authorization, physical
device behavior or a repair to the original C113 capture failure.

The reviewed Panel reset-focus product
`f967d0acf3f04bda304b7fe47e1bf76ca8814634` is bound to C source
`13a655fdd0587cbcd38e05fefefdfb69131d5579`. Fresh independent privacy proofs
and unchanged actual gates are required. The 038b C110/C112/C113 passes remain
exact-head historical evidence; earlier intermittent C113 capture failures and
their unresolved cause are preserved. The accepted native-focus fixture uses
the identical thirteen-dependency component closure. Its synthetic desktop
results do not establish production App routing, backend authorization, physical
device behavior or a repair to the original capture issue.

The healthy-poll command candidate requires fresh independent privacy proofs
and unchanged actual C gates after authorized publication. The focused mounted
App gate uses synthetic HTTP and desktop production preview. Earlier 5368 C110
and C112 passes, C113 capture failure and all prior evidence remain preserved.
The command-eligibility change does not establish a capture reliability repair.

The analytics-expiry privacy correction requires fresh source-bound proofs and
unchanged actual C gates for its exact product. The fourteen focused source
cases and independent real-timer checks remain separate from browser evidence.
Earlier 7985 C110/C112/C113 passes and historical intermittent capture failures
retain their exact-head scope; this correction makes no capture-repair claim.

The in-app notification product requires fresh source-bound proofs and unchanged
actual C gates. Its separate eighteen-case mounted notice/polling browser suite
uses production preview, desktop Chromium and synthetic intercepted HTTP; it
does not establish backend authorization or OS/WebPush delivery. Earlier 348b
C110/C112 passes and C113 ORDER_PDF capture failure retain their exact-head scope.
