-- PROPOSED persistence completion of proposal.2, not an accepted wire change.
-- Fresh candidate only; existing data needs explicit backfill from validated
-- upload records and immutable source submission payloads. Never guess true.
BEGIN;
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM submissions) THEN
    RAISE EXCEPTION 'Existing submissions require a separately reviewed immutable evidence backfill';
  END IF;
END $$;
ALTER TABLE photos ADD COLUMN file_valid boolean;
COMMENT ON COLUMN photos.file_valid IS
  'Trusted decoded-and-sanitized file validation result; NULL is unknown and blocks close';
ALTER TABLE submissions ADD COLUMN after_photo_ids uuid[] NOT NULL;
COMMENT ON COLUMN submissions.after_photo_ids IS
  'Immutable submitted evidence manifest; preserve IDs even if evidence becomes unavailable';
CREATE FUNCTION guard_attached_photo() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.attached_at IS NOT NULL THEN RAISE EXCEPTION 'Attached evidence is immutable'; END IF;
    RETURN OLD;
  END IF;
  IF OLD.attached_at IS NOT NULL AND (
    NEW.id IS DISTINCT FROM OLD.id OR NEW.owner_id IS DISTINCT FROM OLD.owner_id OR
    NEW.section_id IS DISTINCT FROM OLD.section_id OR NEW.purpose IS DISTINCT FROM OLD.purpose OR
    NEW.order_id IS DISTINCT FROM OLD.order_id OR NEW.assignment_revision IS DISTINCT FROM OLD.assignment_revision OR
    NEW.submission_id IS DISTINCT FROM OLD.submission_id OR NEW.storage_key IS DISTINCT FROM OLD.storage_key OR
    NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
    NEW.bytes IS DISTINCT FROM OLD.bytes OR NEW.attached_at IS DISTINCT FROM OLD.attached_at OR
    NEW.exif_removed IS DISTINCT FROM OLD.exif_removed
  ) THEN RAISE EXCEPTION 'Attached evidence is immutable'; END IF;
  -- file_valid can be invalidated after integrity revalidation; close rechecks it.
  RETURN NEW;
END $$;
CREATE TRIGGER attached_photo_binding_immutable BEFORE UPDATE OR DELETE ON photos
  FOR EACH ROW EXECUTE FUNCTION guard_attached_photo();
CREATE FUNCTION guard_committed_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' OR OLD.committed_at IS NOT NULL THEN
    RAISE EXCEPTION 'Committed receipts are immutable';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER committed_receipt_immutable BEFORE UPDATE OR DELETE ON operation_receipts
  FOR EACH ROW EXECUTE FUNCTION guard_committed_receipt();
COMMIT;
