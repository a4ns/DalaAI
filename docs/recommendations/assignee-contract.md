# Executor recommendations v1: deterministic advisory baseline

Base: `064a7a3785a95d61d7150e7785ff17db892bc110`. New additive GET route;
root approved the seam. A5 alone owns package initialization/runtime mount.
No migration, auth change, dictionary change, provider purpose, or dependency.

Case 1 §5.1.3 asks for an optional AI suggestion using availability, specialty,
and equipment-specific rating. This implementation supplies a transparent
**partial deterministic baseline**. It must not be described as satisfying the
AI/specialty/equipment-specific parts: current employee schema has no specialty,
qualification or permits, and this request does not take equipment as a filter.
The human master explicitly chooses the executor; neither advice nor its rank
assigns, reserves, changes a role, or certifies safe work.

## Mount

```python
from app.recommendations.assignee import AssigneeRecommendationService
from app.recommendations.assignee_routes import create_assignee_router

app.include_router(create_assignee_router(AssigneeRecommendationService(
    connector, domain_clock=domain_clock, real_clock=clock,
    synthetic=True,  # Explicit isolated-demo source configuration ONLY.
)))
```

`synthetic` is a required boolean supplied from trusted deployment/data
configuration. General runtime must not silently hard-code `True` or `False`.
No model hook runs. `model_status=disabled_for_purpose` means this purpose has
not been approved/enabled; an existing closure/report budget is not permission.
A5 may add an empty `backend/app/recommendations/__init__.py`; namespace import
already works without it.

## Request

`GET /api/v1/recommendations/assignees?section_id=<UUID>&work_code_id=<optional UUID>&limit=3`

- `section_id` is mandatory and must be in the current active master's sections
- `work_code_id` is optional and, when present, must be a real global work-code ID
- `limit` is an integer string from 1 to 5; default 3
- Unknown/duplicate keys, caller-supplied actor/role, equipment filters, tokens in
  query strings, and empty values are rejected
- Authentication: exactly one existing `__Host-naryadai_session` cookie
- No body/POST/CSRF token: this GET is strictly read-only; POST returns 405
- Current executor, manager and admin roles receive 403; inactive/revoked/expired
  session or inactive caller receives 401

## Success shape

```json
{
  "schema_version": "1",
  "mode": "rules_baseline",
  "model": null,
  "model_status": "disabled_for_purpose",
  "advisory_only": true,
  "synthetic": true,
  "section_id": "00000000-0000-0000-0000-000000000004",
  "work_code_id": null,
  "as_of": "2026-10-08T01:00:00+00:00",
  "domain_as_of": "2026-10-08T01:00:00+00:00",
  "expires_at": "2026-10-08T01:00:30+00:00",
  "eligible_count": 1,
  "returned_count": 1,
  "candidates": [{
    "executor_id": "00000000-0000-0000-0000-000000000002",
    "employee_code": "E-1",
    "rank": 1,
    "on_shift": true,
    "workload": {
      "outstanding_count": 0,
      "active_count": 0,
      "queued_count": 0,
      "awaiting_review_count": 0,
      "overdue_count": 0,
      "norm_minutes_total": 0,
      "status_counts": {"accepted": 0, "ai_review": 0, "done": 0, "in_progress": 0, "issued": 0, "paused": 0, "queued": 0, "rework": 0},
      "scope": "current_master_authorized_sections",
      "evidence": [],
      "evidence_truncated": false
    },
    "history": {
      "status": "no_observations",
      "window_start": "2026-07-10T01:00:00+00:00",
      "window_end": "2026-10-08T01:00:00+00:00",
      "closed_count": 0,
      "matching_work_code_count": null,
      "human_score_mean": null,
      "human_score_count": 0,
      "on_time_rate": null,
      "on_time_count": 0,
      "latest_closed_at": null,
      "evidence": [],
      "evidence_truncated": false
    },
    "reason_codes": ["ACTIVE_ON_SHIFT", "SELECTED_SECTION_MEMBER", "NO_VISIBLE_OUTSTANDING_ORDERS", "NO_CLOSED_HISTORY", "HUMAN_SCORE_UNKNOWN", "WORK_CODE_NOT_SELECTED"]
  }],
  "limitations": ["DETERMINISTIC_RULES_NOT_AI", "QUALIFICATIONS_UNVERIFIED", "WORKLOAD_VISIBLE_SCOPE_ONLY", "WORKLOAD_NORM_NOT_REMAINING", "SNAPSHOT_NOT_RESERVATION", "HISTORICAL_OBSERVATIONS_NOT_SKILL", "SYNTHETIC_DATA", "ONLY_ONE_ELIGIBLE_EXECUTOR"],
  "ranking_policy": "outstanding_then_active_then_observed_work_code_v1"
}
```

`eligible_count` counts the entire captured eligible set before output `limit`;
`returned_count` is the actual returned list length. One candidate remains one;
none returns HTTP 200, `eligible_count=0`, `candidates=[]` and
`NO_ELIGIBLE_EXECUTORS`. No alternatives are fabricated from inactive history.
No selected or preferred executor is returned separately from the list.

### Workload

Candidates must be actual `employees` rows with `active=true`, `on_shift=true`,
role `executor`, and current membership in the selected authorized section.
Historical actors' role/active/PIN/membership state is never modified.

Workload includes each candidate's **current assignments across all sections
currently authorized to the master**, even if the candidate's own membership
in another section was later removed. It never returns workload from a hidden
section, nor assumes that hidden work does not exist.

- Outstanding: `issued`, `queued`, `accepted`, `in_progress`, `paused`, `rework`
- Active: `in_progress`, `paused`
- Explicit queue: `queued` only
- Awaiting review, reported separately: `done`, `ai_review`
- Excluded: `rejected`, `closed`, `cancelled`
- Overdue: outstanding and `due_at < domain_as_of`
- `norm_minutes_total`: sum of full original norms of outstanding work, not
  estimated remaining duration or a capacity/free-time claim
- `status_counts` always includes the eight outstanding/awaiting-review statuses
- Up to five evidence examples: `{order_id,status,due_at,updated_at}` sorted by
  order ID, with `evidence_truncated=true` if more exist

Zero visible outstanding obligations is known zero **within the authorized
scope**, not proof that the worker is free across the enterprise.

### History, attribution, unknowns

Selected section only, inclusive 90 domain-days ending at `domain_as_of`.
A record must be a closed order's final current submission, have matching order
and assignment revision, be submitted by its current executor, and have a human
`close` review in the window with `submitted_at <= reviewed_at`. Old reassigned
attempts, another actor's work, future/out-of-window reviews, other sections,
and AI-only assessments do not contribute.

- `status`: `observed` or `no_observations`
- `closed_count`: count of these observed records
- `matching_work_code_count`: count matching a selected work code, or null when
  none was requested; zero means no observed match, not absent competence
- `human_score_mean`: 0–100 mean of non-null human final scores rounded to 2
  decimals, null when `human_score_count=0`; a real score of 0 remains 0
- `on_time_rate`: non-late observed submissions / `closed_count`, 0–1 rounded
  to 4 decimals; null when there are no observations
- `on_time_count`: numerator, not a separate quality/competence claim
- `latest_closed_at`: latest human close review time, or null
- Up to five most recently reviewed records, order-ID tie-break:
  `{order_id,submission_id,review_id,submitted_at,reviewed_at,work_code_id,
  final_score,done_late}`; nullable work code/score preserved
- `evidence_truncated` limits examples only; totals use the complete bounded
  capture and never silently truncate input rows

This is recorded human-review/timing evidence, not independent verification of
physical work, photos, skill, reliability, safety or a causal performance claim.

### Ranking

Lexicographic policy, ascending:

1. Outstanding assignment count
2. Active assignment count
3. Negative observed matching-work-code completion count, only if code selected

Quality scores and on-time rates are descriptive evidence, not ranking inputs.
Equal substantive triples share a **dense rank** (1,1,2). Within a tie, UTF-8 byte
employee-code order and then executor UUID provide deterministic display order;
this tie-break is not a quality judgment. The limit can cut a tied group, so a
returned position is never a unique-winner claim.

### Codes

Candidate reason codes:

- `ACTIVE_ON_SHIFT`, `SELECTED_SECTION_MEMBER`
- `NO_VISIBLE_OUTSTANDING_ORDERS` or `VISIBLE_OUTSTANDING_ORDERS`
- `ACTIVE_ASSIGNMENTS` when active work exists
- `NO_CLOSED_HISTORY` when no eligible observations exist
- `HUMAN_SCORE_UNKNOWN` when no human score exists
- `WORK_CODE_NOT_SELECTED`, `MATCHING_WORK_CODE_HISTORY`, or `NO_MATCHING_WORK_CODE_HISTORY`

Always-present limitations:
`DETERMINISTIC_RULES_NOT_AI`, `QUALIFICATIONS_UNVERIFIED`,
`WORKLOAD_VISIBLE_SCOPE_ONLY`, `WORKLOAD_NORM_NOT_REMAINING`,
`SNAPSHOT_NOT_RESERVATION`, `HISTORICAL_OBSERVATIONS_NOT_SKILL`.

Conditional limitations: `SYNTHETIC_DATA`, `ONLY_ONE_ELIGIBLE_EXECUTOR`,
`NO_ELIGIBLE_EXECUTORS`.

## Consistency, boundedness, and stale responses

One fresh autocommit connection, REPEATABLE READ transaction, existing current
session/principal stores and FOR SHARE locks. Candidate employee/membership,
visible workload and historical parent orders are share-locked. Immutable
submissions/reviews are consistent snapshot reads without extra UPDATE grants. A concurrent change
since the snapshot can produce 503; it is not retried into a different snapshot
or mixed with old facts. New rows committed after the snapshot appear next time.
The principal is rechecked and real session expiry checked after JSON rendering,
while locks remain held. Security time never uses accelerated demo time.

Hard defaults (may only be lowered via typed server configuration): 100 allowed
sections, 100 candidates, 5,000 workload rows and 5,000 historical rows; 5 evidence
examples per candidate. Output limit 1–5. Employee codes are captured up to 257
characters and rejected beyond 256. JSON response cap 512 KiB. Database statement
timeout 5s, lock timeout 1s, idle-in-transaction timeout 10s. Overflow returns an
error, never a deceptively complete partial result.

`as_of` records real capture start. `domain_as_of` is the domain-time workload/
history reference. `expires_at` is min(real capture start+30s, session expiry).
A capture already that old fails 503. Even unexpired advice is only an as-of
snapshot: it neither reserves capacity nor removes command-side authorization.

UI must clear advice on context change (section/work code and draft
section/equipment/type/brigade), auth loss, failed refresh, or expiry. Responses
from older requests or previous users must be discarded. On explicit “choose”
recheck fresh dictionary, current section/on-shift/brigade eligibility and set
only the draft executor ID. Issuing an order remains a separate explicit action
through the existing authoritative command endpoint. Do not auto-pick rank 1.

## Errors and cache behavior

Existing envelope: `{code,message,request_id,retryable,current_version:null,
field_errors:[]}`. No partial candidate data in an error response.

- 400 `INVALID_REQUEST`: duplicate/unsupported query keys
- 422 `VALIDATION_FAILED`: missing/invalid UUID, unknown work code, invalid limit
- 422 `RECOMMENDATION_LIMIT_EXCEEDED`: bounded scope/input/output exceeded
- 401 `UNAUTHENTICATED`: missing/ambiguous/revoked/expired/inactive auth
- 403 `FORBIDDEN`: role or current section denied
- 503 `TEMPORARILY_UNAVAILABLE`: DB/capture/serialization/staleness failure,
  `retryable=true`, `Retry-After: 1`; no internal exception or DSN leakage

All handled success/error responses: `Cache-Control: private, no-store`,
`Vary: Cookie`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

## Verification / integration handoff

Author focused unit/HTTP suite: **29 passed** before packaging. Covers query
scope, forbidden roles, unknown vs zero, actual obligation semantics, ties,
evidence/output caps, no candidates, serialization-time expiry, stale reads,
no false model claim and no command endpoint. Re-run final code before adoption.

Actual PostgreSQL suite is opt-in and **NOT_RUN by author** (no isolated DB
opt-in). A5 must run it on an explicitly authorized disposable test DB:

```sh
PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_assignee_recommendations.py -v
DALA_ASSIGNEE_POSTGRES_ACCEPTANCE=1 DALA_TEST_DATABASE_URL='<isolated test DB>' \
  PYTHONPATH=backend python -m unittest discover -s backend/tests/integration \
  -p test_assignee_recommendations_postgres.py -v
```

The actual-PG suite covers real eligibility/current master scope, inactive
historical actors remaining locked, workload states across visible/hidden
sections, human history attribution/window/zero/unknown, stable ranking and
bounds, state snapshots proving no business/auth changes, concurrent candidate
state/membership changes, snapshot insert/change races, expiry after order lock
wait, and actual locks blocking revocation until response capture. Owner-role
fixtures do not verify deployment least privilege. Sole reviewer is the assigned
session/security reviewer; A5 performs mount, aggregate and exact-SHA checks.
