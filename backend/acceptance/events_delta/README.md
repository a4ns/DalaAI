# Separate event-page orchestration delta

The frozen v1 lifecycle package and its manifest are unchanged. This delta uses
the real frozen A6 event router on top of that package's real component assembly.
It has no fake service, pure-parser test, simulated transaction or database skip
that can become a green API result.

Frozen event input source-content hash:
`f1ed90bf762e462a6c26e416723af18261e0aa22e8c020e51efb1cb79375ca16`.
No extra migration is required. Import seam:

```python
from app.order_events.http import create_order_events_router
from app.order_events.service import OrderEventService
create_order_events_router(OrderEventService(connect, real_clock=clock))
```

The delta drives real HTTP create → accept → start → submit, then drains event
pages at limit 2 and reconciles the order snapshot. The five returned event IDs
must equal the command receipts; their sequence is 1..5 while order versions are
1,2,3,4,4. Thus the two submit events share a version and remain separate events.

It checks a foreign assignee's 403, then reassigns through a real master command.
The old assignee loses event access, even with a known cursor. The new assignee
can read retained previous-assignment history and the new tail. Its real database
session is explicitly expired as a synthetic fixture mutation; the same cookie
then receives 401. A new Python process and new HTTP logins must recover identical
event pages and current snapshot; a new login cannot restore the old assignment's
permissions. No bearer token is saved or copied between processes.

The direct session expiry is the only post-seed database write outside the real
HTTP APIs. It occurs solely in the invocation's random disposable schema. There
is no physical DB restart or actual network interruption. Expiry-after-lock-wait
and SQL concurrency tests remain A6's separate gate.

## Exact staging and run

Use a new directory; do not mutate the frozen v1 assembly. The source freeze is
verified before these inputs are consumed. A5 may instead point directly at its
new exact-SHA backend containing the accepted event module.

```sh
ROOT=/workspace/scratch/b95acfcfe14a
H="$ROOT/dalaai-vertical-acceptance"
cd "$H"
python - <<'PY'
from pathlib import Path
from hashlib import sha256
import json, shutil
source = Path('../dalaai-a6-events')
freeze = json.loads((source/'evidence/source-freeze.json').read_text())
for name, digest in freeze['owned_files'].items():
    assert sha256((source/'backend'/name).read_bytes()).hexdigest() == digest, name
destination = Path('events_runtime/backend')
assert not destination.exists(), 'Choose a new isolated directory'
shutil.copytree('runtime/backend', destination, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
shutil.copytree(source/'backend/app/order_events', destination/'app/order_events', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
PY

export PYTHONPATH="$H:$ROOT/dalaai-a2-sessions/.test-deps${PYTHONPATH:+:$PYTHONPATH}"
# These variables select the same explicit local disposable service already
# authorized for the first lifecycle gate, with a new random schema per run.
export DALA_TEST_DATABASE_URL='postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/TEST_DB'
export DALA_ACCEPTANCE_DISPOSABLE=1
python events_delta/run_events.py \
  --backend events_runtime/backend \
  --report events_delta/evidence/api-event-acceptance.json --run
```

Run this **after** v1 inside A5's existing serialized job, not a competing pipeline.
Exit codes retain 0 PASS / 1 FAIL / 2 NOTRUN. Missing DB/modules never count as a
real API pass. The report separately inventories the actual `app.main` event
route: until it is found there, the status is **NOT_MOUNTED**, regardless of test
composition. A mounted route is still `MOUNTED_UNEXERCISED` until actual application
factory acceptance covers it.

Current local result: construction/syntax checks only; actual PostgreSQL event
orchestration is **NOTRUN**. See `evidence/preflight.json`. Uploads, providers,
reports, network/TLS, browser/Android and restricted application-role security
remain outside this delta.
