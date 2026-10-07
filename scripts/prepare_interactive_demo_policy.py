#!/usr/bin/env python3
"""One human/operator setup for the owner's explicitly authorized demo scope.

Does not read a key, send data, create credentials, deploy or modify originals.
Morning enable then needs only OPENAI_API_KEY in the preconfigured runtime.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--backend',required=True)
p.add_argument('--project-id',required=True)
p.add_argument('--instance-id',required=True)
p.add_argument('--expires-at',default='2026-10-08T18:59:00Z',help='Default: Oct8 23:59 UTC+5, beyond morning enable')
p.add_argument('--output',required=True)
p.add_argument('--confirm-owner-authorized-demo-processing',action='store_true',required=True)
a=p.parse_args()
sys.path.insert(0,str(Path(a.backend).resolve()))
from app.ai.demo_policy import build_interactive_demo_policy,PROCESSING_DISCLOSURE
policy=build_interactive_demo_policy(project_id=a.project_id,instance_id=a.instance_id,
    expires_at=datetime.fromisoformat(a.expires_at.replace('Z','+00:00')))
with Path(a.output).open('x',encoding='utf-8') as f:json.dump(policy,f,ensure_ascii=False,indent=2);f.write('\n')
print(PROCESSING_DISCLOSURE)
print('Created named-demo policy; no network or credential operation performed.')
