#!/usr/bin/env python3
"""Optional fresh-demo business clock bootstrap; plan-only unless explicitly applied.

No role/credential creation, reset, adoption, upgrade, grant repair, or service
startup. Existing minimal/history worker receipts remain unchanged. Operators
supply three existing database LOGINs and a fixed canonical instance UUID.
"""
import argparse
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID

import enable_worker_capabilities as worker_bootstrap
from prepare_demo_database import worker_migration_plan
from provision_synthetic_demo import schema_name

CLOCK_MIGRATION = ('db/proposals/013_demo_business_clock.sql',
                   'dd37cbfcb25497f67f9390e3b9171b763d7022caa26ee5ef775c34d697c86158')
MARKER_PREFIX = 'DalaAI isolated business clock v1 '
DATABASE_VARIABLES = ('DALA_DEMO_OWNER_DATABASE_URL', 'DALA_DEMO_RUNTIME_DATABASE_URL',
                      'DALA_DEMO_WORKER_DATABASE_URL')
API_PROFILE = {'select': {'demo_clock_state': '*', 'demo_clock_controls': '*'},
               'insert': ('demo_clock_controls',),
               'update': {'demo_clock_state': ('version', 'real_anchor', 'domain_anchor', 'scale')}}
WORKER_PROFILE = {'select': {'demo_clock_state': '*'}, 'insert': (), 'update': {}}


def instance_uuid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError('DEMO_CLOCK_CANONICAL_INSTANCE_REQUIRED') from None
    return value


def migration_plan(backend):
    path, expected = CLOCK_MIGRATION
    source = backend / path
    if (backend / 'db/migrations/013_demo_business_clock.sql').exists():
        raise ValueError('DEMO_CLOCK_DUPLICATE_MIGRATION')
    if not source.is_file() or sha256(source.read_bytes()).hexdigest() != expected:
        raise ValueError('DEMO_CLOCK_MIGRATION_HASH_MISMATCH')
    return {'path': path, 'sha256': expected}


def marker(state, fingerprint):
    if state not in {'initializing', 'complete'} or not re.fullmatch('[0-9a-f]{64}', fingerprint):
        raise ValueError('DEMO_CLOCK_MARKER_INVALID')
    return MARKER_PREFIX + state + ' ' + fingerprint


def capability_fingerprint(*, baseline_fingerprint, instance_id):
    instance_uuid(instance_id)
    payload = {'baseline_fingerprint': baseline_fingerprint, 'instance_id': instance_id,
               'migration': CLOCK_MIGRATION, 'api': API_PROFILE, 'worker': WORKER_PROFILE,
               'initial_scale': 1, 'horizon_hours': 168}
    return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def repeat_action(schema_marker, worker_marker, clock_marker, *, baseline_fingerprint, fingerprint):
    # A completed base profile without OUR completed marker is never adopted.
    worker_bootstrap.repeat_action(schema_marker, worker_marker, baseline_fingerprint)
    if clock_marker != marker('complete', fingerprint):
        raise ValueError('DEMO_CLOCK_EXISTING_CAPABILITY_MARKER_MISMATCH')
    return 'verify_only'


def _runtime_validators():
    from app.runtime import validate_database as api
    from app.worker_runtime import validate_database as worker
    for validate in (api, worker):
        if not {'demo_clock_enabled', 'demo_clock_instance_id'} <= set(inspect.signature(validate).parameters):
            raise ValueError('DEMO_CLOCK_CAPABILITY_AWARE_RUNTIME_REQUIRED')
    return api, worker


def _validate_profiles(api, worker, instance_id):
    api_validate, worker_validate = _runtime_validators()
    api_validate(api, photo_enabled=True, push_enabled=True, notification_enabled=True,
                 demo_clock_enabled=True, demo_clock_instance_id=instance_id)
    worker_validate(worker, ai_enabled=True, notify_enabled=True, web_push=True,
                    demo_clock_enabled=True, demo_clock_instance_id=instance_id)


def _read_markers(db, schema):
    row = db.execute("SELECT obj_description(oid,'pg_namespace') AS marker FROM pg_namespace WHERE nspname=%s",
                     (schema,)).fetchone()
    if row is None:
        return None
    result = {'schema': row['marker']}
    for name, table in (('worker', 'delivery_dispatches'), ('clock', 'demo_clock_state')):
        result[name] = db.execute("SELECT obj_description(to_regclass(%s),'pg_class') AS marker",
                                  (f'{schema}.{table}',)).fetchone()['marker']
    return result


def _verify_singleton(owner, instance_id):
    with owner() as db:
        rows = db.execute('SELECT instance_id::text AS instance_id,synthetic FROM demo_clock_state').fetchall()
    if rows != [{'instance_id': instance_id, 'synthetic': True}]:
        raise ValueError('DEMO_CLOCK_EXACT_SINGLE_INSTANCE_REQUIRED')


def _install_clock(owner, *, schema, backend, plan, fingerprint, instance_id, roles):
    """One clock-only transaction; a failure cannot leave half-applied 013."""
    from psycopg import sql
    data = (backend / plan['path']).read_bytes()
    if sha256(data).hexdigest() != plan['sha256']:
        raise ValueError('DEMO_CLOCK_MIGRATION_CHANGED_AFTER_PLAN')
    with owner() as db, db.transaction():
        db.execute(data.decode('utf-8'))
        # MATERIALIZED makes every anchor originate from ONE real DB sample.
        db.execute('''WITH sample AS MATERIALIZED (SELECT clock_timestamp() AS t)
            INSERT INTO demo_clock_state
              (instance_id,synthetic,version,real_anchor,domain_anchor,domain_start,domain_limit,scale)
            SELECT %s,true,0,t,t,t,t+interval '168 hours',1 FROM sample''', (instance_id,))
        worker_bootstrap._grant_profile(db, schema=schema, role_name=roles[1], profile=API_PROFILE)
        worker_bootstrap._grant_profile(db, schema=schema, role_name=roles[2], profile=WORKER_PROFILE)
        db.execute(sql.SQL('COMMENT ON TABLE {} IS {}').format(sql.Identifier(schema, 'demo_clock_state'),
                   sql.Literal(marker('initializing', fingerprint))))


def _complete_clock(owner, *, schema, fingerprint):
    from psycopg import sql
    with owner() as db, db.transaction():
        db.execute(sql.SQL('COMMENT ON TABLE {} IS {}').format(sql.Identifier(schema, 'demo_clock_state'),
                   sql.Literal(marker('complete', fingerprint))))


def apply_capabilities(args, environment):
    """Operator-owned entry point. Args: backend, schema, expected_database, bootstrap.

    Fresh schema only; repeats require both exact completed profile receipts and
    verify the enabled validators without invoking any initializer or seed.
    """
    if (environment.get('DALA_API_MODE') != 'demo'
            or environment.get('DALA_DEMO_SEED_ALLOWED') != '1'
            or environment.get('DALA_DEMO_WORKER_CAPABILITY_ALLOWED') != '1'
            or environment.get('DALA_DEMO_CLOCK_CAPABILITY_ALLOWED') != '1'
            or not args.bootstrap):
        raise ValueError('DEMO_CLOCK_EXPLICIT_BOOTSTRAP_APPROVAL_REQUIRED')
    schema_name(args.schema)
    instance = instance_uuid(environment.get('DALA_DEMO_CLOCK_INSTANCE_ID'))
    if not args.expected_database or not all(environment.get(key) for key in DATABASE_VARIABLES):
        raise ValueError('DEMO_CLOCK_EXISTING_THREE_IDENTITIES_AND_DATABASE_REQUIRED')
    plan = migration_plan(args.backend)
    baseline_plan = worker_migration_plan(args.backend)
    fixture_mode, _, fixture_manifest = worker_bootstrap.selected_fixture(environment)
    _runtime_validators()  # Refuse an unmounted/old runtime before any DB writes.
    import psycopg
    from psycopg.rows import dict_row
    from database_profile import identity
    def connector(name, scoped=True):
        def connect():
            options = '-c statement_timeout=10000 -c lock_timeout=5000'
            if scoped:
                options += f' -c search_path={args.schema}'
            return psycopg.connect(environment[name], autocommit=True, connect_timeout=5,
                                    options=options, row_factory=dict_row)
        return connect
    owner, api, worker = [connector(name) for name in DATABASE_VARIABLES]
    who = [identity(connect) for connect in (owner, api, worker)]
    worker_bootstrap._ensure_identities(*who, expected_database=args.expected_database)
    roles = [row['role_name'] for row in who]
    base_fingerprint = worker_bootstrap.capability_fingerprint(baseline_plan, owner_role=roles[0],
                          api_role=roles[1], worker_role=roles[2], fixture_manifest=fixture_manifest)
    fingerprint = capability_fingerprint(baseline_fingerprint=base_fingerprint, instance_id=instance)
    with connector(DATABASE_VARIABLES[0], False)() as control:
        if not control.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok',
                ('dalaai-clock-bootstrap:' + args.expected_database + ':' + args.schema,)).fetchone()['ok']:
            raise ValueError('DEMO_CLOCK_BOOTSTRAP_ALREADY_RUNNING')
        for role in roles[1:]:
            if control.execute('''SELECT EXISTS (SELECT 1 FROM pg_roles r
                WHERE pg_has_role(%s,r.oid,'MEMBER') AND (r.rolsuper OR r.rolcreatedb
                    OR r.rolcreaterole OR r.rolbypassrls OR r.rolname=%s)) AS bad''',
                    (role, roles[0])).fetchone()['bad']:
                raise ValueError('DEMO_CLOCK_INHERITED_OWNER_OR_ELEVATED_ROLE')
        receipts = _read_markers(control, args.schema)
        if receipts is not None:
            repeat_action(receipts['schema'], receipts['worker'], receipts['clock'],
                          baseline_fingerprint=base_fingerprint, fingerprint=fingerprint)
            _verify_singleton(owner, instance)
            _validate_profiles(api, worker, instance)
            return {'status': 'DEMO_CLOCK_ALREADY_VERIFIED', 'profile_sha256': fingerprint,
                    'instance_id': instance, 'fixture_mode': fixture_mode, 'migrations_replayed': False,
                    'grants_replayed': False, 'seed_replayed': False, 'roles_created': 0,
                    'reset_supported': False, 'deployment_started': False}
        # Check private operator inputs only on the genuinely fresh path. Repeat
        # neither reads PINs nor touches identities/scopes/history receipts.
        worker_bootstrap.preflight_apply(args, environment)
        try:
            initialized = worker_bootstrap.apply_capabilities(args, environment)
            if initialized['status'] != 'WORKER_CAPABILITIES_READY':
                # Another base initializer may have won the race after our first
                # read. A verified existing base is still NOT fresh clock consent.
                raise ValueError('DEMO_CLOCK_CONCURRENT_BASE_INITIALIZATION')
            _install_clock(owner, schema=args.schema, backend=args.backend, plan=plan,
                           fingerprint=fingerprint, instance_id=instance, roles=roles)
            _verify_singleton(owner, instance)
            _validate_profiles(api, worker, instance)
            _complete_clock(owner, schema=args.schema, fingerprint=fingerprint)
        except Exception:
            # Preserve baseline and any initializing marker. No cleanup/retry,
            # clock reset, grant repair or rollback of an earlier committed seed.
            raise RuntimeError('DEMO_CLOCK_BOOTSTRAP_INCOMPLETE_SCHEMA_PRESERVED') from None
    return {'status': 'DEMO_CLOCK_READY', 'profile_sha256': fingerprint, 'instance_id': instance,
            'fixture_mode': fixture_mode, 'migration_count': len(baseline_plan) + 1,
            'clock_rows_seeded': 1, 'initial_scale': 1, 'business_horizon_hours': 168,
            'migrations_replayed': False, 'grants_replayed': False, 'roles_created': 0,
            'reset_supported': False, 'deployment_started': False}


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
        if args.apply:
            result = apply_capabilities(args, os.environ)
        else:
            mode, _, manifest = worker_bootstrap.selected_fixture(os.environ)
            result = {'status': 'PLAN_ONLY_NO_DATABASE_ACCESS', 'schema': args.schema,
                      'migrations': worker_migration_plan(args.backend) + [migration_plan(args.backend)],
                      'api_clock_profile': API_PROFILE, 'worker_clock_profile': WORKER_PROFILE,
                      'fixture_mode': mode, 'fixture_manifest': manifest, 'roles_created': 0,
                      'instance_id_required': 'DALA_DEMO_CLOCK_INSTANCE_ID (fixed canonical UUID)',
                      'repeat': 'verify_only_no_seed_no_migrations_no_regrants_no_reset'}
    except Exception as error:
        result = {'status': 'DEMO_CLOCK_NOT_CONFIRMED', 'error_type': type(error).__name__,
                  'code': str(error) if type(error) is ValueError and str(error).startswith('DEMO_CLOCK_')
                          else 'DEMO_CLOCK_BOOTSTRAP_FAILED',
                  'next_action': 'Keep services stopped; inspect preserved state. No automatic reset or repair.'}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
