"""Seven independent real-PostgreSQL event cases; no fake fallback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic,sleep
import unittest
from unittest.mock import patch
from uuid import uuid4
import test_persistence_postgres as fixture
from test_persistence_postgres import PostgresCommandTests,MASTER,EXECUTOR,OTHER,SECTION,uid
from app.core.auth_boundary import AuthenticationRequired
from app.core.auth_policy import AccessDenied
from app.orders.models import DomainError
from app.order_events.service import OrderEventService
from app.order_events.postgres import EventRepository
from app.order_events.query import MAX_SEQUENCE

fixture.MIGRATIONS=Path(__file__).resolve().parents[1]/'snapshot/backend/db/migrations'


class IndependentEventsPostgresTests(PostgresCommandTests):
 def setUp(self):
  super().setUp();self.events=OrderEventService(self.connect,real_clock=self.real)

 def page(self,order_id,actor=EXECUTOR,**query):
  return self.events.list_events(order_id,{k:str(v) for k,v in query.items()},session_handle=actor)

 def created_order(self):return self.create()[0].body['order']['id']

 def test_events_page_drain_preserves_two_submit_events_same_version_and_no_cross_order(self):
  order_id=self.start();self.submit(order_id)
  foreign=self.created_order()
  pages=[];after=0
  while True:
   page=self.page(order_id,after_sequence=after,limit=1)
   pages.extend(page['items']);after=page['next_after_sequence']
   if not page['has_more']:break
  self.assertEqual([item['sequence'] for item in pages],[1,2,3,4,5])
  self.assertEqual([item['kind'] for item in pages][-2:],['order.done','order.ai_review_requested'])
  self.assertEqual([item['order_version'] for item in pages][-2:],[4,4])
  self.assertEqual({item['order_id'] for item in pages},{order_id})
  self.assertNotIn(foreign,str(pages))
  self.assertEqual(self.page(order_id,after_sequence=5),{'items':[],'next_after_sequence':5,'has_more':False})

 def test_events_live_append_and_restarted_service_keep_monotonic_sequence(self):
  order_id=self.created_order();self.action(order_id,1,'accept')
  first=self.page(order_id,limit=1)
  self.assertTrue(first['has_more']);self.assertEqual(first['next_after_sequence'],1)
  self.action(order_id,2,'start')
  self.events=OrderEventService(self.connect,real_clock=self.real)
  rest=self.page(order_id,after_sequence=first['next_after_sequence'])
  self.assertEqual([item['sequence'] for item in rest['items']],[2,3])
  self.assertFalse(rest['has_more'])

 def test_events_reassignment_revokes_old_reader_including_future_empty_cursor(self):
  order_id=self.created_order();self.action(order_id,1,'accept')
  self.page(order_id,limit=1)
  self.action(order_id,2,'reassign',MASTER,{'assignment':{'executor_id':OTHER,'brigade_id':None},'reason':'Synthetic reassignment'})
  for after in [0,1,MAX_SEQUENCE]:
   with self.assertRaises(AccessDenied):self.page(order_id,after_sequence=after)
  current=self.page(order_id,OTHER)
  self.assertEqual([row['sequence'] for row in current['items']],[1,2,3])
  self.assertIn(EXECUTOR,[row['actor_id'] for row in current['items']])
  self.assertEqual(self.page(order_id,MASTER)['items'],current['items'])

 def test_events_membership_admin_active_and_missing_object_boundaries(self):
  order_id=self.created_order()
  self.query("UPDATE employees SET role='manager' WHERE id=%s RETURNING id",(MASTER,))
  self.assertEqual(len(self.page(order_id,MASTER)['items']),1)
  self.query("UPDATE employees SET role='admin' WHERE id=%s RETURNING id",(MASTER,))
  with self.assertRaises(AccessDenied):self.page(order_id,MASTER)
  self.query('DELETE FROM employee_sections WHERE employee_id=%s RETURNING employee_id',(EXECUTOR,))
  with self.assertRaises(AccessDenied):self.page(order_id)
  self.query('INSERT INTO employee_sections VALUES (%s,%s) RETURNING employee_id',(EXECUTOR,SECTION))
  self.query('UPDATE employees SET active=false WHERE id=%s RETURNING id',(EXECUTOR,))
  with self.assertRaises(AuthenticationRequired):self.page(order_id)
  self.query('UPDATE employees SET active=true WHERE id=%s RETURNING id',(EXECUTOR,))
  with self.assertRaises(DomainError) as error:self.page(str(uuid4()))
  self.assertEqual(error.exception.code,'NOT_FOUND')
  self.query('UPDATE auth_sessions SET revoked_at=%s WHERE employee_id=%s RETURNING id',(self.real.now(),EXECUTOR))
  with self.assertRaises(AuthenticationRequired):self.page(order_id)

 def test_events_exact_large_sequence_nullable_system_metadata_and_future_cursor(self):
  order_id=self.created_order();big=2**53+1
  self.query('''INSERT INTO order_events(id,order_id,sequence,order_version,assignment_revision,scheduling_revision,
   kind,reason,details,actor_id,operation_id,from_status,to_status,submission_id,occurred_at,recorded_at)
   SELECT %s,order_id,%s,order_version,assignment_revision,scheduling_revision,
   kind,reason,details,NULL,NULL,from_status,to_status,NULL,occurred_at,recorded_at
   FROM order_events WHERE order_id=%s AND sequence=1 RETURNING id''',(str(uuid4()),big,order_id))
  result=self.page(order_id,after_sequence=big-1)
  self.assertEqual(result['items'][0]['sequence'],big);self.assertEqual(result['next_after_sequence'],big)
  self.assertIsNone(result['items'][0]['actor_id']);self.assertIsNone(result['items'][0]['operation_id'])
  self.assertEqual(self.page(order_id,after_sequence=MAX_SEQUENCE),{'items':[],'next_after_sequence':MAX_SEQUENCE,'has_more':False})
  with self.assertRaises(DomainError) as error:self.page(order_id,after_sequence=MAX_SEQUENCE+1)
  self.assertEqual(error.exception.code,'VALIDATION_FAILED')

 def assert_waiting_read_denied(self,mode):
  order_id=self.created_order();entered=Event();pid=[];original=EventRepository.load_scope
  def watched(repo,*args):
   pid.append(repo.db.execute('SELECT pg_backend_pid() AS pid').fetchone()['pid']);entered.set()
   return original(repo,*args)
  with patch.object(EventRepository,'load_scope',watched),ThreadPoolExecutor(max_workers=1) as pool:
   with self.connect() as blocker:
    with blocker.transaction():
     blocker.execute('SELECT id FROM orders WHERE id=%s FOR UPDATE',(order_id,))
     if mode=='reassign':
      blocker.execute('UPDATE orders SET executor_id=%s,assignment_revision=assignment_revision+1,version=version+1 WHERE id=%s',(OTHER,order_id))
     result=pool.submit(self.page,order_id)
     self.assertTrue(entered.wait(10));deadline=monotonic()+10
     while monotonic()<deadline:
      state=self.query('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',(pid[0],))
      if state and state[0]['wait_event_type']=='Lock':break
      sleep(0.01)
     else:self.fail('Event reader never entered observed PostgreSQL lock wait')
     self.assertFalse(result.done())
     if mode=='expire':self.real.value+=timedelta(days=6)
   expected=AuthenticationRequired if mode=='expire' else AccessDenied
   with self.assertRaises(expected):result.result(timeout=15)

 def test_events_expired_session_after_observed_order_lock_wait(self):self.assert_waiting_read_denied('expire')
 def test_events_reassignment_during_observed_order_lock_wait(self):self.assert_waiting_read_denied('reassign')


def load_tests(loader,standard_tests,pattern):
 return unittest.TestSuite(IndependentEventsPostgresTests(name)
  for name in sorted(IndependentEventsPostgresTests.__dict__) if name.startswith('test_events_'))


if __name__=='__main__':unittest.main(verbosity=2)
