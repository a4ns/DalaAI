"""Execute frozen HTTP lifecycle harness on disposable assembled source bytes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
inputs = json.loads((ROOT/'backend/review/sessions/REVIEWED_INPUTS.json').read_text())['files']
for name, expected in inputs.items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Frozen input changed: {name}')
if not os.environ.get('DALA_TEST_DATABASE_URL'):
    raise SystemExit('NOT_RUN: explicit disposable PostgreSQL DSN required')
sha = os.environ.get('GITHUB_SHA') or subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
report = ROOT/'vertical-acceptance.json'
with tempfile.TemporaryDirectory(prefix='dalaai-http-assembly-') as temporary:
    backend = Path(temporary)/'backend'
    shutil.copytree(ROOT/'backend',backend,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    # Candidate keeps 003 proposed. Only this disposable harness assembly promotes
    # its unchanged bytes; author PG fixtures separately apply the same proposal.
    shutil.copyfile(backend/'db/proposals/003_auth_rate_limits.sql',backend/'db/migrations/003_auth_rate_limits.sql')
    env = dict(os.environ, DALA_ACCEPTANCE_DISPOSABLE='1', PYTHONDONTWRITEBYTECODE='1')
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT/'backend/acceptance'),str(backend),env.get('PYTHONPATH','')])
    result = subprocess.run([sys.executable,'-m','vertical_acceptance.run','--backend',str(backend),'--source-sha',sha,'--report',str(report),'--run'],env=env)
    if report.exists():
        data=json.loads(report.read_text())
        print(json.dumps({key:data.get(key) for key in ('status','source_sha','setup','phases','cleanup','error_type','reason')},indent=2))
    raise SystemExit(result.returncode)
