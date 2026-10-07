"""Offline synthetic unit/invariant tests. These are not DB/model/device tests."""
import ast
from collections import Counter
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from generate import ROOT, DEFAULT_COUNT, DEFAULT_SEED, START, END, build_export, canonical_bytes, digest, instant, manifest, evaluator_manifest, example_subset
from schema import history_schema, truth_schema
from validate import ValidationError, detector_payload, validate_history, validate_manifest, validate_truth


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history, cls.truth = build_export()
        cls.raw = canonical_bytes(cls.history)

    def changed(self):
        return deepcopy(self.history)

    def invalid(self, edit):
        value = self.changed()
        edit(value)
        with self.assertRaises(ValidationError):
            validate_history(value)

    def test_default_counts_and_months(self):
        result = validate_history(self.history)
        self.assertEqual(result["calendar_months"], ["2026-07", "2026-08", "2026-09"])
        for name, count in {"sections": 4, "equipment": 25, "brigades": 3, "work_codes": 20,
                            "materials": 40, "orders": 540}.items():
            self.assertEqual(len(self.history[name]), count)
        self.assertEqual(Counter(e["role"] for e in self.history["employees"]), {"master": 2, "executor": 15})

    def test_reproducible_bytes_and_changed_seed(self):
        again, truth = build_export()
        self.assertEqual(canonical_bytes(again), self.raw)
        self.assertEqual(truth, self.truth)
        changed, other_truth = build_export(DEFAULT_SEED+1)
        self.assertNotEqual(digest(changed), digest(self.history))
        self.assertEqual(changed, build_export(DEFAULT_SEED+1)[0])
        validate_history(changed)
        validate_truth(changed, other_truth)

    def test_count_boundaries(self):
        for count in (500, 920):
            h, truth = build_export(count=count)
            validate_history(h)
            validate_truth(h, truth)
        for count in (499, 921, True, 500.0):
            with self.assertRaises(ValueError):
                build_export(count=count)
        for seed in (-1, True, 2**63, 1.5):
            with self.assertRaises(ValueError):
                build_export(seed=seed)

    def test_generated_bytes_and_retained_hashes(self):
        m = json.loads((ROOT / "data/synthetic/v1/history.manifest.json").read_bytes())
        validate_manifest(self.history, m, self.raw)
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), m["history_sha256"])
        self.assertEqual(m["history_sha256"], "7d888cdd5bb6a9c01ca7c543fae9e393335d07210dab811aa754f12331d1d2e1")
        t = json.loads((ROOT / "data/synthetic/evaluator/v1/pattern_truth.manifest.json").read_bytes())
        self.assertEqual(t, evaluator_manifest(self.history, self.truth))
        self.assertEqual(t["truth_sha256"], "bb8002d43c699d182b789e5e5dd47fe2d5d969480adfcb61ab103bb830d3d1ad")
        validate_truth(self.history, self.truth)

    def test_small_example_is_exact_linked_subset(self):
        example = json.loads((ROOT / "data/synthetic/v1/example.json").read_bytes())
        self.assertEqual(example, example_subset(self.history))
        self.assertEqual(example["fixture_kind"], "illustrative_subset_not_full_corpus")
        for table, rows in example["records"].items():
            self.assertTrue(all(row in self.history[table] for row in rows))
        self.assertEqual(len(example["records"]["orders"]), 1)
        self.assertLess(len(canonical_bytes(example)), 10000)

    def test_publication_package_is_small_and_excludes_full_generated_data(self):
        # Works in a source archive too; no Git metadata is needed to regenerate.
        data = ROOT / "data/synthetic"
        self.assertFalse((data / "v1/history.json").exists())
        self.assertFalse((data / "evaluator/v1/pattern_truth.json").exists())
        files = [p for p in data.rglob("*") if p.is_file() and "generated" not in p.relative_to(data).parts]
        files.extend((ROOT / "scripts/synthetic").glob("*.py"))
        self.assertLess(sum(p.stat().st_size for p in files), 100000)

    def test_schema_source_and_file_agree(self):
        for path, schema in [("data/synthetic/v1/history.schema.json", history_schema()),
                             ("data/synthetic/evaluator/v1/pattern_truth.schema.json", truth_schema())]:
            self.assertEqual(json.loads((ROOT/path).read_bytes()), schema)
        # Catch additions unsupported by our intentionally small stdlib validator.
        supported = {"type", "properties", "required", "additionalProperties", "items", "minItems", "maxItems",
                     "enum", "const", "anyOf", "minLength", "pattern", "format", "minimum", "maximum",
                     "exclusiveMinimum", "multipleOf", "$schema", "$id", "title"}
        def walk(schema):
            self.assertLessEqual(set(schema), supported)
            for value in schema.get("properties", {}).values():
                walk(value)
            for value in schema.get("anyOf", []):
                walk(value)
            if "items" in schema:
                walk(schema["items"])
        walk(history_schema())
        walk(truth_schema())

    def test_pinned_core_contract_hash(self):
        core = (ROOT / "coord/proposals/a6-contract-v1/contracts/openapi.yaml").read_bytes()
        self.assertEqual(hashlib.sha256(core).hexdigest(), self.history["metadata"]["core_contract_sha256"])

    def test_order_submission_fields_match_domain_types(self):
        # Read Python AST, without importing app code or contacting persistence.
        tree = ast.parse((ROOT / "backend/app/orders/models.py").read_text())
        for class_name, collection in [("Order", "orders"), ("Submission", "submissions"), ("Review", "reviews")]:
            node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
            fields = {n.target.id for n in node.body if isinstance(n, ast.AnnAssign)}
            self.assertEqual(set(self.history[collection][0]), fields)

    def test_no_truth_or_credentials_in_history(self):
        text = self.raw.decode()
        for forbidden in ("pattern_id", "positive_order_ids", "control_order_ids", "evaluator_only", "ground_truth",
                          "repeat_fault", "material_excess", "long_duration", "late_completion", "pin_hash", "password",
                          "session_token", "api_key", "auth_sessions", "operation_receipts"):
            self.assertNotIn(forbidden, text)
        self.assertTrue(self.history["metadata"]["synthetic"])
        self.assertEqual(self.history["metadata"]["window"]["utc_offset"], "+05:00")
        self.assertEqual(instant(END)-instant(START), timedelta(days=92))

    def test_evaluator_truth_hash_and_disjointness(self):
        self.assertEqual(validate_truth(self.history, self.truth)["patterns"], 4)
        t = deepcopy(self.truth)
        t["history_sha256"] = "0"*64
        with self.assertRaises(ValidationError):
            validate_truth(self.history, t)
        t = deepcopy(self.truth)
        t["patterns"][1]["control_order_ids"] = t["patterns"][1]["positive_order_ids"]
        with self.assertRaises(ValidationError):
            validate_truth(self.history, t)

    def test_four_planted_patterns_are_observable_without_truth_payload(self):
        facts = detector_payload(self.history, as_of=END)["observations"]
        by_order = {r["order_id"]: r for r in facts}
        for p in self.truth["patterns"]:
            positives = [by_order[oid] for oid in p["positive_order_ids"]]
            controls = [by_order[oid] for oid in p["control_order_ids"]]
            self.assertEqual(len(positives), 24)
            self.assertEqual({r["work_code_id"] for r in positives+controls}, {p["work_code_id"]})
            if p["pattern_id"] == "repeat_fault":
                times = sorted(instant(r["submitted_at"]) for r in positives)
                self.assertGreaterEqual(sum(b-a <= timedelta(days=7) for a, b in zip(times, times[1:])), 18)
                self.assertTrue(all(r["type"] == "unplanned" for r in positives))
            elif p["pattern_id"] == "material_excess":
                self.assertEqual({r["materials"][0]["quantity"] for r in positives}, {12})
                self.assertEqual({r["materials"][0]["quantity"] for r in controls}, {2})
                self.assertEqual(len({r["materials"][0]["material_id"] for r in positives+controls}), 1)
            elif p["pattern_id"] == "long_duration":
                self.assertEqual({r["execution_elapsed_minutes"] for r in positives}, {240})
                self.assertEqual({r["execution_elapsed_minutes"] for r in controls}, {60})
                self.assertEqual({r["norm_minutes"] for r in positives+controls}, {60})
            else:
                self.assertTrue(all(instant(r["submitted_at"]) > instant(r["due_at"]) for r in positives))
                self.assertTrue(all(instant(r["submitted_at"]) <= instant(r["due_at"]) for r in controls))

    def test_detector_allowlist_drops_nested_sentinels(self):
        h = self.changed()
        sentinel = "NEVER_SEND_EVALUATOR_SENTINEL"
        h["expected"] = sentinel
        for row in h["orders"]:
            row["expected"] = sentinel
            row["assignment"]["label"] = sentinel
        for row in h["submissions"]:
            row["payload"]["comment"] = sentinel
            row["payload"]["materials"][0]["expected"] = sentinel
        for row in h["order_events"]:
            row["details"]["expected"] = sentinel
        result = detector_payload(h, as_of=END)
        self.assertNotIn(sentinel, canonical_bytes(result).decode())
        self.assertEqual(result, detector_payload(self.history, as_of=END))
        self.assertNotIn("final_score", canonical_bytes(result).decode())
        self.assertNotIn("decision", canonical_bytes(result).decode())

    def test_point_in_time_payload_excludes_future_outcomes(self):
        self.assertEqual(detector_payload(self.history, as_of=START)["observations"], [])
        cutoff = "2026-07-15T12:00:00Z"
        before = detector_payload(self.history, as_of=cutoff)
        self.assertTrue(before["observations"])
        self.assertTrue(all(instant(r["submitted_at"]) <= instant(cutoff) for r in before["observations"]))
        changed = self.changed()
        for r in changed["reviews"]:
            r["final_score"], r["decision"] = 0, "rework"
        for o in changed["orders"]:
            o["status"] = "cancelled"
        for s in changed["submissions"]:
            if instant(s["submitted_at"]) > instant(cutoff):
                s["payload"]["work_description"] = "FUTURE_SENTINEL"
                s["payload"]["materials"][0]["quantity"] = 999
        self.assertEqual(before, detector_payload(changed, as_of=cutoff))
        with self.assertRaises(ValidationError):
            detector_payload(self.history, as_of="2026-10-01T00:00:00Z")

    def test_schema_rejects_unknown_fields_and_non_synthetic(self):
        self.invalid(lambda h: h["metadata"].update(synthetic=False))
        self.invalid(lambda h: h["orders"][0].update(password="not-a-secret"))
        self.invalid(lambda h: h["metadata"].update(watermark=""))
        self.invalid(lambda h: h["ai_assessments"].append({"score": 100}))

    def test_duplicates_and_dangling_references_rejected(self):
        self.invalid(lambda h: h["orders"][1].update(id=h["orders"][0]["id"]))
        self.invalid(lambda h: h["orders"][1].update(number=h["orders"][0]["number"]))
        self.invalid(lambda h: h["orders"][0].update(equipment_id=h["materials"][0]["id"]))
        self.invalid(lambda h: h["orders"][0].update(current_submission_id=h["submissions"][-1]["id"]))
        self.invalid(lambda h: h["material_writeoffs"].append(h["material_writeoffs"][0]))

    def test_scope_and_roles_rejected(self):
        self.invalid(lambda h: h["orders"][0].update(section_id=h["sections"][3]["id"]))
        self.invalid(lambda h: h["orders"][0]["assignment"].update(executor_id=h["employees"][0]["id"]))
        self.invalid(lambda h: h["orders"][0]["assignment"].update(brigade_id=next(b["id"] for b in h["brigades"] if b["id"] != h["orders"][0]["assignment"]["brigade_id"])))
        self.invalid(lambda h: h["orders"][0].update(created_by=h["employees"][-1]["id"]))

    def test_material_validation(self):
        for value in (-1, 0, True, 1.0001, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.invalid(lambda h: h["submissions"][0]["payload"]["materials"][0].update(quantity=value))
        self.invalid(lambda h: h["submissions"][0]["payload"]["materials"].append(h["submissions"][0]["payload"]["materials"][0]))
        self.invalid(lambda h: h["material_writeoffs"][0].update(quantity=3.125))

    def test_time_and_deadline_consistency(self):
        self.invalid(lambda h: h["orders"][0].update(due_at=h["orders"][0]["issued_at"]))
        self.invalid(lambda h: h["orders"][0].update(issued_at="2026-02-30T00:00:00Z"))
        self.invalid(lambda h: h["orders"][0].update(updated_at=END))
        self.invalid(lambda h: h["submissions"][0].update(done_late=not h["submissions"][0]["done_late"]))
        self.invalid(lambda h: h["order_events"][1].update(occurred_at=START))

    def test_event_sequence_version_atomic_submit_and_actors(self):
        self.invalid(lambda h: h["order_events"][1].update(sequence=9))
        self.invalid(lambda h: h["order_events"][1].update(order_version=9))
        self.invalid(lambda h: next(e for e in h["order_events"] if e["kind"] == "order.ai_review_requested").update(actor_id=h["employees"][0]["id"]))
        self.invalid(lambda h: next(e for e in h["order_events"] if e["kind"] == "order.ai_review_requested").update(operation_id=h["orders"][0]["id"]))
        self.invalid(lambda h: h["order_events"][0].update(actor_id=h["employees"][-1]["id"]))
        self.invalid(lambda h: h["order_events"].pop(4))

    def test_attempts_completeness_and_review_consistency(self):
        self.assertTrue(any(r["decision"] == "rework" for r in self.history["reviews"]))
        self.invalid(lambda h: h["submissions"][0].update(attempt_number=7))
        self.invalid(lambda h: h["submissions"][0].update(assignment_revision=2))
        self.invalid(lambda h: h["submissions"][0].update(submitted_by=h["employees"][0]["id"]))
        self.invalid(lambda h: h["submissions"][0].update(completeness="incomplete"))
        self.invalid(lambda h: h["reviews"][0].update(created_at=START))
        self.invalid(lambda h: h["reviews"][0].update(reviewer_id=h["employees"][-1]["id"]))

    def test_photo_placeholders_are_honest_and_scoped(self):
        self.assertTrue(self.history["photos"])
        self.assertTrue(all(not p["artifact_available"] and p["evidence_kind"] == "synthetic_metadata_placeholder" for p in self.history["photos"]))
        self.invalid(lambda h: h["photos"][0].update(artifact_available=True))
        self.invalid(lambda h: h["photos"][0].update(owner_id=h["employees"][0]["id"]))
        self.invalid(lambda h: h["photos"][0].update(uploaded_at=END))
        self.invalid(lambda h: h["photos"][0].update(order_id=h["orders"][-1]["id"]))

    def test_absent_assessments_null_scores_retained(self):
        self.assertEqual(self.history["ai_assessments"], [])
        nulls = [r for r in self.history["reviews"] if r["final_score"] is None]
        self.assertGreater(len(nulls), 0)
        reread = json.loads(canonical_bytes(nulls))
        self.assertTrue(all(r["final_score"] is None for r in reread))

    def test_manifest_tamper_and_noncanonical_file(self):
        m = manifest(self.history)
        m["counts"]["orders"] += 1
        with self.assertRaises(ValidationError):
            validate_manifest(self.history, m)
        with self.assertRaises(ValidationError):
            validate_manifest(self.history, manifest(self.history), json.dumps(self.history).encode())

    def test_cli_exports_only_requested_files_and_no_runtime_effects(self):
        with tempfile.TemporaryDirectory(prefix="synthetic-unit-", dir=ROOT/"scripts/synthetic") as temp:
            output = Path(temp)/"history.json"
            command = [sys.executable, str(ROOT/"scripts/synthetic/generate.py"), "--output", str(output)]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(result.stdout)["evidence_level"], "synthetic_offline_only")
            self.assertEqual(output.read_bytes(), self.raw)
            self.assertEqual({p.name for p in Path(temp).iterdir()}, {"history.json", "history.manifest.json"})
            truth_output = Path(temp)/"evaluator"/"pattern_truth.json"
            subprocess.run(command+["--evaluator-output", str(truth_output)], capture_output=True, check=True)
            self.assertEqual(truth_output.read_bytes(), canonical_bytes(self.truth))
            self.assertEqual(json.loads(truth_output.with_name("pattern_truth.manifest.json").read_bytes()),
                             evaluator_manifest(self.history, self.truth))
            subprocess.run([sys.executable, str(ROOT/"scripts/synthetic/validate.py"), str(output),
                            "--manifest", str(output.with_name("history.manifest.json")),
                            "--evaluator-truth", str(truth_output)], capture_output=True, check=True)
            before = {p.name: p.read_bytes() for p in Path(temp).iterdir() if p.is_file()}
            for conflicting in (output, output.with_name("history.manifest.json")):
                bad = subprocess.run(command+["--evaluator-output", str(conflicting)], capture_output=True)
                self.assertNotEqual(bad.returncode, 0)
            self.assertEqual({p.name: p.read_bytes() for p in Path(temp).iterdir() if p.is_file()}, before)


if __name__ == "__main__":
    unittest.main()
