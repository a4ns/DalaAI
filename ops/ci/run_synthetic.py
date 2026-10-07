#!/usr/bin/env python3
"""Run B's exact synthetic browser suite. Never claim actual API/DB or Android proof."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import hashlib
import shutil
import os
from pathlib import Path
import re
import subprocess
import tempfile

B_SHA = "2a12798c19a26b33aabd9ffd572b99586f80e2f1"
HARNESS_SHA = "9f37c2951cbffb88db8a254beff033f7e31ed6d9"
PROJECT = "android-emulation-pixel-9"
# Verified Git blob IDs of the only accepted harness changes. No branch overlay.
HARNESS_FILES = {
    "frontend/playwright.config.ts": "f244c2cce4c03672147e114e378238fd76809064",
    "frontend/tests/README.md": "e52845d96fa3bcc5680cc999d753f05af58334ab",
    "frontend/tests/browser/executor-synthetic.spec.ts": "40f915f4d9c40725adf8bc8ce242ee437d33add6",
    "frontend/tests/browser/shell.spec.ts": "e8b2925c1ad5416f9c40dde449b2ae3fc637b5aa",
    "frontend/tests/node/staged-receipt.spec.ts": "59c926c4122fd7a445f9e03d196cebcf0e79bcae",
}
EXPECTED = 13


def verify_report(data: dict) -> dict:
    rows = []
    def walk(suite):
        for spec in suite.get("specs", []):
            for test in spec.get("tests", []):
                rows.append(test)
        for child in suite.get("suites", []):
            walk(child)
    for suite in data.get("suites", []):
        walk(suite)
    if (data.get("errors") or len(rows) != EXPECTED
            or any(row.get("projectName") != PROJECT or row.get("expectedStatus") != "passed"
                   or row.get("status") != "expected" or len(row.get("results", [])) != 1
                   or row["results"][0].get("status") != "passed"
                   or row["results"][0].get("retry") != 0 for row in rows)):
        raise ValueError("B_SYNTHETIC_FAILED_OR_INCOMPLETE")
    return {"tests_passed": EXPECTED, "tests_failed": 0, "tests_skipped": 0}


def blob_id(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("B_HARNESS_INPUT_NOT_REGULAR_FILE")
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_head(source: Path, sha: str):
    actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True)
    if actual.returncode or actual.stdout.strip() != sha:
        raise ValueError("B_SOURCE_OR_HARNESS_SHA_MISMATCH")


def assemble_pair(source: Path, harness: Path, *, prepare: bool):
    verify_head(source, B_SHA)
    verify_head(harness, HARNESS_SHA)
    if source == harness or source in harness.parents or harness in source.parents:
        raise ValueError("B_PAIR_CHECKOUTS_MUST_BE_SEPARATE")
    for relative, expected in HARNESS_FILES.items():
        if blob_id(harness / relative) != expected:
            raise ValueError("B_ACCEPTED_HARNESS_BLOB_MISMATCH")
    changed = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", "frontend"], cwd=source, capture_output=True, text=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "frontend"], cwd=source, capture_output=True, text=True)
    if changed.returncode or untracked.returncode:
        raise ValueError("B_PAIR_SOURCE_STATUS_UNAVAILABLE")
    differences = set(changed.stdout.splitlines()) | set(untracked.stdout.splitlines())
    if differences - HARNESS_FILES.keys():
        raise ValueError("B_SOURCE_HAS_UNAPPROVED_CHANGES")
    if prepare and not differences:
        for relative in HARNESS_FILES:
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(harness / relative, target)
    for relative, expected in HARNESS_FILES.items():
        if blob_id(source / relative) != expected:
            raise ValueError("B_SOURCE_PAIR_NOT_ASSEMBLED_EXACTLY")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Separate exact B commit checkout")
    parser.add_argument("--harness-source", type=Path, required=True, help="Separate exact B harness checkout")
    parser.add_argument("--prepare-only", action="store_true", help="Copy only the five verified harness files into the disposable source checkout")
    parser.add_argument("--report", type=Path, default=Path("b-synthetic-summary.json"))
    args = parser.parse_args()
    source = args.source.resolve()
    report = {"schema_version": 1, "status": "BLOCKED_NOT_RUN", "stage": "exact_b_source",
              "source_sha": B_SHA, "harness_sha": HARNESS_SHA, "project": PROJECT,
              "workflow_sha": os.environ.get("GITHUB_SHA", "UNRECORDED"),
              "observed_at": datetime.now(timezone.utc).isoformat(),
              "evidence_level": "B_SYNTHETIC_RENDERING_PIXEL9_ANDROID14_EMULATION",
              "real_api_db_core": "NOT_RUN", "android_emulation": "NOT_RUN",
              "emulation_descriptor": {"device": "Pixel 9", "viewport": {"width": 360, "height": 732}, "touch": True, "dpr": 3},
              "physical_android": "NOT_RUN", "real_push_delivery": "NOT_RUN",
              "full_cycle_green": False, "deployment_performed": False}
    result = 1
    try:
        assemble_pair(source, args.harness_source.resolve(), prepare=args.prepare_only)
        if args.prepare_only:
            print("PASS: exact B product/harness pair assembled from five verified harness blobs")
            return 0
        frontend = source / "frontend"
        cli = frontend / "node_modules/@playwright/test/cli.js"
        if not cli.is_file():
            raise ValueError("B_LOCKED_PLAYWRIGHT_NOT_INSTALLED")
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "CI", "PLAYWRIGHT_BROWSERS_PATH"}}
        env.update(CI="1", UI_TEST_PORT="4176", UI_REVIEW_SHA=f"product:{B_SHA};harness:{HARNESS_SHA}")
        report["stage"] = "synthetic_browser"
        report["android_emulation"] = "ATTEMPTED_NOT_CONFIRMED"
        with tempfile.TemporaryDirectory(prefix="dalaai-b-synthetic-") as temp:
            process = subprocess.run(["node", str(cli), "test", "--project", PROJECT,
                                      "--reporter", "json", "--trace", "off", "--output", temp],
                                     cwd=frontend, env=env, capture_output=True, timeout=300, text=True)
            # Raw report/stderr may contain arbitrary assertion data. Never save or print it.
            data = json.loads(process.stdout)
            report.update(verify_report(data))
            if process.returncode:
                raise ValueError("B_PLAYWRIGHT_NONZERO_EXIT")
        report["status"] = "PASS_B_SYNTHETIC_ANDROID_EMULATION_ONLY"
        report["android_emulation"] = "PASS_SYNTHETIC_FIXTURES_ONLY"
        report["stage"] = "completed"
        result = 0
    except ValueError as error:
        reason = str(error)
        report["reason_code"] = reason if re.fullmatch(r"[A-Z_]+", reason) else "B_REPORT_UNAVAILABLE_OR_INVALID"
        report["status"] = "FAIL" if report["stage"] == "synthetic_browser" else "BLOCKED_NOT_RUN"
    except Exception as error:
        report["status"] = "FAIL"
        report["reason_code"] = "B_RUNNER_FAILURE"
        report["error_type"] = type(error).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
