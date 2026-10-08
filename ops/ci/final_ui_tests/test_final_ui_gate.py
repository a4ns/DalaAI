from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from final_ui_synthetic import PROJECTS,SOURCE_SHA,source_environment,verify_report


def report(project='android-emulation-pixel-9'):
    count=PROJECTS[project]
    row={'projectName':project,'expectedStatus':'passed','status':'expected',
         'results':[{'status':'passed','retry':0,'errors':[]}]}
    return {'config':{'metadata':{'reviewedSha':SOURCE_SHA}},'errors':[],
        'stats':{'expected':count,'unexpected':0,'flaky':0,'skipped':0},
        'suites':[{'specs':[{'tests':[deepcopy(row)]} for _ in range(count)]}]}


class FinalUiGate(unittest.TestCase):
    def test_all_153_source_cases_required(self):
        self.assertEqual(verify_report(report('independent-source'),'independent-source')['tests_passed'],153)
    def test_all_13_browser_cases_required(self):
        self.assertEqual(verify_report(report(),'android-emulation-pixel-9')['tests_passed'],13)
    def test_empty_filtered_suite_rejected(self):
        value=report();value['suites']=[]
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_failed_case_rejected(self):
        value=report();value['suites'][0]['specs'][0]['tests'][0]['results'][0]['status']='failed'
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_skip_rejected(self):
        value=report();value['stats']['skipped']=1
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_retry_rejected(self):
        value=report();value['suites'][0]['specs'][0]['tests'][0]['results'][0]['retry']=1
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_expected_failure_rejected(self):
        value=report();value['suites'][0]['specs'][0]['tests'][0]['expectedStatus']='failed'
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_stale_source_report_rejected(self):
        value=report();value['config']['metadata']['reviewedSha']='0'*40
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_desktop_project_cannot_promote_android(self):
        value=report();value['suites'][0]['specs'][0]['tests'][0]['projectName']='chromium-390'
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_c_journey_is_not_a_permitted_project(self):
        for project in ['c110-android-chromium','c112-android-chromium']:
            with self.assertRaises(ValueError):verify_report(report(),project)
    def test_runner_errors_rejected(self):
        value=report();value['errors']=[{'message':'dummy arbitrary text'}]
        with self.assertRaises(ValueError):verify_report(value,'android-emulation-pixel-9')
    def test_environment_excludes_real_and_browser_override_inputs(self):
        dangerous=['DALA_C112_OBSERVER_DATABASE_URL','DALA_E2E_MASTER_PIN_FILE','OPENAI_API_KEY',
                   'PGPASSWORD','GITHUB_TOKEN','NODE_OPTIONS','DEBUG','PWDEBUG',
                   'PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH','UI_TEST_NO_SERVER']
        with patch.dict(os.environ,{key:'dummy' for key in dangerous}):
            env=source_environment(Path('/repo'))
            self.assertTrue(set(env).isdisjoint(dangerous))
            self.assertEqual(env['UI_REVIEW_SHA'],SOURCE_SHA)
            self.assertEqual(env['UI_TEST_PORT'],'4176')


if __name__=='__main__':unittest.main()
