"""Optional assembly configuration; actual clock/database proof is a separate gate."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4

from app.runtime import RuntimeSettings
from app.worker_runtime import WorkerSettings,WorkerConfigurationError,build_runtime
from app.demo_clock.postgres import PostgresDemoBusinessClock
from app.core.auth_boundary import SystemRealClock


class ClockAssemblyTests(unittest.TestCase):
    def test_api_requires_explicit_mode_flag_and_canonical_instance(self):
        identifier=str(uuid4())
        for kwargs in ({'demo_clock_enabled':True}, {'demo_clock_instance_id':identifier},
                       {'demo_clock_enabled':True,'mode':'demo','database_url':'test','allowed_origin':'https://clock.test'},
                       {'demo_clock_enabled':1}, {'demo_clock_enabled':True,'demo_clock_instance_id':identifier}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):RuntimeSettings(**kwargs)
        good=RuntimeSettings(mode='demo',database_url='test',allowed_origin='https://clock.test',
            demo_clock_enabled=True,demo_clock_instance_id=identifier)
        self.assertEqual(good.demo_clock_instance_id,identifier)

    def test_both_environment_parsers_use_same_explicit_instance(self):
        identifier=str(uuid4())
        env={'DALA_API_MODE':'demo','DATABASE_URL':'test','DALA_ALLOWED_ORIGIN':'https://clock.test',
             'DALA_WORKER_ENABLED':'true','DALA_WORKER_DATABASE_URL':'test',
             'DALA_DEMO_CLOCK_ENABLED':'true','DALA_DEMO_CLOCK_INSTANCE_ID':identifier}
        with patch.dict(os.environ,env,clear=True):
            self.assertEqual(RuntimeSettings.from_env().demo_clock_instance_id,identifier)
            self.assertEqual(WorkerSettings.from_env().demo_clock_instance_id,identifier)
        env['DALA_DEMO_CLOCK_ENABLED']='false'
        with patch.dict(os.environ,env,clear=True),self.assertRaises(ValueError):RuntimeSettings.from_env()
        with self.assertRaises(WorkerConfigurationError):WorkerSettings.from_env(env)

    def test_worker_uses_shared_business_clock_and_real_security_budget_clock(self):
        identifier=str(uuid4());connector=Mock(side_effect=AssertionError('No unit DB'))
        settings=WorkerSettings(enabled=True,database_url='test',runtime_mode='demo',
            demo_clock_enabled=True,demo_clock_instance_id=identifier)
        received=[]
        def model(environment,real_clock,*,runtime_mode):
            received.append(real_clock);return None,'rules_fallback',None
        with patch('app.worker_runtime.validate_database') as validate,patch('app.worker_runtime.build_model_adapter',model):
            runtime=build_runtime(settings,environment={},connect=connector)
        self.assertIsInstance(runtime.assessment.domain_clock,PostgresDemoBusinessClock)
        self.assertEqual(runtime.assessment.domain_clock.instance_id,identifier)
        self.assertIsInstance(runtime.assessment.real_clock,SystemRealClock)
        self.assertIs(received[0],runtime.assessment.real_clock)
        self.assertIsNot(runtime.assessment.real_clock,runtime.assessment.domain_clock)
        self.assertTrue(validate.call_args.kwargs['demo_clock_enabled'])
        connector.assert_not_called()

    def test_operator_identity_matches_existing_fixture_without_new_account(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ops/provision'))
        from provision_synthetic_demo import IDENTITY
        from app.demo_clock.runtime import DEMO_MASTER_ID
        self.assertEqual(DEMO_MASTER_ID,IDENTITY['master'])
        self.assertNotEqual(DEMO_MASTER_ID,IDENTITY['executor'])
