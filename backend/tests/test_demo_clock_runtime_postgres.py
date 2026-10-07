"""Actual restricted API/worker shared-clock integration; no provider calls."""
import argparse
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from uuid import uuid4

from test_worker_runtime_postgres import WorkerRuntimePostgresTests, ROOT, ORIGIN


class MountedClockTests(WorkerRuntimePostgresTests):
    def setUp(self):
        sys.path.insert(0,str(ROOT/'ops/provision'))
        from enable_demo_clock import apply_capabilities
        from app.main import create_app
        from app.runtime import RuntimeSettings
        self.schema='clock_flow_'+uuid4().hex
        self.instance=str(uuid4())
        self.addCleanup(self.drop_schema)
        directory=tempfile.TemporaryDirectory(prefix='dala-clock-photo-')
        self.addCleanup(directory.cleanup)
        self.photo_root=Path(directory.name)
        self.environment=dict(self.inputs,DALA_ACCEPTANCE_DISPOSABLE='1',DALA_API_MODE='demo',
            DALA_DEMO_SEED_ALLOWED='1',DALA_DEMO_WORKER_CAPABILITY_ALLOWED='1',
            DALA_DEMO_CLOCK_CAPABILITY_ALLOWED='1',DALA_DEMO_CLOCK_ENABLED='true',
            DALA_DEMO_CLOCK_INSTANCE_ID=self.instance,
            DALA_DEMO_OWNER_DATABASE_URL=self.inputs['DALA_TEST_DATABASE_URL'],
            DALA_DEMO_RUNTIME_DATABASE_URL=self.inputs['DALA_ACCEPTANCE_RUNTIME_DATABASE_URL'],
            DALA_DEMO_WORKER_DATABASE_URL=self.inputs['DALA_ACCEPTANCE_WORKER_DATABASE_URL'],
            DATABASE_URL=self.inputs['DALA_ACCEPTANCE_RUNTIME_DATABASE_URL'],
            DALA_DATABASE_SCHEMA=self.schema,DALA_ALLOWED_ORIGIN=ORIGIN,
            DALA_NOTIFICATION_CAPABILITY='true',DALA_PUSH_CAPABILITY='true',DALA_DELIVERY_CHANNEL='web_push',
            DALA_WEB_PUSH_ENABLED='false',DALA_PHOTO_STORAGE_ROOT=str(self.photo_root),
            DALA_WORKER_ENABLED='true',DALA_WORKER_AI_ENABLED='true',DALA_WORKER_NOTIFY_ENABLED='true',
            DALA_WORKER_CHANNEL='web_push',DALA_WORKER_DATABASE_URL=self.inputs['DALA_ACCEPTANCE_WORKER_DATABASE_URL'])
        env=patch.dict(os.environ,self.environment,clear=True);env.start();self.addCleanup(env.stop)
        args=argparse.Namespace(backend=ROOT/'backend',schema=self.schema,expected_database=self.database,bootstrap=True)
        self.assertEqual(apply_capabilities(args,self.environment)['status'],'DEMO_CLOCK_READY')
        self.api_settings=RuntimeSettings.from_env()
        self.app=create_app(settings=self.api_settings)

    def control(self,master,csrf,action='set_scale',value=0):
        snapshot=master.get('/api/v1/demo/clock').json()
        body={'instance_id':self.instance,'expected_version':snapshot['version'],'action':action,
              'scale' if action=='set_scale' else 'seconds':value}
        return self._post(master,csrf,'/api/v1/demo/clock',body),body

    def test_control_is_master_only_cas_and_real_session_expiry(self):
        from provision_synthetic_demo import IDENTITY
        with ExitStack() as stack:
            master,executor,mcsrf,ecsr=self._clients(stack)
            self.assertEqual(executor.get('/api/v1/demo/clock').status_code,403)
            self.assertEqual(master.post('/api/v1/demo/clock',json={}).status_code,403)
            paused,_=self.control(master,mcsrf)
            advanced,command=self.control(master,mcsrf,'advance',3600)
            self.assertEqual(datetime.fromisoformat(advanced['domain_now'])-datetime.fromisoformat(paused['domain_now']),timedelta(hours=1))
            self._post(master,mcsrf,'/api/v1/demo/clock',command,expected=409)
            self.assertEqual(master.get('/api/v1/me').status_code,200)
            with self.connect() as db:
                db.execute("UPDATE auth_sessions SET expires_at=created_at+interval '1 microsecond' WHERE employee_id=%s",(IDENTITY['master'],))
            self.assertEqual(master.get('/api/v1/demo/clock').status_code,401)
            self.assertEqual(self.query('SELECT count(*) AS n FROM demo_clock_controls')[0]['n'],2)
            self.assertEqual(executor.get('/api/v1/me').status_code,200)

    def test_pause_does_not_extend_stage_ttl_or_permit_wall_fallback(self):
        from provision_synthetic_demo import IDENTITY
        from PIL import Image
        from app.runtime import validate_database,RuntimePrerequisiteError
        from app.worker_runtime import validate_database as worker_validate,WorkerPrerequisiteError
        with ExitStack() as stack:
            master,executor,mcsrf,ecsr=self._clients(stack)
            frozen,_=self.control(master,mcsrf)
            raw=BytesIO();Image.new('RGB',(8,8),(0,100,40)).save(raw,format='PNG')
            response=master.post('/api/v1/photos/stage',headers={'Origin':ORIGIN,'X-CSRF-Token':mcsrf},
                data={'operation_id':str(uuid4()),'expected_version':'0','purpose':'before','section_id':IDENTITY['section']},
                files={'file':('clock.png',raw.getvalue(),'image/png')})
            self.assertEqual(response.status_code,201)
            photo=response.json()['id']
            self.assertEqual(master.get('/api/v1/photos/'+photo).status_code,200)
            with self.connect() as db:
                db.execute("UPDATE photos SET expires_at=uploaded_at+interval '1 microsecond' WHERE id=%s",(photo,))
            expired=master.get('/api/v1/photos/'+photo)
            self.assertEqual(expired.status_code,422)
            self.assertEqual(expired.json()['code'],'PHOTO_EXPIRED')
            self.assertEqual(master.get('/api/v1/demo/clock').json()['domain_now'],frozen['domain_now'])
        from app.runtime import connection_factory
        with self.assertRaises(RuntimePrerequisiteError) as caught:
            validate_database(connection_factory(self.api_settings),photo_enabled=True,push_enabled=True,notification_enabled=True)
        self.assertEqual(caught.exception.code,'DEMO_CLOCK_CAPABILITY_REQUIRED')
        with self.assertRaises(WorkerPrerequisiteError) as caught:
            worker_validate(lambda:self.connect(worker=True),web_push=True)
        self.assertEqual(caught.exception.code,'WORKER_DEMO_CLOCK_CAPABILITY_REQUIRED')

    def test_clock_grant_options_and_column_references_are_rejected_without_repair(self):
        from app.runtime import connection_factory,validate_database,RuntimePrerequisiteError
        from enable_demo_clock import apply_capabilities
        api=connection_factory(self.api_settings)
        with api() as db:role=db.execute('SELECT current_user AS name').fetchone()['name']
        args=argparse.Namespace(backend=ROOT/'backend',schema=self.schema,expected_database=self.database,bootstrap=True)
        for privilege,column,grant_option in (('SELECT','instance_id',True),('UPDATE','scale',True),
                                              ('INSERT','actor_id',True),('REFERENCES','instance_id',False)):
            table='demo_clock_controls' if privilege=='INSERT' else 'demo_clock_state'
            grant=self.sql.SQL('GRANT {} ({}) ON {} TO {}{}').format(self.sql.SQL(privilege),
                self.sql.Identifier(column),self.sql.Identifier(table),self.sql.Identifier(role),
                self.sql.SQL(' WITH GRANT OPTION' if grant_option else ''))
            with self.connect() as db:db.execute(grant)
            with self.subTest(privilege=privilege),self.assertRaises(RuntimePrerequisiteError) as caught:
                apply_capabilities(args,self.environment)
            self.assertEqual(caught.exception.code,'FORBIDDEN_GRANT')
            # The verifier must not silently revoke/repair an operator change.
            with api() as db:
                self.assertTrue(db.execute('SELECT has_column_privilege(%s,%s,%s) AS ok',
                    (table,column,privilege+(' WITH GRANT OPTION' if grant_option else ''))).fetchone()['ok'])
            with self.connect() as db:
                revoke=self.sql.SQL('REVOKE {}{} ({}) ON {} FROM {}').format(
                    self.sql.SQL('GRANT OPTION FOR ' if grant_option else ''),self.sql.SQL(privilege),
                    self.sql.Identifier(column),self.sql.Identifier(table),self.sql.Identifier(role))
                db.execute(revoke)
            validate_database(api,photo_enabled=True,push_enabled=True,notification_enabled=True,
                demo_clock_enabled=True,demo_clock_instance_id=self.instance)

    def test_shared_mapping_reaches_actual_rules_worker_and_human_close(self):
        from app.worker_runtime import WorkerSettings,build_runtime
        from app.core.auth_boundary import SystemRealClock
        with ExitStack() as stack:
            master,executor,mcsrf,ecsr=self._clients(stack)
            self.control(master,mcsrf)
            snapshot,_=self.control(master,mcsrf,'advance',3600)
            domain_now=datetime.fromisoformat(snapshot['domain_now'])
            worker=build_runtime(WorkerSettings.from_env(),environment=self.environment)
            self.assertEqual(worker.assessment.domain_clock.now(),domain_now)
            self.assertIsInstance(worker.assessment.real_clock,SystemRealClock)
            self.assertLess(abs((worker.assessment.real_clock.now()-datetime.now(timezone.utc)).total_seconds()),5)
            order,submission,photo=self._submit(master,executor,mcsrf,ecsr,with_photo=True)
            self.assertEqual(datetime.fromisoformat(order['issued_at']),domain_now)
            result=self._assert_persisted(master,order,submission,recommendation='needs_master_review')
            self.assertLess(abs((result['created_at']-datetime.now(timezone.utc)).total_seconds()),10)
            current=dict(order,version=order['version']+1)
            closed=self._command(master,mcsrf,current,'review',{'submission_id':submission,'decision':'close',
                'reason':'Синтетическое демо-время; ручное решение','final_score':None})
            self.assertEqual(closed['order']['status'],'closed')
            self.assertEqual(master.get('/api/v1/demo/clock').json()['domain_now'],snapshot['domain_now'])


# The dedicated runner selects the three new cases explicitly. Ordinary aggregate
# discovery does not count inherited worker cases as additional clock evidence.
def load_tests(loader,tests,pattern):
    import unittest
    return unittest.TestSuite(MountedClockTests(name) for name in (
        'test_control_is_master_only_cas_and_real_session_expiry',
        'test_pause_does_not_extend_stage_ttl_or_permit_wall_fallback',
        'test_shared_mapping_reaches_actual_rules_worker_and_human_close',
        'test_clock_grant_options_and_column_references_are_rejected_without_repair'))
