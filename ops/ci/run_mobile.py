#!/usr/bin/env python3
"""Run the fail-closed C-110 Android-emulation gate on disposable real Compose services."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from uuid import uuid4

from fixtures import ORIGIN, prepare_private, prepare_credentials, prepare_tls, write_private
from c110_driver import C110Error, verify_service_inventory, verify_started_inventory, verify_source_blobs, verify_frontend_provenance, secrecy_preflight, observer_dsn, execute_core, TITLE

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BASE_INPUTS = (
    "frontend/package.json", "frontend/package-lock.json", "frontend/src",
    "backend/app/main.py", "ops/demo/compose.yaml", "ops/demo/Dockerfile.api",
    "ops/demo/Dockerfile.web", "ops/demo/entrypoint.py", "ops/demo/setup.py",
    "ops/provision/provision_synthetic_demo.py", "ops/provision/enable_photo_capability.py",
)


class GateError(RuntimeError):
    """Messages must be static codes, never subprocess exception bodies."""


def owned_source(relative: str) -> Path:
    result = (ROOT / relative).resolve()
    if not result.is_relative_to(ROOT):
        raise GateError("SOURCE_PATH_OUTSIDE_REPOSITORY")
    return result


def contract_inputs() -> dict:
    contract = json.loads((HERE / "scenarios.json").read_text())
    if contract.get("accepted") is not True:
        raise GateError("C110_SCENARIOS_NOT_ACCEPTED")
    if contract.get("required_test_title") != TITLE or contract.get("expected_test_count") != 1:
        raise GateError("C110_EXACT_JOURNEY_CONTRACT_REQUIRED")
    if contract.get("config_path") != "tests/e2e/c110_playwright.config.cjs" or contract.get("project") != "c110-android-chromium":
        raise GateError("C110_EXACT_REVIEWED_CONFIG_REQUIRED")
    if not re.fullmatch(r"[a-f0-9]{40}", contract.get("frontend_sha", "")) or not re.fullmatch(r"[a-f0-9]{40}", contract.get("c110_source_sha", "")):
        raise GateError("C110_ACCEPTED_SOURCE_SHAS_REQUIRED")
    inputs = [*BASE_INPUTS, *contract.get("required_source_files", []), contract["config_path"],
              f'{contract["package_dir"]}/package.json', f'{contract["package_dir"]}/package-lock.json']
    if any(not owned_source(name).exists() for name in inputs):
        raise GateError("REQUIRED_SOURCE_INPUT_MISSING")
    package = json.loads(owned_source(f'{contract["package_dir"]}/package.json').read_text())
    dependencies = dict(package.get("dependencies", {}), **package.get("devDependencies", {}))
    if not re.fullmatch(r"\d+\.\d+\.\d+", dependencies.get("@playwright/test", "")):
        raise GateError("PLAYWRIGHT_VERSION_MUST_BE_EXACT")
    contract["playwright_version"] = dependencies["@playwright/test"]
    verify_source_blobs(ROOT, contract.get("c110_source_blobs", {}))
    return contract


def verify_results(data: dict, contract: dict) -> dict:
    rows = data.get("results", [])
    count = contract["expected_test_count"]
    good = (data.get("status") == "passed" and data.get("errors") == 0
            and data.get("discovered") == count and len(rows) == count
            and all(row.get("status") == "passed" and row.get("expected_status") == "passed"
                    and row.get("retry") == 0 for row in rows))
    occurrences = {required: sum(required in row.get("ids", []) for row in rows)
                   for required in contract["required_test_ids"]}
    good = good and all(value == 1 for value in occurrences.values())
    if not good:
        raise GateError("C110_CORE_GATE_FAILED_OR_INCOMPLETE")
    return {"tests_passed": count, "tests_skipped": 0, "tests_failed": 0,
            "required_test_ids": list(occurrences)}


def clean_environment() -> dict:
    # Do not pass account/provider credentials to a disposable app or browser.
    keep = {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "DOCKER_HOST", "DOCKER_CONTEXT",
            "DOCKER_CONFIG", "XDG_RUNTIME_DIR", "SYSTEMROOT", "COMSPEC", "CI", "PLAYWRIGHT_BROWSERS_PATH"}
    return {key: value for key, value in os.environ.items() if key in keep}


def command(argv: list[str], *, env: dict, timeout: int = 600) -> int:
    process = subprocess.run(argv, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, timeout=timeout, check=False)
    # Do not persist raw stdout/stderr: tool/test errors can include credentials.
    return process.returncode


def require_success(argv: list[str], *, env: dict, code: str, timeout: int = 600) -> None:
    if command(argv, env=env, timeout=timeout):
        raise GateError(code)


def compose_command(project: str) -> list[str]:
    if not re.fullmatch(r"dalaai-ci-[a-f0-9]{16}", project):
        raise GateError("INVALID_DISPOSABLE_PROJECT")
    return ["docker", "compose", "--project-name", project, "--project-directory", str(ROOT / "ops/demo"),
            "-f", str(ROOT / "ops/demo/compose.yaml"), "-f", str(HERE / "compose.override.yaml")]


def public_fixture(target: Path) -> None:
    file = ROOT / "ops/provision/provision_synthetic_demo.py"
    spec = importlib.util.spec_from_file_location("ci_synthetic_fixture", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    write_private(target, json.dumps(module.public_manifest(), ensure_ascii=False))


def wait_ready(ca: Path) -> None:
    context = ssl.create_default_context(cafile=str(ca))
    deadline = time.monotonic() + 120
    # No proxy or global trust-store edit. Hostname and certificate checks remain on.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
    while time.monotonic() < deadline:
        try:
            with opener.open(ORIGIN + "/readyz", timeout=5) as response:
                body = json.loads(response.read())
                if response.status == 200 and body.get("status") in {"ok", "ready"}:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise GateError("TRUSTED_HTTPS_READINESS_FAILED")


def source_hash() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    value = result.stdout.strip()
    if result.returncode or not re.fullmatch(r"[a-f0-9]{40}", value):
        raise GateError("EXACT_SOURCE_SHA_UNAVAILABLE")
    if os.environ.get("GITHUB_SHA") and value != os.environ["GITHUB_SHA"]:
        raise GateError("CHECKOUT_SHA_MISMATCH")
    changed = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "backend", "frontend", "ops", "tests/e2e", ".github/workflows/mobile-e2e.yml"], cwd=ROOT, capture_output=True)
    if changed.returncode:
        raise GateError("SOURCE_WORKTREE_DIFFERS_FROM_SHA")
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "backend", "frontend", "ops", "tests/e2e", ".github/workflows/mobile-e2e.yml"], cwd=ROOT, capture_output=True, text=True)
    if untracked.returncode or untracked.stdout.strip():
        raise GateError("SOURCE_HAS_UNTRACKED_INPUTS")
    return value


def run_gate(report: dict, contract: dict) -> None:
    for tool in ("docker", "node", "openssl", "certutil"):
        if not shutil.which(tool):
            raise GateError("REQUIRED_RUNNER_TOOL_MISSING")
    if (ROOT / "mobile-ci-evidence.json").exists():
        raise GateError("C110_PUBLIC_EVIDENCE_OUTPUT_MUST_BE_FRESH")
    report["source_sha"] = source_hash()
    report["playwright_version"] = contract["playwright_version"]
    report["frontend_sha"] = contract["frontend_sha"]
    report["accepted_c110_source_sha"] = contract["c110_source_sha"]
    reference = ROOT / ".ci-c110-frontend-reference"
    verify_frontend_provenance(ROOT, reference, contract["frontend_sha"])
    package_dir = owned_source(contract["package_dir"])
    cli = package_dir / "node_modules/@playwright/test/cli.js"
    if not cli.is_file():
        raise GateError("LOCKED_PLAYWRIGHT_DEPENDENCIES_NOT_INSTALLED")
    project = "dalaai-ci-" + uuid4().hex[:16]
    env = clean_environment()
    if env.get("DOCKER_HOST", "unix:///var/run/docker.sock") != "unix:///var/run/docker.sock" or env.get("DOCKER_CONTEXT", "default") != "default":
        raise GateError("DISPOSABLE_GATE_REQUIRES_LOCAL_DEFAULT_DOCKER")
    env["DOCKER_HOST"] = "unix:///var/run/docker.sock"
    original_home = Path(env.get("HOME", str(Path.home())))
    compose = compose_command(project)
    with tempfile.TemporaryDirectory(prefix="dalaai-mobile-ci-") as temp:
        private = Path(temp) / "private"
        prepare_private(private, credentials=False)
        prepare_tls(private)
        env.update(DALA_CI_PRIVATE_DIR=str(private), DALA_CI_SOURCE_DIR=str(HERE),
                   DALA_DOMAIN="localhost", DALA_ALLOWED_ORIGIN=ORIGIN,
                   DALA_BIND_ADDRESS="127.0.0.1", DALA_HTTP_PORT="18080", DALA_HTTPS_PORT="18443")
        browser_env = dict(env)
        browser_env.update(
            HOME=str(private / "browser-home"),
            XDG_CONFIG_HOME=str(private / "browser-home/.config"),
            XDG_DATA_HOME=str(private / "browser-home/.local/share"),
            NODE_EXTRA_CA_CERTS=str(private / "tls/root.crt"),
            SSL_CERT_FILE=str(private / "tls/root.crt"),
            PLAYWRIGHT_BROWSERS_PATH=env.get("PLAYWRIGHT_BROWSERS_PATH", str(original_home / ".cache/ms-playwright")),
            DALA_C110_PLAYWRIGHT_PACKAGE=str(package_dir / "node_modules/@playwright/test"),
            DALA_E2E_FRONTEND_SHA=contract["frontend_sha"],
        )
        report["stage"] = "c110_dummy_secret_preflight"
        proof = secrecy_preflight(ROOT, browser_env, private)
        report["secrecy_preflight"] = proof["public"]
        # Only after the source-bound dummy-failure test has passed do we supply
        # fixture/PIN/observer fields to the real core process.
        prepare_credentials(private)
        public_fixture(private / "fixture.json")
        attempted_start = False
        try:
            report["stage"] = "compose_config"
            require_success([*compose, "config", "--quiet"], env=env, code="COMPOSE_CONFIG_FAILED")
            config = subprocess.run([*compose, "config", "--format", "json"], cwd=ROOT, env=env, capture_output=True, check=False)
            if config.returncode:
                raise GateError("COMPOSE_CONFIG_UNAVAILABLE")
            report["worker_absence_service_inventory"] = verify_service_inventory(json.loads(config.stdout))
            report["stage"] = "compose_build_start"
            attempted_start = True
            require_success([*compose, "up", "--build", "--detach", "--wait", "--wait-timeout", "180", "api", "web"],
                            env=env, code="COMPOSE_BUILD_OR_START_FAILED", timeout=900)
            inventory = subprocess.run([*compose, "ps", "--all", "--format", "json"], cwd=ROOT, env=env, capture_output=True, check=False)
            if inventory.returncode:
                raise GateError("C110_ACTUAL_COMPOSE_INVENTORY_UNAVAILABLE")
            report["actual_service_inventory"] = verify_started_inventory(inventory.stdout)
            report["stage"] = "trusted_https_readiness"
            wait_ready(private / "tls/root.crt")
            browser_env.update(
                DALA_E2E_BASE_URL=ORIGIN,
                DALA_E2E_FIXTURE_FILE=str(private / "fixture.json"),
                DALA_E2E_MASTER_PIN_FILE=str(private / "master_pin"),
                DALA_E2E_EXECUTOR_PIN_FILE=str(private / "executor_pin"),
                DALA_E2E_FRONTEND_SHA=contract["frontend_sha"],
                DALA_E2E_BACKEND_SHA=report["source_sha"],
                DALA_C110_PREFLIGHT_RECEIPT=proof["path"],
                DALA_C110_AUTHORIZED="operator-provisioned-synthetic-only",
                DALA_C110_WORKERS_DISABLED="ai,delivery,providers",
                DALA_C110_OBSERVER_DATABASE_URL=observer_dsn(private),
                DALA_C110_DATABASE_SCHEMA="dalaai_demo",
                DALA_C110_PYTHON=sys.executable,
                DALA_C110_RUN_ID="c110-" + uuid4().hex,
            )
            report["stage"] = "c110_android_browser"
            core = execute_core(ROOT, browser_env, private, cli)
            report.update(core["summary"])
            # Successful C-owned projection only. Never publish the raw Playwright report.
            with (ROOT / "mobile-ci-evidence.json").open("x") as public:
                public.write(json.dumps(core["evidence"], indent=2) + "\n")
            report["status"] = "PASS_ANDROID_EMULATION_MANUAL_CORE"
        finally:
            if attempted_start:
                report["cleanup"] = "pending"
                if command([*compose, "down", "--volumes", "--remove-orphans"], env=env, timeout=120):
                    report["cleanup"] = "failed"
                    raise GateError("DISPOSABLE_COMPOSE_CLEANUP_FAILED")
            report["cleanup"] = "completed"
    report["stage"] = "completed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument("--report", type=Path, default=ROOT / "mobile-ci-summary.json")
    args = parser.parse_args()
    report = {
        "schema_version": 1, "status": "BLOCKED_NOT_RUN", "stage": "input_contract",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "environment": "real_compose_postgresql_mounted_app_android_chromium_emulation",
        "real_android_device": "NOT_RUN", "real_webpush_provider_delivery": "NOT_RUN",
        "synthetic_push_transport": "NOT_CLAIMED_BY_THIS_GATE",
        "paid_model_calls": "NOT_RUN_NO_KEY", "rules_worker_execution": "NOT_RUN_MANUAL_CORE",
        "full_cycle_green": False, "deployment_performed": False,
    }
    code = 1
    try:
        contract = contract_inputs()
        if args.check_inputs:
            print("PASS: accepted C-110 source inputs and exact Playwright dependency are present")
            return 0
        run_gate(report, contract)
        code = 0
    except (GateError, C110Error) as error:
        report["reason_code"] = str(error)
        report["status"] = "FAIL" if report["stage"] != "input_contract" else "BLOCKED_NOT_RUN"
    except Exception as error:
        report["reason_code"] = "UNEXPECTED_RUNNER_FAILURE"
        report["error_type"] = type(error).__name__
        report["status"] = "FAIL"
    if args.check_inputs:
        print("BLOCKED: " + report["reason_code"])
    else:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
