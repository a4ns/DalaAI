# Actual application factory + restricted LOGIN delta

This delta preserves the original lifecycle harness and manifest. It replaces
test-owned router composition with the **actual `app.main.create_app` factory**,
explicit demo configuration, real lifespan and a separately authenticated
nonowner PostgreSQL connection. It does not create or drop roles/credentials.

## Exact A5 seam

```python
from app.main import create_app
from app.runtime import RuntimeSettings
settings = RuntimeSettings(mode='demo', database_url=runtime_dsn,
    allowed_origin='https://vertical-acceptance.test', database_schema=schema)
app = create_app(settings=settings, connect=runtime_connect)
```

`runtime_connect` uses `DALA_ACCEPTANCE_RUNTIME_DATABASE_URL`, autocommit,
`dict_row` and the one random schema's search_path. It must be a real LOGIN with
`current_user == session_user`, distinct from the owner; no superuser, CREATEDB,
CREATEROLE, BYPASSRLS, schema CREATE or table ownership is allowed. It must connect
to the same local PostgreSQL database as `DALA_TEST_DATABASE_URL`.

Only owner_connect applies migrations, seeds catalogues, checks effects and
drops the invocation's synthetic schema. The runtime connection performs every
application request. There is no owner fallback, SET ROLE substitute, fake
repository, fake verifier, fake limiter, overridden FastAPI dependency or patched
production function.

The fixture grants the reviewed A5 test-role profile on this new schema only:
USAGE, table SELECT, sequence USAGE/SELECT, required command/session INSERTs,
orders/delivery-job UPDATE and explicit narrow receipt/photo/auth/reference
column UPDATEs. Session additions are INSERT on auth_sessions and UPDATE of
revoked_at (plus the guarded id lock column), and INSERT/UPDATE of the rate-limit
window/attempt fields. It does not grant DELETE, DDL, auth identity/token/CSRF
field UPDATEs, PIN/role/active UPDATEs or photo validation UPDATEs. All four schema
migrations must be applied before this profile is used.

A5 provisions the ephemeral restricted LOGIN before the gate and removes it
afterward. This harness only grants access to its own temporary synthetic schema;
dropping that schema removes the object grants. Credentials are never written to
evidence, source, temporary state or stdout.

## What runs

1. Actual startup with owner_connect must specifically raise
   `app.runtime.RuntimePrerequisiteError` with `ROLE_NOT_RESTRICTED` or
   `ROLE_OWNS_OBJECTS`. An unrelated crash does not count as a security pass
2. Each worker constructs actual app.main with explicit demo settings, verifies
   the required route surface, enters its real lifespan, checks runtime_ready,
   `/healthz` and `/readyz`, and verifies shutdown leaves ready=false
3. A versioned copy of the frozen lifecycle scenarios runs with an explicit
   app_factory parameter; all request, lifecycle, 403, 409, receipt, incomplete
   close, rework, logout and persisted-effect assertions are otherwise unchanged
4. A second Python process creates the actual app again and repeats exact
   committed requests through new HTTP logins, proving current state/receipts
   survive backend restart under the restricted runtime connection

`scenarios_runtime.py` differs from frozen v1 only in imports and its explicit
app_factory argument. Its delta is recorded in `evidence/scenario-diff.patch`.
This is an application API acceptance extension, not a second backend.

The default module-global app is forced to health mode while importing modules;
only the explicit factory under test is in demo mode. No external provider,
notification worker, migration-on-startup, deployment or live account is enabled.

## Exact command for A5's existing serialized job

Keep this directory beside the original `vertical_acceptance` package.

```sh
export DALA_TEST_DATABASE_URL='postgresql://OWNER:OWNER_PASSWORD@127.0.0.1:5432/TEST_DB'
export DALA_ACCEPTANCE_RUNTIME_DATABASE_URL='postgresql://RUNTIME:RUNTIME_PASSWORD@127.0.0.1:5432/TEST_DB'
export DALA_ACCEPTANCE_DISPOSABLE=1
PYTHONPATH=<harness-root>:<approved-existing-dependencies> \
  python runtime_delta/run_runtime.py \
    --backend <exact-A5-runtime-backend> \
    --source-sha <exact-commit> \
    --report evidence/actual-runtime-http.json --run
```

Do not copy the placeholder values literally. A5 supplies the already authorized
isolated CI database and temporary test identities. No new installation is
performed by the command. No competing CI pipeline should be started.

Exit 0 means the actual app.main/nonowner lifecycle and cleanup passed; exit 1 is
a real execution/setup/cleanup failure; exit 2 means NOTRUN due to missing
prerequisites. Default health-mode route inventory is retained separately in the
report so it cannot be mistaken for the explicit demo factory under test.

Current local status is **NOTRUN** for actual DB acceptance because the two local
DSNs are unavailable. Constructor, scenario-diff and syntax checks do not prove
runtime SQL permissions or a live lifecycle. The earlier component gate passing
on commit 9954cba5 does not establish this stronger gate.

Physical PostgreSQL restart, deployed TLS/network, browser/Android draft retention,
photo upload/blob validation, model/provider/phone delivery and reports remain
NOTRUN. Exhaustive malicious SQL/grant/key-update tests remain A5's own gate.
