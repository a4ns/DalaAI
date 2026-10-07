# Durable assessment jobs candidate

Base: `c2fbe6a5ce5dd584a6edbdb8e3abf3501e7d1bfd`. A5 alone integrates.

## Scope and host interface

Apply additive `011_durable_job_leases.sql` after the accepted schema migrations.
No dependency, public route, model provider, configuration, or startup changes.
The explicit host interface is:

```python
from app.jobs import AssessmentWorker, WorkerPolicy
worker = AssessmentWorker(connect, domain_clock=domain_clock,
                          real_clock=real_clock, policy=WorkerPolicy())
results = worker.run_batch(limit=20)
```

`connect` must return a fresh, idle, autocommit psycopg3 connection. Both clocks
expose `now()` just like `CommandService`; use a real wall clock for leases and
retries. Import/construction do no work. The host remains responsible for invoking
and supervising the runner. A result state of `done` means an assessment committed,
not that the order was accepted or that any employee was notified.

`claim_one()` and `complete(claim)` are exposed for controlled crash/recovery
checks. A committed claim remains durable on process death. Another process can
claim after the real lease deadline, incrementing attempts and replacing a fresh
UUID token. Expired or replaced claimants cannot publish results or schedule retry.
The default retry policy is bounded exponential real-time delay (2 seconds to
5 minutes), 30-second leases, and 5 attempts. Exhausted crashes become `failed`;
there is no automatic reset that could loop indefinitely.

## Transaction boundary and safety

Claim locks only one eligible job with `SKIP LOCKED`, commits, and closes the
connection. The result transaction reads immutable submission identity, locks the
order, loads current reference/photo evidence using the existing human-close
loader, then locks and checks the job. No job lock is held while waiting for an
order. Failure transactions lock only the job. Clocks are refreshed after lock
waits and again before completion.

The existing short, deterministic `assess_rules` executes under the current-order
and evidence locks. No network call, LLM or image fetch occurs there. A future
model provider needs a separately reviewed compute-outside-transaction flow plus
current mandatory-gate re-evaluation; this is deliberately not a provider seam.

Assessment, current-only aggregate version increment, accepted
`order.assessment_recorded` event, and job completion commit together. Rollback
or a failed final lease fence removes all provisional effects. Repeated delivery
of a claim cannot append twice. UUID5 assessment and event identities are stable
per job. Reassigned, superseded, reworked, closed or cancelled attempts get only a
historical stale assessment: no current version/status/event/delivery-job change.
No successful assessment auto-closes or returns an order.

Stored output is always `rules_fallback`, `provider_not_configured`, null model,
null model version and null score. Rules evaluate mandatory completeness/evidence,
not repair quality or photo semantics. Trusted bound metadata is loaded at completion, not copied from the claim, client
request or an earlier assessment. By default a persisted true `file_valid` is
downgraded to unknown: an earlier upload check is not evidence of current private
blob availability/integrity. Known false remains false; missing and unknown are
not converted to verified. Reasons explicitly describe unavailable verification.

The trusted host may inject `references_factory(repo, principal, real_now, order)`
matching PostgresReferences. Only its server-owned closure_evidence(submission)
result is consumed. A5 owns the shared verifier seam with human CLOSE. The factory
must be bounded/local and must respect order→sorted evidence→job lock order; no
network calls belong inside this transaction. The explicit verifier test uses
synthetic fixture evidence only. Actual blob availability/hash/decode integration
remains a separate required gate, not covered by this database worker.

The migration adds a nullable lease token and partial runnable index, preserving
pending/retry/done/failed rows. Legacy running rows with an old lease wait for its
expiry; legacy running rows lacking any lease can be reclaimed immediately.
Rollback of application code does not require dropping the additive column.
Do not roll back durable job/assessment data or reset attempts to zero.

## Mandatory acceptance commands

From repository root, using the accepted pinned environment:

```sh
make check
DALA_TEST_DATABASE_URL=<explicit-disposable-db> scripts/run_jobs_postgres_tests.sh
```

The second command enforces exactly 18 PostgreSQL tests, zero skips, successful
execution, and applies the full migration set to isolated fresh schemas. It covers
crash/reclaim, old-token completion and failure fencing, duplicate runners,
reassignment, same-assignment rework/resubmission, prior human close, current
invalidated evidence, incomplete results, rollback after provisional writes,
concurrent atomic visibility, order-lock waits, retry timing and exhaustion.
An absent DSN is an error in the mandatory runner, not a green skip.

Additional integration gate: replay the independent review's observed lock-wait
and event-feed interoperability probes on this exact source. Apply migration011
both to a clean DB and a preexisting seeded baseline containing pending, retry,
running (with/without lease), and done jobs. Validate worker execution with a
separate non-owner login granted only the needed table/column operations. The
baseline command application role alone lacks INSERT on ai_assessments and UPDATE
on ai_jobs: do not silently broaden auth or photo-validation permissions.

Minimum worker profile: SELECT on ai_jobs, orders, submissions, material_writeoffs,
photos, work_codes, materials, order_events; UPDATE on ai_jobs worker state/attempt/
lease/retry/error columns and orders version/updated_at; INSERT on ai_assessments
and order_events. PostgreSQL row locking also needs an UPDATE column grant on
work_codes/materials/photos: use the established restricted immutable-key/binding
column profile, never file_valid or auth secrets. Schema/migration ownership stays
separate. This candidate does not create credentials or grant any privileges.

## Evidence and explicit limits

Local `make check` and worker unit/contract tests are recorded under
`evidence/jobs/`. PostgreSQL syntax parsing is a static check only. No PostgreSQL
server/DSN exists in the author environment: runtime migration/concurrency/role
acceptance is NOT_RUN until A5 runs the mandatory gate at the integrated exact SHA.
No real notification, provider/model call, phone, live photo upload, hosted runtime
or Android evidence is claimed. The delivery_jobs consumer and deadline scheduler
reconciliation are outside this AI-only candidate.
