/** Actual optional GET/POST /demo/clock contract. CAS control has no operation receipt. */
import { awareInstant } from './analyticsProtocol';
export interface DemoClockSnapshot {
  mode:'synthetic_demo';label:'Синтетическое демо-время';instance_id:string;version:number;scale:number;
  real_now:string;domain_now:string;real_anchor:string;domain_anchor:string;domain_limit:string;
  storage:'postgres_shared'|'ephemeral_single_process';reset_supported:false;
  limits:{max_scale:60;max_advance_seconds:3600};
}
export type DemoClockChange={action:'set_scale';scale:number}|{action:'advance';seconds:number};
export type DemoClockControl=DemoClockChange&{instance_id:string;expected_version:number};
const obj=(v:unknown):v is Record<string,unknown>=>Boolean(v&&typeof v==='object'&&!Array.isArray(v));
const integer=(v:unknown,min:number,max:number):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=min&&v<=max;
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/.test(v);
export function isDemoClockSnapshot(v:unknown):v is DemoClockSnapshot {
  if(!obj(v)||v.mode!=='synthetic_demo'||v.label!=='Синтетическое демо-время'||!uuid(v.instance_id)||!integer(v.version,0,2147483647)||!integer(v.scale,0,60)||v.reset_supported!==false||(v.storage!=='postgres_shared'&&v.storage!=='ephemeral_single_process')||!obj(v.limits)||v.limits.max_scale!==60||v.limits.max_advance_seconds!==3600)return false;
  if(!['real_now','domain_now','real_anchor','domain_anchor','domain_limit'].every(key=>awareInstant(v[key])))return false;
  return Date.parse(v.real_now as string)>=Date.parse(v.real_anchor as string)&&Date.parse(v.domain_now as string)>=Date.parse(v.domain_anchor as string)&&Date.parse(v.domain_now as string)<=Date.parse(v.domain_limit as string);
}
export function isDemoClockChange(v:unknown):v is DemoClockChange {
  if(!obj(v))return false;const field=v.action==='set_scale'?'scale':v.action==='advance'?'seconds':null;
  return field!==null&&Object.keys(v).length===2&&Object.keys(v).every(key=>['action',field].includes(key))&&integer(v[field],field==='scale'?0:1,field==='scale'?60:3600);
}
export function isDemoClockControl(v:unknown):v is DemoClockControl {
  if(!obj(v)||!uuid(v.instance_id)||!integer(v.expected_version,0,2147483647))return false;
  const field=v.action==='set_scale'?'scale':v.action==='advance'?'seconds':null;
  return field!==null&&Object.keys(v).length===4&&Object.keys(v).every(key=>['instance_id','expected_version','action',field].includes(key))&&integer(v[field],field==='scale'?0:1,field==='scale'?60:3600);
}
/** Reads may advance computed time without a version bump. A receipt never rolls back a newer read. */
export function mergeDemoClock(current:DemoClockSnapshot|null,incoming:DemoClockSnapshot):DemoClockSnapshot {
  if(!current||current.instance_id!==incoming.instance_id)return incoming;
  if(incoming.version<current.version)return current;
  if(incoming.version===current.version&&Date.parse(incoming.real_now)<Date.parse(current.real_now))return current;
  return incoming;
}
