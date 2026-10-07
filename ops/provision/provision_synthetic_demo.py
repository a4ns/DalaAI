#!/usr/bin/env python3
"""Prepare/apply a tiny synthetic demo fixture; never print credentials or apply migrations.

Default is a no-database dry run. Only an explicitly configured operator may
apply. Accounts use real Argon2id hashes and the existing session service. This
script neither creates PostgreSQL roles nor updates existing PINs/permissions.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID, uuid5

NAMESPACE = UUID("554319b7-a2e8-4bfa-b4b3-e630203b090d")
FIXTURE_VERSION = "dalaai-live-vertical-demo-v1"
CODE_PREFIX = "DALA-DEMO-"
IDENTITY = {name: str(uuid5(NAMESPACE, f"{FIXTURE_VERSION}:{name}"))
            for name in ("section", "equipment", "work_code", "material", "master", "executor")}
EMPLOYEES = (("master", "DALA-DEMO-MASTER", "DALA_DEMO_MASTER_PIN"),
             ("executor", "DALA-DEMO-EXECUTOR", "DALA_DEMO_EXECUTOR_PIN"))


class FixtureConflict(RuntimeError):
    pass


def schema_name(value):
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", value):
        raise ValueError("Invalid explicit schema name")
    return value


def public_manifest():
    """Intentionally contains no PIN, hash, session token, CSRF or database DSN."""
    return {
        "fixture_version": FIXTURE_VERSION,
        "data_classification": "synthetic demo only",
        "historical_dataset": False,
        "section": {"id": IDENTITY["section"], "code": "DALA-DEMO-SECTION", "label": "Синтетический демонстрационный участок"},
        "equipment": {"id": IDENTITY["equipment"], "code": "DALA-DEMO-EQUIPMENT", "label": "Синтетический демонстрационный стенд"},
        "work_code": {"id": IDENTITY["work_code"], "code": "DALA-DEMO-WORK", "label": "Синтетическая плановая проверка"},
        "material": {"id": IDENTITY["material"], "code": "DALA-DEMO-MATERIAL", "label": "Синтетический расходный материал", "unit": "шт"},
        "users": [{"id": IDENTITY[role], "employee_code": code, "role": role,
                   "section_ids": [IDENTITY["section"]], "on_shift": True}
                  for role, code, _ in EMPLOYEES],
        "orders_seeded": 0,
        "sessions_seeded": 0,
        "photos_seeded": 0,
        "credentials": "Operator supplies distinct private PINs; never printed or included in this manifest",
        "hero_path": "planned: create -> accept -> start -> submit -> master close",
        "negative_path": "unplanned missing after-photo -> incomplete -> close denied -> master rework",
    }


def read_pins(environment):
    result = {}
    for role, _, variable in EMPLOYEES:
        value = environment.get(variable, "")
        if not re.fullmatch(r"[0-9]{8,32}", value) or len(set(value)) < 3 or value == "71426839":
            raise ValueError(f"{variable} must be a private 8–32 digit demo PIN, distinct from public test fixtures")
        result[role] = value
    if result["master"] == result["executor"]:
        raise ValueError("Master and executor demo PINs must differ")
    return result


def preflight_apply(args, environment):
    if environment.get("DALA_API_MODE") != "demo" or environment.get("DALA_DEMO_SEED_ALLOWED") != "1":
        raise ValueError("Applying requires DALA_API_MODE=demo and DALA_DEMO_SEED_ALLOWED=1")
    if not environment.get("DALA_DEMO_OWNER_DATABASE_URL"):
        raise ValueError("DALA_DEMO_OWNER_DATABASE_URL is required for fixture setup only")
    if not args.expected_database:
        raise ValueError("--expected-database must explicitly identify the isolated demo database")
    return read_pins(environment)


def match_or_insert(db, table, expected, *, key="id", allow_insert=True):
    """No UPSERT updates. Conflicts cause the single fixture transaction to roll back."""
    from psycopg import sql
    columns = list(expected)
    row = db.execute(sql.SQL("SELECT {} FROM {} WHERE {}=%s FOR UPDATE").format(
        sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(table), sql.Identifier(key)),
        (expected[key],)).fetchone()
    if row is not None:
        actual = {name: str(value) if isinstance(value, UUID) else value for name, value in row.items()}
        if actual != expected:
            raise FixtureConflict(f"Existing synthetic {table} row differs; no overwrite permitted")
        return 0
    if not allow_insert:
        raise FixtureConflict(f"Previously seeded synthetic {table} row is missing; no recreation permitted")
    db.execute(sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(sql.Identifier(table),
        sql.SQL(",").join(map(sql.Identifier, columns)), sql.SQL(",").join(sql.Placeholder() for _ in columns)),
        tuple(expected[name] for name in columns))
    return 1


def apply_fixture(connect, expected_database, pins):
    from argon2 import PasswordHasher
    from argon2.profiles import RFC_9106_LOW_MEMORY
    from app.sessions.crypto import Argon2idVerifier
    from psycopg import sql
    # Real implementation/profile; no plaintext or synthetic-login substitute.
    hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
    verifier = Argon2idVerifier()
    counts = {name: 0 for name in ("sections", "equipment", "work_codes", "materials", "employees", "employee_sections")}
    manifest = public_manifest()
    from prepare_demo_database import bootstrap_marker
    with connect() as db:
        with db.transaction():
            actual = db.execute("SELECT current_database() AS name").fetchone()["name"]
            if actual != expected_database:
                raise ValueError("Connected database does not match --expected-database")
            # A single transaction-wide seed lock serializes repeated operator
            # attempts without resetting or touching any existing business data.
            db.execute("SELECT pg_advisory_xact_lock(%s)", (74740825410424401,))
            marker = db.execute("SELECT nspname,obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=current_schema()").fetchone()
            if marker is None or marker["marker"] not in {bootstrap_marker("ready"), bootstrap_marker("seeded")}:
                raise ValueError("Seed requires this package's exact ready/seeded-marked isolated demo schema")
            first_seed = marker["marker"] == bootstrap_marker("ready")
            # Require the auth limiter/evidence schema and actual 004 identity
            # guards. Migration application is owned by A5/A6, never this seed.
            db.execute("SELECT kind,bucket FROM auth_login_limits LIMIT 0")
            db.execute("SELECT file_valid FROM photos LIMIT 0")
            db.execute("SELECT after_photo_ids FROM submissions LIMIT 0")
            guards = db.execute("""SELECT c.relname,t.tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND t.tgenabled IN ('O','A')""").fetchall()
            required = {("employees", "employees_identity_immutable"),
                        ("employee_sections", "employee_sections_ownership_immutable"),
                        ("auth_sessions", "auth_sessions_identity_immutable")}
            if not required <= {(row["relname"], row["tgname"]) for row in guards}:
                raise ValueError("Required identity guards absent; apply accepted migrations first")
            if first_seed:
                # A committed first seed records `seeded` atomically with all
                # rows. Any preexisting owned identity under `ready` is an
                # inconsistency, never permission to adopt/reset that account.
                for table, identifiers in (("sections", [IDENTITY["section"]]),
                    ("equipment", [IDENTITY["equipment"]]), ("work_codes", [IDENTITY["work_code"]]),
                    ("materials", [IDENTITY["material"]]), ("employees", [IDENTITY["master"], IDENTITY["executor"]])):
                    present = db.execute(sql.SQL("SELECT 1 FROM {} WHERE id=ANY(%s::uuid[]) LIMIT 1").format(sql.Identifier(table)), (identifiers,)).fetchone()
                    if present:
                        raise FixtureConflict("Unseeded marker has existing fixture identities; no adoption permitted")
            counts["sections"] = match_or_insert(db, "sections", manifest["section"], allow_insert=first_seed)
            equipment = dict(manifest["equipment"], section_id=IDENTITY["section"])
            counts["equipment"] = match_or_insert(db, "equipment", equipment, allow_insert=first_seed)
            counts["work_codes"] = match_or_insert(db, "work_codes", manifest["work_code"], allow_insert=first_seed)
            counts["materials"] = match_or_insert(db, "materials", manifest["material"], allow_insert=first_seed)
            for role, code, _ in EMPLOYEES:
                existing = db.execute("SELECT id,employee_code,role,active,on_shift,brigade_id,pin_hash FROM employees WHERE id=%s FOR UPDATE", (IDENTITY[role],)).fetchone()
                if existing is None:
                    if not first_seed:
                        raise FixtureConflict("Previously seeded employee is missing; no account recreation permitted")
                    db.execute("""INSERT INTO employees(id,employee_code,role,active,on_shift,brigade_id,pin_hash)
                        VALUES (%s,%s,%s,true,true,NULL,%s)""", (IDENTITY[role], code, role, hasher.hash(pins[role])))
                    counts["employees"] += 1
                else:
                    if (existing["employee_code"] != code or existing["role"] != role
                            or existing["active"] is not True or existing["on_shift"] is not True
                            or existing["brigade_id"] is not None or not verifier.verify(pins[role], existing["pin_hash"])):
                        raise FixtureConflict("Existing synthetic employee or PIN differs; no account reset permitted")
                membership = db.execute("SELECT section_id FROM employee_sections WHERE employee_id=%s FOR UPDATE", (IDENTITY[role],)).fetchall()
                sections = {str(row["section_id"]) for row in membership}
                if existing is not None and sections != {IDENTITY["section"]}:
                    raise FixtureConflict("Synthetic employee membership changed; no privilege restoration or rewrite permitted")
                if existing is None:
                    if sections:
                        raise FixtureConflict("New employee has unexpected membership; no adoption permitted")
                    db.execute("INSERT INTO employee_sections(employee_id,section_id) VALUES (%s,%s)", (IDENTITY[role], IDENTITY["section"]))
                    counts["employee_sections"] += 1
            if first_seed:
                db.execute(sql.SQL("COMMENT ON SCHEMA {} IS {}").format(sql.Identifier(marker["nspname"]), sql.Literal(bootstrap_marker("seeded"))))
    return {"status": "APPLIED" if any(counts.values()) else "ALREADY_PRESENT", "created_rows": counts,
            "fixture": manifest, "existing_credentials_updated": False, "existing_business_data_changed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--schema", default="public", type=schema_name)
    parser.add_argument("--expected-database")
    parser.add_argument("--apply", action="store_true", help="Operator-authorized write to an already migrated isolated demo database")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"status": "DRY_RUN_NO_DATABASE_ACCESS", "fixture": public_manifest()}, ensure_ascii=False, indent=2))
        return 0
    try:
        pins = preflight_apply(args, os.environ)
        sys.path.insert(0, str(args.backend.resolve()))
        import psycopg
        from psycopg.rows import dict_row
        def connect():
            return psycopg.connect(os.environ["DALA_DEMO_OWNER_DATABASE_URL"], autocommit=True, connect_timeout=5,
                options=f"-c search_path={args.schema} -c statement_timeout=10000 -c lock_timeout=5000", row_factory=dict_row)
        result = apply_fixture(connect, args.expected_database, pins)
    except Exception as error:
        # Driver failures/constraint errors may embed connection/query values.
        # Never print their raw messages, tracebacks, DSNs, PINs or hashes.
        safe = {"status": "FAILED_NO_CONFIRMED_CHANGE", "error_type": type(error).__name__}
        if isinstance(error, (ValueError, FixtureConflict)):
            safe["reason"] = str(error)
        print(json.dumps(safe, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
