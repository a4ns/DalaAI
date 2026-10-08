import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from history_diagnostics import failure_projection,STEPS


class Diagnostics(unittest.TestCase):
    def project(self,data,evidence=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); report=root/'report.json'; report.write_text(json.dumps(data))
            e=root/'evidence.json'
            if evidence is not None:e.write_text(json.dumps(evidence))
            return failure_projection(report,e)
    def test_nested_step_error_retained_after_outer_catch(self):
        data={'suites':[{'specs':[{'tests':[{'results':[{'steps':[{'error':{
            'message':'Timed out 15000ms waiting for expect(locator) CANARY',
            'stack':'at /repo/tests/e2e/c112_analytics.spec.cjs:148:7'},
            'location':{'file':'/repo/tests/e2e/c112_analytics.spec.cjs','line':134},'title':'PRIVATE DOM CANARY'}],
            'errors':[{'message':'C112 BLOCKED: ANALYTICS_JOURNEY_FAILED_SEE_SAFE_STAGE_RESULTS'}]}]}]}]}]}
        result=self.project(data)
        self.assertIn({'file':'c112_analytics.spec.cjs','line':148},result['source_locations'])
        self.assertIn('ASSERTION_TIMEOUT',result['error_classes']); self.assertNotIn('CANARY',json.dumps(result))
    def test_fixed_assertion_code_only(self):
        result=self.project({'errors':[{'message':'C112 BLOCKED: API_DB_IDENTITIES_MISMATCH'}]})
        self.assertEqual(result['error_classes'],['API_DB_IDENTITIES_MISMATCH'])
    def test_unknown_error_and_source_are_not_exported(self):
        result=self.project({'errors':[{'message':'C112 BLOCKED: CANARY','stack':'CANARY.py:123:3',
            'location':{'file':'CANARY.py','line':123}}],'attachments':[{'body':'CANARY'}]})
        self.assertEqual(result['error_classes'],[]);self.assertEqual(result['source_locations'],[])
        self.assertNotIn('CANARY',json.dumps(result))
    def test_location_bounds_and_boolean_rejected(self):
        result=self.project({'errors':[{'location':{'file':'c112_contract.cjs','line':v}} for v in [0,-1,1001,True,'12']]})
        self.assertEqual(result['source_locations'],[])
    def test_stage_is_fixed_index_not_dynamic_title(self):
        result=self.project({}, {'steps':[{'name':STEPS[0],'result':'PASS'},{'name':STEPS[1],'result':'FAIL'}],
                                 'observations':['CANARY']*40})
        self.assertEqual(result['completed_steps'],1);self.assertEqual(result['failed_step'],2)
        self.assertEqual(result['observations'],3);self.assertNotIn('CANARY',json.dumps(result))
    def test_c_owned_fixed_diagnostic_labels_are_preserved(self):
        fields={'substep':'FILL_PERIOD_START','failure_category':'ASSERTION_OR_OPERATION_FAILED','analytics_response':'NOT_OBSERVED'}
        result=self.project({}, {'diagnostics':fields})
        self.assertEqual(result['c112_diagnostics'],fields)
    def test_c_diagnostics_extra_values_and_invalid_types_are_excluded(self):
        result=self.project({}, {'diagnostics':{'substep':'CANARY','failure_category':{'secret':'CANARY'},
            'analytics_response':422,'raw_error':'CANARY'}})
        self.assertEqual(result['c112_diagnostics'],{'substep':'UNCLASSIFIED_STEP',
            'failure_category':'ASSERTION_OR_OPERATION_FAILED','analytics_response':'HTTP_OTHER_OR_UNAVAILABLE'})
        self.assertNotIn('CANARY',json.dumps(result))
    def test_c_http_categories_preserve_meaning_without_numeric_status(self):
        result=self.project({}, {'diagnostics':{'substep':'CHECK_RESPONSE_IDENTITY_STATUS',
            'failure_category':'NONE','analytics_response':'HTTP_VALIDATION'}})
        self.assertEqual(result['c112_diagnostics']['analytics_response'],'HTTP_VALIDATION')
        self.assertNotIn('422',json.dumps(result))
    def test_passing_step_location_not_misreported_as_failure(self):
        result=self.project({'steps':[{'location':{'file':'c112_contract.cjs','line':12},'title':'PASS'}]})
        self.assertEqual(result['source_locations'],[])
    def test_missing_report_stays_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=failure_projection(Path(tmp)/'missing',Path(tmp)/'e')
            self.assertEqual(result['report'],'unavailable');self.assertNotIn('PASS',json.dumps(result))
    def test_report_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'real').write_text('{}');(root/'link').symlink_to(root/'real')
            self.assertEqual(failure_projection(root/'link',root/'e')['report'],'unavailable')


if __name__=='__main__':unittest.main()
