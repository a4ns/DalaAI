'use strict';
const c = require('./c113_contract.cjs');
const MEDIA={pdf:'application/pdf',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'};
function expected(kind, selected) {
  const order=kind==='order';
  c.check(kind==='shift'||order,'EXACT_REPORT_KIND_REQUIRED');
  if(order)c.check(c.UUID.test(selected?.order?.id||'') && /^[A-Za-z0-9_-]{1,64}$/.test(String(selected.order.number)), 'OBSERVED_ORDER_REQUIRED');
  const attempts=order?selected.attempts.length:568;
  const photos=order?selected.attempts.reduce((n,a)=>n+a.submission.payload.after_photo_ids.length,0):444;
  return {kind,order_id:order?selected.order.id:null,order_number:order?String(selected.order.number):null,period:c.PERIOD,historical_counts:order?[1,attempts,photos,photos]:[540,568,444,444]};
}
function filename(e, format){c.check(Object.hasOwn(MEDIA,format),'EXACT_FORMAT_REQUIRED');return `naryadai-${e.kind==='shift'?'shift':`order-${e.order_id}`}.${format}`;}
function pathname(e,format){return `/api/v1/reports/${e.kind==='shift'?'shift':`orders/${e.order_id}`}.${format}`;}
function validateInspection(value, expectedValue, format) {
  const keys=['validator','format','bytes','sha256','units','signature_valid','content_valid','synthetic_disclosure','period_matches','scope_matches','historical_disclosure','bounded_structure','expected_sha256'];
  c.check(value && c.stable(Object.keys(value).sort())===c.stable(keys.sort()),'EXACT_INSPECTION_PROJECTION_REQUIRED');
  c.check(value.validator==='c113-generated-subset-v1' && value.format===format && Number.isInteger(value.bytes) && value.bytes>0 && value.bytes<=c.MAX_DOWNLOAD_BYTES && c.HASH.test(value.sha256||'') && value.expected_sha256===c.digest(expectedValue), 'INSPECTION_BINDING_REQUIRED');
  c.check(Number.isInteger(value.units) && value.units>=1 && value.units<=(format==='pdf'?200:20),'BOUNDED_INSPECTION_REQUIRED');
  for(const key of ['signature_valid','content_valid','synthetic_disclosure','period_matches','scope_matches','historical_disclosure','bounded_structure'])c.check(value[key]===true,'COMPLETE_CONTENT_INSPECTION_REQUIRED');
}
function validateDownload(row, e, format) {
  c.check(row && row.kind===e.kind && row.format===format && row.path===pathname(e,format) && row.filename===filename(e,format) && row.status===200 && row.cache==='private,no-store' && row.vary==='Cookie' && row.nosniff===true && row.media===MEDIA[format] && row.csp==="default-src 'none'; sandbox",'PROTECTED_EXPORT_RESPONSE_REQUIRED');
  c.check(row.prepare_via_ui===true && row.save_via_ui===true && row.download_completed===true && row.no_save_before_gesture===true && row.same_response_bytes===true && row.no_network_on_save===true, 'TWO_GESTURE_REAL_DOWNLOAD_REQUIRED');
  validateInspection(row.inspection,e,format);
  c.check(c.HASH.test(row.response_sha256||'') && row.response_sha256===row.saved_sha256 && row.saved_sha256===row.inspection.sha256 && row.bytes===row.inspection.bytes, 'EXACT_DOWNLOADED_BYTES_REQUIRED');
}
module.exports={MEDIA,expected,filename,pathname,validateInspection,validateDownload};
