# Durable external-delivery dispatcher candidate

Base source: c2fbe6a5ce5dd584a6edbdb8e3abf3501e7d1bfd plus the frozen A3 AI worker
package (only WorkerPolicy is reused). A5 alone integrates. Migration012 is
reserved with A5. This package owns only app/notify, migration012, dispatcher tests,
mandatory gate and this evidence; Telegram/Web Push adapters are separate packages.

## Explicit host interface

```python
from app.notify.worker import DeliveryWorker
worker = DeliveryWorker(connect, adapter=adapter, channel='web_push',
                        domain_clock=domain_clock, real_clock=real_clock)
results = worker.run_batch(limit=20)
```

No configuration, background thread, route mount or provider activates on import.
Both clocks expose now(); connect creates a fresh idle autocommit psycopg connection.
The host must explicitly configure one reviewed provider lane. Web Push is the
primary planned channel; Telegram stays behind its explicit feature flag. This
candidate creates no credentials, subscriptions, deployment or live messages.

The shared app/notify/models.py defines DeliveryEnvelope and DeliveryOutcome.
Envelope carries opaque job/order/recipient IDs and bounded scheduling metadata;
it never contains photos, raw work text, employee names, chat IDs or credentials.
The adapter owns private endpoint resolution and a total max_call_seconds timeout.
The worker requires timeout+5 seconds below its real lease, renews before dispatch,
and checks remaining budget immediately before invoking the adapter.

Outcomes: accepted, retryable, permanent_failure, ambiguous; synthetic_recorded is
reserved for an explicit test adapter. accepted requires an opaque provider receipt
and means only API acceptance. Legacy sent_at records that acceptance time; it does
not prove device delivery, notification display, vibration or sound. Retry-after
from an explicit safe provider rejection is honored in full on the real clock.
Timeout/unknown exceptions become ambiguous and are not automatically resent.

## Crash and lock semantics

1. Claim only one due configured-channel job with SKIP LOCKED. Commit and close
   the claim connection before waiting on an order
2. Prepare in a new transaction: order → current recipient/scope → matching job
   token. Recheck current status/assignment/scheduling revision, threshold and
   submission/review cycle using the existing scheduler planner. Refresh real
   time after locks. Commit immutable dispatch intent and renewed lease
3. Call adapter outside every DB transaction, after the final time-budget check
4. In a new job-only transaction, record the observed outcome and update the job
   only for the still-current, unexpired token. Never touch current order state

A crash before committed intent can reclaim its expired lease with a new token.
A crash after intent is conservatively uncertain even when it actually happened
before the socket write: the dispatcher cannot prove whether a provider saw the
request. An expired sending job with intent becomes failed/DELIVERY_OUTCOME_UNKNOWN
and is never automatically resent. Pre-migration sending rows without a token are
also treated as uncertain. This is essential for Telegram and Web Push transports
without a provider-supported idempotency key; stable job UUID is not a send dedupe
guarantee.

Late observed responses remain immutable audit evidence. They do not revive a
cancelled/expired job or current assignment. There is an unavoidable interval after
the final authorized DB check and while an external request is in flight: a
concurrent cancellation/reassignment cannot recall an already sent request. The
result is retained against the old dispatch intent and cannot create new current
jobs/events. Do not promise impossible exactly-once or race-free remote delivery.

A backwards demo-clock jump defers a still-applicable job without consuming an
attempt. Lease/retry/timeout use only real time. Manager escalation is disabled in
this slice. Existing receipt→order→sorted stages→delivery command lock order remains
untouched. The runner consumes existing jobs; a persistent deadline-reconciliation
runner is still a separate integration task, not falsely claimed here.

## Internal migration and compatibility

012 adds nullable delivery_jobs.lease_token, two append-only intent/result tables,
and the explicit synthetic_recorded terminal state. Synthetic outcomes require
SYNTHETIC_NOT_SENT, leave sent_at/provider_receipt empty, and never masquerade as
provider_accepted. Existing queries that invalidate pending/retry/sending still
apply. Existing terminal rows and uniqueness keys are preserved; no backfill or
credential/permission modification occurs.

The accepted OpenAPI DeliveryJob component is an INTERNAL example with no public
operation reference. Its frozen enum is intentionally not edited. Do not expose
synthetic_recorded through a future API using that component without root/consumer
contract review. Current public order/submission/events routes are unchanged. No
existing metrics implementation is present in the accepted backend; future metrics
must exclude synthetic records and keep API acceptance distinct from actual receipt.

Future user-visible in-app sink proposal, not implemented/accepted wire: persist a
recipient-owned notification row atomically with job completion; GET notifications
returns only the authenticated current employee's scoped rows, rechecking order
access; read/seen acknowledgement is a separate authenticated CSRF-protected
operation. One job/recipient unique key prevents duplicate inbox entries. Displayed
or seen states must never be inferred from a row insert or external API response.
Root and consumers must approve that route/receipt/privacy contract before mounting.

## Verification

```sh
make check
DALA_TEST_DATABASE_URL=<disposable-db> scripts/run_delivery_postgres_tests.sh
```

The mandatory runner requires exactly20 real PostgreSQL cases and zero skips.
It covers pre/post-dispatch crashes, stale tokens, scope revocation, reassignment,
same-assignment rework, duplicate attempts, cancellation in flight, atomic outcome
rollback, real retry-after, backwards domain clock, order-lock wait and explicit
synthetic state. All adapters in these tests are fake; passing them would establish
DB behavior, not phone delivery.

A5 must also apply012 to clean and seeded schemas, run with a non-owner worker role,
and rerun exact-SHA integration with the actual approved adapter package. Minimum
additional grants: SELECT/UPDATE relevant delivery_jobs columns; SELECT order,
submission/review/event/employee/scope rows; INSERT/SELECT dispatch intent/results.
Use restricted UPDATE column grants needed for row locks; never grant employee role,
active/session/token or trusted photo flag changes. Migration ownership stays separate.

Local actual results are in evidence/delivery:8 dispatcher unit tests PASS;33
Telegram adapter seam tests PASS using fake transports; aggregate191 tests PASS,
5 opt-in PG classes skipped. Static parser17 SQL statements and migration12 statements
PASS. Real PG/runtime/role/migration application are NOT_RUN here (no server/DSN).
No real Web Push subscription, permission, phone, TLS endpoint delivery or Telegram
message was created by this candidate. Browser permission and real Android receipt
are mandatory later human/device gates. Future adapters must supply separately
reviewed subscription/credential/SSRF/transport safety; this worker does not replace it.
