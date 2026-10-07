import unittest
from app.discovery.workload import WorkloadPolicy,POLICY_NAME


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.policy=WorkloadPolicy(POLICY_NAME)

    def test_multiple_active_rows_choose_numeric_lowest_without_error(self):
        result=self.policy.summarize([
            {"id":"ten","number":"10","status":"in_progress"},
            {"id":"two","number":"2","status":"paused"},
            {"id":"three","number":3,"status":"in_progress"}])
        self.assertEqual(result,{"active_order_id":"two","queue_count":0})

    def test_queue_is_explicit_queued_only(self):
        statuses=['issued','queued','queued','accepted','rejected','in_progress','paused','done','ai_review','rework','closed','cancelled']
        rows=[{"id":str(i),"number":i+1,"status":status} for i,status in enumerate(statuses)]
        self.assertEqual(self.policy.summarize(rows),{"active_order_id":"5","queue_count":2})

    def test_empty_is_scoped_empty_without_global_claim(self):
        self.assertEqual(self.policy.summarize([]),{"active_order_id":None,"queue_count":0})

    def test_reordered_input_has_same_representative(self):
        rows=[{"id":"a","number":30,"status":"paused"},{"id":"b","number":20,"status":"in_progress"}]
        self.assertEqual(self.policy.summarize(rows),self.policy.summarize(list(reversed(rows))))

    def test_conflicting_policy_names_rejected(self):
        for name in ('','unique-active','issued-plus-accepted-are-queue',None):
            with self.subTest(name=name),self.assertRaises(ValueError):
                WorkloadPolicy(name)
