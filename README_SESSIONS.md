# A2 isolated demo session candidate

Status: local REVIEW CANDIDATE, no remote write/deployment. Proposal.2 remains proposed. A0 owns integration, A6 migrations, A5 dependency locks/runtime. Base main snapshot: `120db25356ec1d3e2ed16306cf9d57f9ca457b6a`; frozen persistence target: `1c43accfe7042321ee47be2da63a4d1d5e9b8e96`. Dependency directories were copied from `/dalaai-a6-persistence` for isolated reproduction; integrate only owned files listed in MANIFEST.json.

## Owned additions

- `backend/app/sessions/{__init__,crypto,limiter,service,http}.py`
- `backend/db/proposals/003_auth_rate_limits.sql` (new additive proposal only; A6 assigns/accepts final migration)
- `backend/tests/test_sessions_{unit,http,postgres}.py`
- `scripts/run_session_tests.sh`, `requirements-sessions-proposal.txt`
- This handoff and local evidence

No edits to frozen core, order, persistence, migration 001/002, wire contract, app/main, root configuration or existing lockfiles. No users, password records or session records were created in a live service. Local tests use synthetic inputs and actual installed Argon2id; PostgreSQL tests await a disposable test DB.

## Integration seam

Use existing `psycopg[binary]==3.3.6`, FastAPI/Starlette/httpx pins. Add proposed exact Argon2 closure through A5. Construct:

    from app.sessions.service import SessionService
    from app.sessions.http import create_router
    service = SessionService(connect, allowed_origin="https://EXACT_DEMO_ORIGIN",
                             demo_enabled=True, real_clock=real_clock)
    app.include_router(create_router(service))

`connect` must create a fresh psycopg connection with autocommit=True. Each operation owns/commits its own short transaction. Reuse an explicitly configured real UTC clock, never accelerated domain time. Login defaults OFF (`demo_enabled=False`); no production PIN authentication fallback is created. Existing health/domain routers remain owned by A5/A6. Application startup must fail if required dependencies/migration are absent; do not fall back to fake sessions.

Routes match proposal.2:
- POST `/api/v1/auth/login`: exact `{employee_code, pin}` JSON, exact HTTPS Origin; optional Sec-Fetch-Site must be same-origin
- GET `/api/v1/me`: current DB principal/scope/on_shift, session-bound CSRF, real absolute expiration
- POST `/api/v1/auth/logout`: cookie plus exact Origin and session-bound X-CSRF-Token; revoke transaction then clear cookie, 204

Login returns `Session` and `__Host-naryadai_session` (Secure, HttpOnly, SameSite=Strict, Path=/, no Domain). No bearer in JSON/URL. The DB stores SHA-256 of the 256-bit opaque handle; CSRF is separately generated 256-bit synchronizer token. All responses including errors use private/no-store. Unknown account, wrong PIN, inactive account and invalid stored hash produce generic 401. Duplicate keys/headers/cookies, malformed Unicode/NUL, fields outside the proposal, forms and login body >4096 bytes are refused. PIN remains a string, 4..64 chars as proposal.2 specifies; no digit-only or silently normalized identity rule is invented.

## Security and concurrency

Argon2id RFC_9106_LOW_MEMORY is the only supported stored profile: version 19, m=65536 KiB, t=3, p=4, salt=16 bytes, hash=32 bytes. Unknown/unsupported/malformed hashes do equivalent known-good dummy work. Normal mismatch uses the actual full verification. Malformed encoded hash/Unicode errors fall back to dummy and never leak library details. Source: official argon2-cffi 25.1.0 API https://argon2-cffi.readthedocs.io/en/25.1.0/api.html

At most TWO hash verifications run concurrently per Python process, across verifier instances. Capacity exhaustion fails fast with generic 503 and Retry-After=1; an already-consumed attempt stays consumed. Budget at least 128 MiB hash memory per worker plus Python/app overhead, and select worker count within actual container memory. No local stress/hardware capacity claim is made.

Durable PostgreSQL rate limits consume account AND transport-source budgets atomically BEFORE hash work. Defaults: 5 account attempts and 30 source attempts per 300 REAL seconds. Successful login never resets counters. Attempt reservation commits before credential/session processing so failed auth or an issuance rollback cannot refund brute-force attempts. Every process must use identical policy/schema. Window clock rewind does not reset counters. Rate state is bounded to 65536 deterministic SHA-256 buckets per dimension (131072 total rows). Conservative collisions may rate-limit unrelated users; this is an explicit availability tradeoff, never extra attempts. No raw account/IP/PIN is retained in limiter storage.

Only ASGI request.client.host defines source. Arbitrary Forwarded/X-Forwarded-For headers are ignored here. The deployment MUST configure the server's trusted proxy allowlist correctly (never trust all forwarded peers). Without trusted address rewriting, users behind the reverse proxy share its source budget; that is conservative but may hurt usability. IPv4-mapped IPv6 normalizes to IPv4; IPv6 privacy addresses share a /64 budget. No source => safe 503, no hashing.

Credential verification runs without employee locks. Session issue rechecks the same employee code/hash/active state under lock after hash work. Login with an old cookie rotates identity, revoking the old session transactionally. Lock order: previous/current session FOR UPDATE, employee FOR SHARE, membership rows FOR SHARE. Logout locks session FOR UPDATE first, avoiding a SHARE-to-UPDATE upgrade deadlock. Other routes retain A6 session SHARE before employee/membership SHARE. Recheck real expiry after blocking reads. Session TTL defaults to 8 real hours, bounded configuration 1..86400 seconds, absolute and non-sliding.

Service role minimum delta:
- auth_login_limits: SELECT, INSERT, UPDATE(window_started_at, attempts)
- auth_sessions: SELECT, INSERT, UPDATE(revoked_at); row locks require some UPDATE privilege
- employees/employee_sections: existing SELECT plus A5's narrowly guarded UPDATE privilege for locking
- No table ownership, DDL/TRUNCATE/TRIGGER/security-definer expansion, credential-management rights, table-wide audit UPDATE or DELETE

A5's separate immutable-reference-key proposal may guard IDs/ownership. This candidate never updates identifiers, ownership, employee role/scope/PIN or other reference facts. Production role validation remains NOT_RUN locally. Connections should have operational connect/lock/statement timeouts set by A5. Session retention/cleanup and operational monitoring are not implemented here.

## Reproduction and honest evidence

Install existing A5 pinned requirements plus proposed dependency delta into the test environment. In this isolated task, approved exact pins are already installed under `.test-deps`; use:

    PYTHONPATH=backend:.test-deps python -m unittest discover -s backend/tests -p 'test_sessions_*.py' -v
    python -m compileall -q backend

Local executed result: 28 tests PASS, real PostgreSQL class explicitly NOT_RUN (one class skip covering 16 defined PG cases). These are parser/policy, HTTP stub wiring, and real Argon2 library tests; they do not establish PostgreSQL durability/races. 003 SQL parses with PostgreSQL parser pglast 8.5; parser success is not SQL/PLpgSQL execution. Full runtime versions and output live under evidence/.

Mandatory A5 database gate (never silently skips):

    DALA_TEST_DATABASE_URL='postgresql://SYNTHETIC_TEST_DB_ONLY' \
      PYTHONPATH=.test-deps scripts/run_session_tests.sh

Runner rejects missing DSN/dependencies. Each PG test creates/drops one random `a2_sessions_*` schema, applies frozen 001/002 then proposed 003, and seeds only synthetic accounts. Do not target a production database. Cases cover actual HTTP login/me/logout; hash-only handle persistence; service restart; invalid/inactive/corrupt credentials; account/source limits; real 12-way counter race; no-success-reset; outage fail-closed; scope/role changes; expiry; credential change between verify and issue; session rotation; simultaneous logout; observed lock-wait expiry; bounded schema; clock rewind.

NOT_RUN: all 16 actual PostgreSQL cases, restricted service-role execution, actual HTTPS/browser behavior, frontend cache isolation, full order path, stress tests, devices, deployment. Existing TestClient emits Starlette's httpx deprecation warning; current pinned httpx still executes tests. No independent replacement dependency was added for that warning.

## Review and handoff

Independent reviewer found corrupt Argon2 digest text could throw UnicodeEncodeError or return before dummy work. Fixed before freeze, with real-library regressions. Reviewer also identified hash-concurrency memory risk; the shared two-slot fail-fast cap and recovery/HTTP tests were added. Recheck independent reviewer output and exact hashes before accepting. Archive/package identity is not a tested remote commit; A0/A5 must attach new PG/role evidence to their exact integration SHA.
