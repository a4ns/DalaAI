"""HTTP-only tests use a stub service, never imply database authorization proof."""
import unittest
from unittest.mock import Mock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth_boundary import AuthenticationRequired, RequestProtection, SESSION_COOKIE_NAME
from app.orders.models import DomainError
from app.push.http import create_push_router

ORIGIN='https://naryadai.test'
PATH='/api/v1/push'


class PushHttpTests(unittest.TestCase):
    def setUp(self):
        self.service=Mock()
        self.service.protection=RequestProtection(ORIGIN)
        self.service.config.return_value={'enabled':False,'application_server_key':None,
            'delivery_semantics':'provider_acceptance_is_not_device_delivery','device_policy':'latest_registration_per_user'}
        self.service.mutate.return_value={'enabled':True}
        app=FastAPI()
        app.include_router(create_push_router(self.service))
        self.client=TestClient(app,base_url=ORIGIN)
        self.headers={'Origin':ORIGIN,'X-CSRF-Token':'synthetic-csrf','Content-Type':'application/json',
                      'Cookie':f'{SESSION_COOKIE_NAME}=synthetic-handle'}

    def test_register_passes_only_server_session_context(self):
        response=self.client.post(PATH+'/subscriptions',content='{}',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json(),{'enabled':True})
        self.service.mutate.assert_called_once_with(b'{}',remove=False,session_handle='synthetic-handle',
                                                   origin=ORIGIN,csrf_token='synthetic-csrf')
        self.assertIn('no-store',response.headers['cache-control'])

    def test_remove_empty204(self):
        response=self.client.post(PATH+'/subscriptions/remove',content='{}',headers=self.headers)
        self.assertEqual((response.status_code,response.content),(204,b''))
        self.assertTrue(self.service.mutate.call_args.kwargs['remove'])

    def test_config_auth_and_no_query(self):
        self.assertEqual(self.client.get(PATH+'/config').status_code,401)
        self.assertEqual(self.client.get(PATH+'/config?user_id=x',headers=self.headers).status_code,400)
        response=self.client.get(PATH+'/config',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertIsNone(response.json()['application_server_key'])

    def test_origin_csrf_fetchsite_media_body_size(self):
        for headers,status in [({**self.headers,'Origin':'https://evil.test'},403),
                               ({**self.headers,'X-CSRF-Token':''},403),
                               ({**self.headers,'Sec-Fetch-Site':'same-site'},403),
                               ({**self.headers,'Content-Type':'text/plain'},415)]:
            response=self.client.post(PATH+'/subscriptions',content='{}',headers=headers)
            self.assertEqual(response.status_code,status)
        self.assertEqual(self.client.post(PATH+'/subscriptions',content='x'*4097,headers=self.headers).status_code,413)
        self.service.mutate.assert_not_called()

    def test_duplicate_security_headers_and_cookies(self):
        for name in ('Origin','X-CSRF-Token','Content-Type','Cookie'):
            headers=list(self.headers.items())+[(name,self.headers[name])]
            self.assertEqual(self.client.post(PATH+'/subscriptions',content='{}',headers=headers).status_code,400)
        self.service.mutate.assert_not_called()

    def test_missing_or_revoked_session(self):
        headers={key:value for key,value in self.headers.items() if key!='Cookie'}
        self.assertEqual(self.client.post(PATH+'/subscriptions',content='{}',headers=headers).status_code,401)
        self.service.mutate.side_effect=AuthenticationRequired()
        self.assertEqual(self.client.post(PATH+'/subscriptions',content='{}',headers=self.headers).status_code,401)

    def test_conflict_and_disabled_have_explicit_nonretryable_codes(self):
        for code,status in [('SUBSCRIPTION_CONFLICT',409),('PUSH_DISABLED',503)]:
            self.service.mutate.side_effect=DomainError(code,'Safe public message')
            response=self.client.post(PATH+'/subscriptions',content='{}',headers=self.headers)
            self.assertEqual(response.status_code,status)
            self.assertFalse(response.json()['retryable'])


if __name__=='__main__':
    unittest.main()
