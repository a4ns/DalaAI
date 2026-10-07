"""Integrate C-110's unchanged, source-bound secrecy preflight and exact core gate."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit
from core_diagnostics import failure_projection

TITLE = "C110 real composed master executor lifecycle"
SERVICES = {"db", "photo-directory", "prepare", "api", "web", "observer"}


class C110Error(RuntimeError):
    def __init__(self, code, *, diagnostic=None):
        super().__init__(code)
        self.diagnostic=diagnostic


def verify_service_inventory(model: dict) -> list[str]:
    services = model.get("services", {})
    if not SERVICES <= set(services):
        raise C110Error("C110_WORKER_ABSENCE_NOT_ESTABLISHED")
    # Optional worker services must be explicitly profile-gated. The caller
    # starts only api/web and inherits no COMPOSE_PROFILES environment variable.
    for name in set(services) - SERVICES:
        if not services[name].get("profiles"):
            raise C110Error("C110_EXTRA_SERVICE_NOT_PROFILE_GATED")
    for name in SERVICES:
        dependencies = services[name].get("depends_on", {})
        if set(dependencies) - SERVICES:
            raise C110Error("C110_CORE_DEPENDS_ON_WORKER_SERVICE")
    for name in ("api", "prepare"):
        env = services[name].get("environment", {})
        if any("WORKER" in key.upper() and str(value).lower() not in {"0", "false", "off", "disabled", "none", ""}
               for key, value in env.items()):
            raise C110Error("C110_WORKER_ENABLE_FLAG_PRESENT")
    if services["api"].get("environment", {}).get("OPENAI_API_KEY"):
        raise C110Error("C110_PROVIDER_KEY_PRESENT")
    root=Path(__file__).resolve().parents[2]
    if model.get("networks",{}).get("backend",{}).get("internal") is not True or set(services["db"].get("networks",{}))!={"backend"}:
        raise C110Error("C110_DATABASE_NETWORK_MUST_REMAIN_INTERNAL")
    if services["db"].get("ports"):
        raise C110Error("C110_DATABASE_MUST_REMAIN_UNPUBLISHED")
    observer=services["observer"]
    if (observer.get("network_mode")!="service:db" or observer.get("user")!="10001:10001"
            or observer.get("read_only") is not True or observer.get("ports") or observer.get("networks")
            or observer.get("cap_drop")!=["ALL"] or observer.get("cap_add") or observer.get("privileged")
            or observer.get("security_opt")!=["no-new-privileges:true"]):
        raise C110Error("C110_OBSERVER_ISOLATION_INVALID")
    assigned={item.get("source") if isinstance(item,dict) else item for item in observer.get("secrets",[])}
    if assigned!={"runtime_dsn"}:
        raise C110Error("C110_OBSERVER_SECRET_SCOPE_INVALID")
    volumes=observer.get("volumes",[])
    if len(volumes)!=2 or {item.get("target") for item in volumes}!={"/ci/c110_observe.py","/ci/observer_in_container.py"} or any(item.get("type")!="bind" or item.get("read_only") is not True for item in volumes):
        raise C110Error("C110_OBSERVER_SOURCE_MOUNTS_INVALID")
    expected_mounts={"/ci/c110_observe.py":root/"tests/e2e/c110_observe.py",
                     "/ci/observer_in_container.py":root/"ops/ci/observer_in_container.py"}
    if any(Path(item.get("source","")).resolve()!=expected_mounts[item["target"]].resolve() for item in volumes):
        raise C110Error("C110_OBSERVER_MOUNT_SOURCE_MISMATCH")
    build=observer.get("build",{})
    if build.get("dockerfile")!="ops/demo/Dockerfile.api" or Path(build.get("context","")).resolve()!=root:
        raise C110Error("C110_OBSERVER_MUST_REUSE_PINNED_API_IMAGE")
    return sorted(SERVICES)


def verify_started_inventory(raw: bytes) -> list[str]:
    text = raw.decode()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = [data]
    names = {row.get("Service") for row in data}
    if names != SERVICES:
        raise C110Error("C110_UNEXPECTED_ACTUAL_COMPOSE_SERVICE")
    if any(row.get("Service") in {"api", "db", "web", "observer"} and row.get("State") != "running" for row in data):
        raise C110Error("C110_CORE_SERVICE_NOT_RUNNING")
    return sorted(names)


def verify_source_blobs(root: Path, expected: dict) -> None:
    if not expected:
        raise C110Error("C110_ACCEPTED_SOURCE_BLOBS_MISSING")
    for relative, digest in expected.items():
        if not relative.startswith("tests/e2e/") or not re.fullmatch(r"[a-f0-9]{40}", digest):
            raise C110Error("C110_SOURCE_MANIFEST_INVALID")
        path = root / relative
        if not path.resolve().is_relative_to((root / "tests/e2e").resolve()):
            raise C110Error("C110_SOURCE_PATH_ESCAPE")
        if path.is_symlink() or not path.is_file():
            raise C110Error("C110_SOURCE_NOT_REGULAR_FILE")
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != digest:
            raise C110Error("C110_ACCEPTED_SOURCE_BLOB_MISMATCH")


def frontend_blobs(root: Path) -> dict:
    result = subprocess.run(["git", "ls-tree", "-r", "HEAD", "--", "frontend"], cwd=root, capture_output=True, text=True)
    if result.returncode:
        raise C110Error("C110_FRONTEND_PROVENANCE_UNAVAILABLE")
    blobs = {}
    for line in result.stdout.splitlines():
        header, name = line.split("\t", 1)
        if name.startswith("frontend/tests/") or name == "frontend/playwright.config.ts":
            continue
        mode, kind, digest = header.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise C110Error("C110_FRONTEND_UNEXPECTED_OBJECT")
        blobs[name] = digest
    if not blobs:
        raise C110Error("C110_FRONTEND_PROVENANCE_UNAVAILABLE")
    return blobs


def verify_frontend_provenance(root: Path, reference: Path, expected_sha: str) -> None:
    actual = subprocess.run(["git", "rev-parse", "HEAD"], cwd=reference, capture_output=True, text=True)
    if actual.returncode or actual.stdout.strip() != expected_sha:
        raise C110Error("C110_FRONTEND_REFERENCE_SHA_MISMATCH")
    if frontend_blobs(root) != frontend_blobs(reference):
        raise C110Error("C110_BUILT_FRONTEND_DIFFERS_FROM_REVIEWED_SOURCE")


def run(argv: list[str], env: dict, root: Path, timeout: int) -> int:
    result = subprocess.run(argv, cwd=root, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout, check=False)
    # Deliberately do not persist/echo any raw runner or assertion content.
    return result.returncode


def secrecy_preflight(root: Path, env: dict, private: Path) -> dict:
    if any(env.get(key) for key in ("DALA_E2E_MASTER_PIN_FILE", "DALA_E2E_EXECUTOR_PIN_FILE",
                                   "DALA_E2E_FIXTURE_FILE", "DALA_C110_OBSERVER_DATABASE_URL")):
        raise C110Error("C110_PREFLIGHT_MUST_PRECEDE_PRIVATE_INPUTS")
    proof = private / "c110-preflight-receipt.json"
    if proof.exists() or proof.is_symlink():
        raise C110Error("C110_PREFLIGHT_RECEIPT_MUST_BE_FRESH")
    preflight_env = dict(env, DALA_C110_PREFLIGHT_RECEIPT=str(proof))
    code = run(["node", str(root / "tests/e2e/c110_secrecy_preflight.cjs")], preflight_env, root, 90)
    if code or not proof.is_file():
        raise C110Error("C110_DUMMY_SECRET_PREFLIGHT_FAILED")
    data = json.loads(proof.read_text())
    if data.get("version") != "c110-failure-output-v2" or data.get("frontend_sha") != env.get("DALA_E2E_FRONTEND_SHA") or data.get("result") != "PASS" or data.get("expected_dummy_failures") != 1 or data.get("observed_dummy_failures") != 1 or data.get("sentinel_matches") != 0:
        raise C110Error("C110_DUMMY_SECRET_PROOF_INVALID")
    return {"path": str(proof), "public": {key: data[key] for key in (
        "version", "result", "playwright", "source_sha", "frontend_sha", "created_at", "expected_dummy_failures",
        "observed_dummy_failures", "scanned_outputs", "sentinel_matches", "scanned_output_sha256")}}


def observer_dsn(private: Path) -> str:
    parsed = urlsplit((private / "runtime_dsn").read_text().strip())
    if parsed.scheme != "postgresql" or parsed.hostname != "db" or parsed.username != "naryadai_api" or not parsed.password or parsed.path != "/naryadai":
        raise C110Error("C110_RUNTIME_FIXTURE_DSN_INVALID")
    return f"postgresql://naryadai_api:{parsed.password}@127.0.0.1:5432/naryadai"


def extract_evidence(report: Path, artifact_root: Path, private: Path) -> Path | None:
    if not report.is_file() or report.stat().st_size > 4 * 1024 * 1024:
        return None
    data = json.loads(report.read_text())
    attachments = []
    def walk(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        attachments.extend(a for a in result.get("attachments", [])
                                           if a.get("name") == "c110_evidence" and a.get("contentType") == "application/json")
            walk(suite.get("suites", []))
    walk(data.get("suites", []))
    if len(attachments) != 1:
        return None
    item = attachments[0]
    if item.get("body"):
        raw = base64.b64decode(item["body"], validate=True)
        if len(raw) > 1024 * 1024:
            return None
        target = private / "c110-evidence.json"
        with target.open("xb") as file:
            os.chmod(target, 0o600)
            file.write(raw)
        return target
    if item.get("path"):
        target = Path(item["path"])
        if target.is_symlink() or not target.resolve().is_relative_to(artifact_root.resolve()) or not target.is_file() or target.stat().st_size > 1024 * 1024:
            return None
        return target
    return None


def execute_core(root: Path, env: dict, private: Path, cli: Path) -> dict:
    artifact_root = root / "tests/e2e/c110_artifacts"
    if artifact_root.exists() or artifact_root.is_symlink():
        raise C110Error("C110_ARTIFACT_DIRECTORY_MUST_BE_FRESH")
    artifact_root.mkdir(mode=0o700)
    report = artifact_root / "playwright.json"
    try:
        code = run(["node", str(cli), "test", "--config", str(root / "tests/e2e/c110_playwright.config.cjs")], env, root, 360)
        try:
            evidence = extract_evidence(report, artifact_root, private)
        except Exception:
            evidence = None
        # Mandatory even after Playwright failure/missing reports; never silently skip.
        gate = run(["node", str(root / "tests/e2e/c110_gate.cjs"), str(report),
                    str(evidence or (private / "missing-evidence.json"))], env, root, 30)
        if code or gate or evidence is None:
            raise C110Error("C110_REAL_CORE_OR_EVIDENCE_GATE_FAILED", diagnostic=failure_projection(report,evidence))
        raw = evidence.read_bytes()
        # Extra allowlist-layer check before publication; never display the matching value.
        for name in ("master_pin", "executor_pin", "postgres_owner_password", "postgres_runtime_password"):
            secret = (private / name).read_bytes().strip()
            if secret and secret in raw:
                raise C110Error("C110_PUBLIC_EVIDENCE_SECRET_DETECTED")
        body = json.loads(raw)
        return {"evidence": body, "summary": {"tests_passed": 1, "tests_failed": 0, "tests_skipped": 0,
                "asserted_stages": len(body["steps"]), "committed_commands": len(body["commands"]),
                "persisted_events": len(body["database"]["events"]), "required_test_title": TITLE}}
    finally:
        # Created by this invocation only; never clean up a preexisting output tree.
        shutil.rmtree(artifact_root)


def readonly_observer_probe(root: Path, env: dict, python: str) -> dict:
    """Exercise the unchanged C projection on a nonexistent sentinel order; emit no rows."""
    allowed_types={"OperationalError","ProgrammingError","InsufficientPrivilege","UndefinedColumn",
                   "UndefinedTable","InvalidPassword","InvalidAuthorizationSpecification",
                   "ConnectionTimeout","Blocked","ValueError","ImportError","ModuleNotFoundError",
                   "SyntaxError","TypeError","KeyError","InterfaceError","ObserverRunnerError"}
    process=subprocess.run([python,str(root/"tests/e2e/c110_observe.py"),"00000000-0000-0000-0000-000000000000"],
                           cwd=root,env=env,capture_output=True,timeout=20,check=False)
    try:
        data=json.loads(process.stdout)
    except Exception:
        return {"status":"FAIL","code":"C110_OBSERVER_PROBE_NO_SAFE_JSON"}
    identity=data.get("identity",{})
    if process.returncode==0 and data.get("source")=="actual_postgresql_read_only" and all(identity.get(k) is True for k in ("direct_login","read_only","isolated_schema")):
        return {"status":"PASS","scope":"readonly_zero_uuid_projection_only"}
    code=data.get("code")
    kind=data.get("error_type")
    return {"status":"FAIL","code":code if code=="C110_DB_OBSERVATION_UNAVAILABLE" else "C110_OBSERVER_PROBE_FAILED",
            "error_type":kind if kind in allowed_types else "UNKNOWN"}
