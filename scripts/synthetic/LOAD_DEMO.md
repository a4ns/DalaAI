# Canonical synthetic historical loader, v1

This package imports only the reviewed **540-order offline C1 export** into an
explicitly authorized, isolated demo schema. It is not a live order-creation API,
account provisioner, migration runner or proof of a real completed workflow.

## Evidence status

- Unit, deterministic-source, static-schema and fake-SQL checks are available in
  `test_load_demo.py`. They do not execute PostgreSQL.
- **Real PostgreSQL import: BLOCKED / NOT_RUN.** This package has no authorized
  isolated OWNER connection and no confirmed complete 17-account mapping.
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
required account descriptors, including canonical source IDs, roles, section
IDs and brigades. It reports PostgreSQL as `NOT_RUN`; it never opens a connection.
Only point it at the intended public history file, never a credential document.

## Required external identity seam

An authorized operator must first provide:

1. An isolated demo database/schema with the accepted schema already applied
2. Canonical sections and brigades needed by the preprovisioned accounts' FKs
3. Seventeen already-existing, active synthetic accounts with these exact codes:
   `SYN-M-01`, `SYN-M-02` and `SYN-E-01` through `SYN-E-15`
4. Matching source roles, exact canonical section-membership sets and canonical
   brigade IDs; the offline CLI lists the complete source requirements
5. An explicit one-to-one mapping from each of those codes to its existing
   account UUID, plus an already-open, idle OWNER connection

The two live fixture accounts `DALA-DEMO-MASTER` and `DALA-DEMO-EXECUTOR` are not
historical actors. Their known IDs are rejected by the mapping validator even
if a caller attempts to relabel them. Nothing changes those accounts or their
permissions. Mapping one account to several actors or to a canonical business
entity ID also fails.

The schema must contain no unrelated business rows. Existing catalogue rows
must exactly match the canonical ID, code, label, unit and ownership fields.
All accounts in the selected schema must use `SYN-` codes. The exact matched
17 actors are checked for role, active status, section scopes and brigade;
`on_shift` and credentials are not read or changed. Existing synthetic accounts
outside the map are not used. A shared schema containing the separate live
fixture is deliberately refused; coexistence would require a separately
reviewed namespace policy.

Missing identities/scopes or namespace conflicts stop the import. The loader
never fills the gap by creating accounts, changing membership or expanding
privileges. It does not inspect password hashes, read secret files, discover
environment DSNs, create a role, perform login, or create a session.

## Authorized runner integration

This is an integration contract, **not authorization to run an import now**.
The owner of the isolated seam supplies an already-open psycopg 3 connection
with `autocommit=True`, idle transaction state, and dictionary rows. Its session
role must itself own every required table; `SET ROLE` impersonation is refused.
The caller retains responsibility for its connection and authorization.

```python
from load_demo import load_demo

# owner_connection is supplied by the separately authorized runner.
# mapping contains all 17 exact synthetic employee codes and existing UUIDs.
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

Only the ten business tables listed in `load_demo.COLUMNS` receive INSERTs:
sections, brigades, equipment, work codes, materials, orders, submissions,
material writeoffs, reviews and order events. The loader has no UPDATE, DELETE,
TRUNCATE, UPSERT, DDL, privilege, HTTP or outbound-provider path.

## Transaction, identity and repeat behavior

- One outer transaction uses `READ COMMITTED` with a transaction-scoped advisory
  lock. A repeated concurrent invocation gets a fresh snapshot after waiting
- Deterministically ordered table locks protect all preflight reads and INSERTs
  from concurrent writes; `lock_timeout=5s` and `statement_timeout=60s` bound waits
- Owner/table checks, complete account checks and all-table conflict checks run
  before the first INSERT. Any unexpected/changed row fails closed
- Only an entirely absent business history or an entirely identical complete
  history is accepted. A partial history is refused rather than repaired
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
An operator must review any other recovery outside this package.

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
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s scripts/synthetic -p test_load_demo.py -v
git diff --check
```

The fake checks cover exact canonical input, guards, owner and account mapping,
deterministic projection, full INSERT/no-op behavior, namespace/conflict failure,
partial-import refusal, absent evidence, preserved null scores, mocked rollback,
SQL write allowlists and column compatibility. They do not establish real
PostgreSQL concurrency or FK behavior. Once the isolated seam is authorized,
A5's runner must additionally verify real commit/readback, an identical no-op,
conflict rollback, concurrent invocation outcome and unchanged account rights.
