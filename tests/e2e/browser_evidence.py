#!/usr/bin/env python3
"""Manual assembled-browser evidence harness; never drives or simulates a browser.

prepare creates NOT_RUN records; validate checks structure and artifact integrity;
gate requires every case to be evidenced PASS. None independently attests truth.
No network, credentials, database access, browser package or deployment side effects.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MATRIX = HERE / "journeys.json"
CONTRACT = "coord/proposals/a6-contract-v1/contracts/openapi.yaml"
CONTRACT_SHA256 = "b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97"
STATUSES = {"PASS", "FAIL", "NOT_RUN", "BLOCKED"}
KINDS = {"ui", "browser_network", "backend_reference", "device"}
FORBIDDEN_KEYS = {"password", "pin", "token", "access_token", "csrf_token", "cookie", "cookies", "authorization", "storage_state", "credentials"}


class EvidenceError(ValueError):
    """Invalid preparation or an unsupported evidence claim."""


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(EvidenceError("Non-finite JSON number")))


def check_no_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            require(key.lower() not in FORBIDDEN_KEYS, "Secret-bearing fields are forbidden in evidence/config")
            check_no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            check_no_secrets(child)


def text(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name} is required")


def sha(value, name, size=40):
    require(isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{size}}}", value), f"{name} must be an exact {size}-hex digest")


def utc_timestamp(value, name):
    text(value, name)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceError(f"Invalid {name}") from error
    require(instant.tzinfo is not None and instant.utcoffset().total_seconds() == 0, f"{name} must include UTC offset")
    return instant


def uuid(value, name):
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise EvidenceError(f"{name} must be a provisioned synthetic UUID") from error
    require(parsed.int != 0, f"{name} cannot be a zero placeholder UUID")
    require(str(parsed) == value, f"{name} must use canonical lowercase hyphenated UUID form")


def validate_config(config):
    require(isinstance(config, dict), "Config must be an object")
    check_no_secrets(config)
    require(config.get("schema_version") == 1, "Config schema_version must be 1")
    require(config.get("synthetic_only") is True, "Synthetic-only attestation is required")
    require(config.get("isolated_test_target") is True, "An isolated test target is required")
    require(config.get("authentication") == "operator_browser_login", "Use operator browser login; no credentials/session files")
    url = urlsplit(config.get("base_url", ""))
    require(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password
            and not url.query and not url.fragment and url.path in ("", "/"),
            "base_url must be an explicit HTTPS origin without credentials, query or path")
    for name in ("frontend_sha", "backend_sha"):
        sha(config.get(name), name)
    for name in ("deployment_evidence", "provisioning_evidence", "test_namespace", "browser_name", "browser_version", "network_conditions", "domain_clock"):
        text(config.get(name), name)
    require(config.get("backend_mode") == "real_persistent_backend", "Mock or in-memory backends cannot prepare this suite")
    require(config.get("notifications") == "disabled_or_explicitly_authorized_test_recipients", "Notification safety attestation is required")
    require(config.get("external_model_calls") == "disabled_or_separately_authorized", "Provider/budget authorization cannot be implied")
    roles = config.get("roles")
    require(isinstance(roles, dict) and {"master", "executor"} <= roles.keys(), "Provision distinct master and executor sessions")
    expected = {"master": "master", "executor": "executor", "other_executor": "executor", "foreign_master": "master", "manager": "manager", "admin": "admin"}
    require(set(roles) <= expected.keys(), "Unknown role alias")
    identities = set()
    contexts = set()
    for alias, role in roles.items():
        require(isinstance(role, dict) and role.get("role") == expected[alias], f"Wrong role for {alias}")
        uuid(role.get("user_id"), f"roles.{alias}.user_id")
        text(role.get("browser_context"), f"roles.{alias}.browser_context")
        require(role["user_id"] not in identities, "Role aliases must have distinct identities")
        require(role["browser_context"] not in contexts, "Use separate browser contexts, not tabs sharing cookies")
        identities.add(role["user_id"])
        contexts.add(role["browser_context"])
        require(role.get("provisioned") is True, f"{alias} must be provisioned, not guessed")
        require(isinstance(role.get("section_ids"), list), f"{alias}.section_ids is required")
        for section in role["section_ids"]:
            uuid(section, f"{alias}.section_ids")
    require(set(roles["master"]["section_ids"]) & set(roles["executor"]["section_ids"]), "Master/executor must share the test section")
    if "foreign_master" in roles:
        require(not set(roles["foreign_master"]["section_ids"]) & set(roles["master"]["section_ids"]), "Foreign master must have disjoint section scope")
    device = config.get("physical_android")
    require(isinstance(device, bool), "physical_android must be explicit; emulation is false")
    if device:
        for name in ("device_model", "android_version", "device_operator"):
            text(config.get(name), name)
    return config


def read_matrix():
    matrix = load_json(MATRIX)
    require(matrix.get("contract_sha256") == CONTRACT_SHA256, "Matrix contract digest drift")
    require(digest((ROOT / CONTRACT).read_bytes()) == CONTRACT_SHA256, "Accepted contract bytes changed; obtain handshake before updating")
    ids = [case["id"] for case in matrix["cases"]]
    require(len(ids) == len(set(ids)), "Duplicate case IDs")
    for case in matrix["cases"]:
        checks = [check["id"] for check in case["checks"]]
        require(checks and len(checks) == len(set(checks)), "Duplicate or empty checks")
        require(bool(case["sources"]), "Each case needs source attribution")
        for check in case["checks"]:
            require(set(check["evidence_kinds"]) <= KINDS and bool(check["evidence_kinds"]), "Unknown evidence kind")
    return matrix


def fingerprint():
    """Pin committed harness+matrix bytes, never silently test an edited working tree."""
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    sha(commit, "harness commit")
    for path in (Path(__file__).resolve(), MATRIX):
        relative = path.relative_to(ROOT).as_posix()
        committed = subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
        require(committed == path.read_bytes(), "Commit harness and matrix before preparing evidence")
    return {"commit": commit, "script_sha256": digest(Path(__file__).read_bytes()), "matrix_sha256": digest(MATRIX.read_bytes())}


def verify_provenance(provenance):
    """Ensure a report commit actually contains the claimed harness/matrix bytes."""
    commit = provenance.get("commit")
    sha(commit, "harness.commit")
    for relative, key in (("tests/e2e/browser_evidence.py", "script_sha256"),
                          ("tests/e2e/journeys.json", "matrix_sha256")):
        committed = subprocess.check_output(["git", "show", f"{commit}:{relative}"], cwd=ROOT, stderr=subprocess.DEVNULL)
        require(digest(committed) == provenance.get(key), "Report commit does not contain the claimed harness bytes")


def prepare(config, matrix, provenance, now):
    validate_config(config)
    cases = []
    for case in matrix["cases"]:
        missing = sorted(set(case["roles"]) - config["roles"].keys())
        reason = "Not executed; an operator must run the assembled-product journey"
        if missing:
            reason += "; provision roles: " + ", ".join(missing)
        if case["physical_android"] and not config["physical_android"]:
            reason += "; physical Android required"
        cases.append({"id": case["id"], "status": "NOT_RUN", "reason": reason,
                      "executed_at": None, "operator": None,
                      "checks": [{"id": check["id"], "status": "NOT_RUN", "observation": "", "artifacts": [], "measurements": {}}
                                 for check in case["checks"]]})
    return {"schema_version": 1, "suite_id": matrix["suite_id"], "created_at": now,
            "harness": provenance, "contract_sha256": CONTRACT_SHA256,
            "deployment": config, "artifacts": [], "cases": cases}


def validate_report(report, matrix, report_dir):
    require(isinstance(report, dict), "Report must be an object")
    check_no_secrets(report)
    require(report.get("schema_version") == 1 and report.get("suite_id") == matrix["suite_id"], "Wrong evidence schema or suite")
    require(report.get("contract_sha256") == CONTRACT_SHA256, "Evidence contract digest mismatch")
    created = utc_timestamp(report.get("created_at"), "created_at")
    provenance = report.get("harness", {})
    sha(provenance.get("commit"), "harness.commit")
    require(provenance.get("script_sha256") == digest(Path(__file__).read_bytes()), "Evidence used a different harness; review the pinned version")
    require(provenance.get("matrix_sha256") == digest(MATRIX.read_bytes()), "Evidence used a different matrix")
    config = validate_config(report.get("deployment"))
    artifacts = report.get("artifacts")
    require(isinstance(artifacts, list), "artifacts must be a list")
    indexed = {}
    root = Path(report_dir).resolve()
    for artifact in artifacts:
        text(artifact.get("id"), "artifact.id")
        require(artifact["id"] not in indexed, "Duplicate artifact ID")
        require(artifact.get("kind") in KINDS, "Unknown artifact kind")
        require(artifact.get("sanitized") is True, "Only reviewed, sanitized evidence can be read")
        sha(artifact.get("sha256"), "artifact.sha256", 64)
        text(artifact.get("path"), "artifact.path")
        relative = Path(artifact["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "Artifact must stay relative to report directory")
        candidate = root / relative
        require(not any(parent.is_symlink() for parent in [candidate, *candidate.parents] if parent != root.parent), "Artifact symlinks are forbidden")
        path = candidate.resolve()
        require(path.is_relative_to(root) and path.is_file(), "Artifact file is missing or escaped its evidence directory")
        require(digest(path.read_bytes()) == artifact["sha256"], "Artifact digest mismatch")
        indexed[artifact["id"]] = artifact
    cases = report.get("cases")
    require(isinstance(cases, list), "cases must be a list")
    require(len(cases) == len(matrix["cases"]) and {case.get("id") for case in cases} == {case["id"] for case in matrix["cases"]}, "Evidence must contain every case exactly once")
    expected = {case["id"]: case for case in matrix["cases"]}
    for case in cases:
        spec = expected[case["id"]]
        status = case.get("status")
        require(status in STATUSES, f"Invalid status for {case['id']}")
        checks = case.get("checks")
        require(isinstance(checks, list) and len(checks) == len(spec["checks"]) and {check.get("id") for check in checks} == {check["id"] for check in spec["checks"]}, "Evidence must contain every check exactly once")
        if status in {"PASS", "FAIL"} or any(check.get("status") in {"PASS", "FAIL"} for check in checks):
            executed = utc_timestamp(case.get("executed_at"), "executed_at")
            require(executed >= created and executed <= datetime.now(timezone.utc), "Execution time is outside the run window")
            text(case.get("operator"), "operator")
        else:
            text(case.get("reason"), "Unrun/blocked reason")
        specs = {check["id"]: check for check in spec["checks"]}
        for check in checks:
            require(check.get("status") in STATUSES, "Invalid check status")
            require(isinstance(check.get("artifacts"), list), "Check artifact IDs must be a list")
            require(all(item in indexed for item in check["artifacts"]), "Referenced artifact does not exist")
            if check["status"] in {"PASS", "FAIL"}:
                text(check.get("observation"), "Executed check observation")
                kinds = {indexed[item]["kind"] for item in check["artifacts"]}
                require(set(specs[check["id"]]["evidence_kinds"]) <= kinds, f"Missing required evidence kinds for {check['id']}")
            if check["status"] == "PASS":
                limits = specs[check["id"]].get("maximums", {})
                measurements = check.get("measurements", {})
                for name, maximum in limits.items():
                    value = measurements.get(name)
                    require(type(value) in (int, float) and 0 <= value <= maximum, f"Missing/out-of-limit measured {name}")
        states = [check["status"] for check in checks]
        if status == "PASS":
            require(all(state == "PASS" for state in states), "A skipped, blocked or failed check cannot become a PASS case")
            require(set(spec["roles"]) <= config["roles"].keys(), "PASS requires all provisioned roles")
            require(not spec["physical_android"] or config["physical_android"], "Desktop emulation cannot satisfy physical Android")
        if status == "FAIL":
            require("FAIL" in states, "FAIL case needs an observed failed check")
        if status == "NOT_RUN":
            require(all(state == "NOT_RUN" for state in states), "NOT_RUN cannot conceal executed checks")
        require("FAIL" not in states or status == "FAIL", "An observed failure cannot be concealed as blocked/unrun")
    return dict(Counter(case["status"] for case in cases))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="Print NOT_RUN scope; never contacts deployment")
    start = commands.add_parser("prepare", help="Create an all-NOT_RUN report from nonsecret deployment attestation")
    start.add_argument("--config", type=Path, required=True)
    start.add_argument("--output", type=Path, required=True)
    for name in ("validate", "gate"):
        sub = commands.add_parser(name)
        sub.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        matrix = read_matrix()
        if args.command == "plan":
            print(json.dumps({"status": "NOT_RUN", "suite_id": matrix["suite_id"], "cases": len(matrix["cases"]), "reason": "No browser execution; prepare requires an explicit assembled deployment and provisioned synthetic roles"}, indent=2))
            return 0
        if args.command == "prepare":
            report = prepare(load_json(args.config), matrix, fingerprint(), datetime.now(timezone.utc).isoformat())
            # Create once: a preparation must never erase existing run evidence.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
            print(json.dumps({"status": "NOT_RUN", "cases": len(report["cases"]), "note": "Manifest prepared only; target/browser/session claims are operator attestations"}))
            return 0
        report = load_json(args.report)
        verify_provenance(report.get("harness", {}))
        counts = validate_report(report, matrix, args.report.parent)
        if args.command == "gate":
            passed = counts.get("PASS", 0) == len(matrix["cases"])
            print(json.dumps({"status": "EVIDENCED_PASS" if passed else "NOT_ACCEPTED", "counts": counts, "note": "Evidence validation cannot authenticate observations; independent review required"}))
            return 0 if passed else 1
        print(json.dumps({"status": "EVIDENCE_STRUCTURE_VALID", "counts": counts, "note": "This is not a browser test PASS"}))
        return 0
    except (EvidenceError, OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "NOT_ACCEPTED", "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
