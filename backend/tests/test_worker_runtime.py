"""Process/config/fencing assembly tests; no provider network or live grants."""
import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.worker_runtime import (WorkerConfigurationError, WorkerPrerequisiteError,
    WorkerRuntime, WorkerSettings, build_model_adapter, build_runtime, main, run,
    validate_database, worker_grants)


class TestSettings(unittest.TestCase):
    def test_import_and_disabled_ignore_secrets(self):
        with patch('app.worker_runtime._read_file', side_effect=AssertionError('must not read')):
            settings = WorkerSettings.from_env({'DALA_WORKER_ENABLED': 'false',
                'DALA_WORKER_DATABASE_URL_FILE': '/bad/secret'})
        self.assertFalse(settings.enabled)
        with patch('app.worker_runtime.build_runtime', side_effect=AssertionError('no build')):
            with patch.dict(os.environ, {'DALA_WORKER_ENABLED': 'false'}, clear=True), redirect_stdout(io.StringIO()):
                self.assertEqual(main([]), 0)
                self.assertEqual(main(['--check']), 2)

    def test_no_api_dsn_fallback(self):
        with self.assertRaises(WorkerConfigurationError):
            WorkerSettings.from_env({'DALA_WORKER_ENABLED': 'true', 'DATABASE_URL': 'secret'})

    def test_file_secret_is_hidden_and_conflict_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'secret'
            path.write_text('postgresql://do-not-log')
            settings = WorkerSettings.from_env({'DALA_WORKER_ENABLED': 'true',
                'DALA_WORKER_DATABASE_URL_FILE': str(path)})
            self.assertNotIn('do-not-log', repr(settings))
            with self.assertRaises(WorkerConfigurationError):
                WorkerSettings.from_env({'DALA_WORKER_ENABLED': 'true',
                    'DALA_WORKER_DATABASE_URL_FILE': str(path), 'DALA_WORKER_DATABASE_URL': 'other'})
            link = Path(d)/'link'
            link.symlink_to(path)
            with self.assertRaises(WorkerConfigurationError):
                WorkerSettings.from_env({'DALA_WORKER_ENABLED': 'true',
                    'DALA_WORKER_DATABASE_URL_FILE': str(link)})

    def test_strict_flags_bounds_and_opt_in(self):
        for kwargs in ({'enabled': 1}, {'channel': 'synthetic'}, {'tick_seconds': float('nan')},
                       {'ai_limit': 0}, {'dispatch_limit': 21}, {'reconcile_limit': 1001},
                       {'notify_enabled': True, 'channel': 'telegram'}, {'runtime_mode': 'production'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(WorkerConfigurationError):
                WorkerSettings(**kwargs)

    def test_force_off_never_reads_key(self):
        settings = WorkerSettings(enabled=True, database_url='test', model_force_off=True)
        with patch('app.worker_runtime.validate_database'), patch('app.worker_runtime.build_model_adapter', side_effect=AssertionError()):
            runtime = build_runtime(settings, environment={'OPENAI_API_KEY_FILE': '/absent'}, connect=lambda: None)
        self.assertEqual(runtime.ai_mode, 'rules_fallback_forced_off')
        self.assertIsNot(runtime.assessment.real_clock, runtime.assessment.domain_clock)

    def test_key_absent_uses_rules_without_policy_or_ledger(self):
        clock = SimpleNamespace(now=lambda: datetime.now(timezone.utc))
        adapter, mode, project = build_model_adapter({}, clock, runtime_mode='demo')
        self.assertIsNone(adapter)
        self.assertIsNone(project)
        self.assertEqual(mode, 'rules_fallback')

    def test_notification_disabled_does_not_construct_or_consume_lane(self):
        settings = WorkerSettings(enabled=True, database_url='test', notify_enabled=True)
        with patch('app.worker_runtime.validate_database') as validator:
            runtime = build_runtime(settings, environment={}, connect=lambda: None)
        self.assertIsNone(runtime.dispatcher)
        self.assertIsNone(runtime.reconciler)
        self.assertEqual(runtime.notification_state, 'paused_web_push_disabled')
        self.assertTrue(validator.call_args.kwargs['web_push'])  # provisioned capability preserved

    def test_disabled_only_notification_lane_refuses_start(self):
        settings = WorkerSettings(enabled=True, database_url='test', ai_enabled=False, notify_enabled=True)
        with patch('app.worker_runtime.validate_database', side_effect=AssertionError('no connection')):
            with self.assertRaises(WorkerConfigurationError):
                build_runtime(settings, environment={}, connect=lambda: None)

    def test_telegram_dry_run_never_drains_real_lane(self):
        settings = WorkerSettings(enabled=True, database_url='test', notify_enabled=True,
                                  channel='telegram', telegram_enabled=True)
        with patch('app.worker_runtime.validate_database'):
            runtime = build_runtime(settings, environment={'TELEGRAM_MODE': 'dry_run'}, connect=lambda: None)
        self.assertIsNone(runtime.dispatcher)
        self.assertEqual(runtime.notification_state, 'paused_telegram_not_live')

    def test_push_primary_uses_hard_bounded_adapter(self):
        from app.notify.worker import DeliveryWorker
        settings=WorkerSettings(enabled=True,database_url='secret',notify_enabled=True)
        adapter=SimpleNamespace(max_call_seconds=22)
        with patch('app.worker_runtime.validate_database'), \
             patch('app.push.settings.PushSettings'), \
             patch('app.push.adapter.BoundedPostgresWebPushAdapter',return_value=adapter) as factory:
            runtime=build_runtime(settings,environment={'DALA_WEB_PUSH_ENABLED':'true'},connect=lambda:None)
        self.assertIsInstance(runtime.dispatcher,DeliveryWorker)
        self.assertEqual(runtime.dispatcher.channel,'web_push')
        self.assertIs(runtime.dispatcher.adapter,adapter)
        self.assertEqual(runtime.notification_state,'configured_web_push')
        self.assertEqual(factory.call_args.kwargs['database_url'],'secret')
        self.assertIs(runtime.dispatcher.real_clock,runtime.reconciler.real_clock)
        self.assertIsNot(runtime.dispatcher.real_clock,runtime.dispatcher.domain_clock)

    def test_key_only_selects_actual_provider_and_automatic_camera(self):
        from app.jobs.provider_worker import ProviderAssessmentWorker,CameraAssetsFactory
        from app.ai.demo_policy import build_interactive_demo_policy
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); photo=root/'photos'; photo.mkdir(mode=0o700)
            policy=root/'policy.json'
            policy.write_text(json.dumps(build_interactive_demo_policy(project_id='DalaAI',instance_id='test-demo')))
            settings=WorkerSettings(enabled=True,database_url='test',runtime_mode='demo',photo_storage_root=str(photo))
            environment={'OPENAI_API_KEY':'unit-test-placeholder', 'DALA_WORKER_OPENAI_ENABLED':'false', 'DALA_MODEL_APPROVAL_FILE':str(policy),
                'DALA_MODEL_PROJECT_ID':'DalaAI','DALA_MODEL_INSTANCE_ID':'test-demo',
                'DALA_MODEL_BUDGET_PATH':str(root/'ledger.sqlite')}
            with patch('app.worker_runtime.validate_database'):
                runtime=build_runtime(settings,environment=environment,connect=lambda:None)
            self.assertIsInstance(runtime.assessment,ProviderAssessmentWorker)
            self.assertIsInstance(runtime.assessment.assets_factory,CameraAssetsFactory)
            self.assertEqual(runtime.assessment.demo_project.instance_id,'test-demo')
            self.assertEqual(runtime.ai_mode,'openai_authorized_demo_policy')
            self.assertEqual(runtime.assessment.adapter.ledger.counters()['calls_reserved'],0)

    def test_key_requires_actual_demo_mode_policy_scope_and_verified_photos(self):
        from app.ai.demo_policy import build_interactive_demo_policy
        clock=SimpleNamespace(now=lambda:datetime(2026,10,7,tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); policy=root/'policy.json'
            policy.write_text(json.dumps(build_interactive_demo_policy(project_id='DalaAI',instance_id='test-demo')))
            good={'OPENAI_API_KEY':'unit-test-placeholder','DALA_MODEL_APPROVAL_FILE':str(policy),
                'DALA_MODEL_PROJECT_ID':'DalaAI','DALA_MODEL_INSTANCE_ID':'test-demo',
                'DALA_MODEL_BUDGET_PATH':str(root/'ledger.sqlite')}
            for mode,change in (('health',{}),('demo',{'DALA_MODEL_PROJECT_ID':'Other'}),
                               ('demo',{'DALA_MODEL_INSTANCE_ID':'other-instance'}),
                               ('demo',{'DALA_MODEL_APPROVAL_FILE':''})):
                with self.subTest(mode=mode,change=change),self.assertRaises(WorkerConfigurationError):
                    build_model_adapter({**good,**change},clock,runtime_mode=mode)
            settings=WorkerSettings(enabled=True,database_url='test',runtime_mode='demo')
            with patch('app.worker_runtime.validate_database'),self.assertRaises(WorkerConfigurationError):
                build_runtime(settings,environment=good,connect=lambda:None)

    def test_policy_expiry_and_key_file_source_are_enforced(self):
        from app.ai.demo_policy import build_interactive_demo_policy
        clock=SimpleNamespace(now=lambda:datetime(2026,10,7,tzinfo=timezone.utc))
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); policy=root/'policy.json'; key=root/'key'
            key.write_text('unit-test-placeholder')
            policy.write_text(json.dumps(build_interactive_demo_policy(project_id='DalaAI',instance_id='demo',
                expires_at=datetime(2026,10,6,tzinfo=timezone.utc))))
            env={'OPENAI_API_KEY_FILE':str(key),'DALA_MODEL_APPROVAL_FILE':str(policy),
                 'DALA_MODEL_PROJECT_ID':'DalaAI','DALA_MODEL_INSTANCE_ID':'demo',
                 'DALA_MODEL_BUDGET_PATH':str(root/'ledger.sqlite')}
            with self.assertRaises(WorkerConfigurationError):build_model_adapter(env,clock,runtime_mode='demo')
            policy.write_text(json.dumps(build_interactive_demo_policy(project_id='DalaAI',instance_id='demo')))
            with patch('app.ai.demo_policy.read_demo_policy',side_effect=AssertionError('must not reopen checked path')):
                adapter,mode,project=build_model_adapter(env,clock,runtime_mode='demo')
            self.assertIsNotNone(adapter.transport)
            self.assertEqual(adapter.ledger.counters()['calls_reserved'],0)
            self.assertNotIn('unit-test-placeholder',repr(adapter.transport))

    def test_real_clocks_ignore_demo_environment(self):
        from app.core.auth_boundary import SystemRealClock
        settings = WorkerSettings(enabled=True, database_url='test')
        with patch('app.worker_runtime.validate_database'):
            runtime = build_runtime(settings, environment={'TIME_SCALE': '100000', 'DEMO_NOW': '1900-01-01'}, connect=lambda: None)
        self.assertIsInstance(runtime.assessment.real_clock, SystemRealClock)
        self.assertIsInstance(runtime.assessment.domain_clock, SystemRealClock)
        self.assertLess(abs((runtime.assessment.real_clock.now()-datetime.now(timezone.utc)).total_seconds()), 2)

    def test_errors_do_not_echo_secrets(self):
        output = io.StringIO()
        with patch.dict(os.environ, {'DALA_WORKER_ENABLED': 'true', 'DALA_WORKER_DATABASE_URL': 'secret'}, clear=True), \
             patch('app.worker_runtime.build_runtime', side_effect=RuntimeError('secret')), redirect_stdout(output):
            self.assertEqual(main([]), 2)
        self.assertNotIn('secret', output.getvalue())


class RunnerTests(unittest.TestCase):
    def test_sync_async_limits_and_reconcile_cursor(self):
        calls=[]
        class AI:
            async def run_once(self):
                calls.append('ai')
                return SimpleNamespace(state='done')
        class Dispatch:
            def run_once(self):
                calls.append('dispatch')
                return SimpleNamespace(state='provider_accepted')
        class Reconcile:
            def scan_once(self, *, limit, after_id):
                calls.append(('reconcile', limit, after_id))
                return SimpleNamespace(results=(SimpleNamespace(due_intents=1),), next_after_id='next')
        runtime=WorkerRuntime(WorkerSettings(ai_limit=2,dispatch_limit=3,reconcile_limit=4),
                              AI(), Reconcile(), Dispatch())
        result=asyncio.run(runtime.tick(stop=threading.Event()))
        self.assertEqual(result['ai_states'], {'done':2})
        self.assertEqual(result['dispatch_states'], {'provider_accepted':3})
        self.assertEqual(result['reconciled_orders'],4)
        self.assertEqual(calls[:3], [('reconcile',1,None),'dispatch','ai'])
        self.assertTrue(all(c[1]==1 for c in calls if isinstance(c,tuple)))
        self.assertEqual(runtime._after_id,'next')

    def test_idle_and_end_of_sweep_do_not_busy_loop(self):
        class Idle:
            calls=0
            def run_once(self):
                self.calls+=1
                return SimpleNamespace(state='idle')
        idle=Idle()
        runtime=WorkerRuntime(WorkerSettings(ai_limit=20), assessment=idle)
        self.assertEqual(asyncio.run(runtime.tick(stop=threading.Event()))['ai_states'],{})
        self.assertEqual(idle.calls,1)

    def test_stop_prevents_next_job(self):
        stop=threading.Event()
        class AI:
            def run_once(self):
                stop.set()
                return SimpleNamespace(state='done')
        runtime=WorkerRuntime(WorkerSettings(ai_limit=20),assessment=AI())
        self.assertEqual(asyncio.run(runtime.tick(stop=stop))['ai_states'],{'done':1})

    def test_monotonic_admission_bound(self):
        times=iter((0, 0, 0, 0, 30))
        worker=SimpleNamespace(run_once=lambda:SimpleNamespace(state='done'))
        runtime=WorkerRuntime(WorkerSettings(ai_limit=20),assessment=worker,monotonic=lambda:next(times))
        self.assertEqual(asyncio.run(runtime.tick(stop=threading.Event()))['ai_states'],{'done':1})

    def test_error_backpressure_and_bounded_exit(self):
        class Stop:
            waits=[]
            def is_set(self):return False
            def wait(self,seconds):self.waits.append(seconds)
        class Runtime:
            settings=WorkerSettings(max_consecutive_errors=3)
            async def tick(self,*,stop):raise RuntimeError('secret')
        stop=Stop(); events=[]
        self.assertEqual(run(Runtime(),stop=stop,output=events.append),1)
        self.assertEqual(stop.waits,[2.0,4.0])
        self.assertEqual(len(events),3)
        self.assertNotIn('secret',json.dumps(events))

    def test_signal_handler_is_installed_and_restored(self):
        runtime=WorkerRuntime(WorkerSettings(enabled=True,database_url='test'))
        registered={}
        def register(signum,handler):
            previous=registered.get(signum,'previous')
            registered[signum]=handler
            return previous
        def fake_run(runtime,*,stop):
            registered[signal.SIGTERM](None,None)
            self.assertTrue(stop.is_set())
            return 0
        with patch('app.worker_runtime.WorkerSettings.from_env',return_value=runtime.settings), \
             patch('app.worker_runtime.build_runtime',return_value=runtime), \
             patch('app.worker_runtime.signal.signal',side_effect=register), \
             patch('app.worker_runtime.run',side_effect=fake_run), redirect_stdout(io.StringIO()):
            self.assertEqual(main([]),0)
        self.assertEqual(registered,{signal.SIGINT:'previous',signal.SIGTERM:'previous'})


class ProfileTests(unittest.TestCase):
    def test_minimal_sensitive_grants(self):
        grants=worker_grants(web_push=True)
        self.assertNotIn('pin_hash',grants['select']['employees'])
        self.assertNotIn('csrf_token',grants['select']['auth_sessions'])
        self.assertNotIn('auth_sessions',grants['update'])
        self.assertEqual(grants['update']['photos'],('exif_removed',))
        self.assertEqual(grants['update']['orders'],('version','updated_at'))
        self.assertNotIn('reviews',grants['insert'])
        self.assertNotIn('ai_jobs',grants['insert'])
        notify=worker_grants(ai_enabled=False,web_push=True)
        self.assertIn('attached_at',notify['select']['photos'])

    def test_db_errors_sanitized(self):
        def broken():raise RuntimeError('secret DSN')
        with self.assertRaises(WorkerPrerequisiteError) as error:
            validate_database(broken)
        self.assertNotIn('secret',str(error.exception))
        self.assertEqual(error.exception.code,'WORKER_DATABASE_UNAVAILABLE_OR_SCHEMA_MISSING')


class FakeCatalog:
    """Unit SQL-contract fixture, explicitly NOT a PostgreSQL implementation."""
    def __init__(self, *, extra=None, missing_guard=False, unsafe_photo=False, elevated=False, missing_column=False):
        from app.worker_runtime import _REQUIRED_COLUMNS,_COMMON_GUARDS,_AI_GUARDS,_NOTIFY_GUARDS
        from psycopg.pq import TransactionStatus
        self.autocommit=True
        self.info=SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.grants=worker_grants(web_push=True)
        names=sorted(set(self.grants['select'])|set(self.grants['insert'])|set(self.grants['update'])|{'auth_login_limits'})
        self.tables={i+1:n for i,n in enumerate(names)}
        self.columns={}
        for oid,name in self.tables.items():
            cols=set(_REQUIRED_COLUMNS.get(name,'').split())
            for group in ('select','update'):
                allowed=self.grants[group].get(name,())
                if allowed!='*':cols.update(allowed)
            if name=='employees':cols.add('pin_hash')
            if name=='auth_sessions':cols.add('csrf_token')
            if name=='auth_login_limits':cols.add('bucket')
            self.columns[oid]=cols
        if missing_column:
            self.columns[next(i for i,n in self.tables.items() if n=='ai_jobs')].remove('lease_token')
        self.guards=_COMMON_GUARDS|_AI_GUARDS|_NOTIFY_GUARDS|{('push_subscriptions','push_subscription_owner_immutable')}
        if missing_guard:self.guards=self.guards-{('employees','employees_identity_immutable')}
        self.extra=extra
        self.unsafe_photo=unsafe_photo
        self.elevated=elevated
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def execute(self,query,params=None):
        if not isinstance(query,str):rows=[]
        elif 'current_user=session_user' in query:
            rows=[{'direct_login':True,'can_create':False,'elevated':self.elevated,'owns':False}]
        elif 'FROM pg_trigger' in query:rows=[{'relname':t,'tgname':g} for t,g in self.guards]
        elif 'a.attnotnull' in query:rows=[{'ok':not self.unsafe_photo}]
        elif "c.relkind='S'" in query:rows=[]
        elif 'c.relkind IN' in query:rows=[{'oid':oid,'relname':name} for oid,name in self.tables.items()]
        elif 'has_table_privilege' in query:
            oid=params[0]
            privilege=params[1] if len(params)>1 else 'INSERT'
            rows=[{'ok':privilege=='INSERT' and self.tables[oid] in self.grants['insert']}]
        elif 'FROM pg_attribute' in query:rows=[{'attname':c} for c in self.columns[params[0]]]
        elif 'has_column_privilege' in query:
            oid,col,privilege=params; name=self.tables[oid]
            if privilege in ('SELECT','UPDATE'):
                allowed=self.grants[privilege.lower()].get(name,())
                ok=allowed=='*' or col in allowed
            else:ok=privilege=='INSERT' and name in self.grants['insert']
            if (name,col,privilege)==self.extra:ok=True
            rows=[{'ok':ok}]
        else:raise AssertionError('Unexpected SQL')
        return SimpleNamespace(fetchone=lambda:rows[0] if rows else None,fetchall=lambda:rows)


class CatalogTests(unittest.TestCase):
    def test_intended_grants_match_catalog(self):
        validate_database(lambda:FakeCatalog(),web_push=True)

    def test_extra_column_or_grant_option_is_blocked(self):
        for extra in (('employees','pin_hash','SELECT'),('auth_sessions','csrf_token','SELECT'),
                      ('photos','file_valid','UPDATE'),('orders','status','UPDATE'),
                      ('auth_sessions','csrf_token','INSERT'),('employees','id','SELECT WITH GRANT OPTION')):
            with self.subTest(extra=extra),self.assertRaises(WorkerPrerequisiteError) as caught:
                validate_database(lambda:FakeCatalog(extra=extra),web_push=True)
            self.assertEqual(caught.exception.code,'WORKER_COLUMN_GRANT_MISMATCH')

    def test_guards_privileged_role_and_schema_are_blocked(self):
        for kwargs,code in (({'missing_guard':True},'WORKER_REQUIRED_GUARD_MISSING'),
                            ({'unsafe_photo':True},'WORKER_PHOTO_LOCK_GUARD_MISSING'),
                            ({'elevated':True},'WORKER_ROLE_NOT_RESTRICTED'),
                            ({'missing_column':True},'WORKER_SCHEMA_COLUMNS_MISSING')):
            with self.subTest(kwargs=kwargs),self.assertRaises(WorkerPrerequisiteError) as caught:
                validate_database(lambda:FakeCatalog(**kwargs),web_push=True)
            self.assertEqual(caught.exception.code,code)


class WorkerPostgresGate(unittest.TestCase):
    """Mandatory operator-provisioned isolated-role gate; no grants or writes."""
    @classmethod
    def setUpClass(cls):
        from app.worker_runtime import connection_factory
        url=os.environ['DALA_WORKER_TEST_DATABASE_URL']
        schema=os.environ['DALA_WORKER_TEST_SCHEMA']
        if not schema.startswith('worker_gate_'):
            raise ValueError('Dedicated worker_gate_ schema required')
        cls.settings=WorkerSettings(enabled=True,database_url=url,database_schema=schema,notify_enabled=True)
        cls.connect=staticmethod(connection_factory(cls.settings))

    def test_actual_restricted_catalog(self):
        validate_database(self.connect,ai_enabled=True,notify_enabled=True,web_push=True)

    def test_actual_row_lock_permissions(self):
        with self.connect() as db,db.transaction():
            for query in (
                'SELECT id FROM orders LIMIT 0 FOR UPDATE',
                'SELECT id FROM photos LIMIT 0 FOR SHARE',
                'SELECT id FROM employees LIMIT 0 FOR SHARE',
                'SELECT employee_id FROM employee_sections LIMIT 0 FOR SHARE',
                'SELECT id FROM work_codes LIMIT 0 FOR SHARE',
                'SELECT id FROM materials LIMIT 0 FOR SHARE',
                'SELECT id FROM ai_jobs LIMIT 0 FOR UPDATE',
                'SELECT id FROM delivery_jobs LIMIT 0 FOR UPDATE'):
                db.execute(query)

    def test_actual_sensitive_denials(self):
        from psycopg.errors import InsufficientPrivilege
        queries=(
            'SELECT pin_hash FROM employees LIMIT 0',
            'SELECT csrf_token FROM auth_sessions LIMIT 0',
            'UPDATE employees SET role=role WHERE false',
            'UPDATE photos SET file_valid=false WHERE false',
            'UPDATE photos SET storage_key=storage_key WHERE false',
            'UPDATE orders SET status=status WHERE false',
            'UPDATE auth_sessions SET revoked_at=revoked_at WHERE false',
            'DELETE FROM ai_jobs WHERE false',
            'DELETE FROM delivery_dispatch_results WHERE false')
        for query in queries:
            with self.subTest(query=query),self.connect() as db:
                with self.assertRaises(InsufficientPrivilege):
                    db.execute(query)


def run_postgres_gate():
    if not os.environ.get('DALA_WORKER_TEST_DATABASE_URL') or not os.environ.get('DALA_WORKER_TEST_SCHEMA'):
        print('NOT_RUN: DALA_WORKER_TEST_DATABASE_URL and DALA_WORKER_TEST_SCHEMA are required')
        return 2
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkerPostgresGate))
    return 0 if result.wasSuccessful() else 1


# Keep the explicitly requested database gate out of ordinary unit discovery.
# A missing DSN is NOT a skipped green integration test.
def load_tests(loader, tests, pattern):
    suite=unittest.TestSuite()
    for case in (TestSettings,RunnerTests,ProfileTests,CatalogTests):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite


if __name__=='__main__':
    if sys.argv[1:]==['--postgres']:
        raise SystemExit(run_postgres_gate())
    unittest.main()
