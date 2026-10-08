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


def failure_projection(report, evidence):
    output={'scope':'diagnostic_only_no_controls_pass','completed_steps':0,'failed_step':None,
            'clock_observations':0,'downloads':0,'restrictions':0,'report':'unavailable','error_classes':[],'source_locations':[]}
    try:
        if evidence.is_file() and not evidence.is_symlink() and evidence.stat().st_size<=4*1024*1024:
            body=json.loads(evidence.read_text())
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
