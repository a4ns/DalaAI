"""Real HTTPS/Compose/photo workflow smoke; no browser, AI or push claim."""
import argparse
from datetime import datetime,timedelta,timezone
from http.cookiejar import CookieJar
from io import BytesIO
import json
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor, HTTPSHandler
from uuid import uuid4


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url',required=True);p.add_argument('--ca-file',type=Path,required=True)
    p.add_argument('--secrets',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--source-sha',required=True);p.add_argument('--expect-rules-worker',action='store_true');a=p.parse_args()
    parsed=urlsplit(a.base_url)
    if parsed.scheme!='https' or parsed.hostname!='localhost' or parsed.path:
        raise SystemExit('This disposable smoke requires an explicit localhost HTTPS origin')
    context=ssl.create_default_context(cafile=str(a.ca_file))
    actors={name:build_opener(HTTPCookieProcessor(CookieJar()),HTTPSHandler(context=context)) for name in ('master','executor')}
    report={'source_sha':a.source_sha,'scope':'REAL_COMPOSE_HTTPS_PHOTO_CYCLE','status':'FAIL',
            'browser':'NOT_RUN','AI_worker':'NOT_RUN','push_delivery':'NOT_RUN','steps':[]}
    def call(actor,path,body=None,content_type='application/json'):
        headers={'Origin':a.base_url}
        if isinstance(body,dict):body=json.dumps(body).encode()
        if body is not None:headers['Content-Type']=content_type
        csrf=actor_tokens.get(actor)
        if csrf:headers['X-CSRF-Token']=csrf
        req=Request(a.base_url+path,data=body,headers=headers)
        try:
            with actors[actor].open(req,timeout=15) as response:return response.status,response.read(),response.headers
        except HTTPError as error:return error.code,error.read(),error.headers
    def json_call(actor,path,body=None,expected=200):
        status,raw,_=call(actor,path,body)
        if status!=expected:raise AssertionError(f'HTTP_STATUS_{status}_EXPECTED_{expected}')
        return json.loads(raw)
    actor_tokens={}
    try:
        status,html,headers=call('master','/')
        assert status==200 and 'text/html' in headers.get('Content-Type','') and b'<div id="root"' in html
        assert json_call('master','/readyz')['status']=='ready'
        report['steps'].append('trusted HTTPS frontend and actual API readiness')
        for actor in actors:
            pin=(a.secrets/(actor+'_pin')).read_text().strip()
            session=json_call(actor,'/api/v1/auth/login',{'employee_code':'DALA-DEMO-'+actor.upper(),'pin':pin})
            actor_tokens[actor]=session['csrf_token']
            assert json_call(actor,'/api/v1/me')['principal']['role']==actor
        report['steps'].append('two real Argon2 cookie sessions and CSRF')
        d=json_call('master','/api/v1/dicts');section=d['sections'][0]['id'];equipment=d['equipment'][0]['id'];executor=d['executors'][0]['id']
        created=json_call('master','/api/v1/orders',{'operation_id':str(uuid4()),'expected_version':0,'action':'create','payload':{
            'type':'unplanned','description':'Синтетическая проверка Compose: замена детали','section_id':section,
            'equipment_id':equipment,'assignment':{'executor_id':executor,'brigade_id':None},
            'due_at':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),'norm_minutes':30,
            'priority':'normal','comment':'Только тестовые данные','before_photo_ids':[]}},expected=201)
        order=created['order']['id'];route=f'/api/v1/orders/{order}/commands'
        for version,action in ((1,'accept'),(2,'start')):
            json_call('executor',route,{'operation_id':str(uuid4()),'expected_version':version,'action':action,'payload':{}})
        report['steps'].append('master issue and executor accept/start through HTTPS')
        from PIL import Image
        png=BytesIO();Image.new('RGB',(8,8),(20,120,80)).save(png,format='PNG')
        boundary='dalaai'+uuid4().hex
        fields={'operation_id':str(uuid4()),'expected_version':'0','purpose':'after','section_id':section,'order_id':order,'assignment_revision':'1'}
        chunks=[]
        for name,value in fields.items():chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="synthetic.png"\r\nContent-Type: image/png\r\n\r\n'.encode()+png.getvalue()+f'\r\n--{boundary}--\r\n'.encode())
        status,raw,_=call('executor','/api/v1/photos/stage',b''.join(chunks),'multipart/form-data; boundary='+boundary)
        assert status==201,'PHOTO_STAGE_FAILED';photo=json.loads(raw)['id']
        submitted=json_call('executor',route,{'operation_id':str(uuid4()),'expected_version':3,'action':'submit','payload':{
            'work_description':'Синтетическая работа выполнена','work_code_id':d['work_codes'][0]['id'],
            'materials':[],'after_photo_ids':[photo],'comment':'Синтетическое фото, без семантической оценки'}})
        report['steps'].append('actual sanitized photo upload and submitted immutable evidence')
        if a.expect_rules_worker:
            deadline=time.monotonic()+40
            while True:
                detail=json_call('master',f'/api/v1/orders/{order}/submissions/{submitted["submission_id"]}')
                assessments=detail['assessments']
                if assessments:break
                if time.monotonic()>=deadline:raise AssertionError('RULES_WORKER_ASSESSMENT_TIMEOUT')
                time.sleep(.5)
            assert len(assessments)==1 and assessments[0]['mode']=='rules_fallback' and not assessments[0]['stale']
            report['AI_worker']='PASS_PERSISTED_RULES_FALLBACK'
            report['steps'].append('separate restricted worker persisted actual rules assessment')
        current=json_call('master','/api/v1/orders/'+order)
        # getOrder is an Order snapshot, not a command receipt wrapper.
        version=current['version']
        review={'operation_id':str(uuid4()),'expected_version':version,'action':'review','payload':{
            'submission_id':submitted['submission_id'],'decision':'close','reason':'Синтетическая ручная приёмка','final_score':None}}
        closed=json_call('master',route,review)
        assert closed['order']['status']=='closed'
        assert call('master','/api/v1/photos/'+photo)[0]==200
        assert json_call('master',route,review)==closed
        report['steps'].append('physical-evidence master close, protected read and idempotent replay')
        report['status']='PASS_COMPOSE_PHOTO_CYCLE'
    except Exception as error:
        report['error_type']=type(error).__name__
        if isinstance(error,AssertionError):report['reason']=str(error)
    a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    return 0 if report['status']=='PASS_COMPOSE_PHOTO_CYCLE' else 1

if __name__=='__main__':raise SystemExit(main())
