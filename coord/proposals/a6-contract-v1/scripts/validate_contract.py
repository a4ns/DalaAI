"""Offline proposal validation. Does NOT test a running API, DB, RBAC or delivery."""
from pathlib import Path
from datetime import datetime, timezone
from importlib.metadata import version
import hashlib
import json
import re
import yaml
from fastapi.openapi.models import OpenAPI
from jsonschema import Draft202012Validator, FormatChecker
# jsonschema intentionally treats absent optional format validators as annotations.
# Register our timestamp profile explicitly so missing extras cannot silently pass.
RFC3339 = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]"
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)
FORMATS = FormatChecker()
@FORMATS.checks('date-time', raises=(ValueError, OverflowError))
def check_timestamp(value):
    if not isinstance(value, str):
        return True  # JSON Schema's type keyword owns non-string rejection.
    if not RFC3339.fullmatch(value):
        return False
    parsed = datetime.fromisoformat(value.replace('t', 'T').replace('z', 'Z').replace('Z', '+00:00'))
    return parsed.tzinfo is not None

assert {'date-time', 'uuid'} <= set(FORMATS.checkers), 'Required format checker unavailable'
FORMAT_PROBES = [
    ('date-time', '2026-10-07T17:00:00Z', True),
    ('date-time', '2026-10-07T22:00:00.123+05:00', True),
    ('date-time', '2024-02-29t00:00:00z', True),
    ('date-time', 'not-a-date', False),
    ('date-time', '2026-02-30T17:00:00Z', False),
    ('date-time', '2026-10-07T17:00:00', False),
    ('date-time', '2026-10-07T24:00:00Z', False),
    ('date-time', '2026-10-07T17:00:00+25:00', False),
    ('date-time', '2026-10-07T17:00:60Z', False),
    ('uuid', 'not-a-uuid', False),
    ('uuid', '00000000-0000-4000-8000-000000000001', True),
]
for fmt, value, expected in FORMAT_PROBES:
    assert FORMATS.conforms(value, fmt) is expected, (fmt, value, expected)
ROOT=Path(__file__).resolve().parents[1]
spec=yaml.safe_load((ROOT/'contracts/openapi.yaml').read_text())
# FastAPI's typed OpenAPI model checks document/object syntax. Additional semantic
# checks below cover references, unique operations and path-parameter declarations.
OpenAPI.model_validate(spec)
counts={'paths':len(spec['paths']),'operations':0,'schemas':0,'references':0,'positive_fixtures':0,'negative_fixtures':0,'format_probes':len(FORMAT_PROBES)}
def pointer(ref):
 assert ref.startswith('#/'), f'External reference not permitted in this isolated proposal: {ref}'
 v=spec
 for part in ref[2:].split('/'): v=v[part.replace('~1','/').replace('~0','~')]
 return v
def walk(v):
 if isinstance(v,dict):
  if '$ref' in v:
   pointer(v['$ref']); counts['references']+=1
  for item in v.values(): walk(item)
 elif isinstance(v,list):
  for item in v: walk(item)
walk(spec)
operation_ids=set()
for path,entry in spec['paths'].items():
 for method,op in entry.items():
  if method not in ('get','post','put','patch','delete','head','options','trace'): continue
  oid=op['operationId']; assert oid not in operation_ids,oid
  operation_ids.add(oid); counts['operations']+=1
  parameters=entry.get('parameters',[])+op.get('parameters',[])
  for name in re.findall(r'\{([^}]+)\}',path):
   assert any(p.get('in')=='path' and p['name']==name and p.get('required') is True for p in parameters), (path,name)
  assert op['responses'],path
  if method=='post' and path!='/auth/login':
   assert any(p['name']=='X-CSRF-Token' and p.get('required') for p in parameters),path
for name,schema in spec['components']['schemas'].items():
 Draft202012Validator.check_schema(schema); counts['schemas']+=1
manifest=json.loads((ROOT/'contracts/examples/manifest.json').read_text())
for fixture in manifest['fixtures']:
 schema={'$ref':'#/components/schemas/'+fixture['schema'],'components':spec['components']}
 validator=Draft202012Validator(schema,format_checker=FORMATS)
 payload=json.loads((ROOT/'contracts/examples'/fixture['file']).read_text())
 errors=list(validator.iter_errors(payload))
 if fixture['valid']:
  assert not errors, f"{fixture['file']}: {[e.message for e in errors]}"
  counts['positive_fixtures']+=1
 else:
  assert errors, f"Negative fixture erroneously accepted: {fixture['file']}"
  counts['negative_fixtures']+=1
result={'status':'PASS','level':'offline_contract_structure_and_fixture_validation','executed_at':datetime.now(timezone.utc).isoformat(),'contract_version':spec['info']['version'],'contract_sha256':hashlib.sha256((ROOT/'contracts/openapi.yaml').read_bytes()).hexdigest(),'counts':counts,'validation_dependencies':{p:version(p) for p in ['PyYAML','fastapi','pydantic','jsonschema']},'correction':'Earlier evidence lacked an installed date-time checker; superseded by explicit local timestamp validation and negative fixtures.','checks':['YAML parse','FastAPI OpenAPI typed model syntax','local reference resolution','unique operation IDs','required path parameters','CSRF headers on authenticated POST operations','JSON Schema 2020-12 schema syntax','explicit date-time and UUID format availability/probes','positive/negative JSON fixtures with required format validation'],'not_run':['dedicated OpenAPI specification validator','PostgreSQL DDL parse/application','database concurrency/receipt atomicity','HTTP server/auth/security integration','real device, network latency, notification delivery','A0/B0/C0 approval']}
(ROOT/'evidence/validation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
