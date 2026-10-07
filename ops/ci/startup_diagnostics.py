"""Bounded startup categories and service-state enums; never echo raw Compose logs."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess

SERVICES = {"api", "db", "web", "prepare", "photo-directory", "observer"}
STATES = {"running", "exited", "created", "restarting", "dead", "paused", "removing"}
HEALTH = {"healthy", "unhealthy", "starting", ""}


def classify(raw: bytes) -> list[str]:
    value = raw.lower()
    rules = (
        ("FILE_PERMISSION_DENIED", b"permission denied" in value),
        ("CI_TLS_FILE_UNREADABLE", b"permission denied" in value and b"ci-tls/server." in value),
        ("PORT_BIND_CONFLICT", b"port is already allocated" in value or b"address already in use" in value),
        ("IMAGE_BUILD_FAILED", b"failed to solve" in value),
        ("DEPENDENCY_FAILED", b"dependency failed to start" in value),
        ("CONTAINER_UNHEALTHY", b"unhealthy" in value),
        ("CONTAINER_EXITED", b"exited" in value),
        ("IMAGE_PULL_FAILED", b"pull access denied" in value or b"manifest unknown" in value),
    )
    return [name for name, found in rules if found]


def safe_inventory(raw: bytes) -> list[dict]:
    if len(raw) > 256 * 1024:
        return []
    text = raw.decode()
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(rows, dict):
        rows = [rows]
    result = []
    for row in rows[:16]:
        if row.get("Service") not in SERVICES:
            continue
        code = row.get("ExitCode")
        result.append({"service": row["Service"],
                       "state": row.get("State") if row.get("State") in STATES else "unknown",
                       "health": row.get("Health", "") if row.get("Health", "") in HEALTH else "unknown",
                       "exit_code": code if type(code) is int and 0 <= code <= 255 else None})
    return sorted(result, key=lambda row: row["service"])


def collect(compose: list[str], env: dict, root: Path, up_output: bytes) -> dict:
    result = {"error_classes": classify(up_output), "services": []}
    try:
        status = subprocess.run([*compose, "ps", "--all", "--format", "json"], env=env, cwd=root,
                                capture_output=True, timeout=20, check=False)
        if status.returncode == 0:
            result["services"] = safe_inventory(status.stdout)
        for service in result["services"]:
            logs = subprocess.run([*compose, "logs", "--no-color", "--tail", "20", service["service"]],
                                  env=env, cwd=root, capture_output=True, timeout=10, check=False)
            # No dynamic strings or original bytes enter the public result.
            service["error_classes"] = classify(logs.stdout + logs.stderr)
    except Exception:
        result["diagnostic_incomplete"] = True
    return result
