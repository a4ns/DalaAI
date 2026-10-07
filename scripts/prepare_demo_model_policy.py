#!/usr/bin/env python3
"""Explicit human-run setup, after inspecting/approving the synthetic fixture set.

Runs offline against an integrated backend containing accepted photos, model
adapter, camera derivation and this policy delta. Does not read/create a key.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--backend',required=True,help='Accepted integrated backend directory')
p.add_argument('--manifest',required=True,help='Human-reviewed synthetic fixture manifest JSON')
p.add_argument('--fixture-root',required=True,help='Only these explicit fixture files may be read')
p.add_argument('--expires-at',required=True,help='Timezone-aware expiry, e.g. 2026-10-08T17:00:00Z')
p.add_argument('--output',required=True,help='New policy JSON path; existing files are not overwritten')
p.add_argument('--confirm-reviewed-synthetic-fixtures',action='store_true',required=True,
               help='Human confirms this exact dataset was reviewed and approved for OpenAI egress')
a=p.parse_args()
sys.path.insert(0,str(Path(a.backend).resolve()))
from app.ai.demo_policy import build_demo_policy,read_demo_policy
manifest=read_demo_policy(a.manifest)
expiry=datetime.fromisoformat(a.expires_at.replace('Z','+00:00'))
policy=build_demo_policy(manifest,fixture_root=a.fixture_root,expires_at=expiry)
with Path(a.output).open('x',encoding='utf-8') as f:json.dump(policy,f,ensure_ascii=False,indent=2);f.write('\n')
print('Created exact synthetic-content policy; no key or network call used.')
