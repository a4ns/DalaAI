# Synthetic history v1

**Синтетические данные — не история предприятия.** All employees, assets,
work, quantities, scores and dates are invented. No actual enterprise records,
credentials, sessions, real photographs, model outputs or delivery receipts are
included. This is a deterministic **offline historical export**, not a seed DB
loader, a live API request body, or evidence that the application passed a test.

## Reproduce and check

Requires Python 3.11+ and only its standard library. From the repository root:

```sh
# Generate history plus its manifest. No evaluator labels are written by default.
python3 scripts/synthetic/generate.py --output data/synthetic/generated/v1/history.json

# Explicitly reproduce the separately located evaluator construction labels.
python3 scripts/synthetic/generate.py \
  --output data/synthetic/generated/v1/history.json \
  --evaluator-output data/synthetic/generated/evaluator/v1/pattern_truth.json

# Validate schema, references, timeline, artifact bytes/hash and evaluator linkage.
python3 scripts/synthetic/validate.py data/synthetic/generated/v1/history.json \
  --manifest data/synthetic/generated/v1/history.manifest.json \
  --evaluator-truth data/synthetic/generated/evaluator/v1/pattern_truth.json

# Focused synthetic unit/invariant tests. No DB, HTTP, provider or device runs.
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s scripts/synthetic -p 'test_*.py' -v
```

The full **540-order** history and its evaluator truth are **generated locally,
not shipped in the source package**. The package retains generator/schema
**1.0.0**, seed **20261008**, compact schemas, small checksum manifests and a
single linked illustrative order in `v1/example.json`. That example is explicitly
marked as a subset; it does not satisfy the 500-order requirement by itself.
The commands above create the full corpus under ignored `generated/` paths.
The original full artifact is preserved in the author's earlier Git checkpoint
`5775d6f6aa8e1bbf8796e7ba36c9ada6f1edd6e7`; this change does not rewrite it.
That checkpoint need not be present in a source-only distribution.

The retained `v1/history.manifest.json` pins full-history SHA-256
`7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`.
The separate `evaluator/v1/pattern_truth.manifest.json` pins generated truth
SHA-256 `bb8002d43c699d182b789e5e5dd47fe2d5d969480adfcb61ab103bb830d3d1ad`.
Tests regenerate and check both complete files against these retained hashes;
they also compare the small example to its exact source rows. Generated manifests
can be byte-compared with the retained manifests. Only schema JSON serialization
was compacted for publication; generated history/truth bytes are unchanged.

`--seed` accepts 0..2^63−1; `--count` accepts 500..920. Identical
configuration produces identical bytes; a changed seed changes identifiers and
invented facts. Canonical JSON is UTF-8 with sorted object keys, compact separators,
no NaN, preserved array order and one final LF. The manifest includes SHA-256 of
those exact history bytes, the export schema bytes, configuration and table counts.
No current clock, hostname, user directory or session ID enters the output.
The generated output directory is excluded from Git. Do not ship it as runtime
assets or accidentally add the full corpus to the small publication package.
Generation replaces the named output files; it does not append rows. This file
property is **not** a claim of database idempotency. Golden-byte tests detect drift
in generator/schema/toolchain behavior; bump versions before intentional changes.

## Scope and semantics

- Window: **2026-07-01 00:00 through 2026-10-01 00:00 Asia/Almaty (UTC+5)**,
  start inclusive and end exclusive. Stored timestamps are UTC:
  `2026-06-30T19:00:00Z` to `2026-09-30T19:00:00Z`. As-of is the end boundary.
  Orders are issued in July, August and September, and every lifecycle record
  finishes inside the window. All 540 final snapshots are closed.
- Catalogues: **4 sections, 25 equipment, 2 masters, 15 executors, 3 brigades,
  20 work/fault codes and 40 materials**. `work_codes` is the accepted core name
  for the work/fault-code catalogue, not a second parallel fault dictionary.
- Brigades belong to sections 1–3. Their executors also have section-4 membership;
  section-4 orders use an individual responsible executor and `brigade_id=null`.
  Each master has two sections. Exported employee records contain no authentication
  fields. The corpus avoids overlapping executor assignments for simplicity;
  this is not a change to the core's allowance for multiple active orders.
- `Order`, `Submission` and `Review` record field names follow current internal
  domain types. The referenced core contract is **1.0.0-proposal.2**, SHA-256
  `b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`.
  This export has its **own** versioned schema. It is neither `/dicts` nor an
  OpenAPI response nor a SQL dump. It contains section membership, normalized
  submissions/reviews, and synthetic photo records; it intentionally omits wire
  `domain_now`/`is_overdue`, auth fields, jobs and operation receipts. `number`
  is a stable decimal string, not a preallocated SQL identity.
- Events are ordered by a per-order contiguous sequence. `done` and `ai_review`
  are emitted at the same instant with one operation/version; they are two events
  for one submission. A rework retains the prior submission and review, then adds
  a second attempt. Only the synthetic master reviews close orders. Original
  deadlines never move; each attempt's `done_late` compares its submitted_at to
  that original deadline. Pause duration is not equipment downtime.
- `ai_assessments=[]` means **absent**, not pending, failed, a model execution,
  or a fallback result. Human scores are explicitly invented simulation values;
  `final_score=null` stays unscored and is never replaced with zero or AI output.
- Photo rows are **metadata placeholders only**, explicitly
  `artifact_available=false`. There are no image bytes, storage URLs, image
  hashes or claimed upload/validation results. Synthetic `complete` means that
  the fictional structure has the required references; it does not establish
  trusted evidence or authorize live closure. Before-photo comparison is absent.
- Material writeoffs exactly mirror each immutable attempt's payload. Quantity
  is positive, finite and at most three decimal places; duplicates are rejected.
  Rework-attempt consumption is separate consumption, not a replayed writeoff.

Historical records must not be replayed as live `POST /orders`: their deadlines
are in the past relative to a live current clock. This package does not relax live
validation or mutate clocks. A later explicitly authorized A6/A0 import mapping,
demo guard and isolated DB tests are required before any loading. Authentication,
real photos, persistence, model/provider evaluation, notifications and physical
Android verification remain outside this package.

## Detector/evaluator boundary

`history.json` and its manifest carry no pattern labels or evaluator paths.
The optional generated `data/synthetic/generated/evaluator/v1/pattern_truth.json`
is a **separate, evaluator-only** file pinned to the history SHA-256. Keep the evaluator directory
out of application/runtime assets. Never concatenate it into a prompt, detector
input or model context. Public repository availability is not a confidential or
independent holdout guarantee.

Four construction cohorts are planted: same-equipment/work-code recurrence,
material-quantity increase, longer elapsed execution, and late submission against
an unchanged deadline. They each contain 24 target orders; three include 24
matched earlier-period controls. Cohort IDs and descriptive text in history do not
encode these labels. The generator necessarily knows the construction; its truth
file is **not an independent oracle and does not measure detection quality**.
Cohort order sets are disjoint, but observable signals need not be: long execution
can also be late. These are descriptive synthetic correlations, not causes,
employee judgments, safety decisions or industrial accuracy claims.

`detector_payload(history, as_of=...)` in `scripts/synthetic/validate.py` creates an
explicitly allowlisted projection containing only observed submissions at/before
the UTC cutoff and immutable assignment/deadline/catalogue references. It takes
no truth argument and omits free text, scores, reviews, final statuses, assessments
and future submissions. It does not copy arbitrary nested metadata. Each fact has
source order/submission IDs, work code, material quantities, and elapsed wall-clock
execution from that attempt's start (including pauses, never labeled downtime).
Use the projection when testing temporal detectors; do not feed a full future
history snapshot into an earlier-time decision. The projection is a helper, not
an application detector or an independently evaluated model.

## Validation and safe recovery

The scoped test suite covers byte reproduction, changed seeds, count bounds,
schema drift, domain-field compatibility, minimum counts, local calendar months,
references/scopes/roles, attempt/event/version consistency, placeholder honesty,
material precision, immutable deadlines, null semantics, positive/control facts,
nested label sentinels and point-in-time leakage. Validation is strict for this
v1 corpus profile; it is not a general business-API or database validator.

A failed validation exits nonzero. No library installation or network is needed.
For recovery, regenerate the named export with the same version/seed/count or
revert only this package's commit. No database, service, shared clock or backend
file is touched. Independent review and integration remain separate gates.
