# Minimal schema proposal and acceptance gates

PROPOSAL: A6 authors; A0/human A approves migration; B0/C0 approve affected contract. No database has been changed. PostgreSQL is unavailable in this preparation runtime. SQL is a reviewable candidate, not an applied migration. Do not rename this into a production migration without the gates below.

## Scope and storage mapping

`001_vertical_slice.sql` supplies 18 tables: directory/scope data, opaque sessions, orders, immutable submissions/material rows/assessments/reviews/events, staged photos, receipts, AI jobs and delivery jobs. This is the minimum shared persistence boundary, not analytics, reporting or seed implementation. No historical enterprise data is included. UUIDs are application generated. PostgreSQL identity generates the order number; HTTP renders it as a deterministic display string such as DEMO-2026-0001. Number gaps are acceptable.

- HTTP Principal.user_id maps to employees.id; active and section memberships are checked on every protected request
- HTTP assignment.executor_id and brigade_id map to order columns; brigade membership and section/specialty eligibility are service checks
- `current_submission_id` references the same order AND assignment revision; old attempts remain immutable after reassignment
- Each staged photo stores a verified non-null section_id, including before-photos without an order. Attached photos use a composite order/section foreign key; service checks ownership and destination section before binding. Photo references in JSON are derived from bound rows; an after-photo belongs to exactly one submission and assignment revision
- `domain_now` and `is_overdue` are computed, not saved booleans that can go stale
- Domain times: issued_at, due_at, submitted_at, occurred_at, notification due_at, order updated_at. Real times: auth/photo expiry, job lease/retry/sent timestamps, event recorded_at, receipt times, AI latency
- Missing-evidence evaluation, valid transitions, role/assignment constraints and current delivery eligibility are enforced by the service under a locked/CAS aggregate. DDL alone cannot prove them
- Numeric material quantities are rejected before insert if they exceed three decimal places; PostgreSQL numeric rounding is not input validation
- Unreviewed result corrections create a new approved workflow decision later; this slice only permits a new submission after human rework, preserving one human review per immutable attempt

## Transaction sequence to implement and test

1. Authenticate active principal, check current object/scope authorization and CSRF/Origin
2. Begin a short transaction. Lock the order before mutable authorization/state checks (except new create); recheck current assignment and section permissions
3. Reserve actor+operation_id with canonical hash using INSERT ON CONFLICT DO NOTHING. A competing insert waits for commit/rollback. If an existing committed receipt matches the hash, return its saved status/body after current authorization. Different hash is OPERATION_ID_REUSED
4. For a new command, lock/CAS the order at expected_version. Create/attach validated rows, increment order version once, append ordered events, enqueue unique jobs, finalize the receipt, and commit
5. Roll back the entire transaction on validation/conflict/storage errors. Do not send push or call AI inside the transaction. If retry finds a committed receipt, do not rerun old expected_version or transition checks
6. Lock ordering must be consistent across commands; proposed order lock → receipt reservation prevents same-order deadlocks, but create commands reserve first because no order exists. Same actor reusing one operation ID across different orders must be treated as a conflict, never a cross-resource replay
7. Before a network send, workers recheck revision/status/recipient; external provider timeout may mean sent. Persist/retry with the same provider idempotency key where supported. Do not promise exactly-once network delivery

## Acceptance before promotion

A0/A5 select the actual PostgreSQL version and migration framework from the approved scaffold. Apply the candidate on a fresh isolated DB, then on the synthetic seeded DB; capture exact source hashes, versions and commands. Do not use a shared demo DB for concurrent acceptance.

Required executed tests:

- Create → accept → start → incomplete submission → blocked close → human rework → start → complete submission → close
- Foreign-section/assignment access including photos, historical attempts and receipt replay after reassignment
- Two identical concurrent operation IDs: one effect, one successful replay; altered payload: conflict; same UUID used against a different resource: conflict
- Two distinct operation IDs at the same expected_version: exactly one winner and one version conflict
- Fault injection between each write: no order/event/job/receipt partial commit; empty receipt commit rejected
- Submit generates done and ai_review events in one transaction with one version; sequence remains ordered; no committed standalone done state
- Two masters cannot both close/rework one attempt; missing evidence is checked again under lock
- Stale AI completion stores historical assessment but cannot change active attempt/order or send current-result notification
- Scheduler restart/expired worker lease does not create duplicate logical jobs; cancellation/reassignment invalidates obsolete deliveries
- Wrong-section attachment rejected even if uploader has both section scopes; missing stage section rejected; after-stage section must match DB-loaded order
- Foreign/expired stage rejected; failed create leaves recoverable owned stage; attached photo cannot be garbage collected by staged cleanup
- Append-only UPDATE/DELETE rejected using the real non-owner app DB role; session/secret values excluded from logs
- Migration application on clean and seeded DB; forward recovery preserves audit/receipts

No runtime test above is marked passed. The initial bootstrap has no prior application schema to upgrade; later changes must be additive-first, deploy-compatible, then backfill/verify, then remove obsolete columns in a separate accepted release. For a failed data-bearing release, recover forward or use the previous compatible application. Do not drop tables, clear audit or run demo reset as rollback.
