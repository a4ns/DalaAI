-- Isolated A3 delivery candidate. Internal-only states, no wire route/startup change.
-- Immutable intent distinguishes pre-send lease recovery from uncertain send recovery.
BEGIN;
ALTER TABLE delivery_jobs ADD COLUMN lease_token uuid;
ALTER TABLE delivery_jobs DROP CONSTRAINT delivery_jobs_state_check;
ALTER TABLE delivery_jobs ADD CONSTRAINT delivery_jobs_state_check CHECK
  (state IN ('pending','sending','provider_accepted','retry','cancelled','failed','synthetic_recorded'));
CREATE TABLE delivery_dispatches (
  lease_token uuid PRIMARY KEY, job_id uuid NOT NULL REFERENCES delivery_jobs(id),
  attempt_number integer NOT NULL CHECK (attempt_number>0), started_at timestamptz NOT NULL
);
CREATE INDEX delivery_dispatches_job_idx ON delivery_dispatches(job_id,attempt_number);
CREATE TABLE delivery_dispatch_results (
  lease_token uuid PRIMARY KEY REFERENCES delivery_dispatches(lease_token),
  outcome text NOT NULL CHECK (outcome IN ('accepted','retryable','permanent_failure','ambiguous','synthetic_recorded')),
  error_code text NOT NULL CHECK (error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
  provider_receipt text CHECK (provider_receipt ~ '^[A-Za-z0-9_:-]{1,160}$'),
  retry_after_seconds integer CHECK (retry_after_seconds BETWEEN 0 AND 31622400),
  observed_at timestamptz NOT NULL,
  CHECK (outcome<>'accepted' OR provider_receipt IS NOT NULL),
  CHECK (retry_after_seconds IS NULL OR outcome='retryable'),
  CHECK (outcome<>'synthetic_recorded' OR error_code='SYNTHETIC_NOT_SENT')
);
CREATE TRIGGER delivery_dispatches_immutable BEFORE UPDATE OR DELETE ON delivery_dispatches
  FOR EACH ROW EXECUTE FUNCTION deny_audit_change();
CREATE TRIGGER delivery_dispatch_results_immutable BEFORE UPDATE OR DELETE ON delivery_dispatch_results
  FOR EACH ROW EXECUTE FUNCTION deny_audit_change();
COMMENT ON TABLE delivery_dispatches IS
  'Committed send intent, not proof of a network call; expired unfinished intent is uncertain and MUST NOT auto-retry';
COMMENT ON TABLE delivery_dispatch_results IS
  'Observed adapter outcome only. accepted is API acceptance, never proof of phone receipt, display, vibration or sound';
COMMIT;
