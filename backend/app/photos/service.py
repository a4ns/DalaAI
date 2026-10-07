"""Same-origin photo staging with durable receipts and current authorization.

Lock order: session/principal -> receipt -> owner quota -> order -> photo.
No image decode inside a database transaction; final publication precedes the
atomic photo+receipt commit. A failed/uncertain commit retains its bounded blob.
"""
from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from app.core.auth_boundary import RequestProtection, SystemRealClock, authenticate_session
from app.core.auth_policy import (AccessDenied, OrderAction, PhotoScope, Role, StagedPhotoScope,
    require_create_order, require_order_access, require_photo_read, require_staged_photo_read)
from app.orders.models import DomainError
from app.orders.validation import uid
from app.persistence.postgres import PostgresPrincipals, PostgresRepository, PostgresSessions, sid
from app.persistence.service import CommandResult, wire

from .validation import PhotoUnavailable, decode_raster, parse_fields, request_hash
from .integrity import PhotoIntegrityVerifier


class _BindingChanged(Exception):
    pass


class PhotoService:
    def __init__(self, connect, *, allowed_origin, private_blob_store, real_clock=None,
                 max_outstanding_stages=20):
        if type(max_outstanding_stages) is not int or not 1 <= max_outstanding_stages <= 100:
            raise ValueError("Bounded outstanding-stage quota required")
        self.connect = connect
        self.protection = RequestProtection(allowed_origin)
        self.store = private_blob_store
        self.integrity = PhotoIntegrityVerifier(private_blob_store)
        self.real_clock = real_clock or SystemRealClock()
        self.max_outstanding_stages = max_outstanding_stages

    def _connection(self):
        from psycopg.rows import dict_row
        db = self.connect()
        if not db.autocommit:
            db.close()
            raise ValueError("PhotoService requires a fresh autocommit connection")
        db.row_factory = dict_row
        return db

    def _auth(self, db, session_handle):
        context = authenticate_session(session_handle, sessions=PostgresSessions(db),
            principals=PostgresPrincipals(db), real_clock=self.real_clock)
        # Frozen authenticate_session samples time before membership reads. A
        # principal read may block; check expiration again after it completes.
        now = self.real_clock.now()
        if not context.session.created_at <= now < context.session.expires_at:
            from app.core.auth_boundary import AuthenticationRequired
            raise AuthenticationRequired()
        return context

    def preflight(self, *, session_handle, origin, csrf_token):
        """Run before accepting the multipart stream; rechecked at final commit."""
        with self._connection() as db, db.transaction():
            context = self._auth(db, session_handle)
            self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)

    def _authorize_request(self, db, context, request, *, lock=False, revision=False):
        if request.purpose == "before":
            require_create_order(context.principal, request.section_id)
            return None
        from app.core.auth_policy import OrderScope
        row = db.execute("SELECT id,section_id,executor_id,assignment_revision FROM orders WHERE id=%s"
            + (" FOR SHARE" if lock else ""), (request.order_id,)).fetchone()
        if row is None:
            raise DomainError("NOT_FOUND", "Order does not exist")
        order = OrderScope(sid(row["id"]), sid(row["section_id"]), sid(row["executor_id"]),
                           row["assignment_revision"])
        if context.principal.role != Role.EXECUTOR or order.section_id != request.section_id:
            raise AccessDenied()
        require_order_access(context.principal, OrderAction.UPLOAD, order)
        if revision and request.assignment_revision != order.assignment_revision:
            raise DomainError("STALE_ASSIGNMENT", "Assignment changed; refresh the order")
        return order

    def _read_locked(self, db, photo_id):
        """Discover first; then order before photo, never invert attachment locks."""
        from app.core.auth_policy import OrderScope
        first = db.execute("SELECT order_id FROM photos WHERE id=%s", (photo_id,)).fetchone()
        if first is None:
            raise DomainError("NOT_FOUND", "Photo does not exist")
        order = None
        if first["order_id"] is not None:
            row = db.execute("SELECT id,section_id,executor_id,assignment_revision FROM orders WHERE id=%s FOR SHARE",
                             (first["order_id"],)).fetchone()
            if row is None:
                raise PhotoUnavailable()
            order = OrderScope(sid(row["id"]), sid(row["section_id"]), sid(row["executor_id"]),
                               row["assignment_revision"])
        photo = db.execute("SELECT * FROM photos WHERE id=%s FOR SHARE", (photo_id,)).fetchone()
        if photo is None:
            raise DomainError("NOT_FOUND", "Photo does not exist")
        if sid(first["order_id"]) != sid(photo["order_id"]):
            # Before-photo just attached between discovery and lock. Release
            # transaction and restart, rather than locking an order after photo.
            raise _BindingChanged()
        return photo, order

    def _authorize_photo(self, context, photo, order):
        principal = context.principal
        if photo["attached_at"] is not None:
            if order is None:
                raise PhotoUnavailable()
            require_photo_read(principal, PhotoScope(sid(photo["id"]), sid(photo["section_id"]),
                sid(photo["order_id"])), order)
        else:
            # Scope/ownership denied before any TTL-specific information.
            if sid(photo["owner_id"]) != principal.user_id or sid(photo["section_id"]) not in principal.section_ids:
                raise AccessDenied()
            if photo["purpose"] == "before":
                require_create_order(principal, sid(photo["section_id"]))
                if order is not None or photo["assignment_revision"] is not None:
                    raise AccessDenied()
            else:
                if (principal.role != Role.EXECUTOR or order is None
                        or sid(photo["order_id"]) != order.order_id
                        or sid(photo["section_id"]) != order.section_id
                        or photo["assignment_revision"] != order.assignment_revision):
                    raise AccessDenied()
                require_order_access(principal, OrderAction.SUBMIT, order)
            if photo["expires_at"] <= self.real_clock.now():
                raise DomainError("PHOTO_EXPIRED", "Staged photo expired")
            require_staged_photo_read(principal, StagedPhotoScope(sid(photo["id"]),
                sid(photo["section_id"]), sid(photo["owner_id"]), photo["expires_at"],
                photo["purpose"], sid(photo["order_id"]), photo["assignment_revision"]),
                real_now=self.real_clock.now(), order=order)
        if photo["file_valid"] is not True:
            raise DomainError("VALIDATION_FAILED", "Photo content is not verified")

    def _replay(self, db, request, digest, receipt, *, session_handle, origin, csrf_token):
        if receipt is None or receipt["committed_at"] is None:
            raise PhotoUnavailable()
        context = self._auth(db, session_handle)
        self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
        self._authorize_request(db, context, request)
        if receipt["canonical_hash"] != digest or receipt["resource_kind"] != "photo":
            raise DomainError("OPERATION_ID_REUSED", "Operation ID already identifies another request")
        photo, order = self._read_locked(db, receipt["resource_id"])
        context = self._auth(db, session_handle)
        self._authorize_request(db, context, request)
        self._authorize_photo(context, photo, order)
        if sid(photo["owner_id"]) != context.principal.user_id:
            raise AccessDenied()
        return CommandResult(receipt["response_status"], receipt["response_body"], True)

    def _probe(self, request, digest, *, session_handle, origin, csrf_token):
        with self._connection() as db, db.transaction():
            db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            context = self._auth(db, session_handle)
            self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
            self._authorize_request(db, context, request)
            receipt = PostgresRepository(db).receipt(context.principal.user_id, request.operation_id)
            if receipt is not None:
                return self._replay(db, request, digest, receipt, session_handle=session_handle,
                                    origin=origin, csrf_token=csrf_token)
        return None

    def stage(self, fields, raw, *, session_handle, origin, csrf_token, declared_mime=None):
        self.preflight(session_handle=session_handle, origin=origin, csrf_token=csrf_token)
        request = parse_fields(fields)
        digest = request_hash(request, raw)
        args = dict(session_handle=session_handle, origin=origin, csrf_token=csrf_token)
        # A before photo can change from staged to attached just once. The retry
        # releases every lock and uses the current binding; it never repeats a put.
        for _ in range(2):
            try:
                replay = self._probe(request, digest, **args)
                break
            except _BindingChanged:
                continue
        else:
            raise PhotoUnavailable()
        if replay is not None:
            return replay
        raster = decode_raster(raw, declared_mime)
        for _ in range(2):
            try:
                return self._commit(request, digest, raster, **args)
            except _BindingChanged:
                continue
        raise PhotoUnavailable()

    def _commit(self, request, digest, raster, *, session_handle, origin, csrf_token):
        with self._connection() as db:
            with db.transaction():
                db.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                context = self._auth(db, session_handle)
                self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
                self._authorize_request(db, context, request)
                repo = PostgresRepository(db)
                receipt = repo.receipt(context.principal.user_id, request.operation_id)
                if receipt is not None:
                    return self._replay(db, request, digest, receipt, session_handle=session_handle,
                                        origin=origin, csrf_token=csrf_token)
                actor = context.principal.user_id
                reserved = db.execute("""INSERT INTO operation_receipts
                    (actor_id,operation_id,canonical_hash,resource_kind,created_at)
                    VALUES (%s,%s,%s,'photo',%s) ON CONFLICT (actor_id,operation_id) DO NOTHING
                    RETURNING actor_id""", (actor, request.operation_id, digest, self.real_clock.now())).fetchone()
                if reserved is None:
                    return self._replay(db, request, digest, repo.receipt(actor, request.operation_id),
                        session_handle=session_handle, origin=origin, csrf_token=csrf_token)
                # A stable signed 64-bit namespace serializes quota for one owner
                # across workers. Hash collisions only conservatively serialize.
                quota_key = int.from_bytes(sha256(("photo-quota:" + actor).encode()).digest()[:8], "big", signed=True)
                db.execute("SELECT pg_advisory_xact_lock(%s)", (quota_key,))
                count = db.execute("SELECT count(*) AS n FROM photos WHERE owner_id=%s AND attached_at IS NULL",
                                   (actor,)).fetchone()["n"]
                if count >= self.max_outstanding_stages:
                    raise DomainError("RATE_LIMITED", "Outstanding photo limit reached")
                self._authorize_request(db, context, request, lock=True, revision=True)
                context = self._auth(db, session_handle)
                self.protection.require_http(context, method="POST", origin=origin, csrf_token=csrf_token)
                self._authorize_request(db, context, request, revision=True)
                storage_key = self.store.put(raster.data)
                # Storage may block too. It cannot confer new authority or TTL.
                context = self._auth(db, session_handle)
                self._authorize_request(db, context, request, revision=True)
                now = self.real_clock.now()
                expires = now + timedelta(hours=24)
                photo_id = str(uuid4())
                db.execute("""INSERT INTO photos (id,owner_id,section_id,purpose,order_id,
                    assignment_revision,storage_key,mime_type,bytes,sha256,uploaded_at,expires_at,
                    exif_removed,file_valid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,true)""",
                    (photo_id, actor, request.section_id, request.purpose, request.order_id,
                     request.assignment_revision, storage_key, raster.mime_type, len(raster.data),
                     raster.sha256, now, expires))
                body = wire(dict(id=photo_id, section_id=request.section_id, purpose=request.purpose,
                    owner_id=actor, order_id=request.order_id, assignment_revision=request.assignment_revision,
                    mime_type=raster.mime_type, bytes=len(raster.data), sha256=raster.sha256,
                    uploaded_at=now, expires_at=expires, exif_removed=True))
                repo.finalize_receipt(actor, request.operation_id, photo_id, 201, body, now)
                result = CommandResult(201, body)
            return result

    def get(self, photo_id, *, session_handle):
        photo_id = uid(photo_id, "photo_id")
        for _ in range(2):
            try:
                with self._connection() as db, db.transaction():
                    context = self._auth(db, session_handle)
                    photo, order = self._read_locked(db, photo_id)
                    context = self._auth(db, session_handle)
                    self._authorize_photo(context, photo, order)
                    data = self.integrity.read(photo)
                    context = self._auth(db, session_handle)
                    self._authorize_photo(context, photo, order)
                    return data, photo["mime_type"]
            except _BindingChanged:
                continue
        raise PhotoUnavailable()
