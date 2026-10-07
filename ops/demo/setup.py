"""Setup container alone receives owner/PIN files; API receives runtime DSN only."""
import os
from pathlib import Path

MAPPING={'DALA_DEMO_OWNER_DATABASE_URL':'owner_dsn','DALA_DEMO_RUNTIME_DATABASE_URL':'runtime_dsn',
         'DALA_DEMO_MASTER_PIN':'master_pin','DALA_DEMO_EXECUTOR_PIN':'executor_pin'}
worker_profile=os.environ.get('DALA_DEMO_WORKER_CAPABILITY_ALLOWED')=='1'
if worker_profile:MAPPING['DALA_DEMO_WORKER_DATABASE_URL']='worker_dsn'
for key,name in MAPPING.items():
    value=(Path('/run/secrets')/name).read_text().strip()
    if not value:raise SystemExit('Required setup secret file is empty')
    os.environ[key]=value
helper='enable_worker_capabilities.py' if worker_profile else 'enable_photo_capability.py'
os.execvp('python',['python','ops/provision/'+helper,'--backend','/service',
    '--schema',os.environ['DALA_DATABASE_SCHEMA'],'--expected-database','naryadai','--bootstrap','--apply'])
