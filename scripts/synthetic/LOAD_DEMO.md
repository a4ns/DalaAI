# Canonical synthetic historical loader, v1.1

This package imports only the reviewed **540-order offline C1 export** into an
explicitly authorized, isolated demo schema. It is not a live order-creation API,
login provisioner, migration runner or proof of a real completed workflow.
Under [A0-0037](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046815144),
missing historical actors can be inserted as disabled business records only.

## Evidence status

- Unit, deterministic-source, static-schema and fake-SQL checks are available in
  `test_load_demo.py`. They do not execute PostgreSQL.
- **Real PostgreSQL import: BLOCKED / NOT_RUN.** This package has no authorized
  isolated OWNER connection. Seventeen usable/preprovisioned logins are no
  longer required; the explicit identity mapping is still mandatory.
- Actual PostgreSQL constraints, lock behavior under concurrency, rollback,
  persisted readback, application reports and live browser/mobile flows still
  need their own checks on the integrated exact SHA.
- No database, role, account, password, session, privilege, migration, image or
  provider was created or changed while developing this package.

The implementation targets the tables and columns in migrations
`001_vertical_slice.sql`, `002_trusted_evidence.sql` and the identity guards in
`004_immutable_reference_keys.sql` at base
`e435ec9a290279ab49b8cb63237b872955c79938`. It does not apply these files or disable
any trigger. The implementation's schema-column test is a static compatibility
check, not PostgreSQL execution evidence.

## Reviewed source and deliberately narrow input

- C1 source commit: `8af3897f03aa2f41f0af07ec74ec2c807a4a535a`
- Seed: `20261008`; orders: `540`
- History window: `2026-06-30T19:00:00Z` through
  `2026-09-30T19:00:00Z`, end exclusive; display timezone `Asia/Almaty`
- Canonical history SHA-256:
  `7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1`
- Canonical bytes: UTF-8, sorted keys, compact separators, no NaN, one final LF

The loader hashes the complete input **before JSON decoding**. Other seeds,
counts, illustrative subsets, evaluator ground truth, changed records,
duplicate-key JSON and even alternative whitespace are rejected. A document
merely labelling itself `synthetic` is insufficient. A future source version
requires a separately reviewed checksum, projection and tests; there is no
`--force`, checksum override or generic arbitrary-data import switch.

After the separate public C1 package is available, generate its default export
using that package's documented generator. Validate the resulting public JSON:

```sh
python scripts/synthetic/load_demo.py /path/to/canonical-history.json
```

This CLI is **offline only**. It reports `VALIDATED_OFFLINE`, counts and the
historical actor descriptors, including canonical source IDs, roles, section
IDs and brigades, plus a complete `canonical_identity_mapping`. Current actor
state is shown as inactive/off-shift. It reports PostgreSQL as `NOT_RUN`; it
never opens a connection.
Only point it at the intended public history file, never a credential document.

## Disabled historical actor policy

An authorized operator must first provide:

1. An isolated demo database/schema with the accepted schema already applied
2. An explicit one-to-one mapping from the 17 source codes to runtime UUIDs,
   plus an already-open, idle OWNER connection

The source codes are `SYN-M-01`, `SYN-M-02` and `SYN-E-01` through `SYN-E-15`.
For each missing actor, the mapping **must equal its canonical C1 source UUID**.
The offline CLI emits that complete map. The loader inserts required canonical
section/brigade references, then the missing employee with its historical
master/executor role, `active=false`, `on_shift=false`, and the public non-hash
sentinel `!DISABLED_SYNTHETIC_HISTORY`. It inserts canonical section memberships
only for those newly inserted actors, in the same transaction. No real PIN,
valid hash, credential, session, database role or usable access is created.

An existing mapped actor must already have the exact source code, historical
role, brigade, inactive/off-shift state, locked sentinel and complete canonical
membership set. An explicit noncanonical target UUID may only reference such an
already-existing matching disabled actor; it cannot cause creation of a new
arbitrary ID. Missing/extra memberships on an existing actor are a conflict,
not an invitation to expand or repair its scope. ID/code collisions fail closed.

The two live fixture accounts `DALA-DEMO-MASTER` and `DALA-DEMO-EXECUTOR` are not
historical actors. Their known IDs are rejected by the mapping validator even
if a caller attempts to relabel them. Nothing changes those accounts or their
permissions. Mapping one account to several actors or to a canonical business
entity ID also fails.

The schema must contain no unrelated business rows. Existing catalogue rows
must exactly match the canonical ID, code, label, unit and ownership fields.
All accounts in the selected schema must use `SYN-` codes. The exact matched
17 actors are checked for role, disabled/off-shift status, section scopes and
brigade. SQL returns only a boolean comparison against the public locked
sentinel, never the stored credential hash. Existing synthetic accounts outside
the map are not used. A shared schema containing the separate live
fixture is deliberately refused; coexistence would require a separately
reviewed namespace policy.

Existing mismatched actors/scopes or namespace conflicts stop the import. The
loader never alters, reactivates or expands an existing account or its scope.
It does not retrieve password hashes, read secret files, discover environment
DSNs, create a role, perform login, or create a session.

Historical reports must retain facts referencing these now-disabled actors.
Current reader authorization still applies: authorizing a separate history
viewer, if needed for UI, is an operator-owned later action. The loader does not
broaden the live master's scope or change reports to filter out former actors.

### Concrete A2 non-authentication check

The test imports actual `Argon2idVerifier` from
`backend/app/sessions/crypto.py` at base
`e435ec9a290279ab49b8cb63237b872955c79938` (blob
`19f65c12a24e3eaa123bd5f5b5fecfa443249f6c`). The non-Argon2 sentinel takes its
unsupported-hash path, which performs dummy work and always returns false.
The unit test executes that real verifier with dummy PINs only. It is not a
mock of the verifier and does not attempt a real account login. Dependencies
must match the existing backend lock; a missing dependency fails this test
rather than being reported as a skipped success.

`backend/app/sessions/service.py` independently requires `active=true` before
creating a session and rechecks it inside the transaction. These imported
actors are inactive. Neither real session issuance nor PostgreSQL login is
claimed tested by the sentinel-only check.

## Authorized runner integration

This is an integration contract, **not authorization to run an import now**.
The owner of the isolated seam supplies an already-open psycopg 3 connection
with `autocommit=True`, idle transaction state, and dictionary rows. Its session
role must itself own every required table; `SET ROLE` impersonation is refused.
The caller retains responsibility for its connection and authorization.

```python
from load_demo import load_demo

# owner_connection is supplied by the separately authorized runner.
# mapping contains all 17 codes; missing actors use their canonical source UUIDs.
result = load_demo(
    owner_connection,
    canonical_history_bytes,
    mapping,
    demo_only=True,
    expected_database="operator_verified_isolated_demo_database",
    expected_schema="operator_verified_synthetic_schema",
)
```

The API requires all three explicit guards: `demo_only=True`, the exact connected
database name and a safe explicit schema name. Every target table is schema
qualified; `search_path` is locally restricted to `pg_catalog`. This prevents
accidental default-schema targeting. It cannot independently attest that an
operator-designated database is organizationally approved for demo use.

The ten business tables listed in `load_demo.COLUMNS` receive INSERTs:
sections, brigades, equipment, work codes, materials, orders, submissions,
material writeoffs, reviews and order events. In addition, the two tables in
`ACTOR_COLUMNS` receive only missing canonical disabled employees and their
memberships. The loader has no UPDATE, DELETE,
TRUNCATE, UPSERT, DDL, privilege, HTTP or outbound-provider path.

## Transaction, identity and repeat behavior

- One outer transaction uses `READ COMMITTED` with a transaction-scoped advisory
  lock. A repeated concurrent invocation gets a fresh snapshot after waiting
- Deterministically ordered table locks protect all preflight reads and INSERTs
  from concurrent writes; `lock_timeout=5s` and `statement_timeout=60s` bound waits
- Owner/table checks, complete actor checks and all-table conflict checks run
  before the first INSERT. Any unexpected/changed row fails closed
- Only an entirely absent business history or an entirely identical complete
  history is accepted. A partial history is refused rather than repaired
- Matching disabled actors/references may precede the first import. Once the
  complete business history exists, missing actors also block rather than being
  silently repaired
- An identical repeat returns `NOOP`, performs no INSERTs and consumes no new
  order numbers. A changed map, provenance, source ID or source field conflicts
- Source UUIDs are retained; actor references use the explicit account mapping
- Runtime order numbers use the existing database identity sequence. There is
  no override or reseed. Both source and actual runtime order numbers are stored
  in each creation event's provenance. Changing a runtime number without its
  original provenance is detected on repeat
- All accepted deferred constraints are forced before successful commit. An
  exception causes transaction rollback; no automatic retry masks an uncertain
  commit. PostgreSQL identity sequences may retain gaps after rollback

No automatic recovery or destructive reset is provided. For an uncertain commit,
reinvoke with the identical bytes/map only after the connection outcome is
known: complete matching history is a no-op, partial/conflicting history blocks.
An operator must review any other recovery outside this package. In particular,
v1.0 (`175e40870457ec94df4745083f694956a683927c`) expected active preprovisioned
actors and different provenance. A v1.0-imported state intentionally conflicts
with v1.1; there is no in-place disabling, reactivation, provenance rewrite or
upgrade. No actual v1.0 database import was performed for this package.

## Historical photo and scoring honesty

Every imported order comment is watermarked “Синтетические данные — не история
предприятия” and says that photo bytes are unavailable. Each `order.created`
event carries `synthetic_import` provenance: loader version, source commit,
history checksum, identity-map checksum, source/runtime order numbers and the
complete original metadata-only photo descriptors for that order.

The immutable submission `after_photo_ids` manifest is retained even though
there are **zero imported photo rows, storage objects or image bytes**. No MIME,
byte count, digest, sanitization or `file_valid` result is invented. `photos`,
`ai_assessments`, `ai_jobs`, `delivery_jobs` and `operation_receipts` must be empty
and remain untouched. No historical event schedules notifications or AI work.

Source closed statuses, reviews, historical completeness and human scores are
preserved as **synthetic past narrative**. A historical `complete` flag does not
attest that bytes were decoded or evidence verified; provenance explicitly says
this. Null human scores stay null; there are no fabricated AI scores or jobs.
Live command deadlines and close-time evidence checks are not relaxed. Reports
or UI must disclose the synthetic history and unavailable photos; this import
does not demonstrate a successful live close or count as real photo validation.

## Reproduce bounded checks

The public C1 commit object must already be available locally. Tests verify its
generator source SHA-256 before executing the reviewed generator in memory;
they do not fetch, install, contact a provider or access a database. Missing
objects cause setup failure, not a skipped-as-passed PostgreSQL claim.

```sh
# Use the backend's locked environment, including argon2-cffi and its bindings.
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s scripts/synthetic -p test_load_demo.py -v
git diff --check
```

The fake checks cover exact canonical input, guards, owner and actor mapping,
deterministic projection, full INSERT/no-op behavior, namespace/conflict failure,
disabled canonical actor insertion, refusal to change existing actor state or
scope, partial-import refusal, absent evidence, preserved null scores, mocked
rollback, SQL write allowlists and column compatibility. The separate actual-A2
crypto unit check proves rejection of the locked sentinel for tested dummy PINs.
These checks do not establish real
PostgreSQL concurrency or FK behavior. Once the isolated seam is authorized,
A5's runner must additionally verify real commit/readback, an identical no-op,
conflict rollback, concurrent invocation outcome and unchanged account rights.
