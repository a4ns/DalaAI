# Deadline reconciliation and bounded notification tick

Additive candidate based on A5 snapshot fffaf2fdd36cab937399ec8507543d326da83442,
plus frozen AI and dispatcher dependencies. Owns only new app/notify/reconcile.py,
app/notify/runner.py, focused tests, mandatory gate and documentation. No migrations,
configuration changes, provider activation, credentials or external sends.

## End-to-end queue generation

CommandService._outbox already inserts an immediate new_order job in the same
transaction as create/reassign, receipt and order events. It uses the configured
channel and current assignment event timestamp, not original issued_at after
reassignment. New PG tests cover both actual command paths. Submit/review already
create submission_ready/review_result jobs; existing dispatcher consumes them.

DeadlineReconciler closes the periodic generation gap using the existing
plan_due_jobs implementation. It queues the existing 30-minute reminder,
10-minute normal/high or 3-minute emergency acceptance escalation, and strictly
post-deadline overdue jobs for current executor/master. Repeat/manager intervals
are not invented; manager escalation is explicitly unavailable in this slice.

One order is locked per short transaction, using SKIP LOCKED so a busy order
returns for a later sweep. Current recipient rows and section memberships are
locked in stable employee-ID order before any delivery insertion. The current
assignment event and retained rework submission identity define threshold anchors
and deadline cycles. The original due_at never changes. Both current revisions
and the existing unique job key fence every insertion.

Known keys include every state, including failed/uncertain/cancelled, so a scan
cannot silently reissue a transport outcome that is unsafe to retry. Concurrent
or restarted reconcilers rely on durable uniqueness. There is no in-memory
last-tick timestamp that can lose overdue crossings. Domain time is refreshed
after locks and drives thresholds; real time drives next_attempt_at only.

scan_once(limit,after_id) returns a bounded page of active order IDs, rechecked
under each order lock. The cursor is optional progress optimization and wraps
when a sweep ends; restart starts over without duplicate durable keys. Newly
created IDs before a current cursor join the next sweep. Busy orders likewise
join a later sweep. This is bounded eventual catch-up, not a measured device
latency or guaranteed <=5-second notification claim.

## A5-owned host integration

```python
from app.notify.reconcile import DeadlineReconciler
from app.notify.worker import DeliveryWorker
from app.notify.runner import NotificationRunner

channel = 'web_push'  # explicit reviewed bootstrap choice, never inferred
reconciler = DeadlineReconciler(connect, channel=channel,
    domain_clock=domain_clock, real_clock=real_clock)
dispatcher = DeliveryWorker(connect, adapter=approved_adapter, channel=channel,
    domain_clock=domain_clock, real_clock=real_clock)
runner = NotificationRunner(reconciler=reconciler, dispatcher=dispatcher)
result = runner.tick(reconcile_limit=100, dispatch_limit=20)
```

The runner reconciles before consuming jobs, checks matching lanes, and performs
no work at construction/import. It owns no daemon threads, environment/secrets or
sleep policy. A5 owns the later ops/demo/worker.py process supervisor and actual
provider/recipient bootstrap. Errors propagate; a failed reconciliation does not
produce a false healthy dispatch tick. Every prior order transaction remains
durable when a later batch step fails.

IMPORTANT: the accepted A5 app factory still passed delivery_channel='synthetic'
at author inspection. A5 must intentionally configure CommandService and runner
with the same reviewed channel. Switching the worker alone to web_push would
leave immediate jobs in a different lane. Existing synthetic jobs must not be
silently relabelled or sent as real messages. Bootstrap/config/data policy belongs
to A5/root; this package does not activate external delivery.

Separate worker-role grants are required. The HTTP startup validator rejects
extra worker writes; do not broaden the web login to evade that check. Reconciler
needs SELECT orders/events/current employees/memberships/delivery jobs, restricted
UPDATE columns required by row locks, and INSERT delivery_jobs. No auth-secret or
photo-validation writes are needed. Current immutable-key guards remain enabled.

Known preexisting command nuance flagged to A5: change_priority increments
scheduling_revision and cancels a still-pending old new_order job, while _outbox
only inserts new assignment notices on create/reassign. This package does not
invent replacement-new-notice semantics during a threshold scan. A5/root should
explicitly preserve/reschedule an unprocessed assignment notice on priority
change if that behavior is required. Plain issue/reassign and deadline paths
have actual queue-generation code; the nuance is not hidden as a passed gate.

## Reproduction and evidence

- Local focused unit tests:6 PASS
- Full current snapshot aggregate with existing pinned psycopg/argon2 dependency
  snapshot:227 tests PASS,9 opt-in PostgreSQL classes skipped
- Initial aggregate without psycopg failed dependency imports; that raw result is
  retained. No source fix was concealed as a passing environment
- PostgreSQL static parser:6 new SELECT statements PASS, no new migration
- Mandatory14-case real PostgreSQL suite:NOT_RUN (no local server/DSN)

```sh
make check
DALA_TEST_DATABASE_URL=<explicit-disposable-db> scripts/run_reconcile_postgres_tests.sh
```

The second script requires exactly14 tests, zero skips and successful execution.
It covers atomic immediate issue/reassignment generation, precise threshold
crossings, current assignment timestamps, priority revisions, duplicate/restart/
concurrent reconciliation, same-assignment rework, recipient revocation, paging,
busy order locks, clock separation, inactive orders and no unsafe job replay.
A5 must run it at the exact integrated SHA with all earlier worker gates and the
separate non-owner role. Android/Web Push permission, subscription binding,
provider acceptance and actual phone display remain distinct gates.

Rollback stops host tick invocation; no data reset, receipt deletion, deadline
rewrite, migration reversal or job-state clearing is needed.
