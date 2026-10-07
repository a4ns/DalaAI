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

    def __post_init__(self):
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
        return cls(mode=os.environ.get('DALA_API_MODE', 'health'),
                   database_url=os.environ.get('DATABASE_URL', ''),
                   allowed_origin=os.environ.get('DALA_ALLOWED_ORIGIN', ''),
                   database_schema=os.environ.get('DALA_DATABASE_SCHEMA', 'public'))


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


def validate_database(connect):
    """No grants, seeds, migrations or external calls. Never include DSN in errors."""
    from psycopg import sql
    from psycopg.rows import dict_row
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
            for table, columns in TABLE_COLUMNS.items():
                db.execute(sql.SQL('SELECT {} FROM {} LIMIT 0').format(
                    sql.SQL(',').join(map(sql.Identifier,columns)),sql.Identifier(table)))
            found = db.execute('''SELECT c.relname,t.tgname FROM pg_trigger t
                JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname=current_schema() AND t.tgenabled IN ('O','A')''').fetchall()
            if not REQUIRED_TRIGGERS <= {(r['relname'],r['tgname']) for r in found}:
                raise RuntimePrerequisiteError('REQUIRED_GUARD_MISSING')
            for table in INSERT_TABLES:
                if not db.execute("SELECT has_table_privilege(%s,'INSERT') AS ok",(table,)).fetchone()['ok']:
                    raise RuntimePrerequisiteError('REQUIRED_GRANT_MISSING')
            for table, columns in UPDATE_COLUMNS.items():
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
