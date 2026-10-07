"""Local-only: fake HTTP, real standards crypto, ephemeral in-memory test keys."""
from base64 import urlsafe_b64encode
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import socket
import time
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from app.orders.models import DomainError
from app.notify.models import DeliveryEnvelope, DeliveryOutcome
from app.push.adapter import WebPushAdapter, BoundedPostgresWebPushAdapter, payload_for, retry_delay, _bounded_outcome
from app.push.postgres import StoredSubscription
from app.push.settings import PushSettings
from app.push.transport import TransportResult, PinnedSession, send_library
from app.push.validation import parse_subscription, parse_removal, endpoint_parts, public_addresses

NOW = datetime(2026,10,7,20,tzinfo=timezone.utc)
ENDPOINT = 'https://fcm.googleapis.com/fcm/send/synthetic-test-token'


def b64(raw):
    return urlsafe_b64encode(raw).decode().rstrip('=')


def fixture():
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    # Ephemeral, in-memory test-only key material; never written/configured live.
    recipient = ec.generate_private_key(ec.SECP256R1())
    vapid = ec.generate_private_key(ec.SECP256R1())
    public = lambda k:b64(k.public_key().public_bytes(Encoding.X962,PublicFormat.UncompressedPoint))
    settings = PushSettings(True,public(vapid),b64(vapid.private_numbers().private_value.to_bytes(32,'big')),'mailto:test@example.com')
    body = {'endpoint':ENDPOINT,'keys':{'p256dh':public(recipient),'auth':b64(b'synthetic-auth16')}}
    return recipient,settings,body


def sleepy_child(pipe):
    time.sleep(30)


class PushValidationTests(unittest.TestCase):
    def setUp(self):
        self.recipient,self.settings,self.body = fixture()

    def parse(self, body=None):
        return parse_subscription(json.dumps(body or self.body).encode(),now=NOW)

    def test_valid_subscription_and_null_expiry(self):
        self.assertEqual(self.parse().endpoint,ENDPOINT)
        self.body['expirationTime'] = None
        self.assertIsNone(self.parse().expires_at)
        self.body['expirationTime'] = (NOW+timedelta(days=1)).timestamp()*1000
        self.assertEqual(self.parse().expires_at,NOW+timedelta(days=1))
        self.assertNotIn(ENDPOINT,repr(self.parse()))
        self.assertNotIn(self.settings.private_key,repr(self.settings))

    def test_forbidden_endpoints(self):
        for endpoint in ['http://fcm.googleapis.com/fcm/send/abcdefgh',
                'https://localhost/fcm/send/abcdefgh','https://127.0.0.1/fcm/send/abcdefgh',
                'https://[::1]/fcm/send/abcdefgh','https://fcm.googleapis.com.evil.test/fcm/send/abcdefgh',
                'https://user@fcm.googleapis.com/fcm/send/abcdefgh',
                'https://fcm.googleapis.com:444/fcm/send/abcdefgh','https://fcm.googleapis.com:443/fcm/send/abcdefgh',
                ENDPOINT+'?x=1',ENDPOINT+'#x',ENDPOINT+'?',ENDPOINT+'#',
                ENDPOINT+'\n','https://FCM.GOOGLEAPIS.COM/fcm/send/abcdefgh',
                'https://fcm.googleapis.com/fcm/send/../secret','https://fcm.googleapis.com/fcm/send/%61bcdefgh',
                'https://fcm.googleapis.com/other/abcdefgh','https://web.push.apple.com/abcdefgh']:
            with self.subTest(endpoint=endpoint), self.assertRaises(DomainError):
                endpoint_parts(endpoint)

    def test_provider_families(self):
        for endpoint in [ENDPOINT,'https://fcm.googleapis.com/wp/abcdefgh',
                         'https://updates.push.services.mozilla.com/wpush/v2/abcdefgh']:
            self.assertEqual(endpoint_parts(endpoint).scheme,'https')

    def test_dns_rejects_any_nonpublic_answer(self):
        answer = lambda ip:(socket.AF_INET6 if ':' in ip else socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))
        for ip in ('127.0.0.1','10.0.0.1','169.254.169.254','192.168.1.1','0.0.0.0','::1','fe80::1','::ffff:8.8.8.8','224.0.0.1'):
            with self.subTest(ip=ip),self.assertRaises(DomainError):
                public_addresses('fcm.googleapis.com',resolver=lambda *a,**k:[answer('8.8.8.8'),answer(ip)])
        self.assertEqual(public_addresses('fcm.googleapis.com',resolver=lambda *a,**k:[answer('8.8.8.8')]),('8.8.8.8',))

    def test_strict_body_keys_and_expiry(self):
        cases = [dict(self.body,user_id=str(uuid4())),dict(self.body,expirationTime=0),
                 dict(self.body,expirationTime=True),dict(self.body,expirationTime=float('nan')),
                 dict(self.body,expirationTime=NOW.timestamp()*1000),dict(self.body,keys={'p256dh':'a','auth':'b'})]
        for body in cases:
            with self.assertRaises(DomainError):
                self.parse(body)
        for body in (b'[]',b'{}',b'{"endpoint":"a","endpoint":"b"}',b'{"x":NaN}',b'{}'*3000):
            with self.assertRaises(DomainError):
                parse_subscription(body,now=NOW)
        self.body['keys']['p256dh'] = b64(b'\x04'+b'\x00'*64)
        with self.assertRaises(DomainError):
            self.parse()

    def test_key_pair_mismatch_fail_closed(self):
        _,other,_ = fixture()
        with self.assertRaisesRegex(ValueError,'VAPID'):
            replace(self.settings,public_key=other.public_key)
        self.assertEqual(PushSettings().public_config()['application_server_key'],None)
        for subject in ('mailto:demo\nOTHER_SETTING=synthetic@example.com','mailto:test @example.com','mailto:test\r@example.com'):
            with self.assertRaises(ValueError):
                replace(self.settings,subject=subject)


class PushDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.recipient,self.settings,self.body = fixture()
        self.stored = StoredSubscription(str(uuid4()),str(uuid4()),parse_subscription(json.dumps(self.body).encode(),now=NOW))
        self.store = Mock()
        self.store.current.return_value = self.stored
        self.sender = Mock(max_call_seconds=1)
        self.clock = Mock()
        self.clock.now.return_value = NOW
        self.adapter = WebPushAdapter(store=self.store,settings=self.settings,sender=self.sender,real_clock=self.clock)
        self.envelope = DeliveryEnvelope(str(uuid4()),str(uuid4()),self.stored.employee_id,'new_order',channel='web_push')

    def send(self, status=None, **kwargs):
        self.sender.send.return_value = TransportResult(status,**kwargs)
        return self.adapter.send(self.envelope)

    def test_acceptance_not_delivery_and_minimal_payload(self):
        result = self.send(201,receipt='webpush:synthetic')
        self.assertEqual(result.state,'accepted')
        self.assertEqual(result.code,'PUSH_PROVIDER_ACCEPTED')
        payload = json.loads(self.sender.send.call_args.args[1])
        self.assertEqual(set(payload),{'v','title','body','url','tag'})
        self.assertEqual(payload['url'],'/')
        self.assertNotIn(self.envelope.order_id,json.dumps(payload))
        self.assertNotIn(self.envelope.recipient_id,json.dumps(payload))

    def test_gone_cleanup_uses_generation(self):
        for status in (404,410):
            self.assertEqual(self.send(status).code,'PUSH_GONE')
            self.store.deactivate.assert_called_with(self.stored,now=NOW,code='PUSH_GONE')
        self.store.deactivate.side_effect = RuntimeError('PRIVATE')
        self.assertEqual(self.send(410).code,'PUSH_GONE_CLEANUP_FAILED')

    def test_ambiguous_is_not_retried(self):
        for status in (None,500,502,503,204):
            self.assertEqual(self.send(status).state,'ambiguous')
        self.sender.send.side_effect = TimeoutError('PRIVATE')
        result = self.adapter.send(self.envelope)
        self.assertEqual(result.state,'ambiguous')
        self.assertNotIn('PRIVATE',repr(result))

    def test_rate_limit_honors_delay(self):
        result = self.send(429,retry_after='7200')
        self.assertEqual((result.state,result.retry_after_seconds),('retryable',7200))
        self.assertEqual(retry_delay('Wed, 07 Oct 2026 21:00:00 GMT',NOW),3600)
        self.assertEqual(retry_delay('nonsense',NOW),60)
        self.assertEqual(self.send(429,retry_after='999999999999999').state,'permanent_failure')

    def test_auth_redirect_and_other_rejections(self):
        for status in (301,302,307,400,401,403,413):
            self.assertEqual(self.send(status).state,'permanent_failure')
        self.store.deactivate.assert_not_called()

    def test_disabled_and_no_subscription_never_send(self):
        self.adapter.settings = PushSettings()
        self.assertEqual(self.adapter.send(self.envelope).code,'PUSH_DISABLED')
        self.sender.send.assert_not_called()
        self.store.current.assert_not_called()
        self.adapter.settings = self.settings
        self.store.current.return_value = None
        self.assertEqual(self.adapter.send(self.envelope).code,'PUSH_NOT_SUBSCRIBED')
        self.sender.send.assert_not_called()

    def test_real_crypto_round_trip_over_fake_network(self):
        import requests
        import http_ece
        session = Mock()
        response = requests.Response()
        response.status_code = 201
        response._content = b''
        response.headers = {'Location':'https://provider.test/capability-private'}
        session.post.return_value = response
        result = send_library(self.stored.subscription,payload_for(self.envelope),self.settings,session=session)
        call = session.post.call_args
        encrypted = call.kwargs['data']
        plaintext = http_ece.decrypt(encrypted,private_key=self.recipient,auth_secret=b'synthetic-auth16',version='aes128gcm')
        self.assertEqual(plaintext.decode(),payload_for(self.envelope))
        self.assertIn('vapid ',call.kwargs['headers']['Authorization'])
        self.assertEqual(call.kwargs['headers']['content-encoding'],'aes128gcm')
        self.assertEqual(result.status,201)
        self.assertNotIn('capability',result.receipt)
        self.assertNotIn(self.settings.private_key,repr(call.kwargs))

    def test_pinned_https_no_redirect_or_proxy_and_no_body_read(self):
        response = Mock(status=201,headers={'location':'secret','retry-after':'600','Other':'private'})
        pool = Mock()
        pool.urlopen.return_value = response
        factory = Mock(return_value=pool)
        resolver = Mock(return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))])
        session = PinnedSession(ENDPOINT,resolver=resolver,pool_factory=factory)
        result = session.post(ENDPOINT,data=b'encrypted',headers={'Host':'evil'},timeout=8)
        self.assertEqual(factory.call_args.args,('8.8.8.8',))
        self.assertEqual(factory.call_args.kwargs['assert_hostname'],'fcm.googleapis.com')
        self.assertEqual(factory.call_args.kwargs['server_hostname'],'fcm.googleapis.com')
        self.assertEqual(factory.call_args.kwargs['cert_reqs'],'CERT_REQUIRED')
        kwargs = pool.urlopen.call_args.kwargs
        self.assertFalse(kwargs['redirect'])
        self.assertFalse(kwargs['retries'])
        self.assertFalse(kwargs['preload_content'])
        self.assertEqual(kwargs['headers']['Host'],'fcm.googleapis.com')
        self.assertEqual(result.content,b'')
        self.assertEqual(result.headers.get('Retry-After'),'600')
        self.assertEqual(result.headers.get('Location'),'secret')
        response.close.assert_called_once()
        pool.close.assert_called_once()

    def test_process_bound_terminates_hung_child_without_network(self):
        start = time.monotonic()
        result = _bounded_outcome(sleepy_child,(),seconds=1.5)
        self.assertEqual(result.state,'ambiguous')
        self.assertLess(time.monotonic()-start,2.5)

    def test_production_disabled_never_spawns(self):
        adapter = BoundedPostgresWebPushAdapter(database_url='synthetic-not-connected',settings=PushSettings())
        with patch('app.push.adapter._bounded_outcome') as spawned:
            self.assertEqual(adapter.send(self.envelope).code,'PUSH_DISABLED')
            spawned.assert_not_called()


if __name__ == '__main__':
    unittest.main()
