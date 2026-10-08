import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from day_ui_gate import SOURCE,PROJECTS,FILES,AI_TITLES,VIEWPORTS,verify_report,observation,failure_projection,environment


def report():
    specs=[]
    for project,count in PROJECTS.items():
        names=[('source.spec.ts',f'source-{i}') for i in range(count)] if project=='independent-source' else [
            (name,title) for name,n in FILES.items() for title in (sorted(AI_TITLES) if name.startswith('ai-assistance') else [
                'synthetic unavailable API: RU shell viewport observation' if name=='shell.spec.ts' and i==0 else f'{name}-{i}' for i in range(n)])]
        for name,title in names:
            result={'status':'passed','retry':0,'errors':[],'attachments':[]}
            if title.startswith('synthetic unavailable API: RU shell'):
                width,height=VIEWPORTS[project];value={'project':project,'physicalDevice':False,'viewport':{'width':width,'height':height},'innerWidth':width,'pixelRatio':1,'touchPoints':0}
                result['attachments']=[{'name':'browser-emulation-observation','contentType':'application/json','body':base64.b64encode(json.dumps(value).encode()).decode()}]
            specs.append({'file':'browser/'+name,'title':title,'line':1,'tests':[{'projectName':project,'expectedStatus':'passed','status':'expected','results':[result]}]})
    return {'config':{'metadata':{'reviewedSha':SOURCE,'harnessSha':'a'*40,'scope':'SYNTHETIC_RESPONSIVE_CHROMIUM_ONLY'}},
        'errors':[],'stats':{'expected':272,'unexpected':0,'flaky':0,'skipped':0},'suites':[{'specs':specs}]}


class Gate(unittest.TestCase):
    def test_all_fixed_cases_and_runtime_viewports_required(self):
        value=verify_report(report(),'a'*40,Path('/private'))
        self.assertEqual([v['passed'] for v in value],[218,18,18,18])
    def test_old_source_missing_cases_skip_retry_extra_project_fail(self):
        changes=[lambda d:d['config']['metadata'].update(reviewedSha='f'*40),lambda d:d['suites'][0]['specs'].pop(),
            lambda d:d['stats'].update(skipped=1),lambda d:d['suites'][0]['specs'][0]['tests'][0]['results'][0].update(retry=1),
            lambda d:d['suites'][0]['specs'][0]['tests'][0].update(projectName='unexpected')]
        for change in changes:
            value=report();change(value)
            with self.assertRaises(ValueError):verify_report(value,'a'*40,Path('/private'))
    def test_all_five_authored_ai_mount_cases_are_required_each_viewport(self):
        value=report();spec=next(s for s in value['suites'][0]['specs'] if s['file'].endswith('ai-assistance-mounted.spec.ts'));spec['title']='missing mounted case'
        with self.assertRaisesRegex(ValueError,'AUTHORED_SCENARIOS'):verify_report(value,'a'*40,Path('/private'))
    def test_runtime_dimensions_cannot_be_claimed_from_config_only(self):
        value=report();spec=next(s for s in value['suites'][0]['specs'] if s['title'].startswith('synthetic unavailable API: RU shell'))
        item=spec['tests'][0]['results'][0]['attachments'][0];body=json.loads(base64.b64decode(item['body']));body['innerWidth']=999;item['body']=base64.b64encode(json.dumps(body).encode()).decode()
        with self.assertRaisesRegex(ValueError,'RUNTIME_VIEWPORT'):verify_report(value,'a'*40,Path('/private'))
    def test_physical_device_promotion_rejected(self):
        value=report();spec=next(s for s in value['suites'][0]['specs'] if s['title'].startswith('synthetic unavailable API: RU shell'))
        item=spec['tests'][0]['results'][0]['attachments'][0];body=json.loads(base64.b64decode(item['body']));body['physicalDevice']=True;item['body']=base64.b64encode(json.dumps(body).encode()).decode()
        with self.assertRaises(ValueError):verify_report(value,'a'*40,Path('/private'))
    def test_attachment_cannot_read_outside_owned_output(self):
        item={'name':'browser-emulation-observation','contentType':'application/json','path':'/private-other/secret.json'}
        with self.assertRaisesRegex(ValueError,'ATTACHMENT_BOUNDARY'):observation({'results':[{'attachments':[item]}]},Path('/private'))
    def test_private_file_attachment_is_bounded_and_link_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'observation.json';p.write_text('{"safe":true}')
            item={'name':'browser-emulation-observation','contentType':'application/json','path':str(p)};test={'results':[{'attachments':[item]}]}
            self.assertEqual(observation(test,root),{'safe':True})
            link=root/'link.json';link.symlink_to(p);item['path']=str(link)
            with self.assertRaises(ValueError):observation(test,root)
    def test_only_fixed_failure_locations_escape(self):
        value=report();spec=next(s for s in value['suites'][0]['specs'] if s['file'].endswith('ai-assistance-mounted.spec.ts'))
        spec['tests'][0].update(status='unexpected');spec['tests'][0]['results'][0]['errors']=[{'message':'CANARY strict mode violation'}]
        projected=failure_projection(value);self.assertEqual(projected[0]['category'],'LOCATOR_STRICT_MODE');self.assertNotIn('CANARY',json.dumps(projected))
    def test_environment_drops_live_inputs_and_overrides(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'CANARY','PGPASSWORD':'CANARY','NODE_OPTIONS':'CANARY','DALA_E2E_MASTER_PIN_FILE':'CANARY','PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH':'CANARY','UI_TEST_NO_SERVER':'1'}):
            value=environment(Path('/source'),'a'*40)
        self.assertNotIn('CANARY',json.dumps(value));self.assertNotIn('UI_TEST_NO_SERVER',value)


if __name__=='__main__':unittest.main()
