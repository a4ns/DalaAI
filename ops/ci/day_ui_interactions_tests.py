import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from day_ui_interactions_gate import PRODUCT,SOURCE,PROJECT,VIEWPORTS,TITLES,verify_report,diagnostic,environment,contract


def report():
    suites=[]
    for viewport in sorted(VIEWPORTS):
        suites.append({'title':viewport,'specs':[{'title':title,'file':'browser/interaction-owned-effects.spec.ts','line':50,
            'tests':[{'projectName':PROJECT,'expectedStatus':'passed','status':'expected','results':[{'status':'passed','retry':0,'errors':[]}]}]} for title in sorted(TITLES)]})
    return {'config':{'metadata':{'scope':'SYNTHETIC_NATIVE_COMPONENT_INTERACTIONS_ONLY','testSource':SOURCE,'productSha':PRODUCT,'harnessSha':'a'*40}},
        'errors':[],'stats':{'expected':18,'unexpected':0,'flaky':0,'skipped':0},'suites':[{'title':'interaction-owned-effects.spec.ts','suites':suites}]}


class Gate(unittest.TestCase):
    def test_exact_single_project_matrix(self):
        result=verify_report(report(),'a'*40);self.assertEqual(len(result),3);self.assertTrue(all(x['passed']==6 for x in result))
    def test_old_source_or_other_product_rejected(self):
        for key in ('testSource','productSha','harnessSha'):
            value=report();value['config']['metadata'][key]='f'*40
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_skip_retry_failure_and_extra_project_rejected(self):
        for mutation in ('skip','retry','failure','project'):
            value=report();test=value['suites'][0]['suites'][0]['specs'][0]['tests'][0]
            if mutation=='skip':value['stats']['skipped']=1
            elif mutation=='retry':test['results'][0]['retry']=1
            elif mutation=='failure':test['results'][0]['status']='failed'
            else:test['projectName']='viewport-320'
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_missing_duplicate_or_wrong_viewport_case_rejected(self):
        for mutation in ('missing','duplicate','viewport'):
            value=report();group=value['suites'][0]['suites'][0]
            if mutation=='missing':group['specs'].pop()
            elif mutation=='duplicate':group['specs'][1]=group['specs'][0]
            else:group['title']='owned effects 999x999'
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_unknown_test_or_file_rejected(self):
        for key in ('title','file'):
            value=report();value['suites'][0]['suites'][0]['specs'][0][key]='CANARY'
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_diagnostics_keep_only_fixed_case_and_source_lines(self):
        value=report();test=value['suites'][0]['suites'][0]['specs'][0]['tests'][0];test['status']='unexpected'
        test['results'][0]['errors']=[{'message':'CANARY Timed out','stack':'CANARY interaction-owned-effects.spec.ts:100:4'}]
        result=diagnostic(value);self.assertEqual(result[0]['category'],'TIMEOUT');self.assertEqual(result[0]['source_lines'],[50,100]);self.assertNotIn('CANARY',json.dumps(result))
    def test_environment_excludes_live_inputs_and_capture_overrides(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','PGPASSWORD':'CANARY','NODE_OPTIONS':'CANARY','PWDEBUG':'CANARY','DALA_E2E_MASTER_PIN_FILE':'CANARY','UI_TEST_NO_SERVER':'CANARY'}):
            self.assertNotIn('CANARY',json.dumps(environment(Path('/source'),'a'*40)))
    def test_frozen_fixture_contract(self):
        value=contract();self.assertEqual(len(value['files']),3);self.assertEqual(len(value['product_dependencies']),5);self.assertEqual(value['case_count'],18)


if __name__=='__main__':unittest.main()
