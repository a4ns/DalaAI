-- Forward security fix for narrow UPDATE grants required by PostgreSQL row locks.
-- 003 is reserved for the separately reviewed auth/rate-limit candidate.
-- No data rewrite, new privileges, or wire-contract change. Apply as schema owner.
BEGIN;
CREATE FUNCTION guard_immutable_identity_keys() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE key_name text;
BEGIN
  FOREACH key_name IN ARRAY TG_ARGV LOOP
    IF NOT (to_jsonb(NEW) ? key_name) THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Identity guard configuration is invalid';
    END IF;
    IF (to_jsonb(NEW) -> key_name) IS DISTINCT FROM (to_jsonb(OLD) -> key_name) THEN
      RAISE EXCEPTION USING ERRCODE = '23514', MESSAGE = 'Identity and ownership keys are immutable';
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
CREATE TRIGGER auth_sessions_identity_immutable BEFORE UPDATE OF id, employee_id ON auth_sessions
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('id', 'employee_id');
CREATE TRIGGER employees_identity_immutable BEFORE UPDATE OF id ON employees
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('id');
CREATE TRIGGER employee_sections_ownership_immutable BEFORE UPDATE OF employee_id, section_id ON employee_sections
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('employee_id', 'section_id');
CREATE TRIGGER equipment_identity_immutable BEFORE UPDATE OF id ON equipment
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('id');
CREATE TRIGGER brigades_identity_immutable BEFORE UPDATE OF id ON brigades
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('id');
CREATE TRIGGER work_codes_identity_immutable BEFORE UPDATE OF id ON work_codes
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('id');
CREATE TRIGGER materials_identity_immutable BEFORE UPDATE OF id ON materials
  FOR EACH ROW EXECUTE FUNCTION guard_immutable_identity_keys('id');
COMMIT;
