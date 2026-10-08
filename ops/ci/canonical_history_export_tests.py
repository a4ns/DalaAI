import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from canonical_history_export_gate import contract,projection,runtime_env,fixed_failure
from canonical_history_export_execute import failure,FixedResult,PrivateStream


def example():
    c=contract();return c,{'schema_version':1,'status':'PASS','tests_run':6,'python':c['python'],'packages':c['export_packages'],'optional_packages':{'lxml':False,'numpy':False},'fixture_errors':[],
        'cases':[{'id':name,'status':'PASS','duration_ms':1,'failure':None} for name in c['cases']]}


class Safety(unittest.TestCase):
    def test_exact_six_pass_projection(self):
        c,r=example();p=projection(r,c);self.assertEqual(p['counts']['PASS'],6);self.assertEqual(p['status'],'PASS')
    def test_failure_stays_failure_and_does_not_become_pass(self):
        c,r=example();r['status']='FAIL';r['cases'][2].update(status='FAIL',failure={'category':'ASSERTION_FAILED','domain_code':'TEMPORARILY_UNAVAILABLE','subprocess_timeout_observed':False})
        p=projection(r,c);self.assertEqual(p['counts']['FAIL'],1);self.assertEqual(p['counts']['PASS'],5);self.assertFalse(p['cases'][2]['failure']['subprocess_timeout_observed'])
        r['status']='PASS'
        with self.assertRaises(ValueError):projection(r,c)
    def test_skip_expected_failure_not_run_or_missing_case_cannot_pass(self):
        for status in ('SKIP','EXPECTED_FAILURE','NOT_RUN','UNEXPECTED_SUCCESS'):
            c,r=example();r['cases'][0]['status']=status
            if status=='EXPECTED_FAILURE':r['cases'][0]['failure']={'category':'ASSERTION_FAILED','domain_code':'NONE','subprocess_timeout_observed':False}
            with self.assertRaises(ValueError):projection(r,c)
        c,r=example();r['cases'].pop()
        with self.assertRaises(ValueError):projection(r,c)
    def test_wrong_versions_foreign_case_duplicate_and_excess_duration_rejected(self):
        changes=[lambda r:r.update(python='3.12.14'),lambda r:r.update(optional_packages={'lxml':True,'numpy':False}),lambda r:r['cases'][0].update(id='CANARY'),lambda r:r['cases'].__setitem__(1,r['cases'][0]),lambda r:r['cases'][0].update(duration_ms=90001),lambda r:r.update(tests_run=5)]
        for change in changes:
            c,r=example();change(r)
            with self.assertRaises(ValueError):projection(r,c)
    def test_raw_canary_text_and_unknown_fields_never_escape(self):
        c,r=example();r['raw']='CANARY';r['cases'][0]['message']='CANARY';self.assertNotIn('CANARY',json.dumps(projection(r,c)))
        self.assertNotIn('CANARY',json.dumps(failure(AssertionError('CANARY'))))
        with self.assertRaises(ValueError):fixed_failure({'category':'CANARY','domain_code':'NONE','subprocess_timeout_observed':False})
    def test_timeout_requires_actual_exception_chain_not_domain_message(self):
        Domain=type('DomainError',(Exception,),{'__module__':'app.orders.models','code':'TEMPORARILY_UNAVAILABLE'})
        self.assertFalse(failure(Domain('TimeoutExpired CANARY'))['subprocess_timeout_observed'])
        try:
            try:raise subprocess.TimeoutExpired('CANARY_COMMAND',6)
            except subprocess.TimeoutExpired:
                try:raise Domain('CANARY_DOMAIN') from None
                except Domain:raise AssertionError('CANARY_ASSERTION')
        except AssertionError as error:
            result=failure(error);self.assertEqual(result,{'category':'ASSERTION_FAILED','domain_code':'TEMPORARILY_UNAVAILABLE','subprocess_timeout_observed':True});self.assertNotIn('CANARY',json.dumps(result))
    def test_runtime_environment_has_no_live_inputs_or_import_overrides(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','DATABASE_URL':'CANARY','PYTHONHOME':'CANARY','PYTHONSTARTUP':'CANARY','LD_PRELOAD':'CANARY','HTTP_PROXY':'CANARY'}):
            value=runtime_env(Path('/source'),'/private');self.assertNotIn('CANARY',json.dumps(value));self.assertEqual(value['PYTHONPATH'],'/source/backend');self.assertNotIn('HOME',value)
    def test_fixture_failure_never_emits_untrusted_test_name(self):
        c,_=example();stream=PrivateStream();result=FixedResult(stream,True,2);result.allowed=tuple(c['cases'])
        class Holder:
            def id(self):return 'CANARY_SETUP_NAME'
        result.record(Holder(),'ERROR',ValueError('CANARY'));self.assertEqual(result.fixed,{});self.assertEqual(len(result.fixture_errors),1);self.assertNotIn('CANARY',json.dumps(result.fixture_errors))
    def test_private_output_is_bounded(self):
        stream=PrivateStream();stream.write('x'*(1024*1024))
        with self.assertRaises(RuntimeError):stream.write('CANARY')
        stream.close()
    def test_exact_contract_and_existing_dependency_subset(self):
        c=contract();self.assertEqual(len(c['core_blobs']),109);self.assertEqual(len(c['cases']),6);self.assertEqual(len(c['export_packages']),5);self.assertEqual(c['python'],'3.12.15')


if __name__=='__main__':unittest.main()
