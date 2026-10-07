"""Explicit shared-clock configuration and schema requirements; no provisioning."""
from .clock import DemoClockSettings, DemoClockUnavailable
from .postgres import PostgresDemoBusinessClock, instance_uuid

# Existing synthetic identity, shared by minimal and historical fixtures.
# Never accept an arbitrary request-supplied operator or grant an account role.
DEMO_MASTER_ID = '8d27067c-4e86-50a2-87c4-f1012f53a2bb'
STATE_COLUMNS = ('instance_id','synthetic','version','real_anchor','domain_anchor',
                 'domain_start','domain_limit','scale')
CONTROL_COLUMNS = ('instance_id','version','actor_id','action','recorded_at',
                   'previous_scale','scale','domain_anchor','advance_seconds')
STATE_UPDATES = ('version','real_anchor','domain_anchor','scale')
GUARDS = {('demo_clock_state','demo_clock_state_guard'),
          ('demo_clock_state','demo_clock_audit_at_commit'),
          ('demo_clock_controls','demo_clock_audit_immutable')}


def validate_settings(enabled, instance_id, mode):
    if type(enabled) is not bool:
        raise ValueError('Explicit demo clock flag required')
    if enabled:
        if mode != 'demo':
            raise ValueError('Business clock requires isolated demo mode')
        instance_uuid(instance_id)
    elif instance_id:
        raise ValueError('Configured clock instance cannot silently use wall time')


def verify_state(db, instance_id):
    """One singleton and one fresh DB real sample; no mutation or fallback."""
    instance_uuid(instance_id)
    rows = db.execute('SELECT *,clock_timestamp() AS sampled_at FROM demo_clock_state').fetchall()
    if len(rows) != 1 or str(rows[0]['instance_id']) != instance_id or rows[0]['synthetic'] is not True:
        raise DemoClockUnavailable('Exact configured clock singleton is required')
    mapping = PostgresDemoBusinessClock(None,
        settings=DemoClockSettings(enabled=True,mode='demo',isolated_demo=True), instance_id=instance_id)
    mapping._snapshot(rows[0],rows[0]['sampled_at'])
    guarded = db.execute("""SELECT tgdeferrable AND tginitdeferred AS ok
        FROM pg_trigger WHERE tgrelid='demo_clock_state'::regclass
        AND tgname='demo_clock_audit_at_commit' AND tgenabled IN ('O','A')""").fetchone()
    if not guarded or guarded['ok'] is not True:
        raise DemoClockUnavailable('Deferred clock audit guard is required')
