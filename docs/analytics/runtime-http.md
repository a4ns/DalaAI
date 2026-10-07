# C111 protected runtime analytics and reports

## Integration status and immutable dependencies

This package adds a mountable bridge, not a `main.py` mount or deployment. A5
owns application integration and actual PostgreSQL acceptance. It depends on:

- C108 `711e2fbd69598d06f43da9ff47de60d2c569634c`: exactly
  `backend/app/analytics/c3_types.py` and `c3_facts.py`
- C109 `e999232014be8b16717058c6d9b70b41dec75c89`: exactly
  `backend/app/reports/c4_render.py`

No fallback DTO/renderer, fixture loader, provider call, schema migration,
credential file, package pin, shared auth change or main entry-point change is
part of this package. The five-file scope deliberately cannot install the
missing immutable dependency source. A source-only checkout without these
accepted modules fails import; it does not silently skip or simulate reports.

A0 approved this mount seam in issue #2 comment
[6047684615](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6047684615).

## A5 mount signature

Reuse the existing `SessionService` instance and the deployment's domain clock:

```python
from app.analytics.c3_repository import RuntimeReportService
from app.reports.c4_routes import create_c_runtime_router

app.include_router(create_c_runtime_router(RuntimeReportService(
    session_service,
    domain_clock=clock,
    synthetic=True,  # ONLY when the selected deployment dataset is synthetic.
)))
```

`synthetic` is required, strictly boolean, server configuration. Set it to match
the selected dataset; never infer it from the caller, presence of authentication,
or this test package. There is no request override. Provenance uses a generated,
nonsecret capture reference, domain snapshot time, real capture-start time,
server-authored scope description, `consistent_snapshot` and
`history_complete=True` only after successful complete extraction/validation.
HTML visibly labels synthetic data. The source reference identifies this capture,
not a DB checksum, immutable external export or evidence of deployment readiness.

The current reviewed `SessionService` exposes no public transaction-scoped auth
API. C111 intentionally depends on its existing private `_connection()` and
`_auth(db, handle)` seams and its real security `clock`. These remain owned by A2;
a shared seam change requires A2/A5 coordination. Do not replace them with client
claims, a bearer-token fallback, a dummy principal or `me()` on another connection.
The synchronous service accepts a server-owned `project(facts, format, historical_evidence)` callback
so rendering and response-size validation finish before its final auth check.
This callback is never populated from HTTP content.

## Proposed HTTP surface

The accepted core OpenAPI file is unchanged; A0/A5 must document/accept this
additive runtime surface when mounting. All routes are GET only:

| Route | Output |
|---|---|
| `/api/v1/analytics/shift` | C3 facts JSON, including authorized order facts |
| `/api/v1/reports/shift` | C4 shift JSON, or inert Russian HTML |
| `/api/v1/reports/orders/{order_id}` | C4 one-order JSON, or inert Russian HTML |

Every route requires `start` and `end`: aware ISO-8601 timestamps with `T`, UTC
`Z` or an explicit offset. Period is half-open `[start,end)` with
`start < end <= server domain_as_of` and at most 93 days by default. Snapshot
stocks use `domain_as_of`; this is not historical state reconstruction at `end`.
`format=json` is the default. Only report routes accept `format=html`.

Unknown/repeated parameters, client scope/role/actor/clock/provenance fields,
query session handles, unsupported formats and unbounded periods are rejected.
The only credential transport is the existing `__Host-naryadai_session` cookie,
parsed by the shared `_session()` helper. Missing/duplicate cookies fail closed.
No additional bearer, header or URL authentication mechanism is introduced.

This first mount allows only an active authenticated **master** with at least
one current authorized section. Executor, manager and admin receive 403; the
broader shared read policy is not silently interpreted as report authorization.
Only currently permitted sections enter the parent SQL query. All related rows
are read through those selected order/submission IDs. A single order is selected
by both its ID and the current allowed sections; foreign and missing IDs have
the same generic 404, with no foreign-object existence lookup.

Every response produced by the bridge uses `private, no-store`, `Vary: Cookie`,
`nosniff` and `no-referrer`. HTML also uses an HTTP CSP with no network/script
resources, no framing, no forms/base URLs, and sandboxing. Source values are
escaped by the existing C4 renderer; JSON remains literal data, not HTML-safe
markup. No physical photos, storage keys or resource URLs are loaded/rendered.
Host TLS, cookie issuance, readiness middleware and safe browser handling remain
A5/shared responsibilities.

## Consistency, freshness and bounds

1. Require a fresh autocommit connection with PostgreSQL transaction status IDLE.
2. Begin one transaction and set **REPEATABLE READ before any auth/data query**.
   Set local 10-second statement/idle-in-transaction and 3-second lock timeouts.
3. Existing auth code locks session, employee and membership rows with `FOR SHARE`
   in the shared order. Only the DB determines active status, identity, role and
   current scope. These locks remain held through rendering.
4. Parent orders are scoped in SQL and also `FOR SHARE` locked. A concurrently
   changed parent or auth row after the RR snapshot causes a serialization
   failure rather than stale authorization. Membership additions omitted by an
   established snapshot only narrow the report; held membership rows cannot be
   deleted/changed before report completion.
5. Before transferring table values, bounded SQL aggregate preflight checks
   count and `octet_length(row_to_json(row)::text)` over at most cap+1 selected
   rows. Only sizes/counts return from this preflight. Then fetch the same rows
   from the same snapshot. After each preflight and fetch, reauthenticate using
   the real clock; elapsed lock waits cannot extend session lifetime.
6. Load **all** persisted attempts, reviews, assessments and declared materials
   for the selected parents, including pre-period history. Selection by issuance
   period alone would corrupt independent close/rework/stock cohorts. Related
   material references must be complete. Before-photo references must match the
   selected parent section; live after-photo manifests must exactly match attached
   rows for the same order/submission/revision/section. The narrowly recognized
   canonical historical exception below permits missing metadata-only references,
   with explicit unavailable counts. Contradictory attached rows still fail. No
   physical blob validity or safety claim follows from either path.
7. Validate/project via immutable C3; incomplete/corrupt data or unavailable
   totals fail the entire request. Render via immutable C4, enforce output byte
   bound, reauthenticate again, then leave the transaction. No partial body is
   streamed. No cache of captured principals or authority survives the request.

This is a **logically read-only operation**, not `SET TRANSACTION READ ONLY`:
PostgreSQL READ ONLY forbids the existing `FOR SHARE` auth locks. C111 executes
only SELECT and local transaction settings; it does not write business rows,
sessions, events, deliveries, seed data or grants. It can temporarily block writers
through its locks. The existing runtime role/connection/prerequisite checks remain
necessary. It never retries a serialization conflict at a weaker isolation level.

The default and hard maximum period are 93 days, accepted in
[A0 comment 6048212078](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6048212078).
An exact 93-day window is allowed; an additional second fails. This supports the
full canonical history without introducing an unlimited range or a pattern-detection
claim. All existing scope, row, byte, auth and completeness safeguards remain.

Default limits: 2,000 orders, 20,000 total rows across all captured tables,
64 authorized sections, 8 MiB SQL-estimated captured data, 128 KiB per selected
row, and 8 MiB serialized response. A5 may supply typed `CaptureLimits` within its
hard ceilings. Counts/bytes include historical rows, photos and dictionary
references, so a narrow period need not fit a large authorized history. There is
no misleading pagination fallback. DB-local size calculation is statement-timeout
bounded; byte limits bound transferred data, not an absolute PostgreSQL CPU budget.

401 means missing/expired/revoked/inactive authentication; 403 unauthorized role
or empty/revoked scope; 404 invisible/missing order; 400 unsupported/repeated
parameter; 422 invalid period/format/ID or capture/output limit exceeded.
Serialization/deadlock/schema/database failures, corrupt/partial captures and
renderer failure return generic retryable 503 + `Retry-After: 1`, without SQL,
DSNs, object IDs or raw exceptions. A cap exceeded is explicitly not empty data.

C3's unsupported metrics and C4's limitations remain visible: no invented
composite rating, industrial efficacy, downtime, event history or AI-job state.
Missing human scores remain null and never become AI scores. A smaller authorized
scope is never labeled whole-enterprise totals.

## Canonical C107 historical evidence exception

A0 accepted this additive JSON/HTML disclosure in
[comment 6048093481](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6048093481).
The reviewed C107 loader `2836cec1c5351544c286e72503ad4b5b7590d847`
intentionally preserves 444 after-photo manifest references in 568 submissions
for 540 historical orders, while importing **zero photo rows or image bytes**.
Treating those immutable historical references as verified live attachments is
wrong; rejecting every historical report also prevents the accepted demo history
from being inspected. This exception recognizes that one source and does not
change shared auth, upload, CLOSE, C3 cohort math or the immutable C4 renderer.

The repository reads bounded creation-event rows through selected parent IDs in
the same snapshot. Recognition requires all of the following together:

- A server-configured synthetic dataset; this flag alone grants no exception
- The exact immutable `order.created` provenance for C107 loader 1.1.0, source
  `8af3897f03aa2f41f0af07ec74ec2c807a4a535a`, history SHA-256
  `7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`,
  exact metadata-only photo policy, disabled historical-actor policy and explicit
  statement that historical completeness is not verified evidence
- The canonical 17-actor mapping checksum
  `56ec343e53e4f44208dfd5d5910e235b4626cda7c89f6b642e195c78945a5a64`.
  Noncanonical remapped actors remain 503 because the stored checksum alone cannot
  reconstruct/verify their mapping. No account credential fields are read
- Canonical C1 UUID5 bindings for order ordinal 1..540, creation event/operation,
  submission attempt and photo descriptor; correct source/runtime numbers,
  section/equipment/brigade/master/executor relationships, closed parent,
  revision 1, contiguous attempts and no before-photo references
- Exact creation-event shape and timestamps, unique complete placeholder sets,
  descriptor owner equal to the canonical stored submitter, uploaded time one
  minute before submission, `artifact_available=false`, and the exact
  `synthetic_metadata_placeholder` kind. Every descriptor must match its stored
  order/submission/revision/manifest. Extra, duplicate or contradictory rows fail

Public hashes and deterministic IDs are not authentication capabilities. This
mapping also relies on the existing immutable, server-authored audit boundary and
A5's runtime prerequisite/grant validation. Clients cannot supply creation-event
metadata through these report routes or the current shared create command.
Copying a marker onto an ordinary live order, changing a pin/descriptor/binding,
omitting a canonical history marker, or merely setting `synthetic=true` fails
closed. Recognized canonical IDs without provenance are not silently relabeled
as live, including planned orders with empty photo manifests. Privileged database
owner forgery is outside the trusted repository model; the public checksum is
not a cryptographic attestation of a compromised database.

For recognized rows, metadata-only missing references are retained verbatim;
C3's historical `complete`/closed facts remain past synthetic narrative. JSON
adds `provenance.historical_evidence`, scoped to exactly the captured order(s):

- `status: synthetic_historical_evidence_unavailable`
- `historical_order_count`, `historical_submission_count`
- `historical_after_photo_reference_count`, `missing_after_photo_row_count`
- `physical_evidence_verified: false`
- `historical_completeness_is_verified_evidence: false`
- `source_commit`, `history_sha256`, `loader_version`, `identity_mapping_sha256`

The field is absent for ordinary live-only captures. Counts cover recognized
historical rows only; missing-row count reconciles to referenced IDs minus validly
bound attached rows. A present row still does not prove available image bytes,
physical validity or successful live CLOSE. Every recognized-history capture also
retains an explicit unavailable reason. Both HTML renderers visibly show counts
and explain that historical completeness proves neither photo verification, AI
execution nor successful live closing. The full C3/C4 data models are unchanged.

Author offline verification additionally projected the exact pinned C1 bytes
through the real C107 `read_history`/`prepare_rows`, deliberately changed runtime
order numbers, and exercised all three JSON endpoints and both HTML formats over
recording transport: 540 historical orders, 568 submissions, 444 unavailable
photo references, zero image rows. The exact 93-day window
`2026-06-30T19:00:00Z` through `2026-10-01T19:00:00Z` includes all 540 closed
orders, independently counted from source reviews. This is source/mock-HTTP integration evidence,
not an actual DB import, browser or live workflow. The focused committed tests
also contain independent loader-shaped fixtures and forged/live regression cases.

## Reproduction and evidence levels

The focused suite uses real `SessionService`, `PostgresSessions`,
`PostgresPrincipals` and `authenticate_session` over a recording mock transport.
It does not invoke login, accept PIN input, use password files or contact a DB.
It checks auth/scope changes and post-wait/post-render expiry, RR ordering,
parent locks, strict inputs, old-history cohorts, lossless materials and nulls,
photo-binding contradictions, row/byte/output overflow, error mapping, no mutation
SQL, current-connection state, no-store and inert HTML. These are mock/source/HTTP
checks, **not actual PostgreSQL locking or deployed runtime evidence**.

For a local temporary source assembly (never commit dependency duplicates):

```sh
ASSEMBLY=$(mktemp -d)
git archive HEAD backend/app backend/db/migrations backend/tests/test_c_runtime_routes.py backend/tests/integration/test_c_runtime_reports_postgres.py | tar -x -C "$ASSEMBLY"
for file in c3_types.py c3_facts.py; do
  git show 711e2fbd69598d06f43da9ff47de60d2c569634c:backend/app/analytics/$file > "$ASSEMBLY/backend/app/analytics/$file"
done
git show e999232014be8b16717058c6d9b70b41dec75c89:backend/app/reports/c4_render.py > "$ASSEMBLY/backend/app/reports/c4_render.py"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ASSEMBLY/backend" python3 -m unittest discover -s "$ASSEMBLY/backend/tests" -p test_c_runtime_routes.py -v
git diff --check
```

Use the existing locked Python dependencies. Initial author verification used
Python 3.12.14, FastAPI 0.141.1, httpx 0.28.1, psycopg/psycopg-binary 3.3.6,
argon2-cffi 25.1.0; no lockfiles changed. Temporary import-path additions only
supplied the pinned missing driver and existing pinned Argon2 packages.
A Starlette warning that httpx-based TestClient is deprecated is not a browser
or actual-HTTP-server check.

Actual-PG acceptance is authored separately at
`backend/tests/integration/test_c_runtime_reports_postgres.py`. It requires BOTH
`DALA_C_RUNTIME_POSTGRES_ACCEPTANCE=1` and `DALA_TEST_DATABASE_URL` for an explicitly
authorized disposable isolated database. Without the gate it reports NOT_RUN.
Never copy a production DSN or print credentials to enable this test. Tests create
and drop only their own random schema and apply the existing accepted migrations.
No actual DB was opened, migrated, seeded or queried during author verification.

After A5 supplies its authorized isolated seam:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend python3 -m unittest discover -s backend/tests/integration -p test_c_runtime_reports_postgres.py -v
```

The actual-PG suite includes a canonical loader-shaped missing-photo report
fixture over actual DB transport, plus full-history reports, current membership/role/active
state/revocation, byte and row limits, concurrent child commits excluded by the
snapshot, order-lock expiry, order-change serialization failure, and revocation
waiting behind held auth locks. It is not proof of production-role least privilege,
HTTP deployment, physical photo integrity, live model quality or Android behavior.
A5 must rerun the exact integrated candidate and record these separate gates.
