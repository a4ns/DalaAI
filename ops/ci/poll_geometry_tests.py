import base64
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from poll_geometry_gate import PRODUCT,SOURCE,PROJECT,VIEWPORTS,TITLES,verify_report,diagnostic,environment,contract


def attachments(viewport,title):
    if title.endswith('feedback survives'):return []
    width,height=map(int,viewport.removeprefix('synthetic quiet refresh ').split('x'))
    value={'viewport':{'width':width,'height':height},'screen':title.split()[0],
        'content':'history-empty' if title.startswith('panel empty history') else 'empty' if ' empty:' in title else 'populated',
        'receipt':'observed' if title.startswith('executor receipt:') else 'none','cycles':3,'scrollY':173,
        'measuredElements':30,'maximumRectDeltaCssPx':0,'toleranceCssPx':0.25}
    return [{'name':'synthetic-quiet-refresh-geometry.json','contentType':'application/json','body':base64.b64encode(json.dumps(value).encode()).decode()}]


def report():
    suites=[]
    for viewport in sorted(VIEWPORTS):
        suites.append({'title':viewport,'specs':[{'title':title,'file':'browser/quiet-refresh-geometry.spec.ts','line':50,
            'tests':[{'projectName':PROJECT,'expectedStatus':'passed','status':'expected','results':[{'status':'passed','retry':0,'errors':[],'attachments':attachments(viewport,title)}]}]} for title in sorted(TITLES)]})
    return {'config':{'metadata':{'scope':'SYNTHETIC_QUIET_REFRESH_GEOMETRY_ONLY','testSource':SOURCE,'productSha':PRODUCT,'harnessSha':'a'*40}},
        'errors':[],'stats':{'expected':33,'unexpected':0,'flaky':0,'skipped':0},'suites':[{'title':'quiet-refresh-geometry.spec.ts','suites':suites}]}


class Gate(unittest.TestCase):
    def test_exact_single_project_matrix(self):
        result=verify_report(report(),'a'*40);self.assertEqual(len(result),3);self.assertTrue(all(x['passed']==11 for x in result))
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
            else:group['title']='synthetic quiet refresh 999x999'
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_unknown_test_or_file_rejected(self):
        for key in ('title','file'):
            value=report();value['suites'][0]['suites'][0]['specs'][0][key]='CANARY'
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_diagnostics_keep_only_fixed_case_and_source_lines(self):
        value=report();test=value['suites'][0]['suites'][0]['specs'][0]['tests'][0];test['status']='unexpected'
        test['results'][0]['errors']=[{'message':'CANARY Timed out','stack':'CANARY quiet-refresh-geometry.spec.ts:100:4'}]
        result=diagnostic(value);self.assertEqual(result[0]['category'],'TIMEOUT');self.assertEqual(result[0]['source_lines'],[50,100]);self.assertNotIn('CANARY',json.dumps(result))
    def test_environment_excludes_live_inputs_and_capture_overrides(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','PGPASSWORD':'CANARY','NODE_OPTIONS':'CANARY','PWDEBUG':'CANARY','DALA_E2E_MASTER_PIN_FILE':'CANARY','UI_TEST_NO_SERVER':'CANARY'}):
            self.assertNotIn('CANARY',json.dumps(environment(Path('/source'),'a'*40)))
    def test_missing_or_changed_geometry_measurement_rejected(self):
        for mutation in ('missing','delta','viewport','cycles','canary'):
            value=report();spec=next(s for s in value['suites'][0]['suites'][0]['specs'] if not s['title'].endswith('feedback survives'))
            result=spec['tests'][0]['results'][0]
            if mutation=='missing':result['attachments']=[]
            else:
                a=result['attachments'][0];body=json.loads(base64.b64decode(a['body']))
                if mutation=='delta':body['maximumRectDeltaCssPx']=1
                elif mutation=='viewport':body['viewport']['width']=999
                elif mutation=='cycles':body['cycles']=2
                else:a['body']='CANARY'
                if mutation!='canary':a['body']=base64.b64encode(json.dumps(body).encode()).decode()
            with self.assertRaises(ValueError):verify_report(value,'a'*40)
    def test_frozen_fixture_contract(self):
        value=contract();self.assertEqual(len(value['files']),3);self.assertEqual(len(value['product_dependencies']),8);self.assertEqual(value['case_count'],33)


if __name__=='__main__':unittest.main()
