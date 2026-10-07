"""Explicit demo runtime configuration and fail-closed database prerequisites."""
from dataclasses import dataclass, field
import os
import re

from app.core.auth_boundary import RequestProtection


@dataclass(frozen=True)
class RuntimeSettings:
    mode: str = 'health'
    database_url: str = field(default='', repr=False)
    allowed_origin: str = ''
    database_schema: str = 'public'
    photo_storage_root: str = ''
    photo_max_total_bytes: int = 1024 * 1024 * 1024
    notification_enabled: bool = False
    push_enabled: bool = False
    delivery_channel: str = 'synthetic'
    demo_clock_enabled: bool = False
    demo_clock_instance_id: str = ''

    def __post_init__(self):
        from pathlib import Path
        from app.demo_clock.runtime import validate_settings
        validate_settings(self.demo_clock_enabled,self.demo_clock_instance_id,self.mode)
        if any(type(v) is not bool for v in (self.notification_enabled, self.push_enabled)):
            raise ValueError('Runtime capabilities must be explicit booleans')
        if self.delivery_channel not in {'synthetic', 'web_push', 'telegram'}:
            raise ValueError('Unsupported delivery channel')
        if self.notification_enabled != (self.delivery_channel != 'synthetic'):
            raise ValueError('Notification capability and delivery channel must match')
        if not isinstance(self.photo_storage_root,str) or (self.photo_storage_root and not Path(self.photo_storage_root).is_absolute()):
            raise ValueError('Private photo storage must be an absolute path')
        if type(self.photo_max_total_bytes) is not int or not 8388608 <= self.photo_max_total_bytes <= 10737418240:
            raise ValueError('Photo capacity must be bounded between 8MiB and 10GiB')
        if self.mode not in {'health', 'demo'}:
            raise ValueError('DALA_API_MODE must be health or demo')
        if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', self.database_schema):
            raise ValueError('Invalid configured database schema')
        if self.mode == 'demo':
            if not isinstance(self.database_url, str) or not self.database_url.strip():
                raise ValueError('Demo API requires DATABASE_URL')
            RequestProtection(self.allowed_origin)

    @classmethod
    def from_env(cls):
        def flag(name):
            value = os.environ.get(name, 'false')
            if value not in {'true', 'false'}:
                raise ValueError('Invalid runtime capability flag')
            return value == 'true'
        return cls(mode=os.environ.get('DALA_API_MODE', 'health'),
                   database_url=os.environ.get('DATABASE_URL', ''),
                   allowed_origin=os.environ.get('DALA_ALLOWED_ORIGIN', ''),
                   database_schema=os.environ.get('DALA_DATABASE_SCHEMA', 'public'),
                   photo_storage_root=os.environ.get('DALA_PHOTO_STORAGE_ROOT',''),
                   photo_max_total_bytes=int(os.environ.get('DALA_PHOTO_MAX_TOTAL_BYTES',str(1024*1024*1024))),
                   notification_enabled=flag('DALA_NOTIFICATION_CAPABILITY'),
                   push_enabled=flag('DALA_PUSH_CAPABILITY'),
                   delivery_channel=os.environ.get('DALA_DELIVERY_CHANNEL', 'synthetic'),
                   demo_clock_enabled=flag('DALA_DEMO_CLOCK_ENABLED'),
                   demo_clock_instance_id=os.environ.get('DALA_DEMO_CLOCK_INSTANCE_ID',''))


def connection_factory(settings):
    import psycopg
    from psycopg.rows import dict_row
    def connect():
        return psycopg.connect(settings.database_url, autocommit=True, connect_timeout=3,
            options=f'-c search_path={settings.database_schema} -c statement_timeout=10000 -c lock_timeout=5000',
            row_factory=dict_row)
    return connect


# The checks establish installed schema prerequisites, not migration application.
TABLE_COLUMNS = {
    'sections': ('id','code','label'), 'brigades': ('id','section_id'),
    'employees': ('id','employee_code','role','active','on_shift','pin_hash'),
    'employee_sections': ('employee_id','section_id'),
    'auth_sessions': ('id','employee_id','token_hash','csrf_token','expires_at','revoked_at'),
    'auth_login_limits': ('kind','bucket','window_started_at','attempts'),
    'equipment': ('id','section_id'), 'work_codes': ('id',), 'materials': ('id',),
    'orders': ('id','number','version','assignment_revision','scheduling_revision','current_submission_id'),
    'submissions': ('id','order_id','after_photo_ids'),
    'photos': ('id','section_id','order_id','submission_id','file_valid','attached_at'),
    'material_writeoffs': ('submission_id','material_id','quantity'),
    'ai_assessments': ('id','submission_id'), 'reviews': ('id','submission_id'),
    'order_events': ('id','order_id','sequence'),
    'operation_receipts': ('operation_id','committed_at','response_body'),
    'ai_jobs': ('id','submission_id'), 'delivery_jobs': ('id','order_id'),
}
REQUIRED_TRIGGERS = {
    ('auth_sessions','auth_sessions_identity_immutable'),
    ('employees','employees_identity_immutable'),
    ('employee_sections','employee_sections_ownership_immutable'),
    ('equipment','equipment_identity_immutable'), ('brigades','brigades_identity_immutable'),
    ('work_codes','work_codes_identity_immutable'), ('materials','materials_identity_immutable'),
    ('photos','attached_photo_binding_immutable'),
    ('operation_receipts','committed_receipt_immutable'),
    ('operation_receipts','receipt_complete_at_commit'),
    ('order_events','order_events_immutable'), ('submissions','submissions_immutable'),
    ('ai_assessments','assessments_immutable'), ('reviews','reviews_immutable'),
    ('material_writeoffs','material_writeoffs_immutable'),
}
INSERT_TABLES = ('auth_sessions','auth_login_limits','orders','operation_receipts','submissions',
                 'material_writeoffs','reviews','order_events','ai_jobs','delivery_jobs')
UPDATE_COLUMNS = {
    'orders': ('version','status','updated_at'), 'delivery_jobs': ('state',),
    'operation_receipts': ('resource_id','response_status','response_body','committed_at'),
    'photos': ('order_id','submission_id','attached_at'),
    'auth_sessions': ('id','revoked_at'), 'employees': ('id',),
    'employee_sections': ('employee_id',), 'equipment': ('id',), 'brigades': ('id',),
    'work_codes': ('id',), 'materials': ('id',),
    'auth_login_limits': ('window_started_at','attempts'),
}
FORBIDDEN_UPDATES = {'employees': ('role','active','pin_hash'),
    'auth_sessions': ('employee_id','token_hash','csrf_token'), 'photos': ('file_valid',)}


class RuntimePrerequisiteError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__('Runtime database prerequisites failed')


def validate_database(connect, *, photo_enabled=False, push_enabled=False, notification_enabled=False,
                      demo_clock_enabled=False, demo_clock_instance_id=""):
    """No grants, seeds, migrations or external calls. Never include DSN in errors."""
    from psycopg import sql
    from psycopg.rows import dict_row
    if any(type(v) is not bool for v in (photo_enabled, push_enabled, notification_enabled, demo_clock_enabled)):
        raise RuntimePrerequisiteError('INVALID_RUNTIME_CAPABILITY')
    insert_tables = (*INSERT_TABLES, 'photos') if photo_enabled else INSERT_TABLES
    table_columns = dict(TABLE_COLUMNS)
    required_triggers = set(REQUIRED_TRIGGERS)
    update_columns = dict(UPDATE_COLUMNS)
    if notification_enabled:
        table_columns.update(delivery_dispatches=('lease_token','job_id'),
                             delivery_dispatch_results=('lease_token','outcome'))
        table_columns['ai_jobs'] += ('lease_token',)
        table_columns['delivery_jobs'] += ('lease_token',)
        required_triggers |= {('delivery_dispatches','delivery_dispatches_immutable'),
                              ('delivery_dispatch_results','delivery_dispatch_results_immutable')}
        update_columns['delivery_jobs'] = ('state','attempts','next_attempt_at','lease_until','last_error_code')
    if push_enabled:
        table_columns['push_subscriptions'] = ('employee_id','session_hash','endpoint_hash','endpoint','p256dh','auth',
            'expires_at','generation','active','updated_at','last_error_code')
        update_columns['push_subscriptions'] = table_columns['push_subscriptions'][1:]
        insert_tables = (*insert_tables, 'push_subscriptions')
        required_triggers.add(('push_subscriptions','push_subscription_owner_immutable'))
    if demo_clock_enabled:
        from app.demo_clock.runtime import STATE_COLUMNS, CONTROL_COLUMNS, STATE_UPDATES, GUARDS
        table_columns.update(demo_clock_state=STATE_COLUMNS,demo_clock_controls=CONTROL_COLUMNS)
        update_columns['demo_clock_state'] = STATE_UPDATES
        insert_tables = (*insert_tables,'demo_clock_controls')
        required_triggers |= GUARDS
    try:
        with connect() as db:
            if not db.autocommit:
                raise RuntimePrerequisiteError('CONNECTION_MODE')
            db.row_factory = dict_row
            who = db.execute('''SELECT current_user=session_user AS direct_login,
                rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,
                has_schema_privilege(current_schema(),'CREATE') AS can_create
                FROM pg_roles WHERE rolname=current_user''').fetchone()
            if not who or not who['direct_login'] or any(who[k] for k in who if k != 'direct_login'):
                raise RuntimePrerequisiteError('ROLE_NOT_RESTRICTED')
            owns = db.execute('''SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND pg_has_role(current_user,c.relowner,'MEMBER')) AS owns''').fetchone()
            if owns['owns']:
                raise RuntimePrerequisiteError('ROLE_OWNS_OBJECTS')
            for table, columns in table_columns.items():
                db.execute(sql.SQL('SELECT {} FROM {} LIMIT 0').format(
                    sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table)))
            found = db.execute('''SELECT c.relname,t.tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND t.tgenabled IN ('O','A')
                UNION ALL SELECT 'demo_clock_state','__installed__'
                WHERE to_regclass('demo_clock_state') IS NOT NULL''').fetchall()
            if ('demo_clock_state','__installed__') in {(r['relname'],r['tgname']) for r in found} and not demo_clock_enabled:
                raise RuntimePrerequisiteError('DEMO_CLOCK_CAPABILITY_REQUIRED')
            if not required_triggers <= {(r['relname'],r['tgname']) for r in found}:
                raise RuntimePrerequisiteError('REQUIRED_GUARD_MISSING')
            if demo_clock_enabled:
                from app.demo_clock.runtime import verify_state
                verify_state(db,demo_clock_instance_id)
            for table in table_columns:
                if demo_clock_enabled and table in {'demo_clock_state','demo_clock_controls'}:
                    for privilege in ('REFERENCES','SELECT WITH GRANT OPTION','INSERT WITH GRANT OPTION','UPDATE WITH GRANT OPTION'):
                        if db.execute('SELECT has_table_privilege(%s,%s) AS ok',(table,privilege)).fetchone()['ok']:
                            raise RuntimePrerequisiteError('FORBIDDEN_GRANT')
                    clock_columns = db.execute("SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped",(table,)).fetchall()
                    for column in clock_columns:
                        for privilege in ('REFERENCES','SELECT WITH GRANT OPTION','INSERT WITH GRANT OPTION','UPDATE WITH GRANT OPTION','REFERENCES WITH GRANT OPTION'):
                            if db.execute('SELECT has_column_privilege(%s,%s,%s) AS ok',(table,column['attname'],privilege)).fetchone()['ok']:
                                raise RuntimePrerequisiteError('FORBIDDEN_GRANT')
                for privilege in ('DELETE','TRUNCATE','TRIGGER'):
                    if db.execute('SELECT has_table_privilege(%s,%s) AS ok',(table,privilege)).fetchone()['ok']:
                        raise RuntimePrerequisiteError('FORBIDDEN_GRANT')
                if table not in insert_tables and db.execute("SELECT has_table_privilege(%s,'INSERT') AS ok",(table,)).fetchone()['ok']:
                    raise RuntimePrerequisiteError('FORBIDDEN_GRANT')
                if table != 'orders' and (table != 'delivery_jobs' or notification_enabled):
                    columns = db.execute("SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass AND attnum>0 AND NOT attisdropped",(table,)).fetchall()
                    for column in columns:
                        name = column['attname']
                        if name not in update_columns.get(table, ()) and db.execute("SELECT has_column_privilege(%s,%s,'UPDATE') AS ok",(table,name)).fetchone()['ok']:
                            raise RuntimePrerequisiteError('FORBIDDEN_GRANT')
            for table in insert_tables:
                if not db.execute("SELECT has_table_privilege(%s,'INSERT') AS ok",(table,)).fetchone()['ok']:
                    raise RuntimePrerequisiteError('REQUIRED_GRANT_MISSING')
            for table, columns in update_columns.items():
                for column in columns:
                    if not db.execute("SELECT has_column_privilege(%s,%s,'UPDATE') AS ok",(table,column)).fetchone()['ok']:
                        raise RuntimePrerequisiteError('REQUIRED_GRANT_MISSING')
            for table, columns in FORBIDDEN_UPDATES.items():
                for column in columns:
                    if db.execute("SELECT has_column_privilege(%s,%s,'UPDATE') AS ok",(table,column)).fetchone()['ok']:
                        raise RuntimePrerequisiteError('FORBIDDEN_GRANT')
            if not db.execute("SELECT has_sequence_privilege(pg_get_serial_sequence('orders','number'),'USAGE') AS ok").fetchone()['ok']:
                raise RuntimePrerequisiteError('REQUIRED_GRANT_MISSING')
    except RuntimePrerequisiteError:
        raise
    except Exception:
        raise RuntimePrerequisiteError('DATABASE_UNAVAILABLE_OR_SCHEMA_MISSING') from None


from dataclasses import replace
from app.persistence.postgres import PostgresReferences


class UnavailablePhotoReferences(PostgresReferences):
    """Fail closed while physical private-blob validation is unavailable.

    DB-bound checks still execute under transaction locks. A persisted boolean
    alone never establishes current physical blob integrity. A reviewed photo
    adapter must replace this explicit unavailable boundary.
    """
    def closure_evidence(self, submission):
        codes, materials, photos = super().closure_evidence(submission)
        return codes, materials, tuple(replace(photo,file_valid=None) for photo in photos)
