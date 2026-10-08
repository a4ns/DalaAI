"""Bounded C112 progress and source lines. Raw diagnostic strings never leave here."""
import json
from pathlib import Path
import re

STEPS=('fresh history database corroborated','separate authenticated mobile sessions',
       'master loads canonical historical analytics','master opens protected shift report',
       'master opens observed historical order report','executor cannot access analytics or reports',
       'read-only database unchanged')
SOURCES={'c112_analytics.spec.cjs','c112_contract.cjs','c112_private_boundary.cjs',
         'c112_playwright.config.cjs','c112_preflight_proof.cjs','c112_gate.cjs'}
CODES={'COMPLETE_FACTS_REQUIRED','EXACT_ORDER_COUNT_REQUIRED','API_DB_IDENTITIES_MISMATCH',
       'ACTUAL_PHOTO_REFERENCE_COUNT_REQUIRED','OBSERVED_HISTORICAL_ORDER_REQUIRED','ISSUED_METRIC_REQUIRED',
       'ACTUAL_RUNTIME_PROVENANCE_REQUIRED','HISTORICAL_COUNTS_REQUIRED','UNAVAILABLE_PHOTO_PROVENANCE_REQUIRED',
       'SHIFT_REPORT_FACTS_MISMATCH','SELECTED_ORDER_REPORT_MISMATCH','EXECUTOR_RESTRICTION_REQUIRED',
       'BUSINESS_DATABASE_CHANGED','UNEXPECTED_NETWORK_ACTIVITY','SOURCE_CHANGED_DURING_JOURNEY',
       'REAL_RESPONSE_REQUIRED','PROTECTED_RESPONSE_HEADERS_REQUIRED','SERVICE_WORKER_RESPONSE_FORBIDDEN',
       'SEPARATE_SECURE_SESSIONS_REQUIRED','ANDROID_PROJECT_REQUIRED','REVIEWED_SINGLE_RUN_REQUIRED',
       'REVIEWED_REPORTERS_REQUIRED','REVIEWED_CAPTURE_AND_BROWSER_ENV_REQUIRED',
       'ANALYTICS_JOURNEY_FAILED_SEE_SAFE_STAGE_RESULTS'}
SIGNATURES={
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


C_SUBSTEPS=set(["NOT_STARTED","NAVIGATE_ANALYTICS","FILL_PERIOD_START","FILL_PERIOD_END","WAIT_MATCHING_UI_RESPONSE","CHECK_RESPONSE_IDENTITY_STATUS","CHECK_PROTECTED_HEADERS","CHECK_CACHE_PRIVATE","CHECK_CACHE_NO_STORE","CHECK_VARY_COOKIE","CHECK_NOSNIFF","CHECK_SERVICE_WORKER_ABSENCE","PARSE_RESPONSE_JSON","CHECK_RESPONSE_PERIOD","CHECK_HISTORICAL_PROVENANCE","CHECK_FACTS_SCHEMA","CHECK_ORDER_COUNT","CHECK_API_DATABASE_IDENTITIES","CHECK_PHOTO_REFERENCES","SELECT_OBSERVED_HISTORICAL_ORDER","WAIT_SYNTHETIC_WATERMARK","WAIT_UNAVAILABLE_PHOTO_NOTICE","CHECK_UNAVAILABLE_PHOTO_COUNTS","CHECK_PHYSICAL_EVIDENCE_DISCLOSURE","EXPAND_PROVENANCE_DISCLOSURE","CHECK_PROVENANCE_HASHES","WAIT_PERIOD_METRICS_HEADING","WAIT_EXECUTOR_METRICS_HEADING","CHECK_ISSUED_API_METRIC","CHECK_ISSUED_UI_METRIC","RECORD_ANALYTICS_OBSERVATION","OTHER_JOURNEY_STEP","UNCLASSIFIED_STEP"])
C_HTTP_CATEGORIES=set(["NOT_OBSERVED","HTTP_OTHER_OR_UNAVAILABLE","HTTP_OK","HTTP_BAD_REQUEST","HTTP_UNAUTHENTICATED","HTTP_FORBIDDEN","HTTP_NOT_FOUND","HTTP_VALIDATION","HTTP_RATE_LIMITED","HTTP_SERVER_ERROR","HTTP_GATEWAY_ERROR","HTTP_UNAVAILABLE","HTTP_GATEWAY_TIMEOUT"])
C_FAILURE_CATEGORIES={'NONE','ASSERTION_OR_OPERATION_FAILED'}


def c112_diagnostic_projection(value):
    if not isinstance(value,dict): return None
    result={}
    for key,allowed,fallback in [('substep',C_SUBSTEPS,'UNCLASSIFIED_STEP'),
                                ('failure_category',C_FAILURE_CATEGORIES,'ASSERTION_OR_OPERATION_FAILED'),
                                ('analytics_response',C_HTTP_CATEGORIES,'HTTP_OTHER_OR_UNAVAILABLE')]:
        item=value.get(key)
        result[key]=item if isinstance(item,str) and item in allowed else fallback
    return result


def failure_projection(report, evidence):
    output={'scope':'diagnostic_only_no_history_pass','completed_steps':0,'failed_step':None,
            'observations':0,'restrictions':0,'report':'unavailable','error_classes':[],'source_locations':[]}
    try:
        if evidence.is_file() and not evidence.is_symlink() and evidence.stat().st_size<=4*1024*1024:
            body=json.loads(evidence.read_text())
            fixed=c112_diagnostic_projection(body.get("diagnostics"))
            if fixed is not None: output["c112_diagnostics"]=fixed
            for index,row in enumerate(body.get('steps',[])[:len(STEPS)]):
                if row.get('name')!=STEPS[index]: break
                if row.get('result')=='PASS': output['completed_steps']+=1
                elif row.get('result')=='FAIL': output['failed_step']=index+1; break
            for name in ('observations','restrictions'):
                output[name]=min(len(body[name]),3) if isinstance(body.get(name),list) else 0
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
            for code in re.findall(r'C112 (?:BLOCKED|FAIL): ([A-Z0-9_]+)',message):
                if code in CODES: classes.add(code)
            location(value.get('location'))
            for name,line in re.findall(r'(c112_[A-Za-z_]+\.(?:spec\.)?cjs):(\d+):\d+',str(value.get('stack',''))):
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
