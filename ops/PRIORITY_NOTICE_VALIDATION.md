# Priority edit must not erase a safe, unsent assignment notice

Root-approved intent: a generic assignment notice for the same currently assigned
recipient must survive priority editing while the order remains issued/queued.
Accept/reject/reassignment remains an explicit lifecycle boundary. This is a small
separate delta; previously frozen AI/dispatcher/reconciler packages are untouched.

## Integration

A5 confirmed one shared CommandService hook immediately before invalidate_jobs,
only for CHANGE_PRIORITY and while the command's order lock is held. Apply
patches/priority-notice-service.patch to the current integrated service; do not
replace the entire service with the author's older assembly. The new helper is
app/notify/priority_notice.py. No migration or public wire change is required;
it depends on already proposed migration012 dispatch intent/results. The shared
hook is unconditional for priority commands even in synthetic mode: A5 must add
those tables to startup/provision/readiness requirements. Do not let an older
four-migration runtime start successfully and fail later on priority edits.

The helper locks all new_order rows in stable ID order for the current assignment,
recipient and configured channel, across scheduling revisions. Checking only the
latest revision would allow a second priority edit to bypass an older unknown
external outcome. Existing order→sorted stages→delivery lock order is preserved.
No job lock is followed by acquiring an order lock. No provider call occurs.

If existing history is provably unsent or explicitly rejected safely, a new
current-scheduling-revision job is inserted using the existing unique key and
current assignment event due_at. Old rows remain historical and normal command
invalidation cancels their obsolete revisions. The new notice stays due from the
original assignment event; a priority change does not invent a new assignment or
reset deadline/acceptance clocks. Queued orders remain eligible until accepted or
rejected; accepted/in-progress/rejected/final orders do not get this replacement.

A pending claim with a token but no committed dispatch intent is safe to replace:
the old claimant is fenced by normal cancellation and cannot send later. A
committed unfinished intent, observed acceptance or ambiguous response blocks a
replacement. Failed jobs and synthetic-recorded terminal outcomes likewise stay
quarantined rather than resetting failure/attempt history through a priority edit.
Pre-token sending is durably marked failed/DELIVERY_OUTCOME_UNKNOWN before ordinary
revision invalidation, preserving its uncertainty across repeated priority edits.

The replacement carries forward the maximum prior real next_attempt_at and attempt
count. Priority editing cannot bypass an explicit provider Retry-After or reset
the logical notice retry budget. Marking an unsent replacement is internal metadata,
not success or an external acceptance receipt. Command receipt, priority/version,
events, old-job invalidation and new job all commit or roll back together. Same
operation replay returns the existing command receipt without another replacement.
An explicit reassignment starts a new assignment identity and is not a retry of an
old ambiguous request.

This implements no manual retry UI and cannot recall an already in-flight remote
request. API accepted still is not proof of phone delivery. Command and dispatcher
must use the same intentionally configured channel; existing synthetic jobs must
not be relabelled as live jobs. Disabled external lanes should not be run merely to
consume and fail their durable backlog before provider bootstrap is ready.

## Tests and required gate

Local6 focused safety-decision tests PASS; full isolated assembly233 tests PASS,
10 opt-in PostgreSQL classes skipped, with the existing pinned dependency snapshot.
Static PostgreSQL parse5 helper statements PASS. No real PostgreSQL server/DSN is
available locally: all14 authored database regressions are NOT_RUN.

```sh
DALA_TEST_DATABASE_URL=<explicit-disposable-db> scripts/run_priority_notice_postgres_tests.sh
```

The runner requires exactly14 tests and zero skips: pending/queued replacement,
accept/reject suppression, abandoned pre-intent claim fencing, repeated priority
under unresolved/accepted/ambiguous results, Retry-After and attempt carry-forward,
legacy unknown quarantine, receipt replay, rollback atomicity, explicit new
assignment scope and exhausted retry preservation. All adapter responses are fake;
there are no real sends. A5 must run this on the final shared service patch and
re-run the existing command, dispatcher and non-owner role gates.

No credentials, grants, network calls or deployment were performed.
