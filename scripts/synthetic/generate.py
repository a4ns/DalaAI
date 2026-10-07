#!/usr/bin/env python3
"""Deterministic, offline synthetic history export. No DB, HTTP or auth access."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
from uuid import UUID, uuid5

SCHEMA_VERSION = "1.0.0"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20261008
DEFAULT_COUNT = 540
START = "2026-06-30T19:00:00Z"
END = "2026-09-30T19:00:00Z"
WATERMARK = "Синтетические данные — не история предприятия"
CONTRACT_VERSION = "1.0.0-proposal.2"
CONTRACT_SHA256 = "b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97"
NAMESPACE = UUID("716a1c94-5fd0-5c11-a9e9-13d12b739639")
ROOT = Path(__file__).resolve().parents[2]


def canonical_bytes(value):
    """UTF-8, sorted keys, compact separators, no NaN, exactly one final LF."""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_export(seed=DEFAULT_SEED, count=DEFAULT_COUNT):
    """Return (history, evaluator_truth). Never use the second value as detector input.

    Fixed 92-day window; count 500..920 means at most ten orders/day. The seed
    changes generated identifiers, selection and invented facts, not the window.
    """
    if type(seed) is not int or not 0 <= seed <= 2**63 - 1:
        raise ValueError("seed must be an integer in [0, 2**63-1]")
    if type(count) is not int or not 500 <= count <= 920:
        raise ValueError("count must be an integer in [500, 920]")
    rng = random.Random(seed)
    uid = lambda kind, n: str(uuid5(NAMESPACE, f"{SCHEMA_VERSION}/{seed}/{kind}/{n}"))
    item = lambda kind, n, label: {"id": uid(kind, n), "code": f"SYN-{kind.upper()}-{n:03}",
                                  "label": f"Синтетический {label} {n:02}"}
    sections = [item("section", n, "участок") for n in range(1, 5)]
    equipment = [dict(item("equipment", n, "агрегат"), section_id=uid("section", (n-1) % 4+1))
                 for n in range(1, 26)]
    brigades = [dict(item("brigade", n, "бригада"), section_id=uid("section", n))
                for n in range(1, 4)]
    employees = []
    for n in range(1, 3):
        employees.append({"id": uid("master", n), "employee_code": f"SYN-M-{n:02}", "role": "master",
                          "section_ids": [uid("section", 2*n-1), uid("section", 2*n)],
                          "brigade_id": None, "active": True})
    for n in range(1, 16):
        brigade = (n-1)//5+1
        employees.append({"id": uid("executor", n), "employee_code": f"SYN-E-{n:02}", "role": "executor",
                          "section_ids": [uid("section", brigade), uid("section", 4)],
                          "brigade_id": uid("brigade", brigade), "active": True})
    work_codes = [item("work_code", n, "шифр неисправности/работы") for n in range(1, 21)]
    materials = [dict(item("material", n, "материал"), unit=["шт", "кг", "л", "м"][(n-1) % 4])
                 for n in range(1, 41)]
    start, end = instant(START), instant(END)
    day_for = lambda i: i*92//count
    early = [i for i in range(count) if day_for(i) < 62]
    late = [i for i in range(count) if day_for(i) >= 62]
    rng.shuffle(early)
    rng.shuffle(late)
    # Pattern scheduling is kept outside exported rows. IDs/text never encode labels.
    groups = {"repeat_fault": early[:16] + late[:8], "material_excess": late[8:32],
              "long_duration": late[32:56], "late_completion": late[56:80]}
    controls = {"repeat_fault": [], "material_excess": early[16:40],
                "long_duration": early[40:64], "late_completion": early[64:88]}
    group_of = {i: name for name, rows in groups.items() for i in rows}
    control_of = {i: name for name, rows in controls.items() for i in rows}
    history = {"metadata": {"schema_version": SCHEMA_VERSION, "generator_version": GENERATOR_VERSION,
                "synthetic": True, "watermark": WATERMARK, "purpose": "offline_historical_export",
                "seed": seed, "window": {"start_inclusive": START, "end_exclusive": END,
                                         "display_timezone": "Asia/Almaty", "utc_offset": "+05:00"},
                "as_of": END, "core_contract_version": CONTRACT_VERSION,
                "core_contract_sha256": CONTRACT_SHA256,
                "photo_evidence": "metadata_placeholders_only_no_image_bytes",
                "assessment_semantics": "empty_means_absent_not_pending_or_failed",
                "score_semantics": "synthetic_human_scores_null_means_unscored_not_zero"},
               "sections": sections, "equipment": equipment, "brigades": brigades, "employees": employees,
               "work_codes": work_codes, "materials": materials, "orders": [], "order_events": [],
               "submissions": [], "reviews": [], "photos": [], "material_writeoffs": [], "ai_assessments": []}
    available = {n: start for n in range(1, 16)}
    for i in range(count):
        n = i+1
        group, control = group_of.get(i), control_of.get(i)
        family = group or control
        equipment_no = {"repeat_fault": 1, "material_excess": 2, "long_duration": 3,
                        "late_completion": 4}.get(family, 5 + i % 21)
        section_no = (equipment_no-1) % 4+1
        pool = list(range((section_no-1)*5+1, section_no*5+1)) if section_no < 4 else list(range(1, 16))
        rng.shuffle(pool)
        executor_no = min(pool, key=lambda x: available[x])
        day_start = start + timedelta(days=day_for(i), hours=13)
        issued = max(day_start, available[executor_no])
        accepted, started = issued+timedelta(minutes=5), issued+timedelta(minutes=10)
        duration = 240 if group == "long_duration" else (60 if family else rng.randint(35, 85))
        due = issued+timedelta(minutes=30 if group == "late_completion" else 180)
        work_no = {"repeat_fault": 1, "material_excess": 2, "long_duration": 3,
                   "late_completion": 4}.get(family, 5+i % 16)
        material_no = 1 if family == "material_excess" else 2+i % 39
        quantity = 12 if group == "material_excess" else (2 if family else rng.randint(1, 3))
        rework = not family and i % 13 == 0
        paused = not family and not rework and i % 11 == 0
        order_id, executor_id = uid("order", n), uid("executor", executor_no)
        master_id = uid("master", 1 if section_no <= 2 else 2)
        order = {"id": order_id, "number": str(n), "version": 1, "assignment_revision": 1,
                 "scheduling_revision": 1, "status": "issued", "type": "unplanned" if family or i % 3 else "planned",
                 "description": f"Проверить агрегат и устранить неисправность по шифру SYN-WORK_CODE-{work_no:03}",
                 "section_id": uid("section", section_no), "equipment_id": uid("equipment", equipment_no),
                 "assignment": {"executor_id": executor_id,
                                "brigade_id": uid("brigade", section_no) if section_no < 4 else None},
                 "created_by": master_id, "issued_at": stamp(issued), "due_at": stamp(due), "norm_minutes": 60,
                 "priority": "high" if i % 7 == 0 else "normal", "comment": "Синтетический учебный наряд",
                 "before_photo_ids": [], "current_submission_id": None, "updated_at": stamp(issued)}
        seq = 0
        def event(kind, target, at, actor, *, same_version=False, submission_id=None, reason=None, details=None):
            nonlocal seq
            previous = None if seq == 0 else order["status"]
            if seq and not same_version:
                order["version"] += 1
            seq += 1
            history["order_events"].append({"id": uid("event", f"{n}/{seq}"), "order_id": order_id,
                "sequence": seq, "order_version": order["version"], "assignment_revision": 1, "scheduling_revision": 1,
                "kind": kind, "actor_id": actor, "operation_id": uid("operation", f"{n}/{order['version']}"),
                "from_status": previous, "to_status": target, "submission_id": submission_id,
                "occurred_at": stamp(at), "recorded_at": stamp(at), "reason": reason, "details": details or {}})
            order["status"], order["updated_at"] = target, stamp(at)
        event("order.created", "issued", issued, master_id)
        if i % 5 == 0:
            event("order.queued", "queued", issued+timedelta(minutes=2), executor_id)
        event("order.accepted", "accepted", accepted, executor_id)
        event("order.started", "in_progress", started, executor_id)
        if paused:
            event("order.paused", "paused", started+timedelta(minutes=10), executor_id,
                  reason="Ожидание материала в учебном сценарии")
            event("order.resumed", "in_progress", started+timedelta(minutes=20), executor_id)
        submitted = started+timedelta(minutes=duration)
        for attempt in range(1, 3 if rework else 2):
            incomplete = rework and attempt == 1
            sub_id = uid("submission", f"{n}/{attempt}")
            photo_ids = []
            if order["type"] == "unplanned":
                photo_id = uid("photo", f"{n}/{attempt}")
                photo_ids = [photo_id]
                history["photos"].append({"id": photo_id, "order_id": order_id, "submission_id": sub_id,
                    "assignment_revision": 1, "owner_id": executor_id, "purpose": "after",
                    "uploaded_at": stamp(submitted-timedelta(minutes=1)),
                    "evidence_kind": "synthetic_metadata_placeholder", "artifact_available": False})
            payload = {"work_description": "Выполнены проверка узла, регулировка и контрольный осмотр",
                       "work_code_id": None if incomplete else uid("work_code", work_no),
                       "materials": [{"material_id": uid("material", material_no), "quantity": quantity}],
                       "after_photo_ids": photo_ids, "comment": "Синтетический результат"}
            sub = {"id": sub_id, "order_id": order_id, "assignment_revision": 1, "attempt_number": attempt,
                   "submitted_by": executor_id, "submitted_at": stamp(submitted), "done_late": submitted > due,
                   "payload": payload, "completeness": "incomplete" if incomplete else "complete",
                   "missing_evidence": ["WORK_CODE_REQUIRED"] if incomplete else []}
            history["submissions"].append(sub)
            history["material_writeoffs"].append({"submission_id": sub_id,
                "material_id": uid("material", material_no), "quantity": quantity})
            event("order.done", "done", submitted, executor_id, submission_id=sub_id)
            event("order.ai_review_requested", "ai_review", submitted, None, same_version=True, submission_id=sub_id)
            reviewed = submitted+timedelta(minutes=10)
            review = {"id": uid("review", f"{n}/{attempt}"), "submission_id": sub_id,
                      "reviewer_id": master_id, "decision": "rework" if incomplete else "close",
                      "reason": "Нужен шифр выполненных работ" if incomplete else "Учебный результат принят мастером",
                      "final_score": None if incomplete or i % 10 == 0 else rng.randint(75, 98),
                      "created_at": stamp(reviewed)}
            history["reviews"].append(review)
            order["current_submission_id"] = sub_id
            event("order.reviewed", "rework" if incomplete else "closed", reviewed, master_id,
                  submission_id=sub_id, reason=review["reason"], details={"decision": review["decision"]})
            if incomplete:
                resumed = reviewed+timedelta(minutes=5)
                event("order.started", "in_progress", resumed, executor_id)
                submitted = resumed+timedelta(minutes=30)
        available[executor_no] = reviewed+timedelta(minutes=5)
        history["orders"].append(order)
    specs = {
        "repeat_fault": ("Repeated same-equipment/work-code unplanned completions", "equipment+work_code repeats within 7 days"),
        "material_excess": ("Increased quantity in a matched material cohort", "24 September uses at quantity 12 versus 24 July/August controls at quantity 2"),
        "long_duration": ("Longer elapsed execution in a matched equipment cohort", "24 September executions at 240 minutes versus 24 controls at 60 minutes; norm 60"),
        "late_completion": ("Late submission under an unchanged original deadline", "24 September submissions after original due_at versus 24 on-time controls")}
    truth = {"schema_version": SCHEMA_VERSION, "synthetic": True, "audience": "evaluator_only",
             "history_sha256": digest(history), "seed": seed, "window": deepcopy(history["metadata"]["window"]),
             "limitations": "Planted construction facts, not independent detector accuracy or real industrial evidence.",
             "patterns": [{"pattern_id": name, "description": specs[name][0], "observable": specs[name][1],
                           "positive_order_ids": [uid("order", i+1) for i in sorted(rows)],
                           "control_order_ids": [uid("order", i+1) for i in sorted(controls[name])],
                           "target_equipment_id": uid("equipment", pos+1), "work_code_id": uid("work_code", pos+1)}
                          for pos, (name, rows) in enumerate(groups.items())]}
    return history, truth


def manifest(history):
    return {"schema_version": SCHEMA_VERSION, "generator_version": GENERATOR_VERSION,
            "synthetic": True, "seed": history["metadata"]["seed"], "window": history["metadata"]["window"],
            "canonicalization": "UTF-8; sorted keys; compact separators; no NaN; final LF",
            "history_sha256": digest(history), "counts": {key: len(value) for key, value in history.items() if isinstance(value, list)},
            "schema_sha256": hashlib.sha256((ROOT / "data/synthetic/v1/history.schema.json").read_bytes()).hexdigest()}



def evaluator_manifest(history, truth):
    """Small retained checksum record; evaluator truth itself is generated."""
    return {"schema_version": SCHEMA_VERSION, "generator_version": GENERATOR_VERSION,
            "synthetic": True, "audience": "evaluator_only", "seed": history["metadata"]["seed"],
            "history_sha256": digest(history), "truth_sha256": digest(truth),
            "truth_bytes": len(canonical_bytes(truth)), "pattern_count": len(truth["patterns"]),
            "schema_sha256": hashlib.sha256((ROOT / "data/synthetic/evaluator/v1/pattern_truth.schema.json").read_bytes()).hexdigest()}


def example_subset(history):
    """One fully linked illustrative order, never a substitute for the full corpus."""
    order = history["orders"][0]
    oid = order["id"]
    subs = [s for s in history["submissions"] if s["order_id"] == oid]
    sub_ids = {s["id"] for s in subs}
    employee_ids = {order["created_by"], order["assignment"]["executor_id"]}
    employees = [e for e in history["employees"] if e["id"] in employee_ids]
    section_ids = {sid for e in employees for sid in e["section_ids"]}
    brigade_ids = {e["brigade_id"] for e in employees if e["brigade_id"]}
    work_ids = {s["payload"]["work_code_id"] for s in subs}
    material_ids = {m["material_id"] for s in subs for m in s["payload"]["materials"]}
    records = {"orders": [order], "submissions": subs, "employees": employees,
        "sections": [s for s in history["sections"] if s["id"] in section_ids],
        "brigades": [b for b in history["brigades"] if b["id"] in brigade_ids],
        "equipment": [e for e in history["equipment"] if e["id"] == order["equipment_id"]],
        "work_codes": [w for w in history["work_codes"] if w["id"] in work_ids],
        "materials": [m for m in history["materials"] if m["id"] in material_ids],
        "order_events": [e for e in history["order_events"] if e["order_id"] == oid],
        "reviews": [r for r in history["reviews"] if r["submission_id"] in sub_ids],
        "photos": [p for p in history["photos"] if p["order_id"] == oid],
        "material_writeoffs": [m for m in history["material_writeoffs"] if m["submission_id"] in sub_ids],
        "ai_assessments": []}
    return {"schema_version": SCHEMA_VERSION, "synthetic": True, "watermark": WATERMARK,
            "fixture_kind": "illustrative_subset_not_full_corpus", "source_history_sha256": digest(history),
            "notice": "One linked example only. Generate the full 540-order history for validation/evaluation.",
            "records": deepcopy(records)}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--output", type=Path, required=True, help="Offline history JSON file; never a DB/HTTP destination")
    parser.add_argument("--evaluator-output", type=Path, help="Optional separate evaluator-only truth file")
    args = parser.parse_args()
    manifest_path = args.output.with_name(args.output.stem + ".manifest.json")
    paths = [args.output, manifest_path]
    if args.evaluator_output:
        truth_manifest_path = args.evaluator_output.with_name(args.evaluator_output.stem + ".manifest.json")
        paths.extend([args.evaluator_output, truth_manifest_path])
    if len({path.resolve() for path in paths}) != len(paths):
        parser.error("history, truth and their manifests must be separate files")
    history, truth = build_export(args.seed, args.count)
    from validate import validate_history
    validate_history(history)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_bytes(history))
    manifest_path.write_bytes(canonical_bytes(manifest(history)))
    if args.evaluator_output:
        args.evaluator_output.parent.mkdir(parents=True, exist_ok=True)
        args.evaluator_output.write_bytes(canonical_bytes(truth))
        truth_manifest_path.write_bytes(canonical_bytes(evaluator_manifest(history, truth)))
    print(json.dumps({"status": "PASS", "history_sha256": digest(history), "orders": len(history["orders"]),
                      "evidence_level": "synthetic_offline_only"}, sort_keys=True))


if __name__ == "__main__":
    main()
