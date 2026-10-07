"""Offline source checks plus one explicitly requested disposable PostgreSQL gate."""
import argparse
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'backend'), str(ROOT/'ops/provision')]
import enable_worker_capabilities as helper
from prepare_demo_database import MIGRATIONS, bootstrap_marker, migration_plan, worker_migration_plan


class WorkerCapabilityTests(unittest.TestCase):
    def test_explicit_seven_file_plan_preserves_legacy_four(self):
        plan=worker_migration_plan(ROOT/'backend')
        self.assertEqual([Path(e['path']).name[:3] for e in plan],['001','002','003','004','005','011','012'])
        self.assertEqual(len(migration_plan(ROOT/'backend')),4)
        self.assertEqual(len(MIGRATIONS),4)
        self.assertTrue(plan[2]['path'].startswith('db/proposals/'))
        self.assertTrue(plan[4]['path'].startswith('db/proposals/'))

    def test_api_dispatch_reads_cannot_mutate_history(self):
        p=helper.api_grants()
        self.assertEqual(p['select']['delivery_dispatches'],('lease_token','job_id'))
        self.assertEqual(p['select']['delivery_dispatch_results'],('lease_token','outcome'))
        for table in ('delivery_dispatches','delivery_dispatch_results','ai_assessments'):
            self.assertNotIn(table,p['insert'])
            self.assertNotIn(table,p['update'])
        self.assertNotIn('lease_token',p['update']['delivery_jobs'])
        self.assertNotIn('employee_id',p['update']['push_subscriptions'])

    def test_exact_three_distinct_direct_restricted_identities(self):
        base={'database_name':'isolated','server_address':'127.0.0.1','server_port':5432,
              'rolsuper':False,'rolcreatedb':False,'rolcreaterole':False,'rolbypassrls':False}
        values=[dict(base,role_name=r,session_role=r) for r in ('owner','api','worker')]
        helper._ensure_identities(*values,expected_database='isolated')
        for changes in ({'role_name':'api'},{'session_role':'owner'}, {'rolsuper':True},
                        {'database_name':'foreign'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                helper._ensure_identities(values[0],values[1],dict(values[2],**changes),expected_database='isolated')

    def test_repeat_rejects_missing_partial_foreign_or_changed_role_marker(self):
        fingerprint='a'*64
        self.assertEqual(helper.repeat_action(bootstrap_marker('seeded'),helper.marker('complete',fingerprint),fingerprint),'verify_only')
        for schema_marker,capability_marker in ((None,None),('foreign',None),
            (helper.marker('initializing',fingerprint),None),(bootstrap_marker('seeded'),None),
            (bootstrap_marker('ready'),helper.marker('complete','b'*64))):
            with self.subTest(marker=schema_marker),self.assertRaises(ValueError):
                helper.repeat_action(schema_marker,capability_marker,fingerprint)

    def test_no_database_plan_never_reads_credentials(self):
        output=io.StringIO()
        with patch.dict(os.environ,{'DALA_DEMO_OWNER_DATABASE_URL':'do-not-log'},clear=True):
            with patch('psycopg.connect',side_effect=AssertionError('no database')),redirect_stdout(output):
                self.assertEqual(helper.main(['--backend',str(ROOT/'backend'),'--schema','worker_test']),0)
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'PLAN_ONLY_NO_DATABASE_ACCESS')
        self.assertEqual(len(result['migrations']),7)
        self.assertEqual(result['required_worker_settings']['DALA_WORKER_NOTIFY_ENABLED'],'true')
        self.assertNotIn('do-not-log',output.getvalue())

    def test_rendered_grants_have_no_role_or_wildcard_grant(self):
        class DB:
            statements=[]
            def execute(self,sql):self.statements.append(sql.as_string())
        db=DB()
        helper._grant_profile(db,schema='worker_test',role_name='existing_api',profile=helper.api_grants())
        rendered='\n'.join(db.statements)
        for forbidden in ('CREATE ROLE','ALTER ROLE','PASSWORD','ALL TABLES','ALL SEQUENCES','GRANT ALL'):
            self.assertNotIn(forbidden,rendered)
        self.assertIn('GRANT SELECT ("lease_token","job_id")',rendered)

    def test_repeat_does_not_regrant_after_validation_failure(self):
        plan=worker_migration_plan(ROOT/'backend')
        roles=('owner','api','worker')
        fingerprint=helper.capability_fingerprint(plan,owner_role='owner',api_role='api',worker_role='worker')
        queries=[]
        class DB:
            def __init__(self,role):self.role=role
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,sql,params=None):
                queries.append(str(sql))
                if 'pg_try_advisory_lock' in sql:row={'ok':True}
                elif 'SELECT EXISTS' in sql:row={'bad':False}
                elif "'pg_namespace'" in sql:row={'marker':bootstrap_marker('seeded')}
                elif "'pg_class'" in sql:row={'marker':helper.marker('complete',fingerprint)}
                else:raise AssertionError('Unexpected write/query')
                return SimpleNamespace(fetchone=lambda:row)
        def who(connect):
            with connect() as db:
                return dict(database_name='isolated',server_address='127.0.0.1',server_port=5432,
                    role_name=db.role,session_role=db.role,rolsuper=False,rolcreatedb=False,rolcreaterole=False,rolbypassrls=False)
        env=dict(zip(('DALA_DEMO_OWNER_DATABASE_URL','DALA_DEMO_RUNTIME_DATABASE_URL','DALA_DEMO_WORKER_DATABASE_URL'),roles),
                 DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1')
        args=argparse.Namespace(backend=ROOT/'backend',schema='worker_test',expected_database='isolated',bootstrap=True)
        with patch.object(helper,'preflight_apply',return_value={}),patch('database_profile.identity',side_effect=who), \
             patch('psycopg.connect',side_effect=lambda role,**kwargs:DB(role)), \
             patch.object(helper,'validate_api_profile',side_effect=ValueError('revoked')), \
             patch.object(helper,'_grant_profile',side_effect=AssertionError('must not regrant')), \
             patch.object(helper,'apply_fixture',side_effect=AssertionError('must not reseed')):
            with self.assertRaisesRegex(ValueError,'revoked'):helper.apply_capabilities(args,env)
        self.assertFalse(any(any(v in q for v in ('GRANT','CREATE ','ALTER ','COMMENT ')) for q in queries))


class DisposableWorkerGate(unittest.TestCase):
    """Only --postgres-disposable runs this; existing operator-supplied identities."""
    def test_fresh_repeat_denials_and_revoked_grant_are_not_repaired(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg.errors import InsufficientPrivilege
        names=('DALA_TEST_DATABASE_URL','DALA_ACCEPTANCE_RUNTIME_DATABASE_URL','DALA_ACCEPTANCE_WORKER_DATABASE_URL')
        schema='worker_gate_'+uuid4().hex
        with psycopg.connect(os.environ[names[0]],autocommit=True) as db:
            database=db.execute('SELECT current_database()').fetchone()[0]
        env=dict(os.environ,DALA_API_MODE='demo',DALA_DEMO_SEED_ALLOWED='1',DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1',
            DALA_DEMO_OWNER_DATABASE_URL=os.environ[names[0]],DALA_DEMO_RUNTIME_DATABASE_URL=os.environ[names[1]],
            DALA_DEMO_WORKER_DATABASE_URL=os.environ[names[2]])
        args=argparse.Namespace(backend=ROOT/'backend',schema=schema,expected_database=database,bootstrap=True)
        def connect(role):return psycopg.connect(os.environ[names[role]],autocommit=True,row_factory=dict_row,
                                                options=f'-c search_path={schema}')
        try:
            first=helper.apply_capabilities(args,env)
            self.assertEqual(first['status'],'WORKER_CAPABILITIES_READY')
            self.assertEqual(first['migration_count'],7)
            again=helper.apply_capabilities(args,env)
            self.assertEqual(again['status'],'WORKER_CAPABILITIES_ALREADY_VERIFIED')
            self.assertFalse(again['grants_replayed'])
            with connect(1) as api:
                api.execute('SELECT d.job_id,r.outcome FROM delivery_dispatches d LEFT JOIN delivery_dispatch_results r ON r.lease_token=d.lease_token LIMIT 0')
                with self.assertRaises(InsufficientPrivilege):api.execute('UPDATE delivery_dispatches SET attempt_number=1 WHERE false')
            with connect(2) as worker:
                worker_role=worker.execute('SELECT current_user AS name').fetchone()['name']
                with self.assertRaises(InsufficientPrivilege):worker.execute('SELECT pin_hash FROM employees LIMIT 0')
                with self.assertRaises(InsufficientPrivilege):worker.execute('UPDATE orders SET status=status WHERE false')
            with connect(0) as owner:
                owner.execute(sql.SQL('REVOKE UPDATE (lease_token) ON {} FROM {}').format(
                    sql.Identifier(schema,'ai_jobs'),sql.Identifier(worker_role)))
            with self.assertRaises(Exception):helper.apply_capabilities(args,env)
            with connect(2) as worker:
                self.assertFalse(worker.execute("SELECT has_column_privilege('ai_jobs','lease_token','UPDATE') AS ok").fetchone()['ok'])
        finally:
            # Only the random namespace created by THIS explicitly disposable gate.
            with psycopg.connect(os.environ[names[0]],autocommit=True) as db:
                db.execute(sql.SQL('DROP SCHEMA IF EXISTS {} CASCADE').format(sql.Identifier(schema)))


def run_postgres_gate():
    required=('DALA_TEST_DATABASE_URL','DALA_ACCEPTANCE_RUNTIME_DATABASE_URL','DALA_ACCEPTANCE_WORKER_DATABASE_URL',
              'DALA_DEMO_MASTER_PIN','DALA_DEMO_EXECUTOR_PIN')
    if os.environ.get('DALA_ACCEPTANCE_DISPOSABLE')!='1' or any(not os.environ.get(v) for v in required):
        print('NOT_RUN: explicit disposable local DB, three existing LOGINs and operator-supplied test PINs required')
        return 2
    from psycopg.conninfo import conninfo_to_dict
    if any(os.environ.get(v) for v in ('PGSERVICE','PGSERVICEFILE','PGHOSTADDR')):
        raise ValueError('Ambient service indirection refused')
    for name in required[:3]:
        parts=conninfo_to_dict(os.environ[name]);host=parts.get('host','')
        if (not parts.get('dbname') or not host or ',' in host or parts.get('service') or parts.get('servicefile')
                or parts.get('hostaddr') not in (None,'','127.0.0.1','::1')
                or host not in ('localhost','127.0.0.1','::1') and not host.startswith('/')):
            raise ValueError('Only explicit local disposable PostgreSQL DSNs are supported')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DisposableWorkerGate))
    return 0 if result.wasSuccessful() and result.testsRun==1 and not result.skipped else 1


def load_tests(loader,tests,pattern):return loader.loadTestsFromTestCase(WorkerCapabilityTests)


if __name__=='__main__':
    if sys.argv[1:]==['--postgres-disposable']:
        raise SystemExit(run_postgres_gate())
    unittest.main()
