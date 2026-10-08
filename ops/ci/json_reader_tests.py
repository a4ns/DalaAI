import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from json_reader_gate import projection,outcome,environment,dummy_safety_check,SCRIPT_SHA,READER_SHA,PAYLOAD_SHA,PAYLOAD_BYTES


def example():
    parsed={'outcome':'parsed','hash':PAYLOAD_SHA,'bytes':PAYLOAD_BYTES,'rows':1500}
    return {'reader_source_sha256':READER_SHA,'payload_sha256':PAYLOAD_SHA,'payload_bytes':PAYLOAD_BYTES,
        'browser':'143.0.1.2','counts':{'text':1,'reader':1},'result':'BOTH_ARMS_PASS',
        'arms':[{'arm':arm,'status':200,'app':dict(parsed),'observer':dict(parsed),'request_failure':None,'exact_bytes':True} for arm in ('text','reader')]}


class PublicComparison(unittest.TestCase):
    def test_fixed_public_two_arm_success(self):
        result=projection(example());self.assertEqual(result['status'],'COMPARISON_COMPLETE');self.assertEqual(result['probe_result'],'BOTH_ARMS_PASS')
        self.assertEqual(result['counts'],{'text':1,'reader':1})
    def test_cdp_failure_preserved_with_app_success(self):
        value=example();value['arms'][1]['observer']={'outcome':'failed','error_name':'Error','error_message':'Protocol error Network.getResponseBody CANARY'}
        value['arms'][1]['exact_bytes']=False;value['result']='OBSERVED_DIFFERENCE_OR_FAILURE'
        result=projection(value);self.assertEqual(result['arms'][1]['observer'],{'outcome':'failed','failure_category':'BODY_PROTOCOL_FAILURE'})
        self.assertEqual(result['arms'][1]['app']['outcome'],'parsed');self.assertFalse(result['arms'][1]['exact_bytes']);self.assertNotIn('CANARY',json.dumps(result))
    def test_app_failure_preserved_with_observer_success(self):
        value=example();value['arms'][0]['app']={'outcome':'failed','error_name':'AbortError','error_message':'CANARY'};value['arms'][0]['exact_bytes']=False;value['result']='OBSERVED_DIFFERENCE_OR_FAILURE'
        result=projection(value);self.assertEqual(result['arms'][0]['app']['failure_category'],'ABORTED');self.assertEqual(result['arms'][0]['observer']['outcome'],'parsed')
    def test_blocked_zero_requests_is_not_success(self):
        value=example();value.update(result='BLOCKED',arms=[],counts={'text':0,'reader':0},blocker={'name':'Error','message':'CANARY'})
        result=projection(value);self.assertEqual(result['status'],'BLOCKED');self.assertEqual(result['counts'],{'text':0,'reader':0});self.assertNotIn('CANARY',json.dumps(result))
    def test_changed_source_payload_extra_get_wrong_order_and_promotion_refused(self):
        mutations=[lambda d:d.update(reader_source_sha256='f'*64),lambda d:d.update(payload_sha256='f'*64),lambda d:d['counts'].update(reader=2),
            lambda d:d['arms'].reverse(),lambda d:d['arms'][0].update(exact_bytes=False),lambda d:d['arms'][0]['app'].update(bytes=2**32),lambda d:d['arms'][0].update(arm='CANARY')]
        for mutate in mutations:
            value=example();mutate(value)
            with self.assertRaises(ValueError):projection(value)
    def test_arbitrary_error_paths_and_extra_fields_do_not_escape(self):
        value=example();value['private']='CANARY';value['failures']=[{'path':'CANARY','error':'CANARY'}];value['arms'][0]['request_failure']={'errorText':'net::ERR_ABORTED CANARY','private':'CANARY'}
        value['browser']='CANARY';result=projection(value)
        self.assertTrue(result['arms'][0]['request_failure_present']);self.assertEqual(result['arms'][0]['request_failure_category'],'ABORTED');self.assertNotIn('CANARY',json.dumps(result))
    def test_dummy_output_safety_is_run_without_real_inputs(self):
        dummy_safety_check();self.assertEqual(outcome({'outcome':'failed','error_name':'CANARY','error_message':'CANARY'}),{'outcome':'failed','failure_category':'OTHER'})
    def test_child_environment_drops_credentials_and_execution_overrides(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','PGPASSWORD':'CANARY','NODE_OPTIONS':'CANARY','DALA_E2E_MASTER_PIN_FILE':'CANARY','HTTP_PROXY':'CANARY','PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH':'CANARY'}):
            self.assertNotIn('CANARY',json.dumps(environment()))
    def test_author_source_is_byte_identical(self):
        import hashlib
        self.assertEqual(hashlib.sha256((Path(__file__).parent/'json_reader_probe.cjs').read_bytes()).hexdigest(),SCRIPT_SHA)


if __name__=='__main__':unittest.main()
