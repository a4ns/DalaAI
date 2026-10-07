Integration update (2026-10-07): optional source is assembled behind explicit
`DALA_DEMO_CLOCK_ENABLED` and one persisted instance. Original proposal and local
evidence below are retained as history. New mandatory gates cover6 durable,
8 three-login bootstrap and4 actual API/worker cases plus an optional Compose
profile. Execution results belong to the final integration SHA, not this text.

# A-DEMO-CLOCK-001: shared synthetic business-time candidate

PROPOSED / UNMOUNTED. Base: 5d737eef19e1a7f38e07950f9185a953a2f94e47 (backend 6c2b1c9 + frontend). A5 reserved `backend/db/proposals/013_demo_business_clock.sql`; it is optional and outside core bootstrap. Integration owner A5/root, only after the core cycle. Reviewer: session_security.

## Delivered implementation

- `DemoBusinessClock`: preserved in-memory test harness, explicitly single-process only
- `PostgresDemoBusinessClock`: one configured instance row, no process-local mapping cache, shared API/worker reads; control state and append-only audit commit in one transaction
- `build_domain_clock(settings, connect=..., instance_id=...)`: returns the existing real `SystemRealClock` immediately when disabled, without DB access or instance parsing. Enabled assembly requires explicit `DemoClockSettings(enabled=True, mode="demo", isolated_demo=True)` and a previously initialized shared instance UUID
- No automatic setup, migration application, row initialization, account creation, credential generation, environment parsing or route mounting
- Integer scale 0–60; zero pauses; scale 1 resumes forward normal-speed time. Advance is 1–3600 business seconds; horizon is seven business days. No absolute-time setter, rewind or reset
- Commands require persisted instance UUID + expected version. Repeated/stale advance returns 409 without another effect. A restarted process rereads the same mapping/version; an unrelated instance cannot be addressed by body fields
- Responses expose one mapping revision and matching real/domain samples, anchors, domain limit, scale, `mode: synthetic_demo`, Russian synthetic-time label, storage type and `reset_supported: false`
- Missing/corrupt row, pre-anchor wall time, horizon exhaustion or DB failure fails closed. Never silently fall back to wall time after enabling demo mode

## Proposed HTTP/control seam

Routes exist only in the optional router; `main.py` is unchanged. Disabled harness router has no routes. GET/POST `/api/v1/demo/clock` require a current active session, an explicitly configured existing-role set **and** exact existing-user allowlist. Both are mandatory trusted configuration; neither comes from the request. Example: explicitly authorize one synthetic master ID with `{Role.MASTER}`; no promotion or unprovisioned admin is needed. Other masters still fail. Existing admin accounts are also usable when explicitly authorized.

POST additionally requires exact HTTPS Origin and session-bound CSRF. Auth is checked before parsing and refreshed after clock state-row lock waits. The existing auth scope holds current session/principal rows through the operation. Request body: JSON only, ≤1024 bytes, real async deadline five seconds (bounded configurable ≤10); no duplicate fields/headers/cookies, actor claims, query parameters, floats or booleans-as-integers. Non-same-origin Fetch Metadata is rejected. Responses are private/no-store and contain no credential, CSRF value or raw DB error.

```json
{"instance_id":"00000000-0000-0000-0000-000000000001","expected_version":0,"action":"set_scale","scale":30}
```

For stepping, use `action: advance` and `seconds: 60` instead of scale. Unknown reset actions and `/demo/reset` are rejected. If the result is lost/unconfirmed, GET the snapshot; do not automatically generate a new version and retry advance. CAS avoids duplicate effects but there is no durable replay of the original HTTP response. The audit row persists the control, operator and real recorded time.

## Shared-store and locking contract

013 creates only `demo_clock_state`, `demo_clock_controls` and their guards. Identity/horizon are immutable; state version must increase by one without rewinding. A deferred trigger requires a matching bounded/continuous audit entry for every state update. Audit rows cannot be updated/deleted. No grants or seeds are executed by this package.

Reads use one PostgreSQL MVCC row plus `clock_timestamp()` sampled within that SELECT. API and worker need the same database/schema/instance ID. Read-only workers only need SELECT on state and do not take/write clock row locks. A concurrent control can make a returned snapshot immediately old; the revision is explicit and each new read/tick rereads. No indefinite mapping cache is permitted. Snapshot readers are not a global stop-the-world barrier.

Controls lock the configured row FOR UPDATE, refresh current operator authorization, then read real DB time after the wait, apply CAS and append audit in the same transaction. Outer auth-row SHARE locks are acquired first and remain held; the authorization callback must only reuse those locked stores. It must not acquire unrelated order/job locks. Clock reads inside order/worker operations do not take state-row locks, avoiding the reverse auth/order→clock locking cycle. Lock timeout is one real second, statement timeout three seconds.

Real DB time must be synchronized. The durable mapper rejects samples before the persisted real anchor. It does not persist a high-water timestamp on every read, so a small DB clock regression within an anchor interval can regress business reads. The in-memory harness has an additional per-owner high-water check. Do not claim cross-process monotonic-time proof; operator time synchronization and runtime clock-regression policy remain a gate.

Operator setup after approval: apply 013 only to the verified isolated synthetic schema; initialize exactly one explicit UUID row at version 0, scale 1, real/domain/start all chosen from one DB clock sample and limit=start+168 hours. This is operator-only; the application role receives no INSERT/DELETE/TRUNCATE on state. Worker/readers: SELECT state. Control service: SELECT state/audit, UPDATE only version/real_anchor/domain_anchor/scale, INSERT controls; no audit mutation, identity, auth, scope or budget grants. Validate exact restricted permissions and guards before mounting. No role/credential is created here.

## Injection map: frozen services untouched

| Existing port | Future binding | Must remain real |
|---|---|---|
| `persistence.service.CommandService(domain_clock=...)` | shared business `.now()` | session/TTL, receipt/recorded_at, outbox retry clocks |
| `discovery.service.DiscoveryService(domain_clock=...)` | shared business `.now()` once/list | authentication clock |
| `scheduler.clocks.DomainClock.domain_now(real_now)` | immutable capture for a single tick | scheduler real clock |
| `jobs.worker.AssessmentWorker` / `jobs.provider_worker.ProviderAssessmentWorker` | domain `.now()` only | leases, retries, provider duration, spend/approval clocks |
| `notify.reconcile.DeadlineReconciler` / `notify.worker.DeliveryWorker` | domain `.now()` for thresholds/relevance | lease/backoff, dispatch observations, subscription/session expiry |
| `main.create_app` / `worker_runtime.build_runtime` | both use `build_domain_clock` with same explicit instance | sessions/photos/events/security/monotonic admission retain real clocks |

No global datetime/time monkeypatch. 60× with a one-second real tick spans one business minute; verify emergency threshold latency and bounded catch-up on the actual runtime. The snapshot is a coherent mapping/time sample, not a frozen security clock. Freeze/acceleration must not extend auth, staged photo, leases, budget approvals or external retry windows.

## Safe separate design for a future full data-reset button

No data-reset code is implemented. Reset must be a separately authorized operator workflow with exact instance, seed version/counts, active work and expected generation preview, followed by explicit confirmation.

1. Stop admission and quiesce/fence workers for that isolated instance; stop external sends/provider calls during preparation
2. Save and verify a recoverable manifest/snapshot of its synthetic business data and blobs. Retain old receipts/audit and test restoration
3. Prepare a fresh business-data generation in an approved separate namespace. Exclude identities, auth tables, roles/scopes, credentials, and real OpenAI spend/approval/budget ledgers; never reset those
4. After generation-aware design is accepted, atomically switch matching business-data/clock generation; reject stale jobs/operation IDs and have clients explicitly reload without silently discarding drafts
5. Retain previous generation read-only for recovery. No irreversible deletion. If identity/budget data cannot be separated safely in current schema, use an operator maintenance snapshot/restore workflow rather than a one-click reset

This design is not implemented, and clock-control approval does not authorize it.

## Reproduction and evidence

With existing locked development dependencies:

```sh
PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_demo_clock*.py' -v
python -m compileall -q backend/app/demo_clock backend/tests/test_demo_clock*.py
```

PASS: 32 local synthetic/ASGI/pure-store-contract tests, including concurrent single-owner CAS, scale/pause/advance continuity, emergency threshold crossing, real session/photo TTL, explicit existing-master authorization, CSRF/origin, post-wait auth refresh, bounded/stalled ingress, replay/instance fence, default wall assembly, persisted row mapping validation.

REAL PostgreSQL tests are included: restart mapping/replay, two spawned processes/one CAS winner, read-only worker capture, state+audit rollback, DB immutability guards, denied authorization. Run only with an explicit disposable test DSN and `DALA_DEMO_CLOCK_TEST_DISPOSABLE=true`; they create/drop only uniquely named synthetic test schemas. Current result is **NOT_RUN**, not a PG pass: no local PostgreSQL binary or approved disposable DSN is present. The unittest class reports one skip covering those six cases.

NOT_RUN: applying 013, real/restricted PostgreSQL checks, process-level tests above, mounted API/worker assembly, actual clock skew/transaction interactions, lease/backoff/OpenAI budget runtime regression, full aggregate, hosted HTTPS, UI/real phones, external delivery. No live DB/provider/deployment action. Existing Starlette/httpx deprecation warning only; no dependency change.
