"""Durable-worker adapter: provider acceptance never claims device delivery."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math

from app.core.auth_boundary import SystemRealClock
from app.notify.models import DeliveryOutcome
from .transport import BoundedSender, TransportResult
from .validation import endpoint_parts


def payload_for(envelope):
    # Generic lock-screen text and fixed relative URL. No order id, employee,
    # equipment, reason, deadline or work description reaches the push provider.
    # HTTP GET after click performs current session/object authorization.
    return json.dumps({'v':1,'title':'НарядAI','body':'Есть обновление наряда. Откройте приложение.',
                       'url':'/','tag':'naryadai-update'},ensure_ascii=False,separators=(',',':'))


def retry_delay(value, now):
    if not isinstance(value,str) or len(value)>100:
        return 60
    try:
        if value.isascii() and value.isdigit():
            delay = int(value)
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return 60
            delay = math.ceil((date-now).total_seconds())
        # Refuse unrepresentable waits; do not silently shorten provider limits.
        return max(1,delay) if delay<=366*86400 else None
    except (ValueError,OverflowError,TypeError):
        return 60


class WebPushAdapter:
    # 12 sec network child + two 3sec bounded DB operations + margin, <30sec lease.
    max_call_seconds = 22.0

    def __init__(self, *, store, settings, sender=None, real_clock=None):
        self.store, self.settings = store, settings
        self.sender = sender or BoundedSender()
        self.real_clock = real_clock or SystemRealClock()
        if self.sender.max_call_seconds > 12:
            raise ValueError('Sender bound must be at most 12 seconds')

    def send(self, envelope):
        if envelope.channel != 'web_push':
            return DeliveryOutcome('permanent_failure','PUSH_WRONG_CHANNEL')
        if not self.settings.enabled:
            return DeliveryOutcome('permanent_failure','PUSH_DISABLED')
        try:
            stored = self.store.current(envelope.recipient_id,now=self.real_clock.now())
        except Exception:
            return DeliveryOutcome('retryable','PUSH_SUBSCRIPTION_UNAVAILABLE',retry_after_seconds=30)
        if stored is None:
            return DeliveryOutcome('permanent_failure','PUSH_NOT_SUBSCRIBED')
        try:
            endpoint_parts(stored.subscription.endpoint)
        except Exception:
            return DeliveryOutcome('permanent_failure','PUSH_INVALID_SUBSCRIPTION')
        try:
            result = self.sender.send(stored.subscription,payload_for(envelope),self.settings)
        except Exception:
            return DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')
        if not isinstance(result,TransportResult) or result.status is None:
            return DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')
        status = result.status
        if status in (404,410):
            try:
                self.store.deactivate(stored,now=self.real_clock.now(),code='PUSH_GONE')
            except Exception:
                return DeliveryOutcome('permanent_failure','PUSH_GONE_CLEANUP_FAILED')
            return DeliveryOutcome('permanent_failure','PUSH_GONE')
        if 200 <= status <= 202 and result.receipt:
            return DeliveryOutcome('accepted','PUSH_PROVIDER_ACCEPTED',receipt=result.receipt)
        if status == 429:
            delay = retry_delay(result.retry_after,self.real_clock.now())
            if delay is None:
                return DeliveryOutcome('permanent_failure','PUSH_RETRY_DELAY_UNSUPPORTED')
            return DeliveryOutcome('retryable','PUSH_RATE_LIMITED',retry_after_seconds=delay)
        if 500 <= status < 600 or 200 <= status < 300:
            return DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')
        if status in (401,403):
            return DeliveryOutcome('permanent_failure','PUSH_AUTH_CONFIGURATION_REJECTED')
        if 300 <= status < 500:
            return DeliveryOutcome('permanent_failure','PUSH_PROVIDER_REJECTED')
        return DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')


class PostgresPushStore:
    """Fresh bounded DB connection per pre-send read or late-generation cleanup.

    Connection factory MUST have connect_timeout<=2. SQL/lock deadlines are
    narrowed to 1 second, no cross-provider fanout or DB transaction over network.
    """
    def __init__(self, connect):
        self.connect = connect

    def _run(self, method, *args, **kwargs):
        from psycopg.rows import dict_row
        from psycopg.pq import TransactionStatus
        from .postgres import PushRepository
        with self.connect() as db:
            if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
                raise ValueError('Fresh idle autocommit connection required')
            db.row_factory = dict_row
            with db.transaction():
                db.execute("SET LOCAL statement_timeout='1000ms'")
                db.execute("SET LOCAL lock_timeout='1000ms'")
                return getattr(PushRepository(db),method)(*args,**kwargs)

    def current(self, employee_id, *, now):
        return self._run('current',employee_id,now=now)

    def deactivate(self, stored, *, now, code):
        return self._run('deactivate',stored,now=now,code=code)


def _postgres_child(pipe, database_url, schema, settings, envelope):
    """Entire DB/read/encryption/send/cleanup path under parent wall-clock bound."""
    import logging
    import psycopg
    from .transport import send_library
    logging.disable(logging.CRITICAL)

    class InlineSender:
        max_call_seconds = 12
        def send(self, subscription, payload, config):
            return send_library(subscription,payload,config)

    def connect():
        return psycopg.connect(database_url,autocommit=True,connect_timeout=2,
            options=f'-c search_path={schema} -c statement_timeout=1000 -c lock_timeout=1000')
    try:
        result = WebPushAdapter(store=PostgresPushStore(connect),settings=settings,
                                sender=InlineSender()).send(envelope)
    except Exception:
        result = DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')
    try:
        pipe.send(result)
    finally:
        pipe.close()


def _bounded_outcome(target, args, *, seconds):
    import multiprocessing
    import time
    context = multiprocessing.get_context('spawn')
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=target,args=(child,*args),daemon=True)
    start = time.monotonic()
    try:
        process.start()
        child.close()
        if parent.poll(max(0,seconds-1-(time.monotonic()-start))):
            result = parent.recv()
            if isinstance(result,DeliveryOutcome):
                return result
        return DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')
    except Exception:
        return DeliveryOutcome('ambiguous','PUSH_OUTCOME_UNKNOWN')
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join(timeout=0.5)
            if not process.is_alive():
                process.close()


class BoundedPostgresWebPushAdapter:
    """Production seam: hard bound includes DB connect/locks and DNS/send/cleanup.

    The parent's durable dispatch intent must already be committed. Termination
    means ambiguous, never retry: the child may have sent before it was killed.
    Instantiate from trusted settings only; never expose DB/keys through HTTP.
    """
    max_call_seconds = 22.0

    def __init__(self, *, database_url, database_schema='public', settings):
        import re
        if not database_url or re.fullmatch(r'[a-z_][a-z0-9_]{0,62}',database_schema) is None:
            raise ValueError('Invalid Web Push database configuration')
        self._database_url = database_url
        self._schema = database_schema
        self._settings = settings

    def send(self, envelope):
        if not self._settings.enabled:
            return DeliveryOutcome('permanent_failure','PUSH_DISABLED')
        if envelope.channel != 'web_push':
            return DeliveryOutcome('permanent_failure','PUSH_WRONG_CHANNEL')
        return _bounded_outcome(_postgres_child,
            (self._database_url,self._schema,self._settings,envelope),seconds=self.max_call_seconds)
