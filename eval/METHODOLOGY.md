# Measurement contract

## Frozen scope

Version v1 has 48 hand-authored cases, split 24/24 before first inference. All
expected labels are independently written decisions, based on AGENTS.md
§7/§9 and proposal.2 evidence/quantity constraints. The production implementation
was visible during interface inspection. No production code, threshold or prompt
is tuned here. There is no random seed: the dataset is authored, and `seed: null`
is intentional. Changing any fixture or expected label requires a new dataset
version with a disclosed rationale; do not silently update hashes to match a run.

Mandatory scope includes description/code completeness, trusted catalogues,
positive finite bounded three-decimal material quantities, distinct materials
and photo references, required unplanned after evidence, binding to the current
order/submission/revision, persisted completeness and current workflow state.
Unknown trusted evidence blocks mandatory permission. A good result in another
gate cannot offset this. Text-only semantic match/mismatch/unknown is a separate
expected label, not a safety or quality score.

File validation is a synthetic server fact. No actual image content, pHash,
blur/EXIF, source capture time, repair quality or physical safety is evaluated.
A repeated attachment ID is tested; duplicate image bytes under different IDs
and untrusted photo timestamps are explicit unsupported coverage, not passes.

## Metrics and denominators

Each expected case contributes exactly once. Duplicate or foreign predictions
are an error. Missing predictions become `no_output`; malformed decisions,
non-finite/negative latency or invalid fallback values become `invalid`.
Neither outcome is silently dropped. A valid explicit `abstain` is separate.

For each of `gate_permit`/`gate_block`, and independently the text classes
`match`/`mismatch`/`unknown`:

- Confusion matrix rows are expected classes. Columns include every expected
  class plus `abstain`, `invalid`, `no_output`
- TP is the matching cell, FP other truth rows predicted as that class, FN every
  other prediction in that truth row, **including non-decisions**
- Precision = TP / (TP + FP); recall = TP / (TP + FN)
- F1 = 2TP / (2TP + FP + FN). A supported class with no decisions has F1=0
- Macro-F1 averages supported expected classes only; its number of classes is
  reported. An absent, unpredicted class has null F1, never an invented perfect 1
- Accuracy-all = correct / all expected episodes; coverage = class decisions /
  all expected episodes. Conditional accuracy = correct / class decisions, and
  is labeled separately so abstaining cannot inflate the main number
- Abstention, invalid-output and no-output rates each use all expected episodes
- Every zero denominator is null, including critical risk and unknown cost

Critical false acceptance here means **a mandatory-gate violation or unknown
mandatory proof labeled `critical_gate_block=true`, predicted `gate_permit`**.
An emitted `gate_permit` still counts as a critical false accept if other fields
make that prediction invalid; malformed telemetry must not hide an unsafe claim.
The denominator is all such expected blocking cases, including invalid/missing
outputs. It is not all cases, all accepted cases, or a production closure rate.
All v1 expected gate blocks are in this critical cohort. A run with any missing,
invalid or disagreeing gate output fails fixture expectations even if its
critical-false-accept numerator is zero. Empty datasets cannot pass.

Fallback true / all expected episodes is reported separately from unknown
fallback status / all expected episodes. Missing rows have unknown fallback
status. The rules baseline explicitly returns `rules_fallback` for every valid
assessment and abstains on all text-semantic conclusions. Its semantic F1=0 and
100% abstention are limitations, not measurement failures or fake model scores.

Latency is a monotonic in-process elapsed time covering input decoding plus rule
assessment, excluding interpreter startup and file I/O. p50/p95 use nearest rank
`sorted[ceil(p*n)-1]`; the observed and total episode counts are both reported.
It is local synthetic latency, not provider, HTTP or mobile latency. No rounding
is used to make short calls appear to be exactly zero. No currency conversion or
provider price is assumed: cost USD is null, status NOT_MEASURED, and the actual
paid-provider-call count is 0.

## Actual provider seam at this base

`backend/app/ai/providers.py` defines a future `LLMAdapter.assess(ProviderInput)`
protocol, `minimize_synthetic_input`, strict `parse_provider_result`, and a
`SyntheticProvider` stub. No real provider adapter is implemented. The synthetic
harness only accepts the exact synthetic class and returns rules fallback even
when the stub supplies a valid match/mismatch. No image bytes are sent, so visual
claims are rejected. Gates suppress the stub on an incomplete/stale submission.

`test_provider_seam.py` tests good/mismatch/unknown branches, timeout,
unavailability, invalid JSON/schema, attempted instruction-bearing outputs,
foreign evidence and suppression by gates. These are **synthetic control-flow
unit checks**, never a model-quality evaluation. The measured report therefore
always records model-enabled status NOT_RUN with model/version null. A future
real-provider evaluation requires a separately authorized adapter, privacy/data
review, model ID/version, prompt hash, timeout/budget configuration and real
observed cost/usage. This package cannot make that call.

## Interpret with care

This is a finite, authored conformance suite, not a random industrial sample.
No confidence interval or generalization guarantee is claimed. Zero observed
critical false accepts cannot prove zero future risk. Neither synthetic unit
tests nor these rules establish database close-lock correctness, actual file
validation, permission enforcement or the end-to-end master workflow.
