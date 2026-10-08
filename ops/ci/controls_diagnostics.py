"""Bounded C113 progress and source lines. Raw diagnostic strings never leave here."""
import json
from pathlib import Path
import re

STEPS=('fresh history database corroborated','separate authenticated mobile sessions',
       'master explicitly reads pauses advances and resumes demo clock','master selects canonical historical reports',
       'master saves protected shift PDF and XLSX','master saves protected order PDF and XLSX',
       'executor cannot access clock or exports','business database unchanged')
SOURCES={'c113_download_clock.spec.cjs','c113_contract.cjs','c113_private_boundary.cjs',
         'c113_playwright.config.cjs','c113_preflight_proof.cjs','c113_gate.cjs','c113_clock.cjs','c113_downloads.cjs','c113_inspect_download.py'}
CODES={'COMPLETE_FACTS_REQUIRED','EXACT_ORDER_COUNT_REQUIRED','API_DB_IDENTITIES_MISMATCH',
       'ACTUAL_PHOTO_REFERENCE_COUNT_REQUIRED','OBSERVED_HISTORICAL_ORDER_REQUIRED','ISSUED_METRIC_REQUIRED',
       'ACTUAL_RUNTIME_PROVENANCE_REQUIRED','HISTORICAL_COUNTS_REQUIRED','UNAVAILABLE_PHOTO_PROVENANCE_REQUIRED',
       'SHIFT_REPORT_FACTS_MISMATCH','SELECTED_ORDER_REPORT_MISMATCH','EXECUTOR_RESTRICTION_REQUIRED',
       'BUSINESS_DATABASE_CHANGED','UNEXPECTED_NETWORK_ACTIVITY','SOURCE_CHANGED_DURING_JOURNEY',
       'REAL_RESPONSE_REQUIRED','PROTECTED_RESPONSE_HEADERS_REQUIRED','SERVICE_WORKER_RESPONSE_FORBIDDEN',
       'SEPARATE_SECURE_SESSIONS_REQUIRED','ANDROID_PROJECT_REQUIRED','REVIEWED_SINGLE_RUN_REQUIRED',
       'REVIEWED_REPORTERS_REQUIRED','REVIEWED_CAPTURE_AND_BROWSER_ENV_REQUIRED',
       'DOWNLOAD_CLOCK_JOURNEY_FAILED_SEE_SAFE_STAGE_RESULTS'}
SIGNATURES={
    'PRIVATE_OPERATION_FAILED':'operation failed; private details suppressed',
    'ASSERTION_TIMEOUT':'Timed out',
    'LOCATOR_TIMEOUT':'TimeoutError',
    'ASSERTION_FAILED':'expect(',
    'LOCATOR_STRICT_MODE':'strict mode violation',
    'READONLY_OBSERVER_FAILED':'read-only observer unavailable; details suppressed',
    'PROTECTED_RESPONSE_FAILED':'protected response unavailable; details suppressed',
    'AUTHENTICATED_READ_FAILED':'authenticated read unavailable; details suppressed',
    'MASTER_LOGIN_FAILED':'synthetic master login failed; credential-bearing details suppressed',
    'EXECUTOR_LOGIN_FAILED':'synthetic executor login failed; credential-bearing details suppressed',
}


DOWNLOAD_ENUMS={key:set(value) for key,value in {"target":["NOT_STARTED","SHIFT_PDF","SHIFT_XLSX","ORDER_PDF","ORDER_XLSX","UNCLASSIFIED"],"substep":["NOT_STARTED","OPEN_SHIFT_REPORT","WAIT_SHIFT_REPORT_UI","OPEN_ORDER_REPORT","WAIT_ORDER_REPORT_UI","PREPARE_EXPECTATION","WAIT_PREPARE_RESPONSE","CHECK_PROTECTED_HEADERS","CHECK_EXPORT_MIME","CHECK_EXPORT_DISPOSITION","CHECK_EXPORT_CSP","CHECK_CONTENT_LENGTH","READ_RESPONSE_BYTES","CHECK_RESPONSE_SIZE","WAIT_SAVE_CONTROL","CHECK_NO_EARLY_SAVE","WAIT_SAVE_DOWNLOAD","CHECK_SUGGESTED_FILENAME","WAIT_DOWNLOAD_COMPLETION","SAVE_FILE","CHECK_SAVED_FILE","COMPARE_SAVED_BYTES","WRITE_EXPECTED_VALUES","RUN_INSPECTOR","PARSE_INSPECTOR_RESULT","CHECK_INSPECTOR_BINDING","RECORD_DOWNLOAD","DONE","UNCLASSIFIED"],"inspector":["NOT_RUN","START","READ_EXPECTED_FILE","PARSE_EXPECTED_JSON","READ_SAVED_FILE","EXPECTED_CONTRACT","FILE_BOUND","PDF_XREF","PDF_OBJECTS","PDF_CATALOG_PAGES","PDF_PAGE_SHAPE","PDF_FONT_RESOURCES","PDF_STREAM","PDF_FONT_MAP","PDF_OPERATORS","PDF_VISIBLE_STYLE","PDF_TEXT_DECODE","PDF_CONTENT","XLSX_ARCHIVE","XLSX_ENTRY","XLSX_XML","XLSX_RELATIONSHIPS","XLSX_CELLS","XLSX_CONTENT","RESULT","PASS","PROCESS_FAILED","UNCLASSIFIED"],"response":["NOT_OBSERVED","HTTP_OTHER_OR_UNAVAILABLE","HTTP_OK","HTTP_BAD_REQUEST","HTTP_UNAUTHENTICATED","HTTP_FORBIDDEN","HTTP_NOT_FOUND","HTTP_CONFLICT","HTTP_TOO_LARGE","HTTP_VALIDATION","HTTP_RATE_LIMITED","HTTP_SERVER_ERROR","HTTP_GATEWAY_ERROR","HTTP_UNAVAILABLE","HTTP_GATEWAY_TIMEOUT"],"encoding":["NOT_OBSERVED","IDENTITY","GZIP","ZSTD","BROTLI","OTHER"],"content_length":["NOT_OBSERVED","ABSENT","INVALID","ZERO","TOO_LARGE","POSITIVE_WITHIN_LIMIT"]} .items()}


DOWNLOAD_ENUMS.update({
    'frontend_before_body':{'NOT_OBSERVED','READY','ERROR','LOADING','EXPIRED'},
    'frontend_after_body':{'NOT_OBSERVED','READY','ERROR','LOADING','EXPIRED'},
    'body_failure':{'NOT_OBSERVED','TIMEOUT','BODY_PROTOCOL_FAILURE','BODY_UNAVAILABLE','TARGET_CLOSED','OTHER'},
})


def request_projection(value):
    row=value if isinstance(value,dict) else {}
    completion=row.get('completion')
    return {'completion':completion if isinstance(completion,str) and completion in {'FINISHED','FAILED','NOT_OBSERVED'} else 'NOT_OBSERVED',
            'failure_present':row.get('failure_present') is True}


def download_projection(value):
    if not isinstance(value,dict): return None
    fallbacks={'target':'UNCLASSIFIED','substep':'UNCLASSIFIED','inspector':'UNCLASSIFIED',
               'response':'HTTP_OTHER_OR_UNAVAILABLE','encoding':'OTHER','content_length':'INVALID',
               'frontend_before_body':'NOT_OBSERVED','frontend_after_body':'NOT_OBSERVED','body_failure':'OTHER'}
    result={key:value[key] if isinstance(value.get(key),str) and value[key] in allowed else fallbacks[key]
            for key,allowed in DOWNLOAD_ENUMS.items()}
    for key in ('request_before_body','request_after_body'):
        result[key]=request_projection(value.get(key))
    return result


def failure_projection(report, evidence):
    output={'scope':'diagnostic_only_no_controls_pass','completed_steps':0,'failed_step':None,
            'clock_observations':0,'downloads':0,'restrictions':0,'report':'unavailable','error_classes':[],'source_locations':[]}
    try:
        if evidence.is_file() and not evidence.is_symlink() and evidence.stat().st_size<=4*1024*1024:
            body=json.loads(evidence.read_text())
            phase=download_projection(body.get("download_diagnostic"))
            if phase is not None: output["download_phase"]=phase
            for index,row in enumerate(body.get('steps',[])[:len(STEPS)]):
                if row.get('name')!=STEPS[index]: break
                if row.get('result')=='PASS': output['completed_steps']+=1
                elif row.get('result')=='FAIL': output['failed_step']=index+1; break
            for name,key,maximum in [('clock_observations','clock',6),('downloads','downloads',4),('restrictions','restrictions',6)]:
                output[name]=min(len(body[key]),maximum) if isinstance(body.get(key),list) else 0
    except Exception: pass
    try:
        if not report.is_file() or report.is_symlink() or report.stat().st_size>4*1024*1024: return output
        data=json.loads(report.read_text()); output['report']='present'
        classes=set(); locations=set(); budget=512
        def location(value):
            if not isinstance(value,dict): return
            name=Path(str(value.get('file',''))).name; line=value.get('line')
            if name in SOURCES and type(line) is int and 1<=line<=1000: locations.add((name,line))
        def error(value):
            if not isinstance(value,dict): return
            message=str(value.get('message',''))
            classes.update(name for name,signature in SIGNATURES.items() if signature in message)
            for code in re.findall(r'C113 (?:BLOCKED|FAIL): ([A-Z0-9_]+)',message):
                if code in CODES: classes.add(code)
            location(value.get('location'))
            for name,line in re.findall(r'(c113_[A-Za-z_]+\.(?:spec\.)?cjs):(\d+):\d+',str(value.get('stack',''))):
                if name in SOURCES and 1<=int(line)<=1000: locations.add((name,int(line)))
        def walk(node,depth=0):
            nonlocal budget
            if not isinstance(node,dict) or depth>12 or budget<=0: return
            budget-=1
            errors=node.get('errors',[])
            if isinstance(errors,list):
                for item in errors[:16]: error(item)
            if isinstance(node.get('error'),dict):
                error(node['error']); location(node.get('location'))
            # Deliberately never emit titles, messages, stacks, bodies or attachments.
            for key in ('suites','specs','tests','results','steps'):
                rows=node.get(key,[])
                if isinstance(rows,list):
                    for child in rows[:64]: walk(child,depth+1)
        walk(data)
        output['error_classes']=sorted(classes)
        output['source_locations']=[{'file':name,'line':line} for name,line in sorted(locations)[:12]]
    except Exception: output['report']='projection_incomplete'
    return output


def file_presence(artifact_dir):
    """Eight fixed names inside this invocation's owned artifact folder; no reads."""
    result={}
    for kind in ('shift','order'):
        for format in ('pdf','xlsx'):
            for label,name in [('saved',f'saved-{kind}.{format}'),('expected',f'expected-{kind}-{format}.json')]:
                file=artifact_dir/name
                try: present=not file.is_symlink() and file.is_file()
                except OSError: present=False
                result[f'{kind}_{format}_{label}']=bool(present)
    return result
