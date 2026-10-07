"""Harness-unit checks only: fabricated metadata is never product/browser evidence."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import browser_evidence as h


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.matrix = h.read_matrix()
        self.directory = tempfile.TemporaryDirectory(prefix="unit-evidence-", dir=h.HERE)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {
            "schema_version": 1, "base_url": "https://unit-fixture.invalid",
            "frontend_sha": "a" * 40, "backend_sha": "b" * 40,
            "deployment_evidence": "Unit metadata fixture only", "provisioning_evidence": "Unit metadata fixture only",
            "test_namespace": "unit-metadata-no-service", "synthetic_only": True,
            "isolated_test_target": True, "backend_mode": "real_persistent_backend",
            "authentication": "operator_browser_login", "notifications": "disabled_or_explicitly_authorized_test_recipients",
            "external_model_calls": "disabled_or_separately_authorized",
            "browser_name": "Unit fixture, not a browser", "browser_version": "not run",
            "network_conditions": "No network", "domain_clock": "not run", "physical_android": False,
            "roles": {
                "master": {"role": "master", "user_id": "10000000-0000-4000-8000-000000000001", "section_ids": ["20000000-0000-4000-8000-000000000001"], "browser_context": "unit-master", "provisioned": True},
                "executor": {"role": "executor", "user_id": "10000000-0000-4000-8000-000000000002", "section_ids": ["20000000-0000-4000-8000-000000000001"], "browser_context": "unit-executor", "provisioned": True},
            },
        }
        self.provenance = {"commit": "c" * 40, "script_sha256": h.digest(Path(h.__file__).read_bytes()), "matrix_sha256": h.digest(h.MATRIX.read_bytes()), "push_protocol_sha256": h.digest(h.PUSH_PROTOCOL.read_bytes())}
        self.report = h.prepare(self.config, self.matrix, self.provenance, "2026-10-07T00:00:00Z")

    def validate(self):
        return h.validate_report(self.report, self.matrix, self.root)

    def test_preparation_is_entirely_not_run(self):
        self.assertEqual(self.validate(), {"NOT_RUN": 18})
        self.assertTrue(all(check["status"] == "NOT_RUN" for case in self.report["cases"] for check in case["checks"]))

    def test_example_requires_real_provisioning(self):
        with self.assertRaises(h.EvidenceError):
            h.validate_config(h.load_json(h.HERE / "deployment.example.json"))

    def test_plan_checks_pinned_contract_and_case_sources(self):
        self.assertEqual(len(self.matrix["cases"]), 18)
        for case in self.matrix["cases"]:
            self.assertTrue(set(case["sources"]) <= self.matrix["sources"].keys())
        with patch.object(h, "CONTRACT_SHA256", "0" * 64):
            with self.assertRaises(h.EvidenceError):
                h.read_matrix()

    def test_no_mock_or_in_memory_backend(self):
        for mode in ("mock", "memory", None):
            self.config["backend_mode"] = mode
            with self.assertRaises(h.EvidenceError):
                h.validate_config(self.config)

    def test_no_implicit_authentication_or_credentials(self):
        self.config["authentication"] = "storage_state"
        with self.assertRaises(h.EvidenceError):
            h.validate_config(self.config)
        self.config["authentication"] = "operator_browser_login"
        self.config["roles"]["master"]["password"] = "unit-sentinel-not-a-password"
        with self.assertRaises(h.EvidenceError):
            h.validate_config(self.config)

    def test_explicit_isolated_https_origin(self):
        for url in (None, "", "http://127.0.0.1:8000", "https://user:secret@example.invalid", "https://example.invalid/?token=x", "https://example.invalid/#token", "https://example.invalid/api"):
            self.config["base_url"] = url
            with self.assertRaises(h.EvidenceError):
                h.validate_config(self.config)

    def test_sessions_are_distinct_profiles_not_shared_tabs(self):
        self.config["roles"]["executor"]["browser_context"] = "unit-master"
        with self.assertRaises(h.EvidenceError):
            h.validate_config(self.config)

    def test_roles_must_be_provisioned_and_unique(self):
        for update in ({"provisioned": False}, {"user_id": self.config["roles"]["master"]["user_id"]}, {"user_id": "0" * 32}, {"role": "master"}):
            config = copy.deepcopy(self.config)
            config["roles"]["executor"].update(update)
            with self.assertRaises(h.EvidenceError):
                h.validate_config(config)

    def test_same_uuid_different_case_cannot_bypass_identity_separation(self):
        identity = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        self.config["roles"]["master"]["user_id"] = identity
        self.config["roles"]["executor"]["user_id"] = identity.upper()
        with self.assertRaisesRegex(h.EvidenceError, "canonical lowercase"):
            h.validate_config(self.config)

    def test_scope_uuids_cannot_bypass_comparison_with_alternate_spelling(self):
        section = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        self.config["roles"]["master"]["section_ids"] = [section]
        self.config["roles"]["executor"]["section_ids"] = [section]
        self.config["roles"]["foreign_master"] = {
            "role": "master", "user_id": "10000000-0000-4000-8000-000000000003",
            "section_ids": [section.upper()], "browser_context": "unit-foreign", "provisioned": True}
        with self.assertRaisesRegex(h.EvidenceError, "canonical lowercase"):
            h.validate_config(self.config)
        self.config["roles"]["foreign_master"]["section_ids"] = [section.replace("-", "")]
        with self.assertRaisesRegex(h.EvidenceError, "canonical lowercase"):
            h.validate_config(self.config)

    def test_empty_sections_do_not_pass(self):
        self.config["roles"]["executor"]["section_ids"] = []
        with self.assertRaises(h.EvidenceError):
            h.validate_config(self.config)

    def test_partial_provisioning_does_not_skip_missing_cases(self):
        case = next(case for case in self.report["cases"] if case["id"] == "C5-B03")
        self.assertIn("provision roles:", case["reason"])
        self.assertEqual(case["status"], "NOT_RUN")
        self.assertEqual(len(self.report["cases"]), 18)

    def test_skip_or_missing_case_cannot_be_green(self):
        self.report["cases"][0]["status"] = "SKIPPED"
        with self.assertRaises(h.EvidenceError):
            self.validate()
        self.report["cases"].pop(0)
        with self.assertRaises(h.EvidenceError):
            self.validate()

    def test_case_pass_cannot_hide_unrun_checks(self):
        case = self.report["cases"][0]
        case.update(status="PASS", executed_at="2026-10-07T00:01:00Z", operator="unit-check-only")
        with self.assertRaisesRegex(h.EvidenceError, "skipped, blocked or failed"):
            self.validate()

    def test_observation_without_artifact_is_not_evidence(self):
        check = self.report["cases"][0]["checks"][0]
        check.update(status="PASS", observation="Fabricated unit metadata")
        with self.assertRaises(h.EvidenceError):
            self.validate()

    def test_future_execution_cannot_be_evidence(self):
        self.report["cases"][0].update(status="FAIL", executed_at="2999-01-01T00:00:00Z", operator="unit-only")
        with self.assertRaisesRegex(h.EvidenceError, "run window"):
            self.validate()

    def test_physical_android_requires_device_details(self):
        self.config["physical_android"] = True
        with self.assertRaises(h.EvidenceError):
            h.validate_config(self.config)

    def artifact(self, name="observation.txt"):
        data = b"Unit metadata fixture, no browser executed.\n"
        (self.root / name).write_bytes(data)
        artifact = {"id": "unit-observation", "kind": "ui", "path": name, "sha256": h.digest(data), "sanitized": True}
        self.report["artifacts"].append(artifact)
        return artifact

    def test_sanitized_artifact_hash_checked(self):
        artifact = self.artifact()
        self.validate()
        artifact["sha256"] = "d" * 64
        with self.assertRaisesRegex(h.EvidenceError, "digest mismatch"):
            self.validate()

    def test_unreviewed_artifacts_not_opened(self):
        artifact = self.artifact()
        artifact["sanitized"] = False
        with self.assertRaisesRegex(h.EvidenceError, "sanitized"):
            self.validate()

    def test_path_traversal_and_symlinks_rejected(self):
        artifact = self.artifact()
        artifact["path"] = "../escape.txt"
        with self.assertRaises(h.EvidenceError):
            self.validate()
        link = self.root / "link.txt"
        link.symlink_to(self.root / "observation.txt")
        artifact["path"] = "link.txt"
        with self.assertRaisesRegex(h.EvidenceError, "symlinks"):
            self.validate()

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        for source in ('{"status":"FAIL","status":"PASS"}', '{"duration":NaN}'):
            path = self.root / "bad.json"
            path.write_text(source)
            with self.assertRaises(h.EvidenceError):
                h.load_json(path)

    def test_matrix_and_harness_hashes_cannot_drift(self):
        self.report["harness"]["matrix_sha256"] = "e" * 64
        with self.assertRaises(h.EvidenceError):
            self.validate()

    def test_gate_for_prepared_report_is_nonzero(self):
        path = self.root / "run.json"
        path.write_text(json.dumps(self.report))
        with patch.object(h, "verify_provenance"):
            self.assertEqual(h.main(["gate", "--report", str(path)]), 1)
            self.assertEqual(h.main(["validate", "--report", str(path)]), 0)

    def test_commit_must_contain_claimed_harness(self):
        with patch.object(h.subprocess, "check_output", return_value=b"different committed bytes"):
            with self.assertRaisesRegex(h.EvidenceError, "claimed harness bytes"):
                h.verify_provenance(self.provenance)

    def test_blocked_case_with_observation_still_needs_execution_metadata(self):
        self.report["cases"][0]["status"] = "BLOCKED"
        self.report["cases"][0]["checks"][0]["status"] = "PASS"
        with self.assertRaisesRegex(h.EvidenceError, "executed_at"):
            self.validate()

    def test_push_source_and_three_exact_additive_routes(self):
        protocol = h.load_json(h.PUSH_PROTOCOL)
        self.assertEqual(protocol["source"]["author"], "a4ns")
        self.assertEqual(protocol["source"]["event_id"], "A0-0031")
        self.assertEqual(protocol["source"]["url"], "https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046265475")
        self.assertEqual(protocol["core_contract_sha256"], h.CONTRACT_SHA256)
        self.assertEqual([(protocol[name]["method"], protocol[name]["path"]) for name in ("config", "registration", "removal")], [
            ("GET", "/api/v1/push/config"), ("POST", "/api/v1/push/subscriptions"),
            ("POST", "/api/v1/push/subscriptions/remove")])

    def test_push_disabled_config_and_configured_response_are_distinct(self):
        protocol = h.load_json(h.PUSH_PROTOCOL)
        self.assertEqual(protocol["config"]["disabled_shape"], {
            "enabled": False, "application_server_key": None,
            "delivery_semantics": "provider_acceptance_is_not_device_delivery",
            "device_policy": "latest_registration_per_user"})
        self.assertEqual(protocol["registration"]["response"], {"enabled": True})
        self.assertNotIn("delivered", protocol["registration"]["response"])
        self.assertEqual(protocol["live_permission_subscription_delivery"], "NOT_RUN")

    def test_push_json_fields_do_not_invent_domain_receipts(self):
        protocol = h.load_json(h.PUSH_PROTOCOL)
        registration = protocol["registration"]
        self.assertEqual(registration["required_body_fields"], ["endpoint", "keys"])
        self.assertEqual(registration["optional_body_fields"], ["expirationTime"])
        self.assertIsNone(registration["expirationTime"])
        self.assertEqual(registration["keys_fields"], ["p256dh", "auth"])
        self.assertEqual(protocol["removal"]["body_fields"], ["endpoint"])
        self.assertEqual(protocol["removal"]["status"], 204)
        self.assertIsNone(protocol["removal"]["response_body"])

    def test_push_conflict_and_disabled_retryability_are_preserved(self):
        errors = {entry["code"]: entry for entry in h.load_json(h.PUSH_PROTOCOL)["errors"]}
        self.assertEqual(errors["SUBSCRIPTION_CONFLICT"]["status"], 409)
        self.assertEqual(errors["PUSH_DISABLED"]["status"], 503)
        self.assertIs(errors["PUSH_DISABLED"]["retryable"], False)
        self.assertIs(errors["TEMPORARILY_UNAVAILABLE"]["retryable"], True)
        self.assertEqual(errors["PAYLOAD_TOO_LARGE"]["condition"], "above 4096 bytes")

    def test_push_worker_payload_is_exact_and_minimal(self):
        self.assertEqual(h.load_json(h.PUSH_PROTOCOL)["service_worker_payload"], {
            "v": 1, "title": "НарядAI", "body": "Есть обновление наряда. Откройте приложение.",
            "url": "/", "tag": "naryadai-update"})
        physical = next(case for case in self.matrix["cases"] if case["id"] == "C5-D03")
        self.assertTrue(physical["physical_android"])
        self.assertIn("push_wire", physical["sources"])

    def test_six_push_cases_cannot_be_silently_skipped(self):
        pushes = [case for case in self.report["cases"] if case["id"].startswith("C5-P")]
        self.assertEqual(len(pushes), 6)
        self.assertTrue(all(case["status"] == "NOT_RUN" for case in pushes))
        self.report["cases"] = [case for case in self.report["cases"] if not case["id"].startswith("C5-P")]
        with self.assertRaisesRegex(h.EvidenceError, "every case"):
            self.validate()

    def test_additive_protocol_report_and_provenance_pins_cannot_drift(self):
        self.report["harness"]["push_protocol_sha256"] = "f" * 64
        with self.assertRaisesRegex(h.EvidenceError, "different push protocol"):
            self.validate()
        self.report["harness"]["push_protocol_sha256"] = h.digest(h.PUSH_PROTOCOL.read_bytes())
        self.report["additive_protocols"] = []
        with self.assertRaisesRegex(h.EvidenceError, "additive protocol pin"):
            self.validate()

    def test_edited_protocol_bytes_require_new_matrix_pin(self):
        changed = self.root / "protocol.json"
        changed.write_bytes(h.PUSH_PROTOCOL.read_bytes() + b" ")
        with patch.object(h, "PUSH_PROTOCOL", changed):
            with self.assertRaisesRegex(h.EvidenceError, "protocol digest drift"):
                h.read_matrix()

    def test_measured_target_requires_number_not_boolean(self):
        # Minimal synthetic specification exercises the validator, not C5 outcomes.
        case = self.report["cases"][0]
        self.matrix = copy.deepcopy(self.matrix)
        self.matrix["cases"] = [self.matrix["cases"][0]]
        self.report["cases"] = [case]
        case["checks"] = [case["checks"][0]]
        self.matrix["cases"][0]["checks"] = [self.matrix["cases"][0]["checks"][0]]
        spec = self.matrix["cases"][0]["checks"][0]
        spec.update(evidence_kinds=["ui"], maximums={"elapsed_ms": 10})
        self.artifact()
        case.update(status="PASS", executed_at="2026-10-07T00:01:00Z", operator="unit-fixture")
        check = case["checks"][0]
        check.update(status="PASS", observation="Unit validator probe only", artifacts=["unit-observation"])
        for measurements in ({}, {"elapsed_ms": True}, {"elapsed_ms": 11}, {"elapsed_ms": -1}):
            check["measurements"] = measurements
            with self.assertRaises(h.EvidenceError):
                self.validate()
        check["measurements"] = {"elapsed_ms": 7}
        self.assertEqual(self.validate(), {"PASS": 1})  # Unit-only structural acceptance.
        self.matrix["cases"][0]["physical_android"] = True
        with self.assertRaisesRegex(h.EvidenceError, "Desktop emulation"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
