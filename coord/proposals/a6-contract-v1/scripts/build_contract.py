"""Reproduce this proposal and its deliberately synthetic examples; no network calls."""
from pathlib import Path
import json
import yaml
ROOT = Path(__file__).resolve().parents[1]
def ref(name): return {'$ref': '#/components/schemas/' + name}
def obj(props, required=None): return {'type':'object','additionalProperties':False,'properties':props,'required':list(props) if required is None else required}
def arr(item, **kw): return {'type':'array','items':item,**kw}
def enum(*values): return {'type':'string','enum':list(values)}
def text(maximum=2000, minimum=1): return {'type':'string','minLength':minimum,'maxLength':maximum}
def nullable(schema): return {'anyOf':[schema,{'type':'null'}]}
ID={'type':'string','format':'uuid'}
TS={'type':'string','format':'date-time','description':'RFC3339; normalize inputs to UTC and emit Z. Real/domain clock determined by field semantics.'}
INT={'type':'integer','minimum':1}
S={}
S['Role']=enum('master','executor','manager','admin')
S['Status']=enum('issued','queued','accepted','rejected','in_progress','paused','done','ai_review','rework','closed','cancelled')
S['Assignment']=obj({'executor_id':ID,'brigade_id':nullable(ID)})
S['Principal']=obj({'user_id':ID,'active':{'type':'boolean'},'employee_code':text(40),'role':ref('Role'),'section_ids':arr(ID),'on_shift':{'type':'boolean'}})
S['Session']=obj({'principal':ref('Principal'),'csrf_token':text(256),'expires_at':TS})
S['Login']=obj({'employee_code':text(40),'pin':{'type':'string','minLength':4,'maxLength':64,'writeOnly':True}})
S['FieldError']=obj({'path':text(200),'code':text(80)})
S['Problem']=obj({'code':enum('INVALID_REQUEST','VALIDATION_FAILED','UNAUTHENTICATED','FORBIDDEN','NOT_FOUND','VERSION_CONFLICT','TRANSITION_CONFLICT','OPERATION_ID_REUSED','INCOMPLETE_SUBMISSION','STALE_ASSIGNMENT','PHOTO_EXPIRED','RATE_LIMITED','TEMPORARILY_UNAVAILABLE','PAYLOAD_TOO_LARGE','UNSUPPORTED_MEDIA_TYPE'),'message':text(),'request_id':ID,'retryable':{'type':'boolean'},'current_version':nullable(INT),'field_errors':arr(ref('FieldError'))})
S['CreatePayload']=obj({'type':enum('planned','unplanned'),'description':text(),'section_id':ID,'equipment_id':ID,'assignment':ref('Assignment'),'due_at':TS,'norm_minutes':{'type':'integer','minimum':1,'maximum':525600},'priority':enum('normal','high','emergency'),'comment':text(2000,0),'before_photo_ids':arr(ID,maxItems=5,uniqueItems=True)})
S['CreateOrder']=obj({'operation_id':ID,'expected_version':{'type':'integer','const':0},'action':{'const':'create','type':'string'},'payload':ref('CreatePayload')})
S['MaterialUse']=obj({'material_id':ID,'quantity':{'type':'number','exclusiveMinimum':0,'maximum':999999999,'description':'Up to three fractional digits; unit is the material dictionary unit.'}})
S['SubmitPayload']=obj({'work_description':text(6000),'work_code_id':nullable(ID),'materials':arr(ref('MaterialUse'),maxItems=40),'after_photo_ids':arr(ID,maxItems=5,uniqueItems=True),'comment':text(2000,0)})
S['ReviewPayload']=obj({'submission_id':ID,'decision':enum('close','rework'),'reason':text(),'final_score':nullable({'type':'integer','minimum':0,'maximum':100})})
S['MissingEvidence']=enum('WORK_CODE_REQUIRED','AFTER_PHOTO_REQUIRED')
S['Assessment']=obj({'id':ID,'submission_id':ID,'assignment_revision':INT,'schema_version':{'type':'string','const':'1'},'mode':enum('model','rules_fallback','manual'),'model':nullable(text(120)),'model_version':nullable(text(120)),'duration_ms':{'type':'integer','minimum':0},'recommendation':enum('satisfactory','rework_recommended','needs_master_review'),'score':nullable({'type':'integer','minimum':0,'maximum':100}),'reasons':arr(text(2000)),'evidence_ids':arr(ID),'fallback_reason':nullable(text(120)),'stale':{'type':'boolean'},'created_at':TS})
S['Review']=obj({'id':ID,'submission_id':ID,'reviewer_id':ID,'decision':enum('close','rework'),'reason':text(),'final_score':nullable({'type':'integer','minimum':0,'maximum':100}),'created_at':TS})
S['Submission']=obj({'id':ID,'order_id':ID,'assignment_revision':INT,'attempt_number':INT,'submitted_by':ID,'submitted_at':TS,'done_late':{'type':'boolean'},'payload':ref('SubmitPayload'),'completeness':enum('complete','incomplete'),'missing_evidence':arr(ref('MissingEvidence')),'assessments':arr(ref('Assessment')),'reviews':arr(ref('Review'))})
S['Order']=obj({'id':ID,'number':text(80),'version':INT,'assignment_revision':INT,'scheduling_revision':INT,'status':ref('Status'),'type':enum('planned','unplanned'),'description':text(),'section_id':ID,'equipment_id':ID,'assignment':ref('Assignment'),'created_by':ID,'issued_at':TS,'due_at':TS,'norm_minutes':{'type':'integer','minimum':1},'priority':enum('normal','high','emergency'),'comment':text(2000,0),'before_photo_ids':arr(ID,maxItems=5),'current_submission_id':nullable(ID),'is_overdue':{'type':'boolean'},'domain_now':TS,'updated_at':TS})
S['CommandResult']=obj({'order':ref('Order'),'event_ids':arr(ID,minItems=1),'submission_id':nullable(ID)})
S['OrderPage']=obj({'items':arr(ref('Order')),'next_cursor':nullable(text(512))})
S['OrderEvent']=obj({'id':ID,'order_id':ID,'sequence':INT,'order_version':INT,'assignment_revision':INT,'scheduling_revision':INT,'reason':nullable(text()),'details':{'type':'object','additionalProperties':True,'description':'Trusted server-generated audit changes only; never raw prompts or arbitrary client metadata.'},'kind':enum('order.created','order.queued','order.accepted','order.rejected','order.started','order.paused','order.resumed','order.done','order.ai_review_requested','order.assessment_recorded','order.reviewed','order.reassigned','order.cancelled','order.priority_changed'),'actor_id':nullable(ID),'operation_id':nullable(ID),'from_status':nullable(ref('Status')),'to_status':ref('Status'),'submission_id':nullable(ID),'occurred_at':TS,'recorded_at':TS})
S['EventPage']=obj({'items':arr(ref('OrderEvent')),'next_after_sequence':{'type':'integer','minimum':0},'has_more':{'type':'boolean'}})
S['StagedPhoto']=obj({'id':ID,'section_id':ID,'purpose':enum('before','after'),'owner_id':ID,'order_id':nullable(ID),'assignment_revision':nullable(INT),'mime_type':enum('image/jpeg','image/png','image/webp'),'bytes':{'type':'integer','minimum':1,'maximum':8388608},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'uploaded_at':TS,'expires_at':TS,'exif_removed':{'type':'boolean'}})
S['StagePhotoRequest']=obj({'section_id':ID,'operation_id':ID,'expected_version':{'type':'integer','const':0},'purpose':enum('before','after'),'order_id':ID,'assignment_revision':INT,'file':{'type':'string','format':'binary'}},['section_id','operation_id','expected_version','purpose','file'])
commands={
 'queue':obj({}), 'accept':obj({}), 'start':obj({}), 'resume':obj({}),
 'reject':obj({'reason':text()}), 'pause':obj({'reason':text()}),
 'submit':ref('SubmitPayload'), 'review':ref('ReviewPayload'),
 'reassign':obj({'assignment':ref('Assignment'),'reason':text()}),
 'cancel':obj({'reason':text()}),
 'change_priority':obj({'priority':enum('normal','high','emergency'),'reason':text()})}
for action,payload in commands.items():
 name=''.join(p.title() for p in action.split('_'))+'Command'
 S[name]=obj({'operation_id':ID,'expected_version':INT,'action':{'const':action,'type':'string'},'payload':payload})
S['OrderCommand']={'oneOf':[ref(''.join(p.title() for p in a.split('_'))+'Command') for a in commands],'discriminator':{'propertyName':'action','mapping':{a:'#/components/schemas/'+''.join(p.title() for p in a.split('_'))+'Command' for a in commands}}}
S['DictionaryItem']=obj({'id':ID,'code':text(80),'label':text(200)})
S['EquipmentItem']=obj({'id':ID,'code':text(80),'label':text(200),'section_id':ID})
S['MaterialItem']=obj({'id':ID,'code':text(80),'label':text(200),'unit':text(40)})
S['ExecutorItem']=obj({'id':ID,'employee_code':text(40),'section_ids':arr(ID),'brigade_id':nullable(ID),'on_shift':{'type':'boolean'},'active_order_id':nullable(ID),'queue_count':{'type':'integer','minimum':0}})
S['Dictionaries']=obj({'sections':arr(ref('DictionaryItem')),'equipment':arr(ref('EquipmentItem')),'brigades':arr(ref('DictionaryItem')),'executors':arr(ref('ExecutorItem')),'work_codes':arr(ref('DictionaryItem')),'materials':arr(ref('MaterialItem'))})
S['DeliveryJob']=obj({'id':ID,'order_id':ID,'assignment_revision':INT,'scheduling_revision':INT,'kind':enum('new_order','deadline_reminder','overdue','acceptance_escalation','manager_escalation','submission_ready','review_result'),'recipient_id':ID,'channel':text(40),'bucket':text(100),'due_at':TS,'state':enum('pending','sending','provider_accepted','retry','cancelled','failed'),'attempts':{'type':'integer','minimum':0},'next_attempt_at':TS,'provider_receipt':nullable(text(256))})
S['DeliveryJob']['description']='Internal worker interface only, not a public endpoint or evidence of device delivery. Provider and channel await A3/A0 approval.'
cs={'name':'X-CSRF-Token','in':'header','required':True,'schema':text(256),'description':'Session-bound token returned by login or /me; exact Origin validation also required.'}
orderid={'name':'order_id','in':'path','required':True,'schema':ID}
common={str(n):{'description':d,'content':{'application/json':{'schema':ref('Problem')}}} for n,d in [(400,'Malformed request'),(401,'Unauthenticated'),(403,'Not authorized or CSRF/origin rejected'),(404,'Object does not exist'),(409,'Version, transition, idempotency, completeness, or assignment conflict'),(422,'Semantically invalid input'),(429,'Rate limited; Retry-After header'),(503,'Temporary failure; never a success receipt')]}
for status in ['429','503']:
 common[status]['headers']={'Retry-After':{'schema':{'type':'integer','minimum':1},'description':'Real seconds until retry'}}
def response(schema, desc='Success'): return {'description':desc,'content':{'application/json':{'schema':ref(schema)}}}
def op(oid, summary, schema, body=None, status='200', mutate=False, desc=None):
 d={'operationId':oid,'summary':summary,'responses':{status:response(schema),**common}}
 if body: d['requestBody']={'required':True,'content':{'application/json':{'schema':ref(body)}}}
 if mutate: d['parameters']=[cs]
 if desc: d['description']=desc
 return d
P={}
P['/auth/login']={'post':op('loginDemoSession','Sign in to isolated demo','Session','Login',desc='Same-origin JSON login; generic invalid-credential errors and real-clock rate limits. Secure session cookie is set. No authenticated CSRF token exists before login; require exact same Origin and reject cross-site requests.')}
P['/auth/login']['post']['security']=[]
P['/auth/login']['post']['responses']['200']['headers']={'Set-Cookie':{'schema':{'type':'string'},'description':'__Host-naryadai_session=<opaque>; Path=/; Secure; HttpOnly; SameSite=Strict'}}
P['/auth/logout']={'post':{'operationId':'logoutSession','summary':'Revoke current session and clear cookie','parameters':[cs],'responses':{'204':{'description':'Session revoked'},**common}}}
P['/me']={'get':op('getCurrentSession','Get caller scope and current CSRF token','Session')}
P['/dicts']={'get':op('getDictionaries','Get only dictionaries and executors within caller scope','Dictionaries')}
P['/orders']={'get':op('listOrders','List authorized current snapshots','OrderPage'),'post':op('createOrder','Issue an order as scoped master','CommandResult','CreateOrder','201',True,'One transaction attaches owned staged before-photos, assigns number and domain issued_at, stores events, delivery jobs and receipt. expected_version=0. Identical retry returns original 201 body.')}
P['/orders']['get']['parameters']=[{'name':'cursor','in':'query','schema':text(512)},{'name':'limit','in':'query','schema':{'type':'integer','minimum':1,'maximum':100,'default':50}},{'name':'status','in':'query','schema':ref('Status')}]+[{'name':n,'in':'query','schema':ID} for n in ['section_id','equipment_id','executor_id']]
P['/orders/{order_id}']={'parameters':[orderid],'get':op('getOrder','Read an authorized current snapshot','Order')}
P['/orders/{order_id}/commands']={'parameters':[orderid],'post':op('executeOrderCommand','Apply one authorized idempotent order command','CommandResult','OrderCommand','200',True,'Authentication and CURRENT object authorization precede receipt lookup; identical committed replay bypasses old version/transition checks. Reused ID with a different canonical request => 409 OPERATION_ID_REUSED. Missing required after-photo can produce an incomplete submission; closing it yields 409 INCOMPLETE_SUBMISSION.')}
P['/orders/{order_id}/events']={'parameters':[orderid],'get':op('listOrderEvents','Read append-only authorized per-order event history','EventPage')}
P['/orders/{order_id}/events']['get']['parameters']=[{'name':'after_sequence','in':'query','schema':{'type':'integer','minimum':0,'default':0}},{'name':'limit','in':'query','schema':{'type':'integer','minimum':1,'maximum':200,'default':100}}]
P['/orders/{order_id}/submissions/{submission_id}']={'parameters':[orderid,{'name':'submission_id','in':'path','required':True,'schema':ID}],'get':op('getSubmission','Read an immutable attempt with assessment and human review history','Submission')}
P['/photos/stage']={'post':op('stagePhoto','Validate and privately stage one photo','StagedPhoto',status='201',mutate=True,desc='section_id is required and verified against current authorized scope; after also matches the DB-loaded order section. Before requires neither order_id nor assignment_revision; after requires both and current assigned executor. Wrong-section staging or attachment returns 403 FORBIDDEN. Max 8 MiB and 20 megapixels, decode-and-reencode, strip EXIF/GPS, safe generated storage key. TTL 24 real hours; limits are proposal choices. Hash includes raw file SHA-256 and form metadata. Replay does not extend TTL. No remote URL upload.')}
P['/photos/stage']['post']['requestBody']={'required':True,'content':{'multipart/form-data':{'schema':ref('StagePhotoRequest')}}}
for n,d in [(413,'Maximum upload size exceeded'),(415,'Unsupported or invalid image')]:
 P['/photos/stage']['post']['responses'][str(n)]={'description':d,'content':{'application/json':{'schema':ref('Problem')}}}
P['/photos/{photo_id}']={'parameters':[{'name':'photo_id','in':'path','required':True,'schema':ID}],'get':{'operationId':'getPhoto','summary':'Read a photo after current staged-owner or order authorization','responses':{'200':{'description':'Private image; no public object-storage URL','headers':{'Cache-Control':{'schema':{'type':'string','const':'private, no-store'}}},'content':{m:{'schema':{'type':'string','format':'binary'}} for m in ['image/jpeg','image/png','image/webp']}},**common}}}
spec={'openapi':'3.1.0','info':{'title':'НарядAI thin vertical slice PROPOSAL','version':'1.0.0-proposal.2','description':'Not frozen or implemented. Acceptance owner A0/human A pending; B0 and C0 handshake pending. See CONTRACT.md. No production or device performance claim.'},'servers':[{'url':'/api/v1','description':'Same-origin deployment'}],'security':[{'sessionCookie':[]}],'x-approval-status':{'A0':'pending','B0':'pending','C0':'pending'},'paths':P,'components':{'securitySchemes':{'sessionCookie':{'type':'apiKey','in':'cookie','name':'__Host-naryadai_session'}},'schemas':S}}
# Reuse response components so the wire contract remains readable and compact.
spec['components']['responses']={f'Error{k}':v for k,v in common.items()}
for path in P.values():
 for method,d in path.items():
  if method in ('get','post'):
   for status in common:
    if status in d['responses']: d['responses'][status]={'$ref':f'#/components/responses/Error{status}'}
(ROOT/'contracts/openapi.yaml').write_text(yaml.safe_dump(spec,allow_unicode=True,sort_keys=False,width=105))
# Reserved UUIDs and synthetic enterprise codes only.
def uid(n): return f'00000000-0000-4000-8000-{n:012d}'
T='2026-10-07T17:00:00Z'
payload={'type':'unplanned','description':'Синтетический пример: заменить изношенный ремень','section_id':uid(1),'equipment_id':uid(2),'assignment':{'executor_id':uid(3),'brigade_id':uid(4)},'due_at':'2026-10-07T18:00:00Z','norm_minutes':45,'priority':'normal','comment':'Демонстрационные данные','before_photo_ids':[]}
create={'operation_id':uid(101),'expected_version':0,'action':'create','payload':payload}
order={'id':uid(10),'number':'DEMO-2026-0001','version':1,'assignment_revision':1,'scheduling_revision':1,'status':'issued',**{k:v for k,v in payload.items() if k!='before_photo_ids'},'created_by':uid(5),'issued_at':T,'before_photo_ids':[],'current_submission_id':None,'is_overdue':False,'domain_now':T,'updated_at':T}
fixtures=[]
def fixture(filename,schema,value,valid=True):
 (ROOT/'contracts/examples'/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 fixtures.append({'file':filename,'schema':schema,'valid':valid})
fixture('01-create.request.json','CreateOrder',create)
fixture('02-create.response.json','CommandResult',{'order':order,'event_ids':[uid(201)],'submission_id':None})
for filename,action,version in [('03-accept.request.json','accept',1),('04-start.request.json','start',2)]:
 fixture(filename,'OrderCommand',{'operation_id':uid(102+version),'expected_version':version,'action':action,'payload':{}})
submission_payload={'work_description':'Ремень заменён, выполнена пробная проверка. Синтетический пример.','work_code_id':uid(6),'materials':[{'material_id':uid(7),'quantity':1}],'after_photo_ids':[uid(8)],'comment':'Проверка мастером обязательна'}
fixture('05-submit.request.json','OrderCommand',{'operation_id':uid(105),'expected_version':3,'action':'submit','payload':submission_payload})
fixture('06-review.request.json','OrderCommand',{'operation_id':uid(106),'expected_version':4,'action':'review','payload':{'submission_id':uid(11),'decision':'close','reason':'Результат и обязательные доказательства проверены мастером','final_score':90}})
incomplete={'operation_id':uid(107),'expected_version':3,'action':'submit','payload':{**submission_payload,'after_photo_ids':[]}}
fixture('07-incomplete-submit.request.json','OrderCommand',incomplete)
fixture('08-version-conflict.response.json','Problem',{'code':'VERSION_CONFLICT','message':'Наряд изменён. Обновите данные перед повторным действием.','request_id':uid(901),'retryable':False,'current_version':4,'field_errors':[]})
fixture('09-ai-review.event.json','OrderEvent',{'id':uid(205),'order_id':uid(10),'sequence':5,'order_version':4,'assignment_revision':1,'scheduling_revision':1,'reason':None,'details':{},'kind':'order.ai_review_requested','actor_id':None,'operation_id':uid(105),'from_status':'done','to_status':'ai_review','submission_id':uid(11),'occurred_at':T,'recorded_at':T})
fixture('10-incomplete-submission.response.json','Submission',{'id':uid(11),'order_id':uid(10),'assignment_revision':1,'attempt_number':1,'submitted_by':uid(3),'submitted_at':T,'done_late':False,'payload':incomplete['payload'],'completeness':'incomplete','missing_evidence':['AFTER_PHOTO_REQUIRED'],'assessments':[],'reviews':[]})
fixture('11-rules-fallback.assessment.json','Assessment',{'id':uid(12),'submission_id':uid(11),'assignment_revision':1,'schema_version':'1','mode':'rules_fallback','model':None,'model_version':None,'duration_ms':0,'recommendation':'needs_master_review','score':None,'reasons':['Модель недоступна; требуется решение мастера'],'evidence_ids':[uid(11)],'fallback_reason':'provider_unavailable','stale':False,'created_at':T})
fixture('12-delivery-job.internal.json','DeliveryJob',{'id':uid(13),'order_id':uid(10),'assignment_revision':1,'scheduling_revision':1,'kind':'new_order','recipient_id':uid(3),'channel':'adapter_pending_approval','bucket':'initial','due_at':T,'state':'pending','attempts':0,'next_attempt_at':T,'provider_receipt':None})
fixture('negative-spoofed-actor.json','CreateOrder',{**create,'actor_id':uid(3)},False)
fixture('negative-empty-work.json','OrderCommand',{**incomplete,'payload':{**submission_payload,'work_description':''}},False)
fixture('negative-quantity.json','OrderCommand',{**incomplete,'payload':{**submission_payload,'materials':[{'material_id':uid(7),'quantity':-1}]}},False)
fixture('negative-unknown-action.json','OrderCommand',{**incomplete,'action':'auto_close'},False)
fixture('negative-bad-timestamp.json','CreateOrder',{**create,'payload':{**payload,'due_at':'not-a-date'}},False)
fixture('negative-impossible-timestamp.json','CreateOrder',{**create,'payload':{**payload,'due_at':'2026-02-30T17:00:00Z'}},False)
fixture('negative-unzoned-timestamp.json','CreateOrder',{**create,'payload':{**payload,'due_at':'2026-10-07T17:00:00'}},False)
stage_request={'operation_id':uid(108),'expected_version':0,'section_id':uid(1),'purpose':'before','file':'SYNTHETIC_MULTIPART_BYTES_PLACEHOLDER'}
staged_photo={'id':uid(8),'section_id':uid(1),'purpose':'before','owner_id':uid(5),'order_id':None,'assignment_revision':None,'mime_type':'image/jpeg','bytes':123,'sha256':'0'*64,'uploaded_at':T,'expires_at':'2026-10-08T17:00:00Z','exif_removed':True}
fixture('13-before-stage.request.json','StagePhotoRequest',stage_request)
fixture('14-before-stage.response.json','StagedPhoto',staged_photo)
fixture('15-after-stage.request.json','StagePhotoRequest',{**stage_request,'operation_id':uid(109),'purpose':'after','order_id':uid(10),'assignment_revision':1})
fixture('negative-missing-stage-section.json','StagePhotoRequest',{k:v for k,v in stage_request.items() if k!='section_id'},False)
wrong_section={'description':'Valid schema; cross-object authorization must reject. Both sections are in principal scope to isolate the attachment section-equality rule. This file is not a claim of a running HTTP test.','principal':{'user_id':uid(5),'role':'master','section_ids':[uid(1),uid(20)],'active':True},'staged_photo':{**staged_photo,'section_id':uid(20)},'destination_section_id':uid(1),'real_now':T,'expected_http_status':403,'expected_error_code':'FORBIDDEN'}
(ROOT/'contracts/examples/negative-wrong-section.scenario.json').write_text(json.dumps(wrong_section,ensure_ascii=False,indent=2)+'\n')
(ROOT/'contracts/examples/manifest.json').write_text(json.dumps({'synthetic':True,'contract_version':spec['info']['version'],'fixtures':fixtures,'semantic_scenarios':[{'file':'negative-wrong-section.scenario.json','requires':'A2/A1 authorization adapter execution','expected_http_status':403}]},indent=2)+'\n')
print(f'Generated {len(P)} paths, {len(S)} component schemas, {len(fixtures)} fixtures')
