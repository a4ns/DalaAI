import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from binary_reader_gate import SOURCES,READER_SHA,CANDIDATE_SHA,PAYLOADS,LIMIT,PAIRS,projection,environment,dummy_safety_check


def example():
    rows=[]
    for arm,flow in PAIRS:
        format='xlsx' if flow=='valid_xlsx' else 'pdf'
        app={'outcome':'accepted','blob_received':True,**PAYLOADS[format],
            'mime':'application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'filename':'synthetic.'+format,'aborted':False,'deadline_fired':False,'caller_abort_fired':False}
        observer={'outcome':'bytes',**PAYLOADS[format]};exact=True
        if not flow.startswith('valid_'):
            app.update(outcome='rejected',blob_received=False,error_name='Error',error_message='Report exceeds byte limit' if flow=='overflow_unknown_length' else 'Invalid report signature')
            if flow=='transport_error':app.update(error_name='TypeError',error_message='CANARY_TRANSPORT')
            if flow=='caller_abort':app.update(error_name='AbortError',error_message='CANARY_ABORT',aborted=True,caller_abort_fired=True)
            observer={'outcome':'unavailable','error_name':'Error','error_message':'No resource with given identifier CANARY'};exact=None
        rows.append({'arm':arm,'flow':flow,'status':200,'app':app,'observer':observer,'request_failure':None,'app_expected':True,'original_cdp_exact':exact})
    return {'original_source_sha256':READER_SHA,'candidate_source_sha256':CANDIDATE_SHA,'limit_bytes':LIMIT,'payloads':copy.deepcopy(PAYLOADS),
        'counts':{a+':'+f:1 for a,f in PAIRS},'flows':rows,'complete':True,'result':'COMPLETE_APP_CHECKS_PASS_OBSERVER_RECORDED','browser':'153.0.8010.12'}


class Comparison(unittest.TestCase):
    def test_all_twelve_fixed_flows_complete(self):
        result=projection(example());self.assertEqual(result['status'],'COMPARISON_COMPLETE');self.assertEqual(len(result['flows']),12);self.assertTrue(all(v==1 for v in result['counts'].values()))
    def test_app_success_and_cdp_failure_remain_distinct(self):
        value=example();row=value['flows'][0];row['observer']={'outcome':'unavailable','error_name':'Error','error_message':'No data found for resource CANARY'};row['original_cdp_exact']=False;row['request_failure']={'errorText':'net::ERR_ABORTED CANARY'}
        result=projection(value);row=result['flows'][0];self.assertTrue(row['app_expected']);self.assertFalse(row['original_cdp_exact']);self.assertEqual(row['observer']['failure_category'],'BODY_UNAVAILABLE');self.assertNotIn('CANARY',json.dumps(result))
    def test_completed_app_check_failure_is_not_promoted(self):
        value=example();value['flows'][0]['app']['hash']='f'*64;value['flows'][0]['app_expected']=False;value['result']='COMPLETE_APP_CHECK_FAILED'
        result=projection(value);self.assertEqual(result['probe_result'],'COMPLETE_APP_CHECK_FAILED');self.assertFalse(result['flows'][0]['app_expected']);self.assertTrue(result['flows'][0]['original_cdp_exact'])
    def test_deadline_and_timeout_stay_inconclusive(self):
        for kind in ('deadline','body_timeout'):
            value=example();row=value['flows'][0];value.update(complete=False,result='INCONCLUSIVE')
            if kind=='deadline':row['app']['deadline_fired']=True;row['app_expected']=False
            else:row['observer']={'outcome':'unavailable','error_name':'ProbeTimeout','error_message':'CANARY'};row['original_cdp_exact']=False
            self.assertEqual(projection(value)['status'],'INCONCLUSIVE')
            value.update(complete=True,result='COMPLETE_APP_CHECKS_PASS_OBSERVER_RECORDED')
            with self.assertRaises(ValueError):projection(value)
    def test_zero_request_launch_failure_is_inconclusive(self):
        value=example();value.update(flows=[],counts={k:0 for k in value['counts']},complete=False,result='INCONCLUSIVE',blocker={'name':'Error','message':'CANARY'})
        result=projection(value);self.assertEqual(result['status'],'INCONCLUSIVE');self.assertNotIn('CANARY',json.dumps(result))
    def test_final_inconclusive_app_or_either_timeout_cannot_complete(self):
        for target,name in (('app','Error'),('app','ProbeTimeout'),('app','TimeoutError'),('observer','ProbeTimeout'),('observer','TimeoutError')):
            value=example();row=value['flows'][-1]
            if target=='app':
                row['app']={'outcome':'inconclusive','blob_received':False,'error_name':name,'error_message':'CANARY_TARGET_CLOSED'}
                row['app_expected']=False
            else:row['observer']={'outcome':'unavailable','error_name':name,'error_message':'CANARY_TIMEOUT'}
            value['result']='COMPLETE_APP_CHECK_FAILED' if target=='app' else 'COMPLETE_APP_CHECKS_PASS_OBSERVER_RECORDED'
            with self.assertRaises(ValueError):projection(value)
            value.update(result='INCONCLUSIVE',complete=False)
            result=projection(value);self.assertEqual(result['status'],'INCONCLUSIVE');self.assertNotIn('CANARY',json.dumps(result))
    def test_request_count_order_source_payload_and_fake_success_rejected(self):
        changes=[lambda d:d['counts'].update({'manual:valid_pdf':2}),lambda d:d['flows'].reverse(),lambda d:d.update(original_source_sha256='f'*64),
            lambda d:d.update(candidate_source_sha256='f'*64),lambda d:d['payloads']['pdf'].update(bytes=1),lambda d:d['flows'][0].update(app_expected=False),
            lambda d:d['flows'][0].update(original_cdp_exact=False),lambda d:d['flows'][0]['app'].update(bytes=LIMIT+2),lambda d:d['flows'][0].update(arm='CANARY')]
        for change in changes:
            value=example();change(value)
            with self.assertRaises(ValueError):projection(value)
    def test_incomplete_matrix_cannot_complete(self):
        value=example();value['flows'].pop()
        with self.assertRaises(ValueError):projection(value)
    def test_canary_errors_unknown_extras_and_boolean_strings_do_not_escape(self):
        value=example();value['private']='CANARY';value['flows'][0]['private']='CANARY';value['browser']='CANARY';self.assertNotIn('CANARY',json.dumps(projection(value)))
        value['flows'][0]['app']['aborted']='CANARY'
        with self.assertRaises(ValueError):projection(value)
    def test_dummy_output_and_filtered_environment(self):
        dummy_safety_check()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','PGPASSWORD':'CANARY','NODE_OPTIONS':'CANARY','DALA_E2E_MASTER_PIN_FILE':'CANARY','HTTP_PROXY':'CANARY','PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH':'CANARY'}):self.assertNotIn('CANARY',json.dumps(environment()))
    def test_all_author_sources_are_byte_identical(self):
        import hashlib
        for name,digest in SOURCES.items():self.assertEqual(hashlib.sha256((Path(__file__).parent/'binary_reader_sources'/name).read_bytes()).hexdigest(),digest)


if __name__=='__main__':unittest.main()
