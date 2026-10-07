import unittest
from uuid import uuid4
from app.notify.priority_notice import safe_to_replace


class PriorityNoticeUnitTests(unittest.TestCase):
    def row(self,**changes):
        row=dict(id=str(uuid4()),state='pending',attempts=0,lease_token=None,last_error_code=None)
        row.update(changes);return row

    def test_pending_and_provably_unstarted_claims_can_be_replaced(self):
        for row in (self.row(),self.row(state='sending',attempts=1,lease_token=str(uuid4())),
                    self.row(state='retry',attempts=1,last_error_code='DELIVERY_PREPARE_ERROR'),
                    self.row(state='pending',attempts=2,last_error_code='NOTICE_RESCHEDULED_UNSENT')):
            with self.subTest(row=row):self.assertTrue(safe_to_replace([row],{}))

    def test_accepted_failed_and_legacy_unexplained_states_are_quarantined(self):
        for row in (self.row(state='provider_accepted'),self.row(state='synthetic_recorded'),
                    self.row(state='failed'),self.row(state='sending'),
                    self.row(state='cancelled',attempts=1),self.row(state='retry',attempts=1)):
            with self.subTest(row=row):self.assertFalse(safe_to_replace([row],{}))

    def test_any_unfinished_accepted_or_ambiguous_prior_intent_blocks_replacement(self):
        for outcome in (None,'accepted','ambiguous','synthetic_recorded'):
            row=self.row(state='cancelled',attempts=1,lease_token=str(uuid4()))
            with self.subTest(outcome=outcome):self.assertFalse(safe_to_replace([row],{row['id']:[outcome]}))

    def test_explicit_rejections_are_safe_but_do_not_override_another_unknown(self):
        row=self.row(state='retry',attempts=2)
        self.assertTrue(safe_to_replace([row],{row['id']:['retryable','permanent_failure']}))
        self.assertFalse(safe_to_replace([row],{row['id']:['retryable',None]}))

    def test_old_scheduling_generation_unknown_is_not_hidden_by_new_pending_row(self):
        old=self.row(state='cancelled',attempts=1,lease_token=str(uuid4()))
        current=self.row()
        self.assertFalse(safe_to_replace([old,current],{old['id']:[None]}))

    def test_unstarted_cancelled_history_does_not_make_duplicate_logical_effect(self):
        rows=[self.row(state='cancelled'),self.row(state='cancelled',attempts=1,lease_token=str(uuid4())),self.row()]
        self.assertTrue(safe_to_replace(rows,{}))
