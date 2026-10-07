import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.discovery.http import create_discovery_router


class StubService:
    def __init__(self):self.calls=[]
    def list_orders(self,query,*,session_handle):
        self.calls.append((query,session_handle))
        return {"items":[],"next_cursor":None}
    def get_dictionaries(self,*,session_handle):
        self.calls.append(session_handle)
        return {key:[] for key in ('sections','equipment','brigades','executors','work_codes','materials')}


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.service=StubService()
        app=FastAPI();app.include_router(create_discovery_router(self.service))
        self.app=app;self.client=TestClient(app)
        self.headers={"cookie":"__Host-naryadai_session=synthetic"}

    def test_exact_get_paths_and_operation_ids(self):
        paths=self.app.openapi()['paths']
        self.assertEqual(set(paths),{'/api/v1/orders','/api/v1/dicts'})
        self.assertEqual(paths['/api/v1/orders']['get']['operationId'],'listOrders')
        self.assertEqual(paths['/api/v1/dicts']['get']['operationId'],'getDictionaries')

    def test_duplicate_query_preserved_for_strict_service_validation(self):
        response=self.client.get('/api/v1/orders?status=issued&status=queued',headers=self.headers)
        self.assertEqual(response.status_code,200) # stub only; real service rejects duplicates
        self.assertEqual(self.service.calls[0][0],[('status','issued'),('status','queued')])

    def test_cookie_reused_and_response_private(self):
        response=self.client.get('/api/v1/dicts',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.service.calls,['synthetic'])
        self.assertEqual(response.headers['cache-control'],'private, no-store')

    def test_missing_or_duplicate_session_cookie_denied(self):
        for headers in ({},{'cookie':'__Host-naryadai_session=a; __Host-naryadai_session=b'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.get('/api/v1/orders',headers=headers).status_code,401)
        self.assertEqual(self.service.calls,[])

    def test_no_mutation_routes_or_dictionary_filter_invention(self):
        self.assertEqual(self.client.post('/api/v1/orders',headers=self.headers).status_code,405)
        self.assertEqual(self.client.get('/api/v1/dicts?section_id=foreign',headers=self.headers).status_code,400)
        self.assertEqual(self.service.calls,[])
