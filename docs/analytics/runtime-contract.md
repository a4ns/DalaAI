# C3 trusted runtime facts v1

This is one internal Python DTO, **not a new HTTP/OpenAPI contract**. C4 consumes
it directly. It contains no query, router, migration, role policy, session lookup,
clock read, model call or export transport. The accepted core contract is unchanged.

## Trusted boundary: responsibilities of the A5 repository/router

Call `app.analytics.c3_facts.build_facts(rows: TrustedRows, period: Period)` only
after authenticated server-side authorization and extraction. `TrustedRows` is a
precondition, not a security capability: a Python constructor cannot prove access.
Never construct it from request-body rows, client roles, client section lists or
an `authorized=True` flag. The projection accepts none of those arguments.

The repository/router must:

1. Resolve the current session and apply current object authorization before
   loading any order, submission, review, assessment or dictionary reference.
   Historical submissions do not grant a former assignee access after reassignment.
2. Load related rows through the authorized parent orders. An order report must
   be authorized for that particular ID; a period report must use the authorized
   report scope. Do not query everything and hope a renderer filters private rows.
3. Establish consistent extraction and historical completeness. Independent flows
   need orders issued before the period, final submissions before the period, and
   earlier rework reviews in the same assignment revision. Filtering all tables
   by `issued_at` or all reviews by the period produces incorrect denominators.
4. Supply server-authored provenance: `synthetic`, `source_ref` (safe capture ID or
   checksum, never a secret/private DSN), `scope_description`, `domain_as_of`,
   `captured_at_real`, `coverage`, `history_complete`. Scope text is display
   metadata; it does not authorize, filter, or prove coverage.
5. Own error mapping, endpoint contract, security tests and actual PostgreSQL
   consistency tests. Pure unit checks below prove none of those boundaries.

Current snapshots must describe `domain_as_of`; this module cannot reconstruct
historical snapshots or prove the declaration. Real capture time and domain/demo
time are distinct and are never compared. Completed periods require aware
timestamps and `start < end <= domain_as_of`, with half-open `[start,end)` flows.

## Single DTO and serialization

All dataclasses are frozen with slots, defined in `app.analytics.c3_types`.
`Order`, `Submission`, `Review` are reused from `app.orders.models`; their fields
are not copied into a second source schema. Input collections are tuples.

- `TrustedRows(provenance, orders, submissions, reviews, assessments=(), materials=())`
- `AssessmentFact` preserves the accepted stored assessment fields: id,
  submission_id, assignment_revision, schema_version, mode, model, model_version,
  duration_ms, recommendation, score, reasons, evidence_ids, fallback_reason,
  stale, created_at. Its modes are `model`, `rules_fallback`, `manual`
- `MaterialReference(material_id, label, unit)` is optional dictionary metadata
- `Period(start, end, display_timezone='Asia/Almaty')`
- `AnalyticsFacts(schema_version='c3-runtime-facts/1', provenance, period, orders,
  metrics, ratings, closed_materials, unavailable_reasons)`
- `OrderFact(order, is_overdue, attempts)`; each `AttemptFact` has submission,
  review (nullable), assessments, assessment_status (`absent` or `recorded`)
- `MetricFact(name, source_table, status, numerator, denominator, eligible,
  missing, excluded, value, source_ids, missing_source_ids, excluded_source_ids,
  small_sample)`
- `ExecutorRating(executor_id, human_score, closed_on_time, closed_with_rework,
  composite_score=None, composite_status='unsupported_inputs')`
- `MaterialFact(material_id, label, unit, quantity, order_ids, submission_ids, review_ids)`

`AnalyticsFacts.totals_available` is the one coverage policy exposed to consumers.
`facts_to_dict` in `app.analytics.c3_facts` returns JSON-ready data and adds that
boolean. Decimal values become lossless **strings**; datetimes become UTC ISO
strings; enums become values; tuples become arrays; absent values stay null.
The property checks provenance and the presence of all three aggregate
collections. Serialization suppresses every aggregate when that policy is false,
even if an inconsistent hand-constructed DTO attaches aggregate arrays.
Free text remains unchanged for the renderer to escape. There is no generated
HTML, file URL, photo fetch, or external resource in this projection.

Coverage values are exactly `consistent_snapshot`, `frozen_complete_export`,
`partial_keyset`, `drained_moving_keyset`. Only the first two, together with
`history_complete=True`, permit totals. Other captures retain observed order
details but `metrics`, `ratings`, and `closed_materials` are null, with an explicit
reason. Draining moving keyset pages never upgrades them to a complete snapshot.
No whole-enterprise meaning is implied by a complete **authorized scope**.

## Cohorts, nulls, attribution and numeric policy

The independent definitions come from published C3
`c5984436da2b94bf33e61b8a62a2fe54f3657a60` (`docs/analytics/metric-definitions.md`,
`check_examples.py`, `c1_metrics.py`) and C4
`4a5184fd5caa3c1be35fea5ff55d534967c191bf`
(`docs/reports/c4_report_examples.py`, `c4_c1_history_report.py`). These Git objects
are design evidence, not a runtime dependency or proof of a live database.

- `issued_orders`: original issued_at in period; `submitted_orders`: distinct
  orders with a submission in period; `submission_attempts`: all such submissions
- `closed_orders`: orders linked to human close-reviews in period, independently
  of issuance or submission date; `rework_decisions`: human rework-reviews in period
- `awaiting_review` and `overdue_active`: snapshot stocks at domain_as_of, never
  historical month-end stocks. Overdue uses the seven active statuses and strict
  due_at < domain_as_of; ai_review, closed and cancelled are not active
- `human_score`: close-linked final_score mean; null is missing, score zero is
  observed. AI score is never substituted, even for an unscored human close
- `closed_on_time`: close-linked captured done_late booleans, not current due_at
  or review time. `attempt_on_time` uses every submission in period instead
- `closed_with_rework`: closed orders with an earlier human-reworked attempt of
  the same assignment revision. Equal timestamps are supported through attempt
  identity; a previous assignee's revision does not penalize the next revision
- Ratings group the closed cohort by final `submission.submitted_by`, not the
  current assignment or current brigade. They are ID-sorted descriptive
  components, with no rank, smoothing, complete composite or employment decision
- Materials sum only the final close-linked submission quantities. These are
  **declared materials, not authoritative inventory writeoffs**. Decimal values
  never pass through float. Missing dictionary label/unit stays null; unlike
  materials are not combined. Source order/submission/review IDs are retained

Count metrics have exact numerator/value and denominator=null. Means/rates use
exact integer-derived Decimal numerator and observed denominator; displayed value
is half-even rounded to 12 decimal places under a private precision-40 context,
independent of the caller's Decimal context. Zero eligible gives `no_cohort` and
null value; all missing gives `missing` and null; partly observed gives `partial`.
`small_sample` means 0 < observed n < 5. Full eligible source IDs include missing
IDs. Excluded is explicitly zero in v1: there is no silent within-cohort exclusion
policy; outside-period facts are outside the named cohort, not fabricated missing
or excluded records. Corrupt joins, duplicate identities and invalid values fail.
The domain Submission currently requires done_late bool; defensive projection of
a legacy null preserves it as missing rather than inventing on-time or late.

No assessment means no assessment in this capture; AI job state is unknown.
Stale recommendations and exact mode are retained. Recommendations created after
a review must not be described as advice available to the reviewer at the time.
Attempts and reviews are not a complete OrderEvent audit log. Downtime,
seven-day repeat faults, brigade history and the proposed composite rating remain
unsupported rather than filled with zero or inferred from unrelated fields.

## Focused verification

Run on the exact code SHA reported by the handoff:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p 'test_c3_facts.py' -v
git diff --check
```

The focused suite uses independent hand-calculated synthetic rows: distinct flow
and stock cohorts, half-open/offset times, null versus zero, partial and drained
captures, equal-time rework, reassignment, all three assessment modes, exact
Decimal totals, deterministic ordering, invalid joins and the absence of client
role/scope authorization arguments. DB/RBAC/HTTP/model/browser/device tests are
**NOT_RUN** by this package. A5 integration and C4 rendering are separate gates.
