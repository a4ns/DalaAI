# C112 history/analytics Android CI seam (source preparation)

Source-ready binding: C112 `16175cf561af217b6e200fff45ba1c066b23a7b4` against frontend
`d78b9c3b7cabbcbd05b01df77f2a7ec57739afe5`. Actual C112 execution is pending. Existing
C110 remains an independent exact-one-journey gate; its prior green results do
not establish this new history journey.

## Reserved ownership

- `.github/workflows/history-mobile-e2e.yml`
- New `ops/ci/history_*` files only
- C owns new `tests/e2e/c112_*` and corresponding evidence documents
- A5 owns shared demo Compose, bootstrap/runtime and remote publication

## Accepted historical setup to reuse

The reviewed operator path is `DALA_DEMO_FIXTURE_MODE=history ops/demo/run.sh`.
For this disposable CI job, use the same unchanged preparation and full bootstrap:

1. Install exact existing dependencies and official matching Playwright Chromium
2. Create a new private directory and isolated browser HOME/NSS/TLS fixture
3. Run C112's own exact-config, source/frontend-bound dummy-secret failure preflight
4. Only after it passes, invoke unchanged `ops/demo/prepare.py --workers
   --fixture-mode history` for the new directory and loopback domain/ports
5. Use `ops/demo/compose.yaml` + `ops/demo/compose.workers.yaml` + the new history
   CI overlay, explicitly starting only API/web and approved setup/observer services
6. Validate declared and actual service inventory; no worker/provider process runs
7. Run C112's unchanged configuration and its distinct strict evidence gate
8. Remove only this invocation's disposable stack and private fixture artifacts

The ordinary full-profile preparation creates its normal named model-policy file.
That file is unused in this read-only gate: no worker service is started, provider
keys stay absent and model/push enablement is forced off. Do not replace the
reviewed bootstrap, change grants, adopt an existing fixture or start the human
launcher (which would start the worker too).

The API image/provisioning helpers and seven-migration grants remain A5's existing
reviewed history profile. PostgreSQL must stay internal/unpublished. If C112 needs
direct DB corroboration, a nonroot read-only observer sharing `service:db` may
receive only the runtime DSN and exact reviewed observer source; no owner secret.
Its fixed interpreter adapter must allow only that observer and bounded inputs.

## Public fixture contract

Use the unchanged OBJECT returned by `ops/provision/history_demo.py:public_manifest()`.
Do not substitute the minimal C110 fixture or wrap it in a dry-run response.

- `fixture_version`: `dalaai-canonical-history-live-demo-v1`
- `fixture_mode`: `history`; `synthetic`: true
- `history_sha256`: `7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`
- `history_orders`: 540
- `history_period_utc`: July 1, 2026 00:00Z through October 1, 2026 00:00Z, exclusive end
- `users`: the same stable DALA-DEMO-MASTER / DALA-DEMO-EXECUTOR identities
- Master has all four canonical sections; executor only SYN-SECTION-001
- All 17 historical actors remain disabled and cannot authenticate
- `live_path` supplies existing section/equipment/executor/work-code/material IDs
- No new live orders, sessions or physical photos are seeded
- Historical photo metadata remains missing physical evidence, never verified bytes

Known reviewed API/report expectations for the full period are 540 issued orders,
568 submission attempts and 444 missing historical after-photo rows, with
`physical_evidence_verified=false`. The existing public manifest does not invent
extra fields for those latter counts; C112 can bind its expectations explicitly.
The clock/history dates are never shifted to make today's view look populated.

## Exact C112 process interface

Reuse the already agreed file-based names where appropriate:

- `DALA_E2E_BASE_URL=https://localhost:18443`
- `DALA_E2E_FIXTURE_FILE`: exact public history manifest object
- `DALA_E2E_MASTER_PIN_FILE`, `DALA_E2E_EXECUTOR_PIN_FILE`: private files
- `DALA_E2E_FRONTEND_SHA`, `DALA_E2E_BACKEND_SHA`: exact accepted identities
- A unique C112 run ID and a fresh absolute C112 preflight receipt path
- Optional fixed read-only observer interpreter/schema seam, if required by C

The exact single title is `C112 real history analytics and protected reports`;
project `c112-android-chromium`, seven required steps, Pixel 7 emulation with two
contexts. C112 owns `c112_playwright.config.cjs`, `c112_secrecy_preflight.cjs`,
`c112_preflight_proof.cjs` and `c112_gate.cjs`. The source manifest binds all
17 C112 files and both existing package/lock files. The C112 proof binds the new
C112 test/config/capture/observer code and shared login boundary actually used;
a previous C110 receipt alone cannot authorize unrelated test code. No alternate
reporter/config, skipped mandatory cases, fake API success or reused proof is a pass.

A C112 PASS may establish only its specified read-only historical UI/API journey
under Android emulation. It cannot promote physical Android, native permissions,
live push/provider delivery, model quality or a complete release. Historical
C110 evidence and the current candidate's other report/history/Compose regressions
remain separate and must not be relabeled or silently omitted.


## Running the isolated job

After A5 assembles exact C112 source and product inputs on a clean commit:

```sh
python -m unittest discover -s ops/ci/history_tests -v
python ops/ci/history_runner.py --check-inputs
npm ci --prefix tests/e2e --ignore-scripts
python -m pip install -r backend/requirements.lock
node --test tests/e2e/c112_*.test.cjs
python -m unittest discover -s tests/e2e -p 'c112_*test.py' -v
node tests/e2e/node_modules/@playwright/test/cli.js install --with-deps chromium
python ops/ci/history_runner.py --report history-ci-summary.json
```

The workflow additionally checks out the exact frontend into
`.ci-c112-frontend-reference`, installs `libnss3-tools`, and runs the existing CI
safety suite. Official Ubuntu 24.04, Node 24.21.0, Python 3.12.15 and locked
Playwright 1.63.0 are the same reviewed runner versions as the existing core job.
Docker and its Compose plugin must be available; no local browser/DB execution
is claimed by source-only checks. A5 alone publishes and triggers this workflow.

Preparation explicitly selects history and disables the optional demo clock.
C's UI inputs are 2026-07-01T05:00 to 2026-10-01T05:00 at UTC+5, exactly
mapping to the canonical midnight-UTC interval. The history dates are unchanged.
The worker and budget-init service are inactive profiles and worker flags are off.
Declared configuration and actual six-service inventory are checked independently.
The observer adapter binds its script and both public actor arguments to the
fresh manifest, with no credential arguments or host database port.

The driver creates no actual PIN/database inputs until C112's own fresh proof
passes. It runs the frozen gate even when the browser test fails or has no report.
Only a successful gate permits `history-ci-evidence.json` and the C-owned
`history-ci-gate.json` receipt; failed runs retain only bounded summary/stage
counts. Raw Playwright/stdout/Compose outputs are not uploaded. All private
fixture files, disposable trust and raw artifact trees are removed; stack cleanup
failure fails the job. Existing profiles, source and other Compose projects are
never adopted or removed.

The accepted C correction uses canonical minute-form datetime-local values and
asserts both normalized fields before the request; UTC bounds and all count/time
assertions are unchanged. Its 13 executable/package proof inputs now include the
C-owned fixed diagnostic helper. Fresh proof is mandatory after this source
change. Historical b2eda8c/d4a293 failures remain failures, localized to the old
first date-field fill. CI projects only the helper's fixed substep/failure/HTTP
category labels when a later run fails; diagnostic labels cannot promote a pass.

The subsequent semantic selector correction scopes the exact-name combobox to
the analytics region, requires one matching control, and verifies both returned
selection and field value against the same actual analytics order ID. Its six
new source regressions do not replace a real browser run. The prior 2471afde
receipt remains FAIL at order selection after four completed steps; the next
exact-HEAD proof and run must establish the remaining report/role/data checks.

Historical B9a full acceptance at347119c47b9a0ec70cd30cbc8bce2a2774a439e0 remains attached to that exact source. Final Bfaef is now bound explicitly; fresh C112 proof and real journey are required. Its new clock/download controls remain dormant in this read-only gate and are not promoted by this binding.

The current target is the reviewed deadline-correction product. Earlier faef
history passes remain historical; this exact source requires a fresh C112 proof
and actual gate. Source-reference maintenance does not change the read-only
journey, observer, canonical period, counts or acceptance predicates.

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
