# Isolated persistence runtime validation

This branch tests the frozen A6 candidate; it does not authorize main integration,
mount domain HTTP routes, or declare the complete product ready. Its A3/A4 source
copies are dependency snapshots, not replacements for their full owner handoffs.

Frozen archive SHA-256:
`24c655300837cb3f11da11fa1c86a3bbbc2a1e25ee116382e98077488f3b511c`.
The 24-case mandatory runner applies migrations 001 and 002 to fresh disposable
schemas. A configured but unavailable PostgreSQL server, driver, failed migration,
missing test count or skipped case fails the acceptance job. The ordinary backend
workflow can skip the opt-in DB classes without a DSN; that is not DB acceptance.

## Application-role profile

The additional gate reuses the 24 command-service cases with an actual separate
LOGIN connection and adds five explicit permission tests. The role is non-owner,
NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOINHERIT and NOBYPASSRLS. It is generated
only inside the disposable CI database, with a random credential that is never
printed or saved in the repository. Schema creation, migrations, synthetic fixture
changes and cleanup use a distinct owner connection. Production owner credentials
must never be passed to CommandService.

The profile grants SELECT, exact command INSERT/UPDATE permissions, photo binding
columns, and orders identity-sequence usage. It does not grant DELETE, TRUNCATE,
DDL ownership, trigger disabling, session_replication_role, or writes to employee
role/active, token/CSRF secrets or trusted photo-validation flags. Committed receipt
immutability and deferred completeness must remain effective under this login.

PostgreSQL FOR SHARE/UPDATE requires UPDATE on at least one column, including on
auth/reference tables. This candidate profile uses id/employee_id column grants
rather than broad auth-table UPDATE. This still permits direct modification of
those identifier columns if SQL access is compromised: it is an explicit remaining
DB privilege-design risk, not production hardening or row-level SQL authorization.
A reviewed lock-helper/provisioning design may reduce that risk later; do not grant
UPDATE(role/active/pin_hash/token_hash/csrf_token) just to make locks work.

References:
- https://www.postgresql.org/docs/17/sql-select.html
- https://www.postgresql.org/docs/17/sql-grant.html
- https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers

## Gates still separate

Populated legacy migration/backfill, upload byte validation/storage, session
issuance/PIN/rate limits, mounted same-origin HTTP, full notification dispatch,
stale AI completion and real-device tests remain separate. Application-role tests
use synthetic file_valid flags; they do not certify actual image content.
