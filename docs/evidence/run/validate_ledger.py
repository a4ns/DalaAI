#!/usr/bin/env python3
"""Validate C-106 documentation evidence only; never execute application tests."""
import hashlib
import json
from datetime import datetime
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
LEDGER = ROOT / "docs/evidence/run/c-106.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESULTS = {"PASS", "FAIL", "NOT_RUN", "BLOCKED"}
LAYERS = {"documentation", "source_inspection", "process_http", "synthetic_unit",
          "mock", "real_database", "browser_assembled", "real_model",
          "physical_device", "push_delivery", "timed_rehearsal", "recorded_video"}
REQUIRED = {"id", "requirement", "layer", "source_sha", "tested_checkout_sha",
            "executed_at", "result", "environment", "procedure", "expected",
            "observed", "artifact", "artifact_sha256", "limitation", "reviewer"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def local_file(relative):
    require(isinstance(relative, str), "Artifact path must be a string")
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts, "Unsafe artifact path")
    require(relative.startswith("docs/evidence/run/"), "Artifact outside evidence scope")
    resolved = (ROOT / path).resolve()
    require(resolved.is_relative_to(ROOT / "docs/evidence/run"), "Artifact escapes scope")
    require(resolved.is_file(), f"Missing artifact: {relative}")
    return resolved


def main():
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    require(ledger["schema_version"] == 1, "Unsupported ledger version")
    source_sha = ledger["source_sha"]
    require(SHA.fullmatch(source_sha), "Source must be a full commit SHA")
    require(ledger["task"] == "C-106" and ledger["generation"] == 1, "Wrong task")
    contract = ledger["contract"]
    require(contract["path"] == "coord/proposals/a6-contract-v1/contracts/openapi.yaml",
            "Unexpected contract path")
    source_contract = subprocess.check_output(
        ["git", "show", f"{source_sha}:{contract['path']}"], cwd=ROOT)
    require(hashlib.sha256(source_contract).hexdigest() == contract["sha256"],
            "Contract hash does not match pinned source")
    source_paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", source_sha], cwd=ROOT, text=True).splitlines()
    for path in ledger["inspected_source_paths"]:
        require(path in source_paths, f"Source path absent at SHA: {path}")
    entries = ledger["entries"]
    require(entries and isinstance(entries, list), "Empty ledger")
    seen = set()
    for entry in entries:
        eid = entry.get("id", "missing-id")
        require(set(entry) == REQUIRED, f"Wrong fields: {eid}")
        require(eid not in seen, f"Duplicate ID: {eid}")
        seen.add(eid)
        require(entry["source_sha"] == source_sha, f"Mismatched source SHA: {eid}")
        require(entry["layer"] in LAYERS, f"Unknown layer: {eid}")
        require(entry["result"] in RESULTS, f"Unknown status: {eid}")
        for key in ("requirement", "procedure", "expected", "limitation", "reviewer"):
            require(isinstance(entry[key], str) and entry[key].strip(), f"Missing {key}: {eid}")
        require(isinstance(entry["environment"], dict) and entry["environment"],
                f"Missing environment: {eid}")
        if entry["result"] == "NOT_RUN":
            require(all(entry[key] is None for key in (
                "tested_checkout_sha", "executed_at", "observed", "artifact", "artifact_sha256")),
                f"NOT_RUN has executed evidence: {eid}")
            continue
        require(isinstance(entry["tested_checkout_sha"], str)
                and SHA.fullmatch(entry["tested_checkout_sha"]), f"Missing checkout SHA: {eid}")
        timestamp = datetime.fromisoformat(entry["executed_at"].replace("Z", "+00:00"))
        require(timestamp.utcoffset() is not None, f"Naive timestamp: {eid}")
        require(isinstance(entry["observed"], str) and entry["observed"].strip(),
                f"Missing observation: {eid}")
        require(isinstance(entry["artifact_sha256"], str)
                and SHA256.fullmatch(entry["artifact_sha256"]), f"Missing artifact hash: {eid}")
        artifact = local_file(entry["artifact"])
        require(hashlib.sha256(artifact.read_bytes()).hexdigest() == entry["artifact_sha256"],
                f"Artifact hash mismatch: {eid}")
    for filename in ("README.md", "PITCH_RU.md", "DEVICE_REHEARSAL_RU.md"):
        text = (ROOT / "docs/demo" / filename).read_text(encoding="utf-8")
        require(source_sha in text, f"Unpinned demo document: {filename}")
    counts = {result: sum(e["result"] == result for e in entries) for result in sorted(RESULTS)}
    print("PASS: documentation ledger structure, source paths, contract hash and artifact hashes")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    print("Scope: documentation validation only; no product or device acceptance")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from None
