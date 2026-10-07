"""Disposable CI fixture material. No existing profiles or trust stores are touched."""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import subprocess

ORIGIN = "https://localhost:18443"
MARKER = "dalaai-mobile-ci-private-v1"


def write_private(path: Path, value: str) -> None:
    """Exclusive creation prevents overwriting an operator's existing input."""
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(value)


def prepare_private(directory: Path, *, credentials: bool = True) -> None:
    if directory.exists():
        raise ValueError("Fixture directory must be new")
    directory.mkdir(mode=0o700)
    write_private(directory / ".fixture-owner", MARKER)
    if credentials:
        prepare_credentials(directory)


def prepare_credentials(directory: Path) -> None:
    """Create actual synthetic login material only after C-110 preflight passes."""
    if (directory / ".fixture-owner").read_text() != MARKER:
        raise ValueError("Refusing non-owned credential directory")
    names = ("postgres_owner_password", "postgres_runtime_password", "owner_dsn", "runtime_dsn", "master_pin", "executor_pin")
    if any((directory / name).exists() or (directory / name).is_symlink() for name in names):
        raise ValueError("Credential fixture must be fresh; no rotation or overwrite")
    owner = secrets.token_urlsafe(32)
    runtime = secrets.token_urlsafe(32)
    def pin(excluding=None):
        while True:
            value = "".join(secrets.choice("0123456789") for _ in range(16))
            if len(set(value)) >= 3 and value != excluding:
                return value
    master = pin()
    executor = pin(master)
    for name, value in {
        "postgres_owner_password": owner,
        "postgres_runtime_password": runtime,
        "owner_dsn": f"postgresql://naryadai_owner:{owner}@db:5432/naryadai",
        "runtime_dsn": f"postgresql://naryadai_api:{runtime}@db:5432/naryadai",
        "master_pin": master,
        "executor_pin": executor,
    }.items():
        write_private(directory / name, value + "\n")
        # Compose file-backed secrets preserve host modes. The enclosing0700
        # directory protects host access; only assigned containers see the file.
        os.chmod(directory / name, 0o444)


def run_private(argv: list[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    # Neither tool output nor exception command lines reach public CI logs.
    process = subprocess.run(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, check=False)
    if process.returncode:
        raise RuntimeError(f"Fixture tool failed: {Path(argv[0]).name}")


def prepare_tls(directory: Path) -> None:
    """One-day localhost chain. Trust is applied only to a newly created HOME."""
    if (directory / ".fixture-owner").read_text() != MARKER:
        raise ValueError("Refusing non-owned fixture directory")
    tls = directory / "tls"
    tls.mkdir(mode=0o700)
    root = tls / "root.cnf"
    leaf = tls / "leaf.cnf"
    write_private(root, """[req]
prompt = no
distinguished_name = dn
x509_extensions = ca
[dn]
CN = DalaAI disposable localhost CI root
[ca]
basicConstraints = critical,CA:TRUE,pathlen:0
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
nameConstraints = critical,permitted;DNS:localhost,permitted;IP:127.0.0.1/255.255.255.255
""")
    write_private(leaf, """[req]
prompt = no
distinguished_name = dn
req_extensions = server
[dn]
CN = localhost
[server]
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = DNS:localhost,IP:127.0.0.1
""")
    run_private(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                 "-config", str(root), "-keyout", str(tls / "root.key"), "-out", str(tls / "root.crt")])
    run_private(["openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-config", str(leaf),
                 "-keyout", str(tls / "server.key"), "-out", str(tls / "server.csr")])
    run_private(["openssl", "x509", "-req", "-in", str(tls / "server.csr"), "-CA", str(tls / "root.crt"),
                 "-CAkey", str(tls / "root.key"), "-CAcreateserial", "-days", "1", "-extfile", str(leaf),
                 "-extensions", "server", "-out", str(tls / "server.crt")])
    for path in tls.iterdir():
        os.chmod(path, 0o600)
    # These two files alone are mounted into cap-dropped Caddy, whose UID differs
    # from the CI host owner. Its read-only mounts need readable file modes.
    # Host access remains protected by both enclosing0700 directories. The root
    # CA private key stays0600 and is never mounted into any container.
    for name in ("server.crt", "server.key"):
        os.chmod(tls / name, 0o444)
    home = directory / "browser-home"
    # Existing legacy NSS path is supported by both pre- and post-M146 Chromium.
    # Chromium chooses it when present, so no global or existing user DB is used.
    database = home / ".pki" / "nssdb"
    database.mkdir(parents=True, mode=0o700)
    run_private(["certutil", "-N", "--empty-password", "-d", f"sql:{database}"])
    run_private(["certutil", "-A", "-t", "C,,", "-n", "DalaAI ephemeral localhost only",
                 "-i", str(tls / "root.crt"), "-d", f"sql:{database}"])
    run_private(["openssl", "verify", "-CAfile", str(tls / "root.crt"),
                 "-verify_hostname", "localhost", str(tls / "server.crt")])
