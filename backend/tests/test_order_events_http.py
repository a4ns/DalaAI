import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.orders.models import DomainError
from app.order_events.http import create_order_events_router
from app.order_events.query import MAX_SEQUENCE


class Stub:
    def __init__(self):self.calls=[];self.error=None
    def list_events(self,order_id,query,*,session_handle):
        self.calls.append((order_id,query,session_handle))
        if self.error:raise self.error
        return {'items':[],'next_after_sequence':MAX_SEQUENCE,'has_more':False}


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.stub=Stub();self.app=FastAPI();self.app.include_router(create_order_events_router(self.stub))
        self.client=TestClient(self.app);self.headers={'cookie':'__Host-naryadai_session=synthetic'}

    def test_exact_per_order_get_only(self):
        paths=self.app.openapi()['paths'];self.assertEqual(set(paths),{'/api/v1/orders/{order_id}/events'})
        self.assertEqual(paths['/api/v1/orders/{order_id}/events']['get']['operationId'],'listOrderEvents')
        self.assertEqual(self.client.get('/api/v1/events',headers=self.headers).status_code,404)
        self.assertEqual(self.client.post('/api/v1/orders/order/events',headers=self.headers).status_code,405)

    def test_cookie_query_pairs_and_exact_bigint_json(self):
        response=self.client.get('/api/v1/orders/order/events?after_sequence=1&after_sequence=2',headers=self.headers)
        self.assertEqual(response.status_code,200) # stub records; real service rejects duplicate keys
        self.assertEqual(self.stub.calls,[('order',[('after_sequence','1'),('after_sequence','2')],'synthetic')])
        self.assertIn(f'"next_after_sequence":{MAX_SEQUENCE}',response.text)
        self.assertEqual(response.headers['cache-control'],'private, no-store')

    def test_missing_duplicate_cookie_denied(self):
        for headers in ({},{'cookie':'__Host-naryadai_session=a; __Host-naryadai_session=b'}):
            self.assertEqual(self.client.get('/api/v1/orders/order/events',headers=headers).status_code,401)
        self.assertEqual(self.stub.calls,[])

    def test_contract_errors_and_sanitized_database_failure(self):
        import psycopg
        cases=[(DomainError('INVALID_REQUEST','Invalid query'),400),
               (DomainError('VALIDATION_FAILED','Invalid value'),422),
               (DomainError('NOT_FOUND','Order does not exist'),404),
               (psycopg.OperationalError('secret DSN text'),503)]
        for error,status in cases:
            self.stub.error=error
            with self.subTest(status=status):
                response=self.client.get('/api/v1/orders/order/events',headers=self.headers)
                self.assertEqual(response.status_code,status);self.assertNotIn('secret DSN',response.text)
                self.assertEqual(response.headers['cache-control'],'private, no-store')
                self.assertEqual(response.json()['retryable'],status==503)
                if status==503:self.assertEqual(response.headers['retry-after'],'1')
