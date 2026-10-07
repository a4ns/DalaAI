-- A5 reservation: optional isolated-demo capability. NOT core bootstrap.
-- No seed, account mutation, grants, credentials, deletion, or clock activation.
CREATE TABLE demo_clock_state (
  instance_id uuid PRIMARY KEY,
  synthetic boolean NOT NULL DEFAULT true CHECK (synthetic),
  version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
  real_anchor timestamptz NOT NULL,
  domain_anchor timestamptz NOT NULL,
  domain_start timestamptz NOT NULL,
  domain_limit timestamptz NOT NULL,
  scale integer NOT NULL DEFAULT 1 CHECK (scale BETWEEN 0 AND 60),
  CHECK (domain_limit = domain_start + interval '168 hours'),
  CHECK (domain_anchor BETWEEN domain_start AND domain_limit)
);
CREATE TABLE demo_clock_controls (
  instance_id uuid NOT NULL REFERENCES demo_clock_state(instance_id),
  version integer NOT NULL CHECK (version > 0),
  actor_id uuid NOT NULL,
  action text NOT NULL CHECK (action IN ('set_scale','advance')),
  recorded_at timestamptz NOT NULL,
  previous_scale integer NOT NULL CHECK (previous_scale BETWEEN 0 AND 60),
  scale integer NOT NULL CHECK (scale BETWEEN 0 AND 60),
  domain_anchor timestamptz NOT NULL,
  advance_seconds integer,
  PRIMARY KEY (instance_id,version),
  CHECK ((action='set_scale' AND advance_seconds IS NULL) OR
         (action='advance' AND advance_seconds IS NOT NULL AND advance_seconds BETWEEN 1 AND 3600 AND scale=previous_scale))
);
CREATE FUNCTION guard_demo_clock_state() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'UPDATE' THEN RAISE EXCEPTION 'demo clock removal forbidden'; END IF;
  IF NEW.instance_id<>OLD.instance_id OR NEW.synthetic<>OLD.synthetic OR
     NEW.domain_start<>OLD.domain_start OR NEW.domain_limit<>OLD.domain_limit OR
     NEW.version<>OLD.version+1 OR NEW.real_anchor<OLD.real_anchor OR
     NEW.domain_anchor<OLD.domain_anchor+(NEW.real_anchor-OLD.real_anchor)*OLD.scale THEN
    RAISE EXCEPTION 'demo clock must advance with immutable identity and next version';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER demo_clock_state_guard BEFORE UPDATE OR DELETE ON demo_clock_state
  FOR EACH ROW EXECUTE FUNCTION guard_demo_clock_state();
CREATE FUNCTION guard_demo_clock_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'demo clock audit is append only';
END $$;
CREATE TRIGGER demo_clock_audit_immutable BEFORE UPDATE OR DELETE ON demo_clock_controls
  FOR EACH ROW EXECUTE FUNCTION guard_demo_clock_audit();
CREATE FUNCTION require_demo_clock_audit() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM demo_clock_controls c WHERE c.instance_id=NEW.instance_id
      AND c.version=NEW.version AND c.recorded_at=NEW.real_anchor
      AND c.domain_anchor=NEW.domain_anchor AND c.scale=NEW.scale AND c.previous_scale=OLD.scale
      AND c.domain_anchor=OLD.domain_anchor+(NEW.real_anchor-OLD.real_anchor)*OLD.scale
          +CASE WHEN c.action='advance' THEN c.advance_seconds*interval '1 second' ELSE interval '0 seconds' END) THEN
    RAISE EXCEPTION 'demo clock control audit missing';
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER demo_clock_audit_at_commit AFTER UPDATE ON demo_clock_state
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION require_demo_clock_audit();
