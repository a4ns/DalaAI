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
const DIAGNOSTIC_TARGETS=Object.freeze(['NOT_STARTED','SHIFT_PDF','SHIFT_XLSX','ORDER_PDF','ORDER_XLSX','UNCLASSIFIED']);
const DIAGNOSTIC_STEPS=Object.freeze(['NOT_STARTED','OPEN_SHIFT_REPORT','WAIT_SHIFT_REPORT_UI','OPEN_ORDER_REPORT','WAIT_ORDER_REPORT_UI',
  'PREPARE_EXPECTATION','WAIT_PREPARE_RESPONSE','CHECK_PROTECTED_HEADERS','CHECK_EXPORT_MIME','CHECK_EXPORT_DISPOSITION','CHECK_EXPORT_CSP',
  'CHECK_CONTENT_LENGTH','READ_RESPONSE_BYTES','CHECK_RESPONSE_SIZE','WAIT_SAVE_CONTROL','CHECK_NO_EARLY_SAVE','WAIT_SAVE_DOWNLOAD',
  'CHECK_SUGGESTED_FILENAME','WAIT_DOWNLOAD_COMPLETION','SAVE_FILE','CHECK_SAVED_FILE','COMPARE_SAVED_BYTES','WRITE_EXPECTED_VALUES',
  'RUN_INSPECTOR','PARSE_INSPECTOR_RESULT','CHECK_INSPECTOR_BINDING','RECORD_DOWNLOAD','DONE','UNCLASSIFIED']);
const INSPECTOR_STAGES=Object.freeze(['NOT_RUN','START','READ_EXPECTED_FILE','PARSE_EXPECTED_JSON','READ_SAVED_FILE','EXPECTED_CONTRACT',
  'FILE_BOUND','PDF_XREF','PDF_OBJECTS','PDF_CATALOG_PAGES','PDF_PAGE_SHAPE','PDF_FONT_RESOURCES','PDF_STREAM','PDF_FONT_MAP',
  'PDF_OPERATORS','PDF_VISIBLE_STYLE','PDF_TEXT_DECODE','PDF_CONTENT','XLSX_ARCHIVE','XLSX_ENTRY','XLSX_XML','XLSX_RELATIONSHIPS',
  'XLSX_CELLS','XLSX_CONTENT','RESULT','PASS','PROCESS_FAILED','UNCLASSIFIED']);
function createDownloadDiagnostic(){return {target:'NOT_STARTED',substep:'NOT_STARTED',response:'NOT_OBSERVED',encoding:'NOT_OBSERVED',content_length:'NOT_OBSERVED',inspector:'NOT_RUN'};}
function downloadCheckpoint(state,label,target){
  state.substep=DIAGNOSTIC_STEPS.includes(label)?label:'UNCLASSIFIED';
  if(target!==undefined)state.target=DIAGNOSTIC_TARGETS.includes(target)?target:'UNCLASSIFIED';
}
function downloadResponse(state,status){
  const categories={200:'HTTP_OK',400:'HTTP_BAD_REQUEST',401:'HTTP_UNAUTHENTICATED',403:'HTTP_FORBIDDEN',404:'HTTP_NOT_FOUND',409:'HTTP_CONFLICT',413:'HTTP_TOO_LARGE',422:'HTTP_VALIDATION',429:'HTTP_RATE_LIMITED',500:'HTTP_SERVER_ERROR',502:'HTTP_GATEWAY_ERROR',503:'HTTP_UNAVAILABLE',504:'HTTP_GATEWAY_TIMEOUT'};
  state.response=Number.isInteger(status)&&Object.hasOwn(categories,status)?categories[status]:'HTTP_OTHER_OR_UNAVAILABLE';
}
function downloadTransport(state,headers){
  const encoding=headers?.['content-encoding'],length=headers?.['content-length'];
  const known={identity:'IDENTITY',gzip:'GZIP',zstd:'ZSTD',br:'BROTLI'};
  state.encoding=encoding===undefined?'IDENTITY':typeof encoding==='string'&&Object.hasOwn(known,encoding.trim().toLowerCase())?known[encoding.trim().toLowerCase()]:'OTHER';
  state.content_length=length===undefined?'ABSENT':typeof length!=='string'||!(/^[0-9]+$/.test(length))?'INVALID':Number(length)===0?'ZERO':Number(length)>c.MAX_DOWNLOAD_BYTES?'TOO_LARGE':'POSITIVE_WITHIN_LIMIT';
}
function inspectorFailure(error){
  try{
    const bytes=error?.stdout;
    if(!(typeof bytes==='string'||Buffer.isBuffer(bytes))||Buffer.byteLength(bytes)>16384)return 'PROCESS_FAILED';
    const row=JSON.parse(bytes.toString());
    if(c.stable(Object.keys(row).sort())!==c.stable(['code','stage','status'])||row.status!=='BLOCKED'||row.code!=='C113_DOWNLOAD_INSPECTION_FAILED'||!INSPECTOR_STAGES.includes(row.stage)||['NOT_RUN','PASS','PROCESS_FAILED','UNCLASSIFIED'].includes(row.stage))return 'PROCESS_FAILED';
    return row.stage;
  }catch{return 'PROCESS_FAILED';}
}
module.exports={MEDIA,expected,filename,pathname,validateInspection,validateDownload,DIAGNOSTIC_TARGETS,DIAGNOSTIC_STEPS,INSPECTOR_STAGES,createDownloadDiagnostic,downloadCheckpoint,downloadResponse,downloadTransport,inspectorFailure};
