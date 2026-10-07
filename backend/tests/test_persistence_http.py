"""Router wiring/ingress tests only. Database behavior is tested against real PG."""
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.persistence.http import create_router
from app.persistence.service import CommandResult


class StubService:
    def __init__(self):
        self.calls=[]
    def execute(self,raw,**kwargs):
        self.calls.append((raw,kwargs))
        return CommandResult(201,{"stub":True})
    def get_order(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return {"stub":True}
    def get_submission(self,*args,**kwargs):
        return self.get_order(*args,**kwargs)


class HttpWiringTests(unittest.TestCase):
    def setUp(self):
        self.service=StubService()
        self.app=FastAPI()
        self.app.include_router(create_router(self.service))
        self.client=TestClient(self.app)
        self.headers={"cookie":"__Host-naryadai_session=synthetic","origin":"https://naryadai.test",
                      "x-csrf-token":"synthetic-csrf","content-type":"application/json"}

    def test_routes_and_operation_ids_match_contract_subset(self):
        expected={"/api/v1/orders":"createOrder","/api/v1/orders/{order_id}/commands":"executeOrderCommand",
                  "/api/v1/orders/{order_id}":"getOrder",
                  "/api/v1/orders/{order_id}/submissions/{submission_id}":"getSubmission"}
        actual={path:operation["operationId"] for path,methods in self.app.openapi()["paths"].items()
                for operation in methods.values()}
        self.assertEqual(actual,expected)

    def test_raw_json_and_protection_fields_reach_service(self):
        response=self.client.post("/api/v1/orders",content=b'{"x":1}',headers=self.headers)
        self.assertEqual(response.status_code,201)
        self.assertEqual(self.service.calls,[(b'{"x":1}',{"session_handle":"synthetic",
            "origin":"https://naryadai.test","csrf_token":"synthetic-csrf"})])
        self.assertEqual(response.headers["cache-control"],"private, no-store")

    def test_duplicate_cookie_denied_before_service(self):
        headers=dict(self.headers,cookie="__Host-naryadai_session=a; __Host-naryadai_session=b")
        self.assertEqual(self.client.post("/api/v1/orders",content=b'{}',headers=headers).status_code,401)
        self.assertEqual(self.service.calls,[])

    def test_missing_cookie_denied_before_service(self):
        self.assertEqual(self.client.get("/api/v1/orders/test").status_code,401)
        self.assertEqual(self.service.calls,[])

    def test_body_limit_prevents_service_execution(self):
        self.assertEqual(self.client.post("/api/v1/orders",content=b'x'*65537,headers=self.headers).status_code,413)
        self.assertEqual(self.service.calls,[])

    def test_nested_submission_route_passes_both_ids(self):
        response=self.client.get("/api/v1/orders/order-a/submissions/sub-a",headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.service.calls[0][0],("order-a","sub-a"))

    def test_non_json_rejected(self):
        headers=dict(self.headers,**{"content-type":"text/plain"})
        self.assertEqual(self.client.post("/api/v1/orders",content='{}',headers=headers).status_code,415)
        self.assertEqual(self.service.calls,[])
