"""Bounded one-device-per-user subscription storage. No credentials in results."""
from dataclasses import dataclass, field
from uuid import uuid4

from app.orders.models import DomainError
from .validation import SubscriptionInput


@dataclass(frozen=True)
class StoredSubscription:
    employee_id: str
    generation: str
    subscription: SubscriptionInput = field(repr=False)


class PushRepository:
    def __init__(self, db):
        self.db = db

    def register(self, employee_id, session_hash, subscription, *, now):
        # Serialize this user's writes without upgrading the authentication SHARE
        # lock (concurrent SHARE-to-UPDATE upgrades can deadlock).
        self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('push:' || %s,0))", (employee_id,))
        other = self.db.execute('SELECT employee_id FROM push_subscriptions WHERE endpoint_hash=%s',
                               (subscription.endpoint_hash,)).fetchone()
        if other is not None and str(other['employee_id']) != employee_id:
            raise DomainError('SUBSCRIPTION_CONFLICT', 'Unsubscribe in this browser before switching accounts')
        generation = str(uuid4())
        self.db.execute('''INSERT INTO push_subscriptions
            (employee_id,session_hash,endpoint_hash,endpoint,p256dh,auth,expires_at,generation,active,updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,%s)
            ON CONFLICT (employee_id) DO UPDATE SET
            session_hash=EXCLUDED.session_hash,endpoint_hash=EXCLUDED.endpoint_hash,
            endpoint=EXCLUDED.endpoint,p256dh=EXCLUDED.p256dh,auth=EXCLUDED.auth,
            expires_at=EXCLUDED.expires_at,generation=EXCLUDED.generation,active=true,
            updated_at=EXCLUDED.updated_at,last_error_code=NULL''',
            (employee_id,session_hash,subscription.endpoint_hash,subscription.endpoint,
             subscription.p256dh,subscription.auth,subscription.expires_at,generation,now))
        return {'enabled': True}

    def remove(self, employee_id, endpoint_hash, *, now):
        self.db.execute("SELECT pg_advisory_xact_lock(hashtextextended('push:' || %s,0))", (employee_id,))
        self.db.execute('''UPDATE push_subscriptions SET active=false,updated_at=%s,
            last_error_code='USER_DISABLED' WHERE employee_id=%s AND endpoint_hash=%s''',
            (now,employee_id,endpoint_hash))

    def current(self, employee_id, *, now):
        row = self.db.execute('''SELECT p.* FROM push_subscriptions p
            JOIN auth_sessions s ON s.token_hash=p.session_hash AND s.employee_id=p.employee_id
            JOIN employees e ON e.id=p.employee_id
            WHERE p.employee_id=%s AND p.active AND e.active AND s.revoked_at IS NULL
            AND s.created_at<=%s AND s.expires_at>%s
            AND (p.expires_at IS NULL OR p.expires_at>%s)''', (employee_id,now,now,now)).fetchone()
        if row is None:
            return None
        return StoredSubscription(str(row['employee_id']),str(row['generation']),
            SubscriptionInput(row['endpoint'],row['p256dh'],row['auth'],row['expires_at']))

    def deactivate(self, stored, *, now, code):
        if code not in {'PUSH_GONE','PUSH_INVALID_SUBSCRIPTION'}:
            raise ValueError('Sanitized cleanup code required')
        # A late 410 for the prior key/endpoint must never disable a fresh register.
        self.db.execute('''UPDATE push_subscriptions SET active=false,updated_at=%s,last_error_code=%s
            WHERE employee_id=%s AND generation=%s AND endpoint_hash=%s''',
            (now,code,stored.employee_id,stored.generation,stored.subscription.endpoint_hash))
