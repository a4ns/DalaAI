"""Check real HTTP liveness/readiness; no mocks or business-flow claims."""

import argparse
import json
import time
import urllib.error
import urllib.request


def fetch(url: str) -> tuple[int, dict]:
    try:
        response = urllib.request.urlopen(url, timeout=5)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--unready", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=60)
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait_seconds
    expected = (503, {"status": "not_ready"}) if args.unready else (200, {"status": "ready"})
    while True:
        try:
            healthy = fetch(args.base_url.rstrip("/") + "/healthz") == (200, {"status": "ok"})
            ready = fetch(args.base_url.rstrip("/") + "/readyz") == expected
            if healthy and ready:
                print("PASS: real HTTP liveness and expected readiness state")
                return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise SystemExit("FAIL: HTTP probes did not reach expected state")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
