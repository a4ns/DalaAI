-- A2 PROPOSED ADDITIVE migration, A6/A0 acceptance and numbering pending.
-- Apply after existing frozen migrations. Never changes domain/session schemas.
BEGIN;
CREATE TABLE auth_login_limits (
  kind text NOT NULL CHECK (kind IN ('account','source')),
  bucket integer NOT NULL CHECK (bucket BETWEEN 0 AND 65535),
  window_started_at timestamptz NOT NULL,
  attempts integer NOT NULL CHECK (attempts BETWEEN 0 AND 1000000),
  PRIMARY KEY (kind,bucket)
);
-- Maximum 131072 rows; no PIN, raw account identifier, IP or token is stored.
-- Restricted service role: SELECT, INSERT, UPDATE only on auth_login_limits.
-- App must not own tables or have DDL/TRIGGER/TRUNCATE/BYPASSRLS privileges.
COMMIT;
