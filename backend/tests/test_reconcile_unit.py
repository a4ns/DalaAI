from types import SimpleNamespace
import unittest
from uuid import uuid4

from app.notify.reconcile import DeadlineReconciler, ReconcilePage, ReconcileResult
from app.notify.runner import NotificationRunner
from app.scheduler import SchedulePolicy
from datetime import timedelta


class ReconcileUnitTests(unittest.TestCase):
    def test_constructor_and_import_start_no_work(self):
        def forbidden():raise AssertionError('Unexpected connection')
        self.assertEqual(DeadlineReconciler(forbidden,channel='web_push',domain_clock=None).channel,'web_push')

    def test_channel_and_unconfigured_manager_policy_rejected(self):
        for channel,policy in [('email',None),('web_push',SchedulePolicy(channel='telegram')),
                              ('web_push',SchedulePolicy(channel='web_push',manager_escalation_after=timedelta(0)))]:
            with self.subTest(channel=channel),self.assertRaises(ValueError):
                DeadlineReconciler(None,channel=channel,domain_clock=None,policy=policy)

    def test_scan_limit_checked_before_any_database_access(self):
        worker=DeadlineReconciler(None,channel='web_push',domain_clock=None)
        for limit in (0,1001,True,None):
            with self.subTest(limit=limit),self.assertRaises(ValueError):worker.scan_once(limit=limit)

    def test_runner_reconciles_before_dispatch_and_wraps_scan_cursor(self):
        calls=[];next_id=str(uuid4())
        pages=iter((ReconcilePage((ReconcileResult(str(uuid4()),'reconciled'),),next_id),
                    ReconcilePage((),None),ReconcilePage((),None)))
        def scan(**kwargs):calls.append(('scan',kwargs));return next(pages)
        def dispatch(**kwargs):calls.append(('dispatch',kwargs));return ()
        runner=NotificationRunner(reconciler=SimpleNamespace(channel='web_push',scan_once=scan),
                                  dispatcher=SimpleNamespace(channel='web_push',run_batch=dispatch))
        for _ in range(3):runner.tick()
        self.assertEqual([call[0] for call in calls],['scan','dispatch']*3)
        self.assertEqual([call[1]['after_id'] for call in calls if call[0]=='scan'],[None,next_id,None])

    def test_runner_mismatched_channel_fails_before_work(self):
        with self.assertRaises(ValueError):
            NotificationRunner(reconciler=SimpleNamespace(channel='web_push'),dispatcher=SimpleNamespace(channel='synthetic'))

    def test_failed_reconciliation_is_not_followed_by_dispatch(self):
        calls=[]
        def fail(**kwargs):raise RuntimeError('database unavailable')
        runner=NotificationRunner(reconciler=SimpleNamespace(channel='web_push',scan_once=fail),
            dispatcher=SimpleNamespace(channel='web_push',run_batch=lambda **kwargs:calls.append(kwargs)))
        with self.assertRaises(RuntimeError):runner.tick()
        self.assertEqual(calls,[])
