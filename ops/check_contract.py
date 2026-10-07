"""Verify the proposal manifest and validate a copy, preserving recorded evidence."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    proposal = root / "coord/proposals/a6-contract-v1"
    manifest = json.loads((proposal / "MANIFEST.json").read_text(encoding="utf-8"))
    if manifest["status"] != "PROPOSED_NOT_FROZEN":
        raise ValueError("Expected a review-only proposal; coordinate contract promotion separately")
    for record in manifest["files"]:
        path = (proposal / record["path"]).resolve()
        if not path.is_relative_to(proposal.resolve()):
            raise ValueError("Manifest path must stay inside proposal")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Proposal manifest mismatch: {record['path']}")
    with tempfile.TemporaryDirectory(prefix="dalaai-contract-check-") as directory:
        scratch = Path(directory) / "proposal"
        shutil.copytree(proposal, scratch)
        subprocess.run([sys.executable, "scripts/validate_contract.py"], cwd=scratch, check=True)
    print("PASS: proposal manifest and offline contract checks; no acceptance implied")


if __name__ == "__main__":
    main()
