"""Explicit single-process durable worker. Importing is inert; no credential creation.

Run with ``python -m app.worker_runtime``. The API process never imports this to
start background activity. All SQL grants are rendered separately for operators.
"""
from dataclasses import dataclass, field
from functools import partial
import asyncio
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import threading
import time


class WorkerConfigurationError(ValueError):
    pass


class WorkerPrerequisiteError(RuntimeError):
    """Fixed code only; connection strings and provider errors never escape."""
    def __init__(self, code):
        self.code = code
        super().__init__('Worker database prerequisites failed')


def _flag(env, name, default='false'):
    value = env.get(name, default)
    if value not in ('true', 'false'):
        raise WorkerConfigurationError('WORKER_INVALID_FLAG')
    return value == 'true'


def _read_file(path, cap):
    """Bounded operator-mounted regular file, never an HTTP-supplied path."""
    try:
        if not Path(path).is_absolute():
            raise ValueError()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
                raise ValueError()
            raw = stream.read(cap + 1)
        if len(raw) > cap:
            raise ValueError()
        return raw.decode('utf-8').strip()
    except (OSError, ValueError, TypeError, UnicodeError):
        raise WorkerConfigurationError('WORKER_MOUNTED_FILE_INVALID') from None


def _secret(env, name, *, cap=16384):
    value, file = env.get(name, ''), env.get(name + '_FILE', '')
    if value and file:
        raise WorkerConfigurationError('WORKER_DUPLICATE_SECRET_SOURCE')
    return _read_file(file, cap) if file else value


@dataclass(frozen=True)
class WorkerSettings:
    enabled: bool = False
    ai_enabled: bool = True
    notify_enabled: bool = False
    channel: str = 'web_push'
    telegram_enabled: bool = False
    model_force_off: bool = False
    runtime_mode: str = 'health'
    demo_clock_enabled: bool = False
    demo_clock_instance_id: str = ''
    database_url: str = field(default='', repr=False)
    database_schema: str = 'public'
    photo_storage_root: str = ''
    photo_max_total_bytes: int = 1073741824
    tick_seconds: float = 1.0
    tick_admission_seconds: float = 25.0
    ai_limit: int = 1
    reconcile_limit: int = 25
    dispatch_limit: int = 1
    max_consecutive_errors: int = 5

    def __post_init__(self):
        from app.demo_clock.runtime import validate_settings
        try:
            validate_settings(self.demo_clock_enabled,self.demo_clock_instance_id,self.runtime_mode)
        except ValueError:
            raise WorkerConfigurationError('WORKER_DEMO_CLOCK_CONFIG_INVALID') from None
        for name in ('enabled', 'ai_enabled', 'notify_enabled', 'telegram_enabled', 'model_force_off'):
            if type(getattr(self, name)) is not bool:
                raise WorkerConfigurationError('WORKER_INVALID_FLAG')
        if self.channel not in {'web_push', 'telegram'}:
            raise WorkerConfigurationError('WORKER_INVALID_CHANNEL')
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', self.database_schema):
            raise WorkerConfigurationError('WORKER_INVALID_SCHEMA')
        if self.enabled and not self.database_url.strip():
            raise WorkerConfigurationError('WORKER_DATABASE_URL_REQUIRED')
        if self.enabled and not (self.ai_enabled or self.notify_enabled):
            raise WorkerConfigurationError('WORKER_NO_LANES_ENABLED')
        if self.notify_enabled and self.channel == 'telegram' and not self.telegram_enabled:
            raise WorkerConfigurationError('WORKER_TELEGRAM_OPT_IN_REQUIRED')
        if self.runtime_mode not in {'health', 'demo'}:
            raise WorkerConfigurationError('WORKER_RUNTIME_MODE_INVALID')
        if self.photo_storage_root and not Path(self.photo_storage_root).is_absolute():
            raise WorkerConfigurationError('WORKER_ABSOLUTE_PHOTO_ROOT_REQUIRED')
        if type(self.photo_max_total_bytes) is not int or not 8388608 <= self.photo_max_total_bytes <= 10737418240:
            raise WorkerConfigurationError('WORKER_PHOTO_CAPACITY_INVALID')
        for name, minimum, maximum in (('tick_seconds', .1, 60), ('tick_admission_seconds', 1, 60)):
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or not minimum <= value <= maximum:
                raise WorkerConfigurationError('WORKER_TICK_BOUND_INVALID')
        for name, maximum in (('ai_limit', 20), ('reconcile_limit', 1000), ('dispatch_limit', 20), ('max_consecutive_errors', 20)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= maximum:
                raise WorkerConfigurationError('WORKER_BATCH_BOUND_INVALID')

    @classmethod
    def from_env(cls, environment=None):
        env = os.environ if environment is None else environment
        enabled = _flag(env, 'DALA_WORKER_ENABLED')
        # Disabled startup neither reads mounted secrets nor opens a database.
        if not enabled:
            return cls()
        try:
            return cls(enabled=True,
                ai_enabled=_flag(env, 'DALA_WORKER_AI_ENABLED', 'true'),
                notify_enabled=_flag(env, 'DALA_WORKER_NOTIFY_ENABLED'),
                channel=env.get('DALA_WORKER_CHANNEL', 'web_push'),
                telegram_enabled=_flag(env, 'DALA_WORKER_TELEGRAM_ENABLED'),
                model_force_off=_flag(env, 'DALA_MODEL_FORCE_OFF'),
                runtime_mode=env.get('DALA_API_MODE', 'health'),
                demo_clock_enabled=_flag(env,'DALA_DEMO_CLOCK_ENABLED'),
                demo_clock_instance_id=env.get('DALA_DEMO_CLOCK_INSTANCE_ID',''),
                database_url=_secret(env, 'DALA_WORKER_DATABASE_URL'),
                database_schema=env.get('DALA_DATABASE_SCHEMA', 'public'),
                photo_storage_root=env.get('DALA_PHOTO_STORAGE_ROOT', ''),
                photo_max_total_bytes=int(env.get('DALA_PHOTO_MAX_TOTAL_BYTES', '1073741824')),
                tick_seconds=float(env.get('DALA_WORKER_TICK_SECONDS', '1')),
                tick_admission_seconds=float(env.get('DALA_WORKER_TICK_ADMISSION_SECONDS', '25')),
                ai_limit=int(env.get('DALA_WORKER_AI_LIMIT', '1')),
                reconcile_limit=int(env.get('DALA_WORKER_RECONCILE_LIMIT', '25')),
                dispatch_limit=int(env.get('DALA_WORKER_DISPATCH_LIMIT', '1')),
                max_consecutive_errors=int(env.get('DALA_WORKER_MAX_CONSECUTIVE_ERRORS', '5')))
        except WorkerConfigurationError:
            raise
        except (TypeError, ValueError):
            raise WorkerConfigurationError('WORKER_INVALID_ENVIRONMENT') from None


def connection_factory(settings):
    import psycopg
    from psycopg.rows import dict_row
    def connect():
        return psycopg.connect(settings.database_url, autocommit=True, connect_timeout=2,
            options=f'-c search_path={settings.database_schema} -c statement_timeout=2000 -c lock_timeout=1000',
            row_factory=dict_row)
    return connect


# '*' is restricted to tables whose frozen SQL currently performs SELECT *.
# No sequence, login-token write, PIN/hash, human decision or photo-validity grant.
def worker_grants(*, ai_enabled=True, notify_enabled=True, web_push=False):
    if any(type(v) is not bool for v in (ai_enabled, notify_enabled, web_push)) or not (ai_enabled or notify_enabled):
        raise WorkerConfigurationError('WORKER_INVALID_PROFILE')
    if web_push and not notify_enabled:
        raise WorkerConfigurationError('WORKER_INVALID_PROFILE')
    reads = {'orders': '*', 'photos': '*' if ai_enabled else ('id', 'order_id', 'purpose', 'attached_at')}
    inserts, updates = set(), {}
    if ai_enabled:
        reads.update({'ai_jobs': '*', 'submissions': '*',
            'material_writeoffs': ('submission_id', 'material_id', 'quantity'),
            'work_codes': ('id',), 'materials': ('id',),
            'order_events': ('order_id', 'sequence')})
        inserts.update(('ai_assessments', 'order_events'))
        updates.update({'orders': ('version', 'updated_at'),
            'ai_jobs': ('state', 'attempts', 'next_attempt_at', 'lease_until', 'lease_token', 'last_error_code'),
            'work_codes': ('id',), 'materials': ('id',), 'photos': ('exif_removed',)})
    if notify_enabled:
        reads.update({'employees': ('id', 'role', 'active'),
            'employee_sections': ('employee_id', 'section_id'),
            'order_events': ('order_id', 'sequence', 'kind', 'assignment_revision', 'occurred_at'),
            'delivery_jobs': '*', 'delivery_dispatches': '*',
            'delivery_dispatch_results': ('lease_token',),
            'reviews': ('submission_id', 'created_at')})
        if not ai_enabled:
            reads['submissions'] = ('id', 'submitted_at')
        inserts.update(('delivery_jobs', 'delivery_dispatches', 'delivery_dispatch_results'))
        updates.update({'employees': ('id',), 'employee_sections': ('employee_id',),
            'delivery_jobs': ('state', 'attempts', 'next_attempt_at', 'lease_until', 'lease_token',
                              'last_error_code', 'provider_receipt', 'sent_at')})
        updates.setdefault('orders', ('version',))  # FOR UPDATE needs a column privilege.
    if web_push:
        reads.update({'push_subscriptions': '*',
            'auth_sessions': ('token_hash', 'employee_id', 'created_at', 'expires_at', 'revoked_at')})
        updates['push_subscriptions'] = ('active', 'updated_at', 'last_error_code')
    return {'select': reads, 'insert': tuple(sorted(inserts)), 'update': updates}



_REQUIRED_COLUMNS = {
    'orders': 'id number version assignment_revision scheduling_revision status type description section_id equipment_id executor_id brigade_id created_by issued_at due_at norm_minutes priority comment current_submission_id updated_at',
    'photos': 'id owner_id section_id purpose order_id assignment_revision submission_id storage_key mime_type bytes sha256 uploaded_at expires_at attached_at exif_removed file_valid',
    'submissions': 'id order_id assignment_revision attempt_number submitted_by submitted_at done_late work_description work_code_id comment completeness missing_evidence after_photo_ids',
    'ai_jobs': 'id submission_id assignment_revision state attempts next_attempt_at lease_until last_error_code created_at lease_token',
    'ai_assessments': 'id submission_id assignment_revision mode schema_version model model_version duration_ms recommendation score reasons evidence_ids fallback_reason stale created_at',
    'order_events': 'id order_id sequence order_version assignment_revision scheduling_revision kind reason details actor_id operation_id from_status to_status submission_id occurred_at recorded_at',
    'delivery_jobs': 'id order_id assignment_revision scheduling_revision kind recipient_id channel bucket due_at state attempts next_attempt_at lease_until sent_at provider_receipt last_error_code lease_token',
    'delivery_dispatches': 'lease_token job_id attempt_number started_at',
    'delivery_dispatch_results': 'lease_token outcome error_code provider_receipt retry_after_seconds observed_at',
    'push_subscriptions': 'employee_id session_hash endpoint_hash endpoint p256dh auth expires_at generation active updated_at last_error_code',
}


_COMMON_GUARDS = {('photos', 'attached_photo_binding_immutable'),
    ('submissions', 'submissions_immutable'), ('order_events', 'order_events_immutable')}
_AI_GUARDS = {('ai_assessments', 'assessments_immutable'), ('material_writeoffs', 'material_writeoffs_immutable'),
    ('work_codes', 'work_codes_identity_immutable'), ('materials', 'materials_identity_immutable')}
_NOTIFY_GUARDS = {('employees', 'employees_identity_immutable'),
    ('employee_sections', 'employee_sections_ownership_immutable'), ('reviews', 'reviews_immutable'),
    ('delivery_dispatches', 'delivery_dispatches_immutable'),
    ('delivery_dispatch_results', 'delivery_dispatch_results_immutable')}


def validate_database(connect, *, ai_enabled=True, notify_enabled=True, web_push=False,
                      demo_clock_enabled=False, demo_clock_instance_id=""):
    """Read-only capability gate, including inherited grants; never applies SQL."""
    from psycopg import sql
    from psycopg.pq import TransactionStatus
    from psycopg.rows import dict_row
    grants = worker_grants(ai_enabled=ai_enabled, notify_enabled=notify_enabled, web_push=web_push)
    if type(demo_clock_enabled) is not bool:
        raise WorkerPrerequisiteError('WORKER_CLOCK_CAPABILITY_INVALID')
    if demo_clock_enabled:
        grants['select']['demo_clock_state'] = '*'
    required = set(grants['select']) | set(grants['insert']) | set(grants['update'])
    guards = _COMMON_GUARDS | (_AI_GUARDS if ai_enabled else set()) | (_NOTIFY_GUARDS if notify_enabled else set())
    if demo_clock_enabled:
        from app.demo_clock.runtime import GUARDS
        guards |= GUARDS
    if web_push:
        guards |= {('push_subscriptions', 'push_subscription_owner_immutable')}
    try:
        with connect() as db:
            if not db.autocommit or db.info.transaction_status != TransactionStatus.IDLE:
                raise WorkerPrerequisiteError('WORKER_CONNECTION_MODE')
            db.row_factory = dict_row
            row = db.execute('''SELECT current_user=session_user AS direct_login,
                has_schema_privilege(current_schema(),'CREATE') AS can_create,
                EXISTS (SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER')
                    AND (r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolbypassrls)) AS elevated,
                EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname=current_schema() AND pg_has_role(current_user,c.relowner,'MEMBER')) AS owns''').fetchone()
            if not row or not row['direct_login'] or any(row[k] for k in ('can_create', 'elevated', 'owns')):
                raise WorkerPrerequisiteError('WORKER_ROLE_NOT_RESTRICTED')
            found = db.execute('''SELECT c.relname,t.tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND t.tgenabled IN ('O','A')''').fetchall()
            if not guards <= {(r['relname'], r['tgname']) for r in found}:
                raise WorkerPrerequisiteError('WORKER_REQUIRED_GUARD_MISSING')
            if ai_enabled:
                # UPDATE(exif_removed) is a lock-only privilege: NOT NULL and
                # the validated CHECK permit only its existing boolean TRUE.
                safe = db.execute('''SELECT a.attnotnull AND a.atttypid='boolean'::regtype
                    AND EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conrelid=a.attrelid
                    AND c.contype='c' AND c.convalidated AND pg_get_constraintdef(c.oid)='CHECK (exif_removed)') AS ok
                    FROM pg_attribute a WHERE a.attrelid='photos'::regclass AND a.attname='exif_removed' ''').fetchone()
                if not safe or not safe['ok']:
                    raise WorkerPrerequisiteError('WORKER_PHOTO_LOCK_GUARD_MISSING')
            tables = db.execute('''SELECT c.relname,c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND c.relkind IN ('r','p','v','m','f')''').fetchall()
            if not required <= {r['relname'] for r in tables}:
                raise WorkerPrerequisiteError('WORKER_SCHEMA_MISSING')
            if any(r['relname']=='demo_clock_state' for r in tables) and not demo_clock_enabled:
                raise WorkerPrerequisiteError('WORKER_DEMO_CLOCK_CAPABILITY_REQUIRED')
            if demo_clock_enabled:
                from app.demo_clock.runtime import verify_state
                verify_state(db,demo_clock_instance_id)
            for table in tables:
                name, oid = table['relname'], table['oid']
                for privilege in ('DELETE', 'TRUNCATE', 'TRIGGER', 'REFERENCES'):
                    if db.execute('SELECT has_table_privilege(%s,%s) AS ok', (oid, privilege)).fetchone()['ok']:
                        raise WorkerPrerequisiteError('WORKER_FORBIDDEN_GRANT')
                if db.execute("SELECT has_table_privilege(%s,'INSERT') AS ok", (oid,)).fetchone()['ok'] != (name in grants['insert']):
                    raise WorkerPrerequisiteError('WORKER_INSERT_GRANT_MISMATCH')
                columns = db.execute('''SELECT attname FROM pg_attribute
                    WHERE attrelid=%s AND attnum>0 AND NOT attisdropped''', (oid,)).fetchall()
                if name in required and not set(_REQUIRED_COLUMNS.get(name, '').split()) <= {c['attname'] for c in columns}:
                    raise WorkerPrerequisiteError('WORKER_SCHEMA_COLUMNS_MISSING')
                allowed_select = grants['select'].get(name, ())
                allowed_update = grants['update'].get(name, ())
                for column in columns:
                    col = column['attname']
                    for privilege, expected in (('SELECT', allowed_select == '*' or col in allowed_select),
                                                 ('UPDATE', col in allowed_update),
                                                 ('INSERT', name in grants['insert']), ('REFERENCES', False),
                                                 ('SELECT WITH GRANT OPTION', False),
                                                 ('INSERT WITH GRANT OPTION', False),
                                                 ('UPDATE WITH GRANT OPTION', False)):
                        actual = db.execute('SELECT has_column_privilege(%s,%s,%s) AS ok',
                                            (oid, col, privilege)).fetchone()['ok']
                        if actual != expected:
                            raise WorkerPrerequisiteError('WORKER_COLUMN_GRANT_MISMATCH')
                if allowed_select:
                    selection = sql.SQL('*') if allowed_select == '*' else sql.SQL(',').join(map(sql.Identifier, allowed_select))
                    db.execute(sql.SQL('SELECT {} FROM {} LIMIT 0').format(selection, sql.Identifier(name)))
            sequences = db.execute('''SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND c.relkind='S' ''').fetchall()
            for sequence in sequences:
                for privilege in ('USAGE', 'SELECT', 'UPDATE'):
                    if db.execute('SELECT has_sequence_privilege(%s,%s) AS ok',
                                  (sequence['oid'], privilege)).fetchone()['ok']:
                        raise WorkerPrerequisiteError('WORKER_FORBIDDEN_SEQUENCE_GRANT')
            # Required mutable lease columns are not inferred from a mere table.
            for table, columns in grants['update'].items():
                db.execute(sql.SQL('SELECT {} FROM {} LIMIT 0').format(
                    sql.SQL(',').join(map(sql.Identifier, columns)), sql.Identifier(table)))
    except WorkerPrerequisiteError:
        raise
    except Exception:
        raise WorkerPrerequisiteError('WORKER_DATABASE_UNAVAILABLE_OR_SCHEMA_MISSING') from None


def build_model_adapter(environment, real_clock, *, runtime_mode):
    """Key-only activation AFTER normal named-demo policy/bootstrap configuration.

    A key cannot authorize another project/instance, production data or an expired
    policy. No per-order manifest is generated or required for the interactive demo.
    """
    from app.ai.model_adapter import ModelAdapter, DemoProjectContext, strict_json
    from app.ai.openai_runtime import OpenAIHTTPTransport, openai_demo_budget, openai_demo_settings
    from app.ai.model_budget import SqliteBudgetLedger
    from app.ai.demo_policy import load_interactive_demo_policy
    key = _secret(environment, 'OPENAI_API_KEY', cap=4096)
    if not key:
        return None, 'rules_fallback', None
    if runtime_mode != 'demo':
        raise WorkerConfigurationError('WORKER_MODEL_DEMO_MODE_REQUIRED')
    settings = openai_demo_settings()
    path = environment.get('DALA_MODEL_APPROVAL_FILE', '')
    ledger_path = environment.get('DALA_MODEL_BUDGET_PATH', '')
    try:
        project = DemoProjectContext(environment.get('DALA_MODEL_PROJECT_ID', ''),
                                     environment.get('DALA_MODEL_INSTANCE_ID', ''))
        if not path or not Path(path).is_absolute():
            raise ValueError()
        # Same A4 strict JSON reader, using the already bounded/no-follow read.
        # Reopening the path here would lose the validated inode guarantee.
        policy = strict_json(_read_file(path, 1048576), cap=1048576)
        if not ledger_path or not Path(ledger_path).is_absolute() or not Path(ledger_path).parent.is_dir():
            raise ValueError()
        ledger = SqliteBudgetLedger(ledger_path, openai_demo_budget())
        approval = load_interactive_demo_policy(policy, settings=settings, ledger=ledger,
            project_context=project, runtime_mode=runtime_mode)
        if approval.expires_at <= real_clock.now():
            raise ValueError()
        adapter = ModelAdapter(settings=settings, transport=OpenAIHTTPTransport(key),
                               approval=approval, ledger=ledger)
    except Exception:
        raise WorkerConfigurationError('WORKER_MODEL_POLICY_OR_BUDGET_INVALID') from None
    return adapter, 'openai_authorized_demo_policy', project


@dataclass
class WorkerRuntime:
    settings: WorkerSettings
    assessment: object = None
    reconciler: object = None
    dispatcher: object = None
    ai_mode: str = 'disabled'
    notification_state: str = 'disabled'
    monotonic: object = time.monotonic
    _after_id: str | None = None
    _rotation: int = 0

    async def tick(self, *, stop):
        """No overlap/prefetch. Admission time is not a promise to kill in-flight SQL.

        Reconciliation pages are ONE order so backpressure/shutdown is checked
        between orders; provider adapters separately bound the current call.
        Rotate first lane for fairness when a preceding unit exhausts the budget.
        """
        remaining = {'reconcile': self.settings.reconcile_limit if self.reconciler else 0,
                     'dispatch': self.settings.dispatch_limit if self.dispatcher else 0,
                     'ai': self.settings.ai_limit if self.assessment else 0}
        counts = {'reconciled_orders': 0, 'due_intents': 0, 'dispatch_states': {}, 'ai_states': {}}
        order = ('reconcile', 'dispatch', 'ai')
        order = order[self._rotation:] + order[:self._rotation]
        self._rotation = (self._rotation + 1) % 3
        deadline = self.monotonic() + self.settings.tick_admission_seconds
        while any(remaining.values()):
            for lane in order:
                if stop.is_set() or self.monotonic() >= deadline:
                    return counts
                if not remaining[lane]:
                    continue
                remaining[lane] -= 1
                if lane == 'reconcile':
                    page = self.reconciler.scan_once(limit=1, after_id=self._after_id)
                    self._after_id = page.next_after_id
                    counts['reconciled_orders'] += len(page.results)
                    counts['due_intents'] += sum(r.due_intents for r in page.results)
                    if self._after_id is None:
                        remaining[lane] = 0  # Do not rescan this sweep in one tick.
                else:
                    worker = self.dispatcher if lane == 'dispatch' else self.assessment
                    result = worker.run_once()
                    if hasattr(result, '__await__'):
                        result = await result
                    allowed = {'idle', 'done', 'exhausted', 'failed', 'retry', 'lost_lease', 'cancelled',
                               'already_started', 'unconfirmed', 'provider_accepted', 'synthetic_recorded'}
                    if result.state not in allowed:
                        raise RuntimeError('WORKER_INVALID_RESULT_STATE')
                    if result.state == 'idle':
                        remaining[lane] = 0
                    else:
                        states = counts['dispatch_states' if lane == 'dispatch' else 'ai_states']
                        states[result.state] = states.get(result.state, 0) + 1
        return counts


def build_runtime(settings, *, environment=None, connect=None):
    """Explicit assembly only. Security and domain clocks are separate wall clocks.

    Optional shared business time never replaces security, budget or lease time.
    """
    if not settings.enabled:
        raise WorkerConfigurationError('WORKER_EXPLICIT_ENABLE_REQUIRED')
    env = os.environ if environment is None else environment
    from app.core.auth_boundary import SystemRealClock
    from app.jobs.worker import AssessmentWorker
    from app.jobs.evidence import UnverifiedPhysicalReferences
    connector = connect or connection_factory(settings)
    real_clock, domain_clock = SystemRealClock(), SystemRealClock()
    if settings.demo_clock_enabled:
        from app.demo_clock.clock import DemoClockSettings
        from app.demo_clock.postgres import build_domain_clock
        domain_clock = build_domain_clock(DemoClockSettings(enabled=True,mode='demo',isolated_demo=True),
            connect=connector,instance_id=settings.demo_clock_instance_id)
    runtime = WorkerRuntime(settings)
    adapter = None
    if settings.notify_enabled:
        if settings.channel == 'web_push':
            from app.push.settings import PushSettings
            from app.push.adapter import BoundedPostgresWebPushAdapter
            enabled = _flag(env, 'DALA_WEB_PUSH_ENABLED')
            if enabled:
                push = PushSettings(enabled=True, public_key=env.get('DALA_VAPID_PUBLIC_KEY', ''),
                    private_key=_secret(env, 'DALA_VAPID_PRIVATE_KEY'), subject=env.get('DALA_VAPID_SUBJECT', ''))
                adapter = BoundedPostgresWebPushAdapter(database_url=settings.database_url,
                    database_schema=settings.database_schema, settings=push)
            runtime.notification_state = 'configured_web_push' if adapter else 'paused_web_push_disabled'
        else:
            from app.notifications.telegram import TelegramAdapter, TelegramConfig
            config_env = dict(env)
            if config_env.get('TELEGRAM_MODE', 'disabled') == 'live':
                config_env['TELEGRAM_BOT_TOKEN'] = _secret(env, 'TELEGRAM_BOT_TOKEN')
            config = TelegramConfig.from_environment(config_env)
            if config.mode == 'live':
                adapter = TelegramAdapter(config)
            runtime.notification_state = 'configured_telegram' if adapter else 'paused_telegram_not_live'
    active_notify = adapter is not None
    # A disabled provider never reconciles or claims jobs to mark them failed.
    if not (settings.ai_enabled or active_notify):
        raise WorkerConfigurationError('WORKER_NO_CONFIGURED_LANES')
    clock_options = dict(demo_clock_enabled=True,demo_clock_instance_id=settings.demo_clock_instance_id) if settings.demo_clock_enabled else {}
    validate_database(connector, ai_enabled=settings.ai_enabled, notify_enabled=settings.notify_enabled,
                      web_push=settings.notify_enabled and settings.channel == 'web_push', **clock_options)
    references = UnverifiedPhysicalReferences
    verifier = None
    if settings.ai_enabled and settings.photo_storage_root:
        from app.photos.storage import PrivateFileStore
        from app.photos.integrity import PhotoIntegrityVerifier
        from app.integration.photo_evidence import VerifiedPhotoReferences
        store = PrivateFileStore(settings.photo_storage_root, max_total_bytes=settings.photo_max_total_bytes)
        verifier = PhotoIntegrityVerifier(store)
        references = partial(VerifiedPhotoReferences, verifier=verifier)
    if settings.ai_enabled:
        model, runtime.ai_mode, project = (None, 'rules_fallback_forced_off', None) if settings.model_force_off else \
            build_model_adapter(env, real_clock, runtime_mode=settings.runtime_mode)
        if model is not None:
            from app.jobs.provider_worker import ProviderAssessmentWorker, CameraAssetsFactory
            if verifier is None:
                raise WorkerConfigurationError('WORKER_VERIFIED_PHOTO_ROOT_REQUIRED')
            runtime.assessment = ProviderAssessmentWorker(connector, adapter=model,
                domain_clock=domain_clock, real_clock=real_clock, references_factory=references,
                assets_factory=CameraAssetsFactory(verifier.read), demo_project=project)
        else:
            runtime.assessment = AssessmentWorker(connector, domain_clock=domain_clock,
                real_clock=real_clock, references_factory=references)
    if active_notify:
        from app.notify.reconcile import DeadlineReconciler
        from app.notify.worker import DeliveryWorker
        runtime.reconciler = DeadlineReconciler(connector, channel=settings.channel,
            domain_clock=domain_clock, real_clock=real_clock)
        runtime.dispatcher = DeliveryWorker(connector, adapter=adapter, channel=settings.channel,
            domain_clock=domain_clock, real_clock=real_clock)
    return runtime


def emit(event):
    print(json.dumps(event, sort_keys=True, separators=(',', ':')), flush=True)


def run(runtime, *, stop, output=emit):
    consecutive_errors = 0
    while not stop.is_set():
        try:
            counts = asyncio.run(runtime.tick(stop=stop))
            consecutive_errors = 0
            if any(counts.values()):
                output({'state': 'tick', **counts})
        except Exception:
            consecutive_errors += 1
            output({'state': 'tick_failed', 'code': 'WORKER_TICK_ERROR', 'consecutive_errors': consecutive_errors})
            if consecutive_errors >= runtime.settings.max_consecutive_errors:
                return 1
        # Always pause, even on a full batch or error: no catch-up/busy loop.
        stop.wait(min(60.0, runtime.settings.tick_seconds * 2 ** min(consecutive_errors, 6)))
    output({'state': 'stopped'})
    return 0


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='Explicit durable worker; never provisions credentials or schema')
    parser.add_argument('--check', action='store_true', help='Validate and assemble only; no job claims/provider calls')
    args = parser.parse_args(argv)
    try:
        settings = WorkerSettings.from_env()
        if not settings.enabled:
            emit({'state': 'disabled'})
            return 2 if args.check else 0
        runtime = build_runtime(settings)
        emit({'state': 'ready', 'ai_mode': runtime.ai_mode, 'notifications': runtime.notification_state,
              'device_delivery': 'unverified', 'clock_mode': 'wall_utc'})
        if args.check:
            return 0
        stop = threading.Event()
        previous = {}
        try:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, lambda *_: stop.set())
            return run(runtime, stop=stop)
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    except WorkerPrerequisiteError as exc:
        emit({'state': 'startup_failed', 'code': exc.code})
        return 2
    except Exception:
        emit({'state': 'startup_failed', 'code': 'WORKER_CONFIGURATION_OR_DEPENDENCY_ERROR'})
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
