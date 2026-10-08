# Grounded AI shift/history reports, version 1

Base: `064a7a3785a95d61d7150e7785ff17db892bc110`.
Scope: case 1 §§6.5, 7, 8, 11. This is an additive, explicit-request narrative
layer over the existing protected C111 capture. Existing C111/C5 outputs,
closures, human decisions and assessments are unchanged.

## HTTP contract

`POST /api/v1/reports/ai-summary`, operation ID `createGroundedAIReportSummary`.
There is no GET generation endpoint, background generation or polling-triggered
provider call. The frontend invokes this route only on an explicit master action.

- Existing `__Host-naryadai_session` cookie, exact configured Origin and
  `X-CSRF-Token` are required. Only a current active master with current sections
  is allowed. Manager, executor and admin roles do not acquire report generation.
- Content-Type is application/json. Body cap is 2,048 bytes and body-read timeout is five real seconds. Query parameters and
  unknown/duplicate JSON fields are rejected.
- Exactly four fields: `operation_id` (UUID), `start` and `end` (zoned ISO8601),
  `report_kind` (`shift` or `history`). Start is inclusive, end exclusive.
- Shift is at most 24 hours; history is at most 93 days. End cannot exceed the
  authoritative domain clock. Period and scope are checked by C111 again.
- No client role, actor, section, snapshot assertion, free prompt, provider or
  model is accepted. This captures a NEW authorized snapshot; it is not the
  earlier dashboard snapshot even when the requested period is identical.

Example request:

```json
{"operation_id":"2f1b4c19-1691-4466-a721-56f429cb7456","start":"2026-10-07T00:00:00Z","end":"2026-10-08T00:00:00Z","report_kind":"shift"}
```

Success is 200 with private/no-store, Vary:Cookie, nosniff and no-referrer.
Missing model configuration is a successful, clearly labelled factual fallback.

| Field | Contract |
|---|---|
| schema_version | `ai-report-summary/1` |
| operation_id, report_kind | Canonical request values |
| mode | `openai`, `recorded_fixture`, `deterministic_fallback` |
| label | Russian explanation of the actual execution mode |
| summary | Russian text rendered only from referenced server facts |
| highlights | At most 5 `{fact_id,text,source_table,source_ids,equipment_id}` objects |
| source_table | `orders`, `submissions` or `reviews` |
| source_ids | Scoped C111 UUIDs kept local; never supplied by the model |
| equipment_id | Scoped UUID for a history equipment fact; otherwise null |
| recommendations | At most 3 `{code,text,fact_ids}` objects; every fact ID resolves to a selected highlight |
| provenance | Unmodified C111 provenance, including historical_evidence when present |
| period | C111 `{start,end,display_timezone}` with Asia/Almaty display zone |
| limitations | Required source, advisory and unsupported-input disclosures |
| unavailable_reasons | C111 unavailable reason codes, preserved |
| fallback_reason | null for valid model/fixture selection, otherwise a bounded diagnostic code |
| model | Exact pinned snapshot for valid model/fixture selection; null for fallback |
| generated_at_real | Real UTC timestamp; never demo/domain time |
| advisory | Always true |
| reserved_upper_bound_microusd | Conservative amount reserved for this attempt; integer, not billed cost |
| actual_billed_cost | Always null; this module does not retrieve invoices |

Modes are not interchangeable. `openai` is emitted only for a valid response
from the existing exact OpenAIHTTPTransport. Injected/recorded transports emit
`recorded_fixture`; their label explicitly says they are not live OpenAI.
Fallback labels state that AI analysis was not performed. A stored closure AI
assessment never proves that this report ran a model.

Standard error envelope: `{code,message,request_id,retryable,current_version:null,field_errors:[]}`.
400 invalid query/ambiguous headers, 401 unauthenticated/expired, 403 denied,
408 REQUEST_TIMEOUT for a stalled body, 409 OPERATION_ID_REUSED, 413 oversized body, 415 wrong media type,
422 invalid/excessive period or report limit, 503 unavailable capture/storage.
No raw exception, provider response, key or partial report body is returned.

## Facts and grounding

The model returns only this selection format, not arbitrary narrative:

```json
{"schema_version":"ai-report-selection/1","highlights":["m_closed_orders"],"recommendations":[]}
```

Strict validation rejects unknown or duplicated JSON keys, fact aliases,
recommendation codes, duplicate highlights, excessive arrays, incomplete/refused
responses, unexpected model versions, tools, arbitrary prose or invented numbers.
An action must be supported by every referenced fact and all references must be
selected highlights. For example, review_overdue is unavailable when the actual
current-overdue count is zero. Server templates bind labels, values and cohorts;
checking that a number merely occurs somewhere in input is never used.

C111 supplies the exact 11 metrics, including null/missing values, denominators,
small samples, source IDs and separate human scores. Current awaiting-review and
overdue counts are snapshot-time facts, not historical period flows. Unsupported
composite scores, downtime, brigade history and repeat-fault-7d remain unavailable.

History adds two deterministic, labelled top-five projections over the COMPLETE
scoped capture, with stable count/ID tie ordering:

1. Distinct unplanned orders issued in the requested period, grouped by equipment
2. Distinct unplanned orders with an in-period submission of the same equipment
   and work-code combination; multiple attempts of one order count once

Groups with fewer than two distinct orders are omitted. These are counts of
recorded orders/work-code declarations, not failure diagnoses, causal findings,
physical verification, downtime estimates, forecasts or employee judgements.
Only source-linked narrative and human-review recommendations are emitted.

Outbound content contains allowlisted metric names/statuses/values and temporary
fact aliases. It omits all database/source/entity IDs, employee identities,
comments, descriptions, labels, material names, photos and original filenames.
Synthetic status and unavailable-photo/human-decision disclosures are retained
in the returned report. No historical photo metadata becomes verified imagery.

## Idempotency, real-time authorization and budgets

Every C111 auth check is bound to the initial current principal through a small
session proxy. This prevents a capture under a changed scope being returned when
the old scope later reappears. Current session/role/sections/CSRF are checked before
attempt lookup and immediately before provider egress, including after reservation.
The complete response is serialized inside a final short current-auth transaction,
then expiry/scope is checked again. C111 capture and every auth transaction end
BEFORE the provider call. No database locks span network I/O.

The existing shared SqliteBudgetLedger and `openai_demo_budget()` are required:
$50 total, $10 for request starts before 2026-10-08 04:00 UTC, existing rate and
concurrency limits, one conservative $0.42 upper-bound reservation per attempt.
These are the same reservations used by closure/photo processing, not a new budget.
Existing reserve/finish/counters and accounting tables are not modified.

A5 approved the single additive table `ai_report_attempt_v1` in the SAME ledger
file. It stores only canonical actor+operation SHA-256, an immutable binding SHA-256,
and real claim time. Binding includes approval/project/instance/purpose/policy,
settings, exact normalized period/kind and current principal scope. A short atomic
BEGIN IMMEDIATE claim commits before reserve/network. No raw identities, prompts,
facts or responses are persisted by this table. The hard table cap is 4,096 rows.

- Missing key, closure-only policy, invalid/expired policy and initial auth denial
  do not claim a provider attempt; an offline preview does not poison activation
- Once eligible and claimed, an operation is never reclaimed, purged or retried,
  even after crash, timeout, budget denial or an unknown remote outcome
- Same operation/binding returns a fresh authorized deterministic snapshot with
  `operation_already_attempted`; it does NOT replay or pretend to recover earlier
  AI output. Repeating the same operation can never cause another model charge
- Reusing the same actor+operation with changed request/scope/policy/instance
  returns 409. Policy/instance changes cannot create a second eligible key
- Capacity exhaustion is labelled `report_attempt_capacity_exhausted`, no call
- The frontend keeps operation_id/body across unknown outcomes. A new user action
  may create a new operation only with an explicit decision to generate again

There are zero SDK/HTTP retries. Provider timeout is 8 seconds, output cap 400
tokens/32,768 provider bytes, input fact text cap 24,000 bytes, public response cap
1 MiB. C111 retains its separate 93-day/2,000-order/20,000-row/8-MiB capture bounds.
Reservation amounts are never refunded or represented as actual invoices.

Common fallback codes: provider_not_configured, report_purpose_not_approved,
provider_policy_unavailable, provider_policy_expired, operation_already_attempted,
provider_timeout, provider_invalid_response, provider_unavailable,
provider_budget_exhausted, provider_period_budget_exhausted, provider_rate_limited,
provider_concurrency_limited, report_attempt_capacity_exhausted.

## Exact integration seams, owned by A5

No dependency, main.py, runtime, C111/C5, auth, existing ledger or PostgreSQL schema
file is edited by this five-file artifact.

Keyless mount using the existing live report_service:

```python
from app.reports.ai_summary import SummaryService
from app.reports.ai_summary_routes import create_ai_summary_router
app.include_router(create_ai_summary_router(SummaryService(report_service)))
```

This may sit beside existing C111/C5 mounts; it does not replace them. Host may pass
`fallback_reason='report_purpose_not_approved'` without constructing a transport.

Approved shared policy seam (A5 supplies separately):
`build_interactive_demo_policy(..., include_grounded_reports=False)` keeps legacy
closure-only purpose/disclosure by default. Explicit true produces purpose
`closure_text_before_after_images_and_grounded_reports` and its distinct exact
processing disclosure. Common loader accepts only the two exact purpose/disclosure
pairs. The operator must explicitly opt in; never rewrite or silently upgrade an
existing closure-only policy. Reports reject it even though closures still accept it.

After reviewed host configuration, injection is:

```python
adapter = ReportModelAdapter.from_operator_policy(
    settings=openai_demo_settings(), transport=authorized_transport,
    policy=operator_policy, ledger=shared_existing_ledger,
    project_context=existing_demo_project_context,
    runtime_mode='demo', real_clock=existing_real_clock)
service = SummaryService(report_service, adapter=adapter)
```

The factory makes no network calls, reads no keys/environment and does not create a
separate ledger. It requires the unchanged pinned OpenAI settings/budget contract.
The host owns exact existing secret acquisition, same durable ledger mount and
approved outbound access. Production mode cannot activate this demo policy.
Current key absence is not a reason to manufacture a credential or expand access.

## Verification and rollback

Focused command after applying A5's agreed shared-policy seam:

`PYTHONPATH=backend:backend/tests python -m unittest test_ai_summary -v`

Source tests cover fake/recorded response validation, provenance, no raw source
egress, exact cohort projection, missing/forged/expired policy, budget sharing,
night/total/rate/concurrency limits, cross-restart and concurrent attempt fencing,
capacity/unknown crash handling, auth/CSRF/role/scope changes and final expiry.

Actual PostgreSQL gate:
`DALA_AI_SUMMARY_POSTGRES_ACCEPTANCE=1 DALA_TEST_DATABASE_URL=<isolated disposable DSN> PYTHONPATH=backend:backend/tests python -m unittest integration.test_ai_summary_postgres -v`.
It uses fresh random schemas and recorded responses, checking no provider-time PG
locks, final revocation/expiry, unchanged application rows and no retry charging.
Its opt-in is an execution safeguard, not a request for new user permission. A5
can run it within the already authorized isolated test environment.

At author handoff: 27 focused source/HTTP/recorded tests PASS; PostgreSQL gate NOT_RUN (opt-in environment not set), browser
NOT_RUN, live OpenAI NOT_RUN. Passing source tests is not any of those gates.
Rollback removes the mount and these new modules. Leave durable attempts and
budget reservations intact; do not reset/purge them to regain spending headroom.
