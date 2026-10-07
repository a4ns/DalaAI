-- PROPOSAL: A6/A0 acceptance and restricted-role migration application required.
-- One row per employee bounds storage and deliberately chooses latest device.
BEGIN;
CREATE TABLE push_subscriptions (
  employee_id uuid PRIMARY KEY REFERENCES employees(id),
  session_hash text NOT NULL REFERENCES auth_sessions(token_hash),
  endpoint_hash text NOT NULL UNIQUE CHECK (endpoint_hash ~ '^[0-9a-f]{64}$'),
  endpoint text NOT NULL CHECK (length(endpoint) BETWEEN 1 AND 2048),
  p256dh text NOT NULL CHECK (length(p256dh)=87),
  auth text NOT NULL CHECK (length(auth)=22),
  expires_at timestamptz,
  generation uuid NOT NULL,
  active boolean NOT NULL DEFAULT true,
  updated_at timestamptz NOT NULL,
  last_error_code text CHECK (last_error_code IN ('USER_DISABLED','PUSH_GONE','PUSH_INVALID_SUBSCRIPTION'))
);
CREATE FUNCTION protect_push_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.employee_id IS DISTINCT FROM OLD.employee_id THEN
    RAISE EXCEPTION 'subscription ownership is immutable' USING ERRCODE='check_violation';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER push_subscription_owner_immutable BEFORE UPDATE ON push_subscriptions
  FOR EACH ROW EXECUTE FUNCTION protect_push_owner();
COMMIT;
-- Grant proposal (runtime role name supplied by A5, never interpolated from HTTP):
-- GRANT SELECT,INSERT ON push_subscriptions TO runtime_role;
-- GRANT UPDATE(session_hash,endpoint_hash,endpoint,p256dh,auth,expires_at,generation,
--              active,updated_at,last_error_code) ON push_subscriptions TO runtime_role;
-- No DELETE/TRUNCATE/owner UPDATE/DDL/grant permission.
