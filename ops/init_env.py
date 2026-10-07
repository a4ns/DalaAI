"""Create ignored development-only configuration, without replacing existing data."""

import os
import secrets
from pathlib import Path


def main() -> None:
    path = Path(__file__).resolve().parents[1] / ".env"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print("Existing .env preserved")
        return
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\nAPI_PORT=8000\n")
    print("Created local development .env; do not commit or share it")


if __name__ == "__main__":
    main()
