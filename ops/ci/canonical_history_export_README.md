# Isolated canonical-history export reproduction

Exact C test source `743474bcb60212c98c0d2b28776164467d5f67bf`, parent
`5947af4c9999bbc95f6dd0542c132e528206bce3`, adds only
`backend/tests/test_c_day_canonical_history_exports.py` (SHA256
`523586b9e7f656c621a1ddf76511adc4e38db29eb07093902ef00bd8ce37ce82`).
The 109 reused backend/app, generator and lockfile blobs are byte-identical to
current reference `038bcb06351b187301614d9f18cef49fa27b96df`.

[Author/reviewer handoff](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6056702580)
records mixed local results: author 6 PASS, reviewer 5 PASS with one full XLSX
subprocess timeout. This runner supplies a separate supported CI observation;
it does not promote either local outcome into acceptance.

Only `validation/canonical-history-exports-20261008` triggers this workflow.
Official Ubuntu24.04/Python3.12.15, a fresh venv, official DejaVu fonts and the five
already-locked export packages are used. Optional lxml/NumPy are absent. The
six exact unittest cases run once in their normal discovery order. No test,
renderer, six-second deadline, CPU/memory/output cap or dependency version is
modified; no retries or skipped/expected-failure promotion are allowed.

The standard unittest result adapter retains raw output privately and emits
only fixed case IDs, statuses, bounded durations and failure categories. A
TEMPORARILY_UNAVAILABLE code remains generic. The separate timeout-observed
boolean is true only if an actual subprocess.TimeoutExpired object exists in
the caught exception chain. The 90-second outer process ceiling prevents a hung
runner and cannot make any renderer timeout pass. Runtime receives no provider,
DB, credential or network configuration inputs. No exports or raw failures are
uploaded; only the bounded summary is retained.

These are offline canonical-source/renderer checks. They do not establish live
HTTP/DB authorization, stored-photo evidence, physical-device behavior or C113
browser-capture reliability. Main integration and optimization are separate.

```sh
python ops/ci/canonical_history_export_tests.py
python ops/ci/canonical_history_export_gate.py --source .ci-canonical-source --current .ci-canonical-current --check-inputs
python ops/ci/canonical_history_export_gate.py --source .ci-canonical-source --current .ci-canonical-current --python "$RUNNER_TEMP/dalaai-canonical-python/bin/python"
```
