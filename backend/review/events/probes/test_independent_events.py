"""Independent event boundary probes; doubles do not establish DB locking."""
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import random
import unittest
from unittest.mock import patch
from uuid import UUID
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.auth_boundary import AuthenticationRequired, AuthContext, SessionRecord
from app.core.auth_policy import AccessDenied, Principal, Role, OrderScope
from app.orders.models import DomainError
from app.order_events.query import parse_query, MAX_SEQUENCE
from app.order_events.serialization import event_wire, EVENT_FIELDS
from app.order_events.postgres import EventRepository
from app.order_events.service import OrderEventService
from app.order_events.http import create_order_events_router


def uid(n):return str(UUID(int=n))
ACTOR,OTHER,SECTION,ORDER,OTHER_ORDER=map(uid,range(1,6))
NOW=datetime(2026,10,7,19,tzinfo=timezone.utc)
SCOPE=OrderScope(ORDER,SECTION,ACTOR,1)


def context(role=Role.EXECUTOR,*,actor=ACTOR,sections=(SECTION,)):
 return AuthContext(Principal(actor,role,frozenset(sections)),SessionRecord(actor,NOW-timedelta(hours=1),NOW+timedelta(hours=1),'synthetic'))


def row(sequence=1,**changes):
 result={'id':uid(100+sequence),'order_id':ORDER,'sequence':sequence,'order_version':1,'assignment_revision':1,'scheduling_revision':1,
  'reason':None,'details':{},'kind':'order.created','actor_id':ACTOR,'operation_id':uid(50),'from_status':None,'to_status':'issued','submission_id':None,
  'occurred_at':NOW.astimezone(timezone(timedelta(hours=5))),'recorded_at':NOW+timedelta(minutes=1)}
 result.update(changes);return result


class DB:
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def transaction(self):return nullcontext()
 def execute(self,*args):return self


class QueryAndWireTests(unittest.TestCase):
 def test_strict_query_numbers_and_allowlist(self):
  self.assertEqual((parse_query({}).after_sequence,parse_query({}).limit),(0,100))
  self.assertEqual(parse_query({'after_sequence':str(MAX_SEQUENCE),'limit':'200'}).after_sequence,MAX_SEQUENCE)
  for value in ['', '-1','+1','01','00',' 1','1 ','1.0','1e2','true','１',str(MAX_SEQUENCE+1),'9'*10000]:
   with self.subTest(value=value),self.assertRaises(DomainError):parse_query({'after_sequence':value})
  for value in ['0','201','01','+1','1 ','1.0']:
   with self.subTest(limit=value),self.assertRaises(DomainError):parse_query({'limit':value})
  for q in [[('role','master')],[('actor_id',OTHER)],[('after_sequence','0'),('after_sequence','0')],[('limit','1'),('limit','2')]]:
   with self.assertRaises(DomainError):parse_query(q)

 def test_random_query_abuse_fails_without_unexpected_exceptions(self):
  rng=random.Random(73189)
  for _ in range(1000):
   text=''.join(rng.choices('x%+ =aé\x00',k=rng.randrange(1,90)))
   with self.assertRaises(DomainError):parse_query({'after_sequence':text})

 def test_wire_is_exact_projection_preserves_nulls_and_two_clocks(self):
  original=row(actor_id=None,operation_id=None,submission_id=None,private_provider_token='synthetic-secret',pin_hash='never-export')
  result=event_wire(original,order_id=ORDER)
  self.assertEqual(set(result),set(EVENT_FIELDS));self.assertNotIn('synthetic-secret',str(result))
  self.assertIsNone(result['actor_id']);self.assertIsNone(result['operation_id']);self.assertIsNone(result['submission_id'])
  self.assertEqual(result['occurred_at'],'2026-10-07T19:00:00.000000Z')
  self.assertEqual(result['recorded_at'],'2026-10-07T19:01:00.000000Z')

 def test_wire_positive_int_types_and_exact_above_js_safe_integer(self):
  value=2**53+1
  result=event_wire(row(value),order_id=ORDER)
  self.assertEqual(json.loads(json.dumps(result))['sequence'],value)
  for key in ['sequence','order_version','assignment_revision','scheduling_revision']:
   for bad in [True,False,0,-1,1.0,'1',MAX_SEQUENCE+1,None]:
    with self.subTest(key=key,bad=bad),self.assertRaises(DomainError):event_wire(dict(row(),**{key:bad}),order_id=ORDER)

 def test_wire_rejects_cross_order_and_schema_corruption(self):
  for key in EVENT_FIELDS:
   record=row();del record[key]
   with self.subTest(missing=key),self.assertRaises(DomainError):event_wire(record,order_id=ORDER)
  for changes in [{'order_id':OTHER_ORDER},{'kind':'secret.debug'},{'details':[]},{'details':{'score':float('nan')}},{'details':{'score':float('inf')}},{'to_status':'secret'},{'from_status':'bad'},{'reason':''},{'reason':'x'*2001},{'recorded_at':datetime(2026,1,1)},{'actor_id':'no-uuid'}]:
   with self.subTest(changes=changes),self.assertRaises(DomainError):event_wire(row(**changes),order_id=ORDER)


class ServiceTests(unittest.TestCase):
 def setUp(self):
  self.service=OrderEventService(lambda:None)
  p=patch.object(self.service,'_connection',return_value=DB());p.start();self.addCleanup(p.stop)

 def run_rows(self,rows,query=None,auth=None,scope=SCOPE):
  with patch.object(self.service,'_auth',side_effect=auth or [context()]*3),patch('app.order_events.service.EventRepository') as repo:
   repo.return_value.load_scope.return_value=scope;repo.return_value.read_page.return_value=rows
   result=self.service.list_events(ORDER,query or {},session_handle='synthetic')
   return result,repo

 def test_event_pages_use_sequence_not_version_and_lookahead(self):
  rows=[row(4,order_version=4,kind='order.done',to_status='done'),row(5,order_version=4,kind='order.ai_review_requested',to_status='ai_review'),row(9,order_version=5,kind='order.assessment_recorded',to_status='ai_review')]
  result,_=self.run_rows(rows,{'after_sequence':'3','limit':'2'})
  self.assertEqual([item['sequence'] for item in result['items']],[4,5]);self.assertEqual([item['order_version'] for item in result['items']],[4,4])
  self.assertEqual((result['next_after_sequence'],result['has_more']),(5,True))

 def test_empty_future_and_exact_end_keep_correct_cursor(self):
  result,_=self.run_rows([],{'after_sequence':str(MAX_SEQUENCE)})
  self.assertEqual(result,{'items':[],'next_after_sequence':MAX_SEQUENCE,'has_more':False})
  result,_=self.run_rows([row(7)],{'after_sequence':'5','limit':'1'})
  self.assertEqual((result['next_after_sequence'],result['has_more']),(7,False))

 def test_unauthorized_never_reads_history_even_for_empty_future_page(self):
  for who in [context(actor=OTHER),context(Role.ADMIN),context(sections=())]:
   with patch.object(self.service,'_auth',return_value=who),patch('app.order_events.service.EventRepository') as repo:
    repo.return_value.load_scope.return_value=SCOPE
    with self.assertRaises(AccessDenied):self.service.list_events(ORDER,{'after_sequence':str(MAX_SEQUENCE)},session_handle='synthetic')
    repo.return_value.read_page.assert_not_called()

 def test_missing_order_and_expired_session_do_not_touch_history(self):
  with patch.object(self.service,'_auth',return_value=context()),patch('app.order_events.service.EventRepository') as repo:
   repo.return_value.load_scope.return_value=None
   with self.assertRaises(DomainError) as error:self.service.list_events(ORDER,{},session_handle='synthetic')
   self.assertEqual(error.exception.code,'NOT_FOUND');repo.return_value.read_page.assert_not_called()
  for auth in [[AuthenticationRequired()],[context(),AuthenticationRequired()],[context(),context(),AuthenticationRequired()]]:
   with self.assertRaises(AuthenticationRequired):self.run_rows([row()],auth=auth)

 def test_post_read_scope_role_and_actor_revocation_fail_closed(self):
  for later in [context(actor=OTHER),context(Role.ADMIN),context(sections=())]:
   with self.assertRaises(AccessDenied):self.run_rows([row()],auth=[context(),context(),later])

 def test_sequence_regression_duplicate_and_corrupt_lookahead_fail_closed(self):
  for rows,query in [([row(3),row(2)],{}),([row(2),row(2)],{}),([row(3)],{'after_sequence':'3'}),([row(2),row(3,order_id=OTHER_ORDER)],{'limit':'1'})]:
   with self.subTest(rows=rows),self.assertRaises(DomainError) as error:self.run_rows(rows,query)
   self.assertEqual(error.exception.code,'TEMPORARILY_UNAVAILABLE')

 def test_current_manager_master_can_read_entire_existing_history(self):
  for role in [Role.MASTER,Role.MANAGER]:
   result,_=self.run_rows([row(actor_id=OTHER)],auth=[context(role)]*3)
   self.assertEqual(result['items'][0]['actor_id'],OTHER)


class RecordingDB:
 def __init__(self):self.calls=[]
 def execute(self,sql,params):self.calls.append((sql,params));return self
 def fetchone(self):return None
 def fetchall(self):return []


class SqlTests(unittest.TestCase):
 def test_projection_scopes_order_and_sequence_and_only_public_fields(self):
  db=RecordingDB();repo=EventRepository(db)
  repo.load_scope(ORDER);repo.read_page(ORDER,parse_query({'after_sequence':'7','limit':'2'}))
  self.assertIn('FOR SHARE',db.calls[0][0]);self.assertEqual(db.calls[0][1],(ORDER,))
  query,params=db.calls[1]
  self.assertNotIn('SELECT *',query);self.assertNotIn(ORDER,query)
  self.assertIn('WHERE order_id=%s AND sequence>%s ORDER BY sequence ASC LIMIT %s',query)
  self.assertEqual(params,(ORDER,7,3))


class FakeService:
 def __init__(self):self.error=None;self.calls=[]
 def list_events(self,order_id,query,*,session_handle):
  self.calls.append((order_id,query,session_handle))
  if self.error:raise self.error
  parsed=parse_query(query)
  return {'items':[],'next_after_sequence':parsed.after_sequence,'has_more':False}


class HttpTests(unittest.TestCase):
 def setUp(self):
  self.service=FakeService();app=FastAPI();app.include_router(create_order_events_router(self.service));self.client=TestClient(app)
  self.url='/api/v1/orders/'+ORDER+'/events';self.cookie={'cookie':'__Host-naryadai_session=synthetic'}

 def test_cookie_ambiguity_denied_before_service(self):
  for headers in [{},{'cookie':'__Host-naryadai_session=a; __Host-naryadai_session=b'},[('cookie','__Host-naryadai_session=a'),('cookie','__Host-naryadai_session=b')]]:
   r=self.client.get(self.url,headers=headers);self.assertEqual(r.status_code,401)
  self.assertEqual(self.service.calls,[])

 def test_http_query_errors_and_no_store(self):
  for query,code in [('?after_sequence=1&after_sequence=1',400),('?after_sequence='+str(MAX_SEQUENCE+1),422),('?actor_id='+OTHER,400),('?limit=201',422),('?after_sequence='+str(MAX_SEQUENCE),200)]:
   result=self.client.get(self.url+query,headers=self.cookie)
   self.assertEqual(result.status_code,code);self.assertEqual(result.headers['cache-control'],'private, no-store')

 def test_sql_error_sanitized_retryable_and_denial_not_retryable(self):
  import psycopg
  for error,status in [(psycopg.OperationalError('secret DSN password'),503),(AccessDenied(),403),(DomainError('NOT_FOUND','Order does not exist'),404)]:
   self.service.error=error;result=self.client.get(self.url,headers=self.cookie)
   self.assertEqual(result.status_code,status);self.assertNotIn('secret',result.text)
   self.assertEqual(result.json()['retryable'],status==503)
   self.assertEqual(result.headers['cache-control'],'private, no-store')
   if status==503:self.assertEqual(result.headers['retry-after'],'1')


if __name__=='__main__':unittest.main(verbosity=2)
