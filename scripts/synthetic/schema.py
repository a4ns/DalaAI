"""Build the versioned offline export schema; deliberately not an API/DB schema."""
import json
from pathlib import Path


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def arr(items, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


def enum(*values):
    return {"enum": list(values)}


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


TEXT = {"type": "string", "minLength": 1}
EMPTY_TEXT = {"type": "string"}
UUID = {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}
TIME = {"type": "string", "format": "date-time", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
BOOL = {"type": "boolean"}
POS = {"type": "integer", "minimum": 1}
SCORE = nullable({"type": "integer", "minimum": 0, "maximum": 100})
QUANTITY = {"type": "number", "exclusiveMinimum": 0, "maximum": 999999999, "multipleOf": 0.001}
STATUS = enum("issued", "queued", "accepted", "rejected", "in_progress", "paused", "done", "ai_review", "rework", "closed", "cancelled")
ITEM = {"id": UUID, "code": TEXT, "label": TEXT}
USE = obj({"material_id": UUID, "quantity": QUANTITY})
WINDOW = obj({"start_inclusive": TIME, "end_exclusive": TIME, "display_timezone": enum("Asia/Almaty"), "utc_offset": enum("+05:00")})
METADATA = obj({"schema_version": enum("1.0.0"), "generator_version": enum("1.0.0"), "synthetic": {"const": True},
    "watermark": enum("Синтетические данные — не история предприятия"), "purpose": enum("offline_historical_export"),
    "seed": {"type": "integer", "minimum": 0, "maximum": 2**63-1}, "window": WINDOW, "as_of": TIME,
    "core_contract_version": enum("1.0.0-proposal.2"), "core_contract_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    "photo_evidence": enum("metadata_placeholders_only_no_image_bytes"),
    "assessment_semantics": enum("empty_means_absent_not_pending_or_failed"),
    "score_semantics": enum("synthetic_human_scores_null_means_unscored_not_zero")})
ORDER = obj({"id": UUID, "number": {"type": "string", "pattern": "^[1-9][0-9]*$"}, "version": POS,
    "assignment_revision": POS, "scheduling_revision": POS, "status": STATUS, "type": enum("planned", "unplanned"),
    "description": TEXT, "section_id": UUID, "equipment_id": UUID,
    "assignment": obj({"executor_id": UUID, "brigade_id": nullable(UUID)}), "created_by": UUID,
    "issued_at": TIME, "due_at": TIME, "norm_minutes": {"type": "integer", "minimum": 1, "maximum": 525600},
    "priority": enum("normal", "high", "emergency"), "comment": EMPTY_TEXT,
    "before_photo_ids": arr(UUID), "current_submission_id": nullable(UUID), "updated_at": TIME})
SUBMISSION = obj({"id": UUID, "order_id": UUID, "assignment_revision": POS, "attempt_number": POS,
    "submitted_by": UUID, "submitted_at": TIME, "done_late": BOOL,
    "payload": obj({"work_description": TEXT, "work_code_id": nullable(UUID), "materials": arr(USE),
                    "after_photo_ids": arr(UUID), "comment": EMPTY_TEXT}),
    "completeness": enum("complete", "incomplete"), "missing_evidence": arr(enum("WORK_CODE_REQUIRED", "AFTER_PHOTO_REQUIRED"))})
EVENT = obj({"id": UUID, "order_id": UUID, "sequence": POS, "order_version": POS,
    "assignment_revision": POS, "scheduling_revision": POS, "reason": nullable(TEXT),
    "details": {"type": "object", "properties": {"decision": enum("close", "rework")}, "additionalProperties": False},
    "kind": enum("order.created", "order.queued", "order.accepted", "order.started", "order.paused", "order.resumed",
                 "order.done", "order.ai_review_requested", "order.reviewed"),
    "actor_id": nullable(UUID), "operation_id": UUID, "from_status": nullable(STATUS), "to_status": STATUS,
    "submission_id": nullable(UUID), "occurred_at": TIME, "recorded_at": TIME})
REVIEW = obj({"id": UUID, "submission_id": UUID, "reviewer_id": UUID, "decision": enum("close", "rework"),
              "reason": TEXT, "final_score": SCORE, "created_at": TIME})
PHOTO = obj({"id": UUID, "order_id": UUID, "submission_id": UUID, "assignment_revision": POS, "owner_id": UUID,
             "purpose": enum("after"), "uploaded_at": TIME, "evidence_kind": enum("synthetic_metadata_placeholder"),
             "artifact_available": {"const": False}})


def history_schema():
    schema = obj({"metadata": METADATA, "sections": arr(obj(ITEM), 4),
        "equipment": arr(obj(dict(ITEM, section_id=UUID)), 25),
        "brigades": arr(obj(dict(ITEM, section_id=UUID)), 3),
        "employees": arr(obj({"id": UUID, "employee_code": TEXT, "role": enum("master", "executor"),
                              "section_ids": arr(UUID, 1), "brigade_id": nullable(UUID), "active": BOOL}), 17),
        "work_codes": arr(obj(ITEM), 20), "materials": arr(obj(dict(ITEM, unit=TEXT)), 40),
        "orders": arr(ORDER, 500), "order_events": arr(EVENT, 1), "submissions": arr(SUBMISSION, 1),
        "reviews": arr(REVIEW, 1), "photos": arr(PHOTO),
        "material_writeoffs": arr(obj({"submission_id": UUID, "material_id": UUID, "quantity": QUANTITY})),
        "ai_assessments": {"type": "array", "maxItems": 0}})
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "$id": "urn:dalai:synthetic:history:1.0.0", "title": "Synthetic offline history v1"})
    return schema


def truth_schema():
    schema = obj({"schema_version": enum("1.0.0"), "synthetic": {"const": True}, "audience": enum("evaluator_only"),
        "history_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "seed": {"type": "integer", "minimum": 0}, "window": WINDOW, "limitations": TEXT,
        "patterns": dict(arr(obj({"pattern_id": enum("repeat_fault", "material_excess", "long_duration", "late_completion"),
            "description": TEXT, "observable": TEXT, "positive_order_ids": arr(UUID, 1), "control_order_ids": arr(UUID),
            "target_equipment_id": UUID, "work_code_id": UUID}), 4), maxItems=4)})
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "$id": "urn:dalai:synthetic:pattern-truth:1.0.0", "title": "Evaluator-only synthetic construction truth v1"})
    return schema


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    for path, schema in [("data/synthetic/v1/history.schema.json", history_schema()),
                         ("data/synthetic/evaluator/v1/pattern_truth.schema.json", truth_schema())]:
        (root / path).write_text(json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
