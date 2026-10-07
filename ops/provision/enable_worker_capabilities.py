#!/usr/bin/env python3
"""Explicit operator-owned seven-migration bootstrap; default is a no-DB plan.

SOURCE CANDIDATE ONLY. No database/role/key/grant operation occurs on import.
Existing owner/API/worker LOGINs are supplied by the operator. An existing schema
must already have this helper's exact completed capability marker: no adoption,
upgrade, repair, regrant, migration replay or scope restoration on repeat.
"""
import argparse
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import sys

from prepare_demo_database import bootstrap_marker, worker_migration_plan
from provision_synthetic_demo import apply_fixture, preflight_apply, schema_name


API_PUSH_SELECT = '*'
API_PUSH_UPDATES = ('session_hash', 'endpoint_hash', 'endpoint', 'p256dh', 'auth',
                    'expires_at', 'generation', 'active', 'updated_at', 'last_error_code')
API_DISPATCH_READS = {'delivery_dispatches': ('lease_token', 'job_id'),
                      'delivery_dispatch_results': ('lease_token', 'outcome')}
MARKER_PREFIX = 'DalaAI isolated worker capabilities v1 '
FULL_WORKER_ENVIRONMENT = {'DALA_WORKER_AI_ENABLED': 'true', 'DALA_WORKER_NOTIFY_ENABLED': 'true',
                           'DALA_WORKER_CHANNEL': 'web_push'}


def api_grants():
    """Frozen baseline API capabilities plus photos, push and priority-hook reads.

    No SELECT ALL TABLES/SEQUENCES, worker job/assessment inserts, dispatch writes,
    role creation or secret management. Existing broad orders UPDATE is required
    by the accepted full-row persist_order implementation.
    """
    from app.runtime import TABLE_COLUMNS, INSERT_TABLES, UPDATE_COLUMNS
    reads = {table: '*' for table in TABLE_COLUMNS}
    reads.update(API_DISPATCH_READS)
    reads['push_subscriptions'] = API_PUSH_SELECT
    inserts = tuple(sorted(set(INSERT_TABLES) | {'photos', 'push_subscriptions'}))
    updates = dict(UPDATE_COLUMNS)
    updates.update({'orders': '*', 'delivery_jobs': ('state', 'attempts', 'next_attempt_at',
                    'lease_until', 'last_error_code'), 'push_subscriptions': API_PUSH_UPDATES})
    return {'select': reads, 'insert': inserts, 'update': updates}


def selected_fixture(environment):
    mode = environment.get('DALA_DEMO_FIXTURE_MODE', 'minimal')
    if mode not in {'minimal', 'history'}:
        raise ValueError('WORKER_FIXTURE_MODE_INVALID')
    if mode == 'history':
        from history_demo import apply_fixture as history_fixture, public_manifest
        return mode, history_fixture, public_manifest()
    return mode, apply_fixture, None


def capability_fingerprint(plan, *, owner_role, api_role, worker_role, fixture_manifest=None):
    from app.worker_runtime import worker_grants
    payload = {'migrations': plan, 'roles': [owner_role, api_role, worker_role],
               'api': api_grants(), 'worker': worker_grants(web_push=True)}
    # Preserve every accepted minimal fingerprint byte-for-byte. The opt-in
    # historical profile adds its immutable source/identity/scope manifest.
    if fixture_manifest is not None:
        payload['fixture'] = fixture_manifest
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def marker(state, fingerprint):
    if state not in {'initializing', 'complete'} or len(fingerprint) != 64:
        raise ValueError('WORKER_CAPABILITY_MARKER_INVALID')
    return MARKER_PREFIX + state + ' ' + fingerprint


def repeat_action(schema_marker, capability_marker, fingerprint):
    """Pure state decision; a missing/revoked capability is never fresh consent."""
    if schema_marker not in {bootstrap_marker('ready'), bootstrap_marker('seeded')}:
        raise ValueError('WORKER_EXISTING_SCHEMA_NOT_COMPLETED')
    if capability_marker != marker('complete', fingerprint):
        raise ValueError('WORKER_EXISTING_CAPABILITY_MARKER_MISMATCH')
    return 'verify_only'


def _ensure_identities(owner, api, worker, *, expected_database):
    identities = (owner, api, worker)
    if owner['database_name'] != expected_database:
        raise ValueError('WORKER_EXPECTED_DATABASE_MISMATCH')
    if any(any(value[key] != owner[key] for key in ('database_name', 'server_address', 'server_port'))
           for value in identities[1:]):
        raise ValueError('WORKER_IDENTITIES_DATABASE_MISMATCH')
    if len({value['role_name'] for value in identities}) != 3:
        raise ValueError('WORKER_THREE_DISTINCT_IDENTITIES_REQUIRED')
    for value in identities:
        if value['role_name'] != value['session_role']:
            raise ValueError('WORKER_DIRECT_LOGINS_REQUIRED')
    for value in identities[1:]:
        if any(value[key] for key in ('rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolbypassrls')):
            raise ValueError('WORKER_RESTRICTED_IDENTITIES_REQUIRED')


def _grant_profile(db, *, schema, role_name, profile):
    from psycopg import sql
    role = sql.Identifier(role_name)
    db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema), role))
    for permission in ('select', 'update'):
        for table, columns in profile[permission].items():
            if columns == '*':
                clause = sql.SQL(permission.upper())
            else:
                clause = sql.SQL(permission.upper() + ' ({})').format(sql.SQL(',').join(map(sql.Identifier, columns)))
            db.execute(sql.SQL('GRANT {} ON {} TO {}').format(clause, sql.Identifier(schema, table), role))
    for table in profile['insert']:
        db.execute(sql.SQL('GRANT INSERT ON {} TO {}').format(sql.Identifier(schema, table), role))


def validate_api_profile(connect, *, schema):
    """Validate baseline API and only the explicit capability extension, read-only."""
    from app.runtime import validate_database
    # A5 may extend the accepted validator. Pass only its declared capabilities.
    kwargs = {'photo_enabled': True}
    parameters = inspect.signature(validate_database).parameters
    if 'push_enabled' in parameters:
        kwargs['push_enabled'] = True
    if 'notification_enabled' in parameters:
        kwargs['notification_enabled'] = True
    validate_database(connect, **kwargs)
    from psycopg.rows import dict_row
    from psycopg import sql
    expected = api_grants()
    with connect() as db:
        db.row_factory = dict_row
        guards = db.execute('''SELECT c.relname,t.tgname FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname=%s AND t.tgenabled IN ('O','A')''', (schema,)).fetchall()
        needed = {('push_subscriptions', 'push_subscription_owner_immutable'),
                  ('delivery_dispatches', 'delivery_dispatches_immutable'),
                  ('delivery_dispatch_results', 'delivery_dispatch_results_immutable')}
        if not needed <= {(r['relname'], r['tgname']) for r in guards}:
            raise ValueError('WORKER_API_CAPABILITY_GUARD_MISSING')
        for table in ('push_subscriptions', 'delivery_dispatches', 'delivery_dispatch_results'):
            cols = db.execute('''SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass
                AND attnum>0 AND NOT attisdropped''', (f'{schema}.{table}',)).fetchall()
            if not cols:
                raise ValueError('WORKER_API_CAPABILITY_TABLE_MISSING')
            for privilege in ('DELETE', 'TRUNCATE', 'TRIGGER', 'REFERENCES'):
                if db.execute('SELECT has_table_privilege(%s,%s) AS ok', (f'{schema}.{table}', privilege)).fetchone()['ok']:
                    raise ValueError('WORKER_API_CAPABILITY_GRANT_EXCESS')
            for col in cols:
                name = col['attname']
                for privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES',
                                  'SELECT WITH GRANT OPTION', 'INSERT WITH GRANT OPTION', 'UPDATE WITH GRANT OPTION'):
                    allow = expected.get(privilege.lower(), {}).get(table, ()) if privilege in ('SELECT', 'UPDATE') else ()
                    wanted = table in expected['insert'] if privilege == 'INSERT' else allow == '*' or name in allow
                    actual = db.execute('SELECT has_column_privilege(%s,%s,%s) AS ok',
                                        (f'{schema}.{table}', name, privilege)).fetchone()['ok']
                    if actual != wanted:
                        raise ValueError('WORKER_API_CAPABILITY_GRANT_MISMATCH')
        db.execute(sql.SQL('SELECT lease_token FROM {} LIMIT 0').format(sql.Identifier(schema, 'ai_jobs')))
        db.execute(sql.SQL('SELECT lease_token FROM {} LIMIT 0').format(sql.Identifier(schema, 'delivery_jobs')))


def apply_capabilities(args, environment):
    """Intended for an authorized operator only; never called by source tests."""
    fixture_mode, seed_fixture, fixture_manifest = selected_fixture(environment)
    if environment.get('DALA_DEMO_WORKER_CAPABILITY_ALLOWED') != '1' or not args.bootstrap:
        raise ValueError('WORKER_EXPLICIT_BOOTSTRAP_APPROVAL_REQUIRED')
    pins = preflight_apply(args, environment)
    names = ('DALA_DEMO_OWNER_DATABASE_URL', 'DALA_DEMO_RUNTIME_DATABASE_URL', 'DALA_DEMO_WORKER_DATABASE_URL')
    if not all(environment.get(name) for name in names):
        raise ValueError('WORKER_EXISTING_THREE_DATABASE_IDENTITIES_REQUIRED')
    plan = worker_migration_plan(args.backend)
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from database_profile import identity
    from app.worker_runtime import worker_grants, validate_database as validate_worker
    def connector(name, scoped=True):
        def connect():
            options = f'-c search_path={args.schema} -c statement_timeout=10000 -c lock_timeout=5000' if scoped else '-c statement_timeout=10000 -c lock_timeout=5000'
            return psycopg.connect(environment[name], autocommit=True, connect_timeout=5,
                                    options=options, row_factory=dict_row)
        return connect
    owner, api, worker = [connector(name) for name in names]
    who = [identity(connect) for connect in (owner, api, worker)]
    _ensure_identities(*who, expected_database=args.expected_database)
    fingerprint = capability_fingerprint(plan, owner_role=who[0]['role_name'],
                                         api_role=who[1]['role_name'], worker_role=who[2]['role_name'],
                                         fixture_manifest=fixture_manifest)
    with connector(names[0], False)() as control:
        # Session lock spans the migration files' own commits; closes on all exits.
        locked = control.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok",
            ('dalaai-worker-bootstrap:' + args.expected_database + ':' + args.schema,)).fetchone()['ok']
        if not locked:
            raise ValueError('WORKER_BOOTSTRAP_ALREADY_RUNNING')
        for identity_row in who[1:]:
            elevated = control.execute('''SELECT EXISTS (SELECT 1 FROM pg_roles r
                WHERE pg_has_role(%s,r.oid,'MEMBER') AND (r.rolsuper OR r.rolcreatedb
                    OR r.rolcreaterole OR r.rolbypassrls OR r.rolname=%s)) AS bad''',
                (identity_row['role_name'], who[0]['role_name'])).fetchone()['bad']
            if elevated:
                raise ValueError('WORKER_INHERITED_OWNER_OR_ELEVATED_ROLE')
        present = control.execute("SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s", (args.schema,)).fetchone()
        if present:
            with owner() as db:
                completion = db.execute("SELECT obj_description(to_regclass(%s),'pg_class') AS marker",
                                        (f'{args.schema}.delivery_dispatches',)).fetchone()['marker']
            repeat_action(present['marker'], completion, fingerprint)
            validate_api_profile(api, schema=args.schema)
            validate_worker(worker, ai_enabled=True, notify_enabled=True, web_push=True)
            seed = seed_fixture(owner, args.expected_database, pins)
            return {'status': 'WORKER_CAPABILITIES_ALREADY_VERIFIED', 'migrations_replayed': False,
                    'grants_replayed': False, 'seed': seed, 'roles_created': 0, 'deployment_started': False,
                    'required_worker_settings': dict(FULL_WORKER_ENVIRONMENT), 'fixture_mode': fixture_mode}
        try:
            with control.transaction():
                control.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(args.schema)))
                control.execute(sql.SQL('COMMENT ON SCHEMA {} IS {}').format(
                    sql.Identifier(args.schema), sql.Literal(marker('initializing', fingerprint))))
            with owner() as db:
                for entry in plan:
                    data = (args.backend / entry['path']).read_bytes()
                    if sha256(data).hexdigest() != entry['sha256']:
                        raise ValueError('WORKER_MIGRATION_CHANGED_AFTER_PLAN')
                    db.execute(data.decode('utf-8'))
                with db.transaction():
                    _grant_profile(db, schema=args.schema, role_name=who[1]['role_name'], profile=api_grants())
                    sequence = db.execute("SELECT pg_get_serial_sequence('orders','number') AS name").fetchone()['name']
                    # The accepted API uses nextval. Grant only this known sequence.
                    db.execute(sql.SQL('GRANT USAGE, SELECT ON SEQUENCE {} TO {}').format(
                        sql.Identifier(*sequence.split('.')), sql.Identifier(who[1]['role_name'])))
                    _grant_profile(db, schema=args.schema, role_name=who[2]['role_name'], profile=worker_grants(web_push=True))
            validate_api_profile(api, schema=args.schema)
            validate_worker(worker, ai_enabled=True, notify_enabled=True, web_push=True)
            with owner() as db, db.transaction():
                db.execute(sql.SQL('COMMENT ON TABLE {} IS {}').format(sql.Identifier(args.schema, 'delivery_dispatches'),
                    sql.Literal(marker('complete' if fixture_mode == 'minimal' else 'initializing', fingerprint))))
                db.execute(sql.SQL('COMMENT ON SCHEMA {} IS {}').format(sql.Identifier(args.schema),
                    sql.Literal(bootstrap_marker('ready'))))
            seed = seed_fixture(owner, args.expected_database, pins)
            if fixture_mode == 'history':
                # C107 commits its own history transaction. Never advertise the
                # full profile complete before the live-account receipt exists.
                with owner() as db, db.transaction():
                    db.execute(sql.SQL('COMMENT ON TABLE {} IS {}').format(
                        sql.Identifier(args.schema, 'delivery_dispatches'), sql.Literal(marker('complete', fingerprint))))
            return {'status': 'WORKER_CAPABILITIES_READY', 'migration_count': len(plan),
                    'profile_sha256': fingerprint, 'migrations_replayed': False, 'grants_replayed': False,
                    'seed': seed, 'roles_created': 0, 'deployment_started': False,
                    'required_worker_settings': dict(FULL_WORKER_ENVIRONMENT), 'fixture_mode': fixture_mode}
        except Exception:
            # No cleanup, grants repair or replay: preserve the in-progress marker
            # (or ready marker when only the transactional fixture step failed).
            raise RuntimeError('WORKER_BOOTSTRAP_INCOMPLETE_SCHEMA_PRESERVED') from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--schema', type=schema_name, required=True)
    parser.add_argument('--expected-database')
    parser.add_argument('--bootstrap', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        sys.path.insert(0, str(args.backend.resolve()))
        fixture_mode, _, fixture_manifest = selected_fixture(os.environ)
        plan = worker_migration_plan(args.backend)
        if not args.apply:
            result = {'status': 'PLAN_ONLY_NO_DATABASE_ACCESS', 'schema': args.schema,
                      'migrations': plan, 'api_profile': api_grants(), 'worker_profile': 'separate exact column profile',
                      'existing_identities_required': ['owner', 'api', 'worker'], 'roles_created': 0,
                      'required_worker_settings': dict(FULL_WORKER_ENVIRONMENT),
                      'fixture_mode': fixture_mode, 'fixture_manifest': fixture_manifest,
                      'repeat': 'verify_only_no_migrations_no_regrants_no_scope_reset'}
        else:
            result = apply_capabilities(args, os.environ)
    except Exception as error:
        # No raw DB/provider exception, DSN or key is rendered.
        result = {'status': 'WORKER_CAPABILITIES_NOT_CONFIRMED', 'error_type': type(error).__name__,
                  'code': str(error) if type(error) is ValueError and str(error).startswith('WORKER_') else 'WORKER_BOOTSTRAP_FAILED',
                  'next_action': 'Keep services stopped; inspect preserved state. No automatic reset or repair.'}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
