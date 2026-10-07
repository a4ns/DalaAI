-- Additive internal worker migration, reserved with A5. No HTTP contract change.
-- Existing running jobs without a token are reclaimable only once their old
-- lease expires (or immediately if no lease was recorded). No data is discarded.
BEGIN;
ALTER TABLE ai_jobs ADD COLUMN lease_token uuid;
COMMENT ON COLUMN ai_jobs.lease_token IS
  'Fresh per-claim fencing identity; result transaction also checks attempts and real lease expiry';
CREATE INDEX ai_jobs_runnable_idx ON ai_jobs(next_attempt_at,id)
  WHERE state IN ('pending','retry','running');
COMMIT;
