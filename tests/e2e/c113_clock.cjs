'use strict';
const c = require('./c113_contract.cjs');
const KEYS = ['mode','label','instance_id','version','scale','real_now','domain_now','real_anchor','domain_anchor','domain_limit','storage','reset_supported','limits'];
const millis = value => Date.parse(value);
function snapshot(s) {
  c.check(s && c.stable(Object.keys(s).sort()) === c.stable([...KEYS].sort()), 'EXACT_CLOCK_FIELDS_REQUIRED');
  c.check(s.mode === 'synthetic_demo' && s.label === 'Синтетическое демо-время' && c.UUID.test(s.instance_id) && s.storage === 'postgres_shared' && s.reset_supported === false, 'DURABLE_SYNTHETIC_CLOCK_REQUIRED');
  c.check(Number.isSafeInteger(s.version) && s.version >= 0 && s.version < 2147483647 && Number.isSafeInteger(s.scale) && s.scale >= 0 && s.scale <= 60, 'BOUNDED_CLOCK_VERSION_SCALE_REQUIRED');
  c.check(c.stable(s.limits) === c.stable({max_scale:60,max_advance_seconds:3600}), 'CLOCK_LIMITS_REQUIRED');
  for (const key of ['real_now','domain_now','real_anchor','domain_anchor','domain_limit']) c.check(typeof s[key] === 'string' && /Z$/.test(s[key]) && Number.isFinite(millis(s[key])), 'UTC_CLOCK_FIELDS_REQUIRED');
  c.check(millis(s.real_now) >= millis(s.real_anchor) && millis(s.domain_now) >= millis(s.domain_anchor) && millis(s.domain_now) <= millis(s.domain_limit), 'CLOCK_ORDER_REQUIRED');
  c.check(Math.abs(millis(s.domain_now) - (millis(s.domain_anchor) + (millis(s.real_now)-millis(s.real_anchor))*s.scale)) <= 2, 'SERVER_CLOCK_MAPPING_REQUIRED');
  return s;
}
function command(before, action) {
  snapshot(before);
  const extra = action === 'pause' ? {action:'set_scale',scale:0} : action === 'advance' ? {action:'advance',seconds:c.ADVANCE_SECONDS} : action === 'resume' ? {action:'set_scale',scale:1} : null;
  c.check(extra, 'EXACT_CLOCK_ACTION_REQUIRED');
  return {instance_id:before.instance_id,expected_version:before.version,...extra};
}
function sameClock(a,b) {
  snapshot(a); snapshot(b);
  c.check(a.instance_id === b.instance_id && a.domain_limit === b.domain_limit && millis(b.real_now) >= millis(a.real_now), 'CLOCK_INSTANCE_AND_REAL_TIME_REQUIRED');
}
function transition(before, after, action) {
  sameClock(before,after);
  c.check(after.version === before.version + 1 && millis(after.real_anchor) === millis(after.real_now) && millis(after.domain_anchor) === millis(after.domain_now), 'CLOCK_MUTATION_RECEIPT_REQUIRED');
  const scale = action === 'pause' ? 0 : action === 'advance' ? 0 : 1;
  c.check(after.scale === scale, 'CLOCK_EFFECT_SCALE_REQUIRED');
  if(action === 'advance') c.check(before.scale === 0 && millis(after.domain_now)-millis(before.domain_now) === c.ADVANCE_SECONDS*1000, 'EXACT_PAUSED_ADVANCE_REQUIRED');
  else if(action === 'resume') c.check(before.scale === 0 && millis(after.domain_now) === millis(before.domain_now), 'RESUME_DOMAIN_CONTINUITY_REQUIRED');
  else c.check(before.scale === 1 && Math.abs(millis(after.domain_now)-millis(before.domain_now)-(millis(after.real_now)-millis(before.real_now))) <= 2, 'PAUSE_DOMAIN_CONTINUITY_REQUIRED');
}
function readAfter(before, after, delay) {
  sameClock(before,after);
  c.check(after.version === before.version && after.scale === before.scale && after.real_anchor === before.real_anchor && after.domain_anchor === before.domain_anchor, 'CLOCK_READ_CANNOT_MUTATE_REQUIRED');
  c.check(millis(after.real_now)-millis(before.real_now) >= delay, 'REAL_WAIT_OBSERVED_REQUIRED');
  if(before.scale === 0) c.check(after.domain_now === before.domain_now, 'PAUSED_DOMAIN_UNCHANGED_REQUIRED');
  else c.check(millis(after.domain_now) > millis(before.domain_now), 'RESUMED_DOMAIN_PROGRESS_REQUIRED');
}
function validateJourney(rows, start, end) {
  c.check(Array.isArray(rows) && rows.length === 6, 'SIX_CLOCK_OBSERVATIONS_REQUIRED');
  const names=['initial','pause','paused_read','advance','resume','resumed_read'];
  rows.forEach((r,i)=>{
    c.check(r.name===names[i] && r.status===200 && r.path==='/api/v1/demo/clock' && r.cache==='private,no-store' && r.vary==='Cookie' && r.ui_snapshot_visible===true && c.HASH.test(r.body_sha256||''), 'CLOCK_UI_RESPONSE_REQUIRED');
    snapshot(r.snapshot);
    c.check(r.body_sha256===c.digest(r.snapshot),'CLOCK_RESPONSE_HASH_REQUIRED');
    c.check(millis(r.snapshot.real_now)>=start-2000 && millis(r.snapshot.real_now)<=end+2000, 'CLOCK_REAL_WINDOW_REQUIRED');
    const mutation=['pause','advance','resume'].includes(r.name);
    c.check(r.method === (mutation?'POST':'GET'), 'CLOCK_METHOD_REQUIRED');
    if(mutation)c.check(c.stable(r.command)===c.stable(command(rows[i-1].snapshot,r.name)), 'CLOCK_CAS_COMMAND_REQUIRED');
    else c.check(r.command===null,'CLOCK_GET_BODY_FORBIDDEN');
  });
  c.check(rows[0].snapshot.version===0 && rows[5].snapshot.version===3 && rows[0].snapshot.scale===1 && millis(rows[0].snapshot.domain_limit)-millis(rows[0].snapshot.domain_now)>120000, 'INITIAL_RUNNING_CLOCK_HORIZON_REQUIRED');
  transition(rows[0].snapshot,rows[1].snapshot,'pause');
  readAfter(rows[1].snapshot,rows[2].snapshot,250);
  transition(rows[2].snapshot,rows[3].snapshot,'advance');
  transition(rows[3].snapshot,rows[4].snapshot,'resume');
  readAfter(rows[4].snapshot,rows[5].snapshot,250);
}
module.exports={snapshot,command,transition,readAfter,validateJourney};
