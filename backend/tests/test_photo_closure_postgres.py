"""Actual app.main upload -> submit -> physical-evidence human CLOSE."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import create_app
from app.core.auth_boundary import SESSION_COOKIE_NAME
import test_runtime_postgres as runtime
import test_persistence_postgres as data
from test_photos_unit import image_bytes

class PhotoClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.MountedRuntimeTests.setUpClass()
        cls.addClassCleanup(runtime.MountedRuntimeTests.doClassCleanups)
    def setUp(self):
        self.base=runtime.MountedRuntimeTests('test_schema_owner_is_rejected')
        self.addCleanup(self.base.doCleanups);self.base.setUp();self.f=self.base.fixture
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.settings=replace(self.base.settings,photo_storage_root=str(self.root))
        with self.f.connect() as db:
            db.execute(self.f.sql.SQL('GRANT INSERT ON photos TO {}').format(self.f.sql.Identifier(self.f.runtime_role)))
    def app(self,settings=None):return create_app(settings=settings or self.settings,connect=self.f.runtime_connect)
    def actor(self,client,actor):
        client.cookies.clear();client.cookies.set(SESSION_COOKIE_NAME,actor)
    def post(self,client,path,body):
        return client.post(path,json=body,headers={'Origin':data.ORIGIN,'X-CSRF-Token':'synthetic-csrf'})
    def prepare(self,client):
        self.actor(client,data.MASTER)
        command=data.create_command();command['operation_id']=str(uuid4())
        command['payload']['due_at']=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
        created=self.post(client,'/api/v1/orders',command);self.assertEqual(created.status_code,201)
        order=created.json()['order']['id'];self.actor(client,data.EXECUTOR)
        for version,action in ((1,'accept'),(2,'start')):
            response=self.post(client,f'/api/v1/orders/{order}/commands',{'operation_id':str(uuid4()),'expected_version':version,'action':action,'payload':{}})
            self.assertEqual(response.status_code,200)
        form={'operation_id':str(uuid4()),'expected_version':'0','section_id':data.SECTION,
              'purpose':'after','order_id':order,'assignment_revision':'1'}
        stage=client.post('/api/v1/photos/stage',data=form,files={'file':('synthetic.png',image_bytes(),'image/png')},
                          headers={'Origin':data.ORIGIN,'X-CSRF-Token':'synthetic-csrf'})
        self.assertEqual(stage.status_code,201,stage.text);photo=stage.json()['id']
        self.assertEqual(client.get('/api/v1/photos/'+photo).status_code,200)
        submit=self.post(client,f'/api/v1/orders/{order}/commands',{'operation_id':str(uuid4()),'expected_version':3,'action':'submit',
            'payload':{'work_description':'Synthetic physical evidence','work_code_id':data.CODE,'materials':[],
                       'after_photo_ids':[photo],'comment':''}})
        self.assertEqual(submit.status_code,200,submit.text)
        self.actor(client,data.MASTER)
        review={'operation_id':str(uuid4()),'expected_version':4,'action':'review','payload':{
            'submission_id':submit.json()['submission_id'],'decision':'close','reason':'Synthetic review','final_score':None}}
        row=self.f.query('SELECT * FROM photos WHERE id=%s',(photo,))[0]
        return order,review,self.root/row['storage_key']
    def unchanged(self,before):
        self.assertEqual(self.f.query('SELECT status,version FROM orders')[0],{'status':'ai_review','version':4})
        self.assertEqual(self.f.query('SELECT * FROM reviews'),[])
        self.assertEqual(len(self.f.query('SELECT * FROM operation_receipts')),before)
        self.assertIs(self.f.query('SELECT file_valid FROM photos')[0]['file_valid'],True)
    def test_valid_private_photo_closes_and_survives_app_restart(self):
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            order,review,path=self.prepare(client)
            result=self.post(client,f'/api/v1/orders/{order}/commands',review)
            self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['order']['status'],'closed')
            self.assertTrue(path.is_file())
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            self.actor(client,data.MASTER)
            self.assertEqual(self.post(client,f'/api/v1/orders/{order}/commands',review).json(),result.json())
    def test_known_hash_mismatch_is_409_without_effects(self):
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            order,review,path=self.prepare(client);before=len(self.f.query('SELECT * FROM operation_receipts'))
            raw=path.read_bytes();path.write_bytes(bytes([raw[0]^1])+raw[1:])
            result=self.post(client,f'/api/v1/orders/{order}/commands',review)
            self.assertEqual(result.status_code,409,result.text);self.assertEqual(result.json()['code'],'INCOMPLETE_SUBMISSION');self.unchanged(before)
    def test_missing_blob_is_retryable_503_and_same_command_recovers(self):
        with TestClient(self.app(),base_url=data.ORIGIN) as client:
            order,review,path=self.prepare(client);before=len(self.f.query('SELECT * FROM operation_receipts'))
            held=path.with_name('.test-held');path.rename(held)
            result=self.post(client,f'/api/v1/orders/{order}/commands',review)
            self.assertEqual(result.status_code,503,result.text);self.assertTrue(result.json()['retryable']);self.assertEqual(result.headers['retry-after'],'1');self.unchanged(before)
            held.rename(path)
            self.assertEqual(self.post(client,f'/api/v1/orders/{order}/commands',review).status_code,200)
    def test_absent_verifier_cannot_close_existing_valid_photo(self):
        with TestClient(self.app(),base_url=data.ORIGIN) as client:order,review,path=self.prepare(client)
        with self.f.connect() as db:
            db.execute(self.f.sql.SQL('REVOKE INSERT ON photos FROM {}').format(self.f.sql.Identifier(self.f.runtime_role)))
        before=len(self.f.query('SELECT * FROM operation_receipts'))
        with TestClient(self.app(replace(self.settings,photo_storage_root='')),base_url=data.ORIGIN) as client:
            self.actor(client,data.MASTER)
            result=self.post(client,f'/api/v1/orders/{order}/commands',review)
            self.assertEqual(result.status_code,409,result.text);self.unchanged(before)
