"""Exercise HTTP boundary with a fake httpx client. No socket or real key."""
import asyncio
import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from app.ai.model_adapter import build_chat_request, prepare_input, TransportResponse
from app.ai.openai_runtime import OpenAIHTTPTransport, OPENAI_ENDPOINT, openai_demo_settings
from test_model_adapter import good, response


class FakeResponse:
    def __init__(self, status=200, chunks=(), encoding='identity'):
        self.status_code, self.chunks = status, chunks
        self.headers = {'content-encoding': encoding}
        self.entered, self.closed = 0, 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, *args):
        self.closed += 1

    async def aiter_raw(self):
        for c in self.chunks:
            yield c


class FakeClient:
    calls=[]
    options=[]
    next_response=None

    def __init__(self, **kwargs):
        self.options.append(kwargs)

    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass

    def stream(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return self.next_response


class TransportTests(IsolatedAsyncioTestCase):
    def setUp(self):
        FakeClient.calls=[];FakeClient.options=[]
        self.transport=OpenAIHTTPTransport('fake-key-unit-test-only')
        d,c=good()
        self.body=build_chat_request(openai_demo_settings(),prepare_input(d,c))

    async def call(self):
        return await self.transport.post_json(endpoint=OPENAI_ENDPOINT,body=self.body,
                                              timeout_seconds=.1,max_response_bytes=4096)

    async def test_exact_https_endpoint_bounded_stream_no_proxy_retry_redirect(self):
        r=response()
        FakeClient.next_response=FakeResponse(chunks=[r.body[:10],r.body[10:]])
        with patch('httpx.AsyncClient',FakeClient): result=await self.call()
        self.assertEqual(result,r)
        self.assertEqual(FakeClient.options,[{'timeout':.1,'follow_redirects':False,'trust_env':False,'verify':True}])
        args,kw=FakeClient.calls[0]
        self.assertEqual(args,('POST',OPENAI_ENDPOINT))
        self.assertNotIn('fake-key',json.dumps(kw['json']))
        self.assertEqual(kw['headers']['Accept-Encoding'],'identity')
        self.assertEqual(len(FakeClient.calls),1)
        self.assertEqual(FakeClient.next_response.closed,1)

    async def test_response_limit_closes_stream(self):
        FakeClient.next_response=FakeResponse(chunks=[b'x'*4000,b'x'*97])
        with patch('httpx.AsyncClient',FakeClient),self.assertRaisesRegex(ValueError,'TOO_LARGE'):
            await self.call()
        self.assertEqual(FakeClient.next_response.closed,1)

    async def test_encoded_response_denied_before_read(self):
        FakeClient.next_response=FakeResponse(chunks=[b'compressed'],encoding='gzip')
        with patch('httpx.AsyncClient',FakeClient),self.assertRaisesRegex(ValueError,'ENCODED'):
            await self.call()

    async def test_non_success_discards_private_body_no_redirect_or_retry(self):
        for status in [302,307,401,429,500]:
            FakeClient.next_response=FakeResponse(status,[b'PRIVATE_ERROR_OR_REDIRECT'])
            with patch('httpx.AsyncClient',FakeClient): result=await self.call()
            self.assertEqual(result,TransportResponse(status,b''))
        self.assertEqual(len(FakeClient.calls),5)

    async def test_endpoint_and_spend_profile_cannot_be_switched(self):
        with patch('httpx.AsyncClient',FakeClient):
            for change in [{'model':'other'},{'max_completion_tokens':2000},{'tools':[]},
                           {'service_tier':'priority'},{'n':2},{'prediction':{}},{'store':True}]:
                body=self.body.copy();body.update(change)
                with self.assertRaises(ValueError):
                    await self.transport.post_json(endpoint=OPENAI_ENDPOINT,body=body,
                                                    timeout_seconds=.1,max_response_bytes=4096)
            with self.assertRaises(ValueError):
                await self.transport.post_json(endpoint='https://evil.invalid',body=self.body,
                                                timeout_seconds=.1,max_response_bytes=4096)
        self.assertEqual(FakeClient.calls,[])
