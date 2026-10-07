# Session and component lifecycle validation candidate

Base: accepted discovery c2fbe6a5ce5dd584a6edbdb8e3abf3501e7d1bfd. This isolated
candidate adds the frozen A2 session implementation, four independent adversarial
PostgreSQL probes, nine targeted restricted-login session checks, and the frozen
real HTTP-ASGI/PostgreSQL lifecycle harness. No app.main routes are activated by
this commit. Exact result evidence belongs to CI at the published SHA.

Frozen inputs and unchanged file hashes are in
backend/review/sessions/REVIEWED_INPUTS.json. Only owned source/test files were
copied. The Argon2 dependency closure is pinned in requirements.lock and verified
against official PyPI version pages for argon2-cffi 25.1.0,
argon2-cffi-bindings 25.1.0, cffi 2.0.0 and pycparser 2.23.

Mandatory serialized gates: prior 24 persistence +33 restricted-role cases,
security forward-fix control, discovery 13 author +7 independent +13 restricted,
sessions 28 local +16 real PostgreSQL +4 independent +9 restricted-login cases,
6 harness safety cases, two fresh-process real HTTP lifecycle phases, and full
aggregate tests with the disposable PostgreSQL DSN configured. Every dedicated
runtime gate fails on missing dependencies, skipped cases or wrong counts.

003 remains a proposal at its frozen path so the author fixture applies it once.
The lifecycle wrapper copies unchanged 003 bytes to migrations ONLY inside its
disposable backend assembly, alongside 001/002/004. This is test assembly, not
migration activation or a production account provisioning script.

The restricted session role has only SELECT on the four needed tables, INSERT
on sessions/limit buckets, narrowly protected identity UPDATE for row locks,
UPDATE(revoked_at) on sessions and UPDATE(window_started_at,attempts) on limits.
It cannot alter employees' role/PIN, session hashes/CSRF, delete rate state or
remove triggers. Schema setup and hostile administrative fixture changes stay
owner-only. The role and generated credential exist only in a disposable CI DB.

The HTTP harness mounts real routers in a test-owned factory, uses a logical
HTTPS ASGI origin and two distinct Python processes over one real PostgreSQL
schema. It proves planned lifecycle, incomplete unplanned close denial, foreign
403, stale409 and idempotent replay after application restart. It does not prove
app.main wiring, actual TLS/network/browser/Android, physical database restart,
photo bytes, model quality, notification delivery, reports or production load.
Those remain separate gates. No live users, real PINs or provider secrets are
included. The source README's original NOT_RUN claims describe author-local
execution; new exact-head CI evidence supersedes only the gates actually run.
