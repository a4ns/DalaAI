import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from healthy_poll_gate import ROOT,SCOPE,PROFILE,COUNTS,TOTAL,contract,verify_report,diagnostic,environment,progress


def fixture_contract():
    c=json.loads((ROOT/'ops/ci/healthy_poll_contract.json').read_text());c['accepted']=True;return c


def report(c):
    return {'config':{'metadata':{'scope':SCOPE,'serverMode':'PRODUCTION_BUILD_PREVIEW','testSource':c['test_source_sha'],'productSha':c['product_sha'],'harnessSha':'a'*40,'browserProfile':copy.deepcopy(PROFILE)}},
        'errors':[],'stats':{'expected':TOTAL,'unexpected':0,'flaky':0,'skipped':0},'suites':[{'title':'fixed specs','specs':[
            {'title':r['title'],'file':r['file'],'line':30,'tests':[{'projectName':r['project'],'expectedStatus':'passed','status':'expected','results':[{'status':'passed','retry':0,'errors':[]}]}]} for r in c['cases']]}]}


class Gate(unittest.TestCase):
    def test_exact_source_and_mounted_matrix(self):
        c=fixture_contract();self.assertEqual(verify_report(report(c),c,'a'*40),{'source_cases':COUNTS['healthy-poll-source'],'mounted_browser_cases':COUNTS['healthy-poll-chromium'],'skipped':0,'retries':0})
    def test_wrong_candidate_source_harness_and_device_rejected(self):
        c=fixture_contract()
        for field in ('testSource','productSha','harnessSha','browserProfile','serverMode'):
            value=report(c);value['config']['metadata'][field]='CANARY'
            with self.assertRaises(ValueError):verify_report(value,c,'a'*40)
    def test_missing_duplicate_and_foreign_case_rejected(self):
        c=fixture_contract()
        for kind in ('missing','duplicate','title','project','file'):
            value=report(c);specs=value['suites'][0]['specs']
            if kind=='missing':specs.pop()
            elif kind=='duplicate':specs[1]=specs[0]
            elif kind=='project':specs[0]['tests'][0]['projectName']='CANARY'
            else:specs[0][kind]='CANARY'
            with self.assertRaises(ValueError):verify_report(value,c,'a'*40)
    def test_skip_retry_failure_and_extra_result_rejected(self):
        c=fixture_contract()
        for kind in ('skip','retry','failure','extra'):
            value=report(c);result=value['suites'][0]['specs'][0]['tests'][0]['results'][0]
            if kind=='skip':value['stats']['skipped']=1
            elif kind=='retry':result['retry']=1
            elif kind=='failure':result['status']='failed'
            else:value['suites'][0]['specs'][0]['tests'][0]['results'].append(copy.deepcopy(result))
            with self.assertRaises(ValueError):verify_report(value,c,'a'*40)
    def test_diagnostics_project_only_fixed_case_and_source_lines(self):
        c=fixture_contract();value=report(c);test=value['suites'][0]['specs'][0]['tests'][0];test['status']='unexpected';test['results'][0]['status']='failed'
        test['results'][0]['errors']=[{'message':'CANARY Timed out','stack':'CANARY poll-command-lock.spec.ts:89:4\npoll-command-lock.spec.ts:99999:1'}]
        result=diagnostic(value,c);self.assertEqual(result[0]['category'],'TIMEOUT');self.assertEqual(result[0]['source_lines'],[30,89]);self.assertNotIn('CANARY',json.dumps(result))
    def test_foreign_diagnostic_never_emits_text(self):
        c=fixture_contract();value=report(c);spec=value['suites'][0]['specs'][0];spec['title']='CANARY';spec['tests'][0]['status']='unexpected'
        self.assertEqual(diagnostic(value,c),[])
    def test_skipped_and_unrun_cases_are_not_reported_as_failures(self):
        c=fixture_contract();value=report(c);specs=value['suites'][0]['specs'];p=specs[0]['tests'][0]['projectName']
        specs[0]['tests'][0].update(status='skipped',results=[])
        specs[1]['tests'][0].update(status='skipped',results=[{'status':'skipped','retry':0}])
        self.assertEqual(diagnostic(value,c),[]);counts=progress(value,c);self.assertEqual(counts[p]['not_run'],1);self.assertEqual(counts[p]['skipped'],1);self.assertEqual(counts[p]['failed'],0)
    def test_nested_source_location_is_bounded(self):
        c=fixture_contract();value=report(c);test=value['suites'][0]['specs'][0]['tests'][0];test['status']='unexpected';test['results'][0]['status']='failed'
        test['results'][0]['steps']=[{'error':{'message':'strict mode violation CANARY','location':{'file':'/CANARY/poll-command-lock.spec.ts','line':53}}}]
        result=diagnostic(value,c);self.assertEqual(result[0]['category'],'STRICT_LOCATOR');self.assertEqual(result[0]['source_lines'],[30,53]);self.assertNotIn('CANARY',json.dumps(result))
    def test_child_environment_drops_live_inputs_and_overrides(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','PGPASSWORD':'CANARY','NODE_OPTIONS':'CANARY','PWDEBUG':'CANARY','DALA_E2E_MASTER_PIN_FILE':'CANARY','UI_TEST_NO_SERVER':'CANARY','PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH':'CANARY'}):
            self.assertNotIn('CANARY',json.dumps(environment(Path('/source'),fixture_contract(),'a'*40)))
    def test_unaccepted_or_incomplete_contract_fails_closed(self):
        c=fixture_contract()
        for key,value in [('accepted',False),('product_sha','short'),('case_counts',{'healthy-poll-source':-1,'healthy-poll-chromium':-1})]:
            d=copy.deepcopy(c);d[key]=value
            with patch('healthy_poll_gate.Path.read_text',return_value=json.dumps(d)):
                with self.assertRaises(ValueError):contract()
    def test_frozen_matrix_matches_counts(self):
        c=fixture_contract();self.assertEqual(c['case_counts'],COUNTS);self.assertEqual(len(c['files']),7);self.assertEqual(len(c['product_dependencies']),8)


if __name__=='__main__':unittest.main()
