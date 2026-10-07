#!/usr/bin/env python3
"""Strict stdlib validation of the v1 synthetic export and evaluator boundary."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from generate import ROOT, canonical_bytes, digest, instant


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def validate_schema(value, schema, path="$", root=None):
    """Validate exactly the JSON Schema keywords used by our checked-in schemas.

    This is not a general JSON Schema implementation. Schema drift is tested.
    """
    if "anyOf" in schema:
        for choice in schema["anyOf"]:
            try:
                validate_schema(value, choice, path)
                return
            except ValidationError:
                pass
        raise ValidationError(f"{path}: no allowed type")
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "null": type(None)}
    if kind == "number":
        require(type(value) in (int, float), f"{path}: number required")
        require(Decimal(str(value)).is_finite(), f"{path}: finite number required")
    elif kind:
        require(type(value) is types[kind], f"{path}: {kind} required")
    if "const" in schema:
        require(type(value) is type(schema["const"]) and value == schema["const"], f"{path}: invalid constant")
    if "enum" in schema:
        require(value in schema["enum"], f"{path}: invalid enum")
    if isinstance(value, dict):
        require(set(schema.get("required", ())) <= set(value), f"{path}: missing required fields")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(value) <= set(props), f"{path}: unexpected fields {set(value)-set(props)}")
        for key, item in value.items():
            if key in props:
                validate_schema(item, props[key], f"{path}.{key}")
    if isinstance(value, list):
        require(len(value) >= schema.get("minItems", 0), f"{path}: too few items")
        require(len(value) <= schema.get("maxItems", len(value)), f"{path}: too many items")
        for i, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{path}[{i}]")
    if isinstance(value, str):
        require(len(value) >= schema.get("minLength", 0), f"{path}: empty string")
        if "pattern" in schema:
            require(re.search(schema["pattern"], value) is not None, f"{path}: invalid format")
        if schema.get("format") == "date-time":
            try:
                instant(value)
            except ValueError as exc:
                raise ValidationError(f"{path}: invalid date-time") from exc
    if type(value) in (int, float):
        v = Decimal(str(value))
        if "minimum" in schema:
            require(v >= Decimal(str(schema["minimum"])), f"{path}: below minimum")
        if "maximum" in schema:
            require(v <= Decimal(str(schema["maximum"])), f"{path}: above maximum")
        if "exclusiveMinimum" in schema:
            require(v > Decimal(str(schema["exclusiveMinimum"])), f"{path}: nonpositive quantity")
        if "multipleOf" in schema:
            require(v % Decimal(str(schema["multipleOf"])) == 0, f"{path}: excess decimal precision")


def schema_at(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def validate_history(h):
    validate_schema(h, schema_at("data/synthetic/v1/history.schema.json"))
    meta = h["metadata"]
    start, end, as_of = (instant(meta["window"]["start_inclusive"]),
                         instant(meta["window"]["end_exclusive"]), instant(meta["as_of"]))
    require(start < end == as_of, "invalid window/as_of")
    tables = {key: {row["id"]: row for row in rows} for key, rows in h.items()
              if isinstance(rows, list) and key not in {"material_writeoffs", "ai_assessments"}}
    all_ids = []
    for key, table in tables.items():
        require(len(table) == len(h[key]), f"duplicate id in {key}")
        all_ids.extend(table)
        codes = [r.get("code", r.get("employee_code")) for r in h[key] if "code" in r or "employee_code" in r]
        require(len(codes) == len(set(codes)), f"duplicate code in {key}")
    require(len(all_ids) == len(set(all_ids)), "cross-table duplicate identifiers")
    require(len({o["number"] for o in h["orders"]}) == len(h["orders"]), "duplicate order number")
    employees, equipment, brigades = tables["employees"], tables["equipment"], tables["brigades"]
    roles = Counter(e["role"] for e in employees.values())
    require(roles["master"] >= 2 and roles["executor"] >= 15, "insufficient role coverage")
    for e in employees.values():
        require(len(e["section_ids"]) == len(set(e["section_ids"])), "duplicate employee section")
        require(set(e["section_ids"]) <= tables["sections"].keys(), "unknown employee section")
        if e["brigade_id"] is not None:
            require(e["brigade_id"] in brigades, "unknown employee brigade")
            require(brigades[e["brigade_id"]]["section_id"] in e["section_ids"], "employee/brigade scope mismatch")
    for r in [*equipment.values(), *brigades.values()]:
        require(r["section_id"] in tables["sections"], "unknown catalogue section")
    for b in brigades:
        require(any(e["role"] == "executor" and e["brigade_id"] == b for e in employees.values()), "empty brigade")
    months = {instant(o["issued_at"]).astimezone(timezone(timedelta(hours=5))).strftime("%Y-%m") for o in h["orders"]}
    require(len(months) >= 3, "history must span at least three local calendar months")
    events_by_order, subs_by_order, reviews_by_sub, photos_by_sub = (defaultdict(list) for _ in range(4))
    for ev in h["order_events"]:
        require(ev["order_id"] in tables["orders"], "event references unknown order")
        events_by_order[ev["order_id"]].append(ev)
    for sub in h["submissions"]:
        require(sub["order_id"] in tables["orders"], "submission references unknown order")
        subs_by_order[sub["order_id"]].append(sub)
    for r in h["reviews"]:
        require(r["submission_id"] in tables["submissions"], "review references unknown submission")
        reviews_by_sub[r["submission_id"]].append(r)
    for photo in h["photos"]:
        require(photo["submission_id"] in tables["submissions"], "photo references unknown submission")
        photos_by_sub[photo["submission_id"]].append(photo)
    writeoffs = {}
    for row in h["material_writeoffs"]:
        key = (row["submission_id"], row["material_id"])
        require(key not in writeoffs, "duplicate material writeoff")
        require(key[0] in tables["submissions"] and key[1] in tables["materials"], "dangling material writeoff")
        writeoffs[key] = row["quantity"]
    allowed = {"order.created": {(None, "issued")}, "order.queued": {("issued", "queued")},
        "order.accepted": {("issued", "accepted"), ("queued", "accepted")},
        "order.started": {("accepted", "in_progress"), ("rework", "in_progress")},
        "order.paused": {("in_progress", "paused")}, "order.resumed": {("paused", "in_progress")},
        "order.done": {("in_progress", "done")}, "order.ai_review_requested": {("done", "ai_review")},
        "order.reviewed": {("ai_review", "closed"), ("ai_review", "rework")}}
    expected_writeoffs = {}
    occupied = defaultdict(list)
    for order in h["orders"]:
        oid, section = order["id"], order["section_id"]
        require(section in tables["sections"], "unknown order section")
        require(order["equipment_id"] in equipment and equipment[order["equipment_id"]]["section_id"] == section,
                "equipment/order scope mismatch")
        eid, bid = order["assignment"]["executor_id"], order["assignment"]["brigade_id"]
        require(eid in employees and employees[eid]["role"] == "executor", "assignment must reference executor")
        require(section in employees[eid]["section_ids"], "executor outside order scope")
        if bid is not None:
            require(bid in brigades and brigades[bid]["section_id"] == section and employees[eid]["brigade_id"] == bid,
                    "brigade assignment mismatch")
        master = employees.get(order["created_by"])
        require(master is not None and master["role"] == "master" and section in master["section_ids"], "creator outside master scope")
        issued, due, updated = map(instant, [order["issued_at"], order["due_at"], order["updated_at"]])
        require(start <= issued < due < end and issued <= updated < end, "order timestamp outside historical window")
        require(order["assignment_revision"] == order["scheduling_revision"] == 1, "v1 has no reassignment or rescheduling")
        require(not order["before_photo_ids"], "v1 has no before-photo artifact")
        seq, version, status, last_time = 0, 0, None, issued
        for ev in events_by_order[oid]:
            seq += 1
            require(ev["sequence"] == seq, "event sequence gap/reorder")
            version += 0 if ev["kind"] == "order.ai_review_requested" else 1
            require(ev["order_version"] == version, "event version gap")
            require(ev["assignment_revision"] == ev["scheduling_revision"] == 1, "event revision mismatch")
            require(ev["from_status"] == status and (status, ev["to_status"]) in allowed[ev["kind"]], "invalid state transition")
            at, recorded = instant(ev["occurred_at"]), instant(ev["recorded_at"])
            require(last_time <= at <= recorded < end, "event chronology invalid")
            if seq == 1:
                require(at == issued, "creation/issued timestamp mismatch")
            if ev["kind"] in {"order.created", "order.reviewed"}:
                require(ev["actor_id"] == order["created_by"], "master event actor mismatch")
            elif ev["kind"] == "order.ai_review_requested":
                previous = events_by_order[oid][seq-2]
                require(ev["actor_id"] is None and previous["kind"] == "order.done" and
                        previous["occurred_at"] == ev["occurred_at"] and previous["operation_id"] == ev["operation_id"],
                        "submit must atomically emit done then ai_review")
            else:
                require(ev["actor_id"] == eid, "executor event actor mismatch")
            if ev["kind"] in {"order.done", "order.ai_review_requested", "order.reviewed"}:
                sub = tables["submissions"].get(ev["submission_id"])
                require(sub is not None and sub["order_id"] == oid, "event submission mismatch")
                if ev["kind"] != "order.reviewed":
                    require(sub["submitted_at"] == ev["occurred_at"], "submit event timestamp mismatch")
                else:
                    rr = reviews_by_sub[sub["id"]]
                    require(len(rr) == 1 and rr[0]["created_at"] == ev["occurred_at"] and
                            ev["details"] == {"decision": rr[0]["decision"]} and
                            ev["to_status"] == ("closed" if rr[0]["decision"] == "close" else "rework"), "review event mismatch")
            else:
                require(ev["submission_id"] is None, "unexpected event submission")
            if ev["kind"] == "order.paused":
                require(bool(ev["reason"]), "pause reason required")
            status, last_time = ev["to_status"], at
        require(status == order["status"] == "closed" and version == order["version"] and last_time == updated,
                "terminal snapshot/event mismatch")
        subs = subs_by_order[oid]
        require(bool(subs) and order["current_submission_id"] == subs[-1]["id"], "current submission mismatch")
        previous_submission = issued
        for attempt, sub in enumerate(subs, 1):
            sid, at, payload = sub["id"], instant(sub["submitted_at"]), sub["payload"]
            require(sub["attempt_number"] == attempt and sub["assignment_revision"] == 1 and sub["submitted_by"] == eid,
                    "submission attempt/owner/revision mismatch")
            require(previous_submission < at <= updated, "submission chronology invalid")
            previous_submission = at
            require(sub["done_late"] == (at > due), "done_late must use immutable original due_at")
            work_id = payload["work_code_id"]
            require(work_id is None or work_id in tables["work_codes"], "unknown work code")
            missing = ([] if work_id else ["WORK_CODE_REQUIRED"]) + (["AFTER_PHOTO_REQUIRED"] if order["type"] == "unplanned" and not payload["after_photo_ids"] else [])
            require(sub["missing_evidence"] == missing and sub["completeness"] == ("incomplete" if missing else "complete"), "completeness mismatch")
            require(len(payload["after_photo_ids"]) == len(set(payload["after_photo_ids"])), "duplicate photo")
            require(set(payload["after_photo_ids"]) == {p["id"] for p in photos_by_sub[sid]}, "photo payload/reference mismatch")
            for photo in photos_by_sub[sid]:
                require(photo["order_id"] == oid and photo["owner_id"] == eid and photo["assignment_revision"] == 1,
                        "photo ownership mismatch")
                require(issued <= instant(photo["uploaded_at"]) <= at, "photo chronology invalid")
            used = set()
            for material in payload["materials"]:
                mid = material["material_id"]
                require(mid in tables["materials"] and mid not in used, "unknown/duplicate submission material")
                used.add(mid)
                expected_writeoffs[(sid, mid)] = material["quantity"]
            rr = reviews_by_sub[sid]
            require(len(rr) == 1, "exactly one synthetic human review required per attempt")
            r = rr[0]
            require(r["reviewer_id"] == order["created_by"] and at <= instant(r["created_at"]) <= updated,
                    "review actor/chronology mismatch")
            require(r["decision"] == ("close" if attempt == len(subs) else "rework"), "review attempt decision mismatch")
            require(r["decision"] != "close" or not missing, "incomplete submission cannot close")
            for kind in ("order.done", "order.ai_review_requested", "order.reviewed"):
                require(sum(e["kind"] == kind and e["submission_id"] == sid for e in events_by_order[oid]) == 1,
                        "submission must have exactly one matching lifecycle event")
        occupied[eid].append((issued, updated))
    require(writeoffs == expected_writeoffs, "writeoffs/payload quantities disagree")
    # This corpus elects not to overlap executor assignments; this is not a core
    # domain constraint (multiple live active orders remain contractually allowed).
    for intervals in occupied.values():
        ordered = sorted(intervals)
        require(all(a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), "synthetic executor intervals overlap")
    return {"status": "PASS", "orders": len(h["orders"]), "calendar_months": sorted(months),
            "history_sha256": digest(h), "evidence_level": "synthetic_offline_only"}


def validate_truth(history, truth):
    validate_schema(truth, schema_at("data/synthetic/evaluator/v1/pattern_truth.schema.json"))
    require(truth["history_sha256"] == digest(history), "truth/history hash mismatch")
    require(truth["seed"] == history["metadata"]["seed"] and truth["window"] == history["metadata"]["window"], "truth provenance mismatch")
    orders = {r["id"]: r for r in history["orders"]}
    pattern_ids, labels = set(), set()
    for p in truth["patterns"]:
        require(p["pattern_id"] not in pattern_ids, "duplicate pattern")
        pattern_ids.add(p["pattern_id"])
        pos, control = p["positive_order_ids"], p["control_order_ids"]
        require(len(pos) == len(set(pos)) and len(control) == len(set(control)), "duplicate truth order")
        require(not set(pos) & set(control), "truth positive/control overlap")
        require(not labels & set(pos+control), "pattern cohorts overlap")
        labels.update(pos+control)
        for oid in pos+control:
            require(oid in orders and orders[oid]["equipment_id"] == p["target_equipment_id"], "truth order/equipment mismatch")
    return {"status": "PASS", "patterns": len(pattern_ids), "evidence_level": "synthetic_construction_truth_only"}


def validate_manifest(history, value, history_bytes=None):
    from generate import manifest
    require(value == manifest(history), "manifest counts/hash/schema/config mismatch")
    if history_bytes is not None:
        require(history_bytes == canonical_bytes(history), "history file is not canonical")
        require(hashlib.sha256(history_bytes).hexdigest() == value["history_sha256"], "history bytes hash mismatch")


def detector_payload(history, *, as_of):
    """Allowlisted, point-in-time observed facts. No truth, scores or future outcomes.

    Each row is an observed submission, not an anomaly label. Elapsed execution
    includes pauses and is not an equipment downtime measurement. No inference
    about a pending/failed model is made from absent assessments.
    """
    cutoff = instant(as_of)
    require(instant(history["metadata"]["window"]["start_inclusive"]) <= cutoff <= instant(history["metadata"]["as_of"]), "detector cutoff outside history")
    orders = {o["id"]: o for o in history["orders"]}
    starts = defaultdict(list)
    for e in history["order_events"]:
        if e["kind"] == "order.started" and instant(e["occurred_at"]) <= cutoff:
            starts[e["order_id"]].append(instant(e["occurred_at"]))
    observations = []
    for sub in history["submissions"]:
        at = instant(sub["submitted_at"])
        if at > cutoff:
            continue
        o = orders[sub["order_id"]]
        relevant_starts = [s for s in starts[o["id"]] if s <= at]
        require(bool(relevant_starts), "observed submission has no prior start")
        observations.append({"order_id": o["id"], "submission_id": sub["id"], "equipment_id": o["equipment_id"],
            "section_id": o["section_id"], "executor_id": o["assignment"]["executor_id"],
            "brigade_id": o["assignment"]["brigade_id"], "type": o["type"], "issued_at": o["issued_at"], "due_at": o["due_at"],
            "submitted_at": sub["submitted_at"], "attempt_number": sub["attempt_number"], "work_code_id": sub["payload"]["work_code_id"],
            "norm_minutes": o["norm_minutes"], "execution_elapsed_minutes": (at-max(relevant_starts)).total_seconds()/60,
            "materials": [{"material_id": m["material_id"], "quantity": m["quantity"]} for m in sub["payload"]["materials"]]})
    return {"schema_version": "1.0.0", "synthetic": True, "as_of": as_of, "observations": observations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--evaluator-truth", type=Path)
    args = parser.parse_args()
    try:
        raw = args.history.read_bytes()
        h = json.loads(raw)
        result = validate_history(h)
        if args.manifest:
            validate_manifest(h, json.loads(args.manifest.read_bytes()), raw)
        if args.evaluator_truth:
            result["truth"] = validate_truth(h, json.loads(args.evaluator_truth.read_bytes()))
    except (ValidationError, ValueError, OSError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
