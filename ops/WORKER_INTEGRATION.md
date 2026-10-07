# Worker integration and executable gates

The API, worker and owner-only bootstrap are assembled from the reviewed AI,
delivery, reconciliation, priority-notice, Web Push, model/camera and worker
runtime packages. Telegram is available as an explicitly selected alternative;
the default full Compose lane is Web Push. No provider is contacted by the test
gates. No deployment or live credentials are created by source publication.

`python ops/run_worker_source_gates.py` requires an explicit disposable
`DALA_TEST_DATABASE_URL` and executes 18 AI, 20 delivery, 14 reconciliation,
14 priority-notice, 9 push, 8 model-provider and 7 independent PostgreSQL cases.
Every count is enforced and a skip fails the gate. The independent probe bytes
are preserved under `backend/review/workers`; its migration path is supplied by
the runner so it exercises this integration's schema.

`python ops/run_worker_runtime_tests.py` exercises the full owner/API/worker
profile using separate temporary LOGINs in the disposable CI database. It must
prove actual restricted startup and a persisted rules assessment. Local unit
success is not a substitute for this PostgreSQL gate.

The full Compose job invokes the human launcher in disposable localhost CI,
waits for a real rules worker verdict through HTTPS, then verifies human CLOSE
and repeat startup. C-110 deliberately keeps its worker-free base profile and
measures the manual lifecycle separately. Synthetic browser rendering, this
HTTP smoke, live providers and physical Android are distinct evidence.

Runtime settings:

- `DALA_NOTIFICATION_CAPABILITY=true` requires 011/012 and pairs with
  `DALA_DELIVERY_CHANNEL=web_push` (or an explicitly selected Telegram lane)
- `DALA_PUSH_CAPABILITY=true` requires 005 subscription storage and mounts the
  authenticated push routes even while delivery is disabled
- `DALA_WEB_PUSH_ENABLED=false` pauses notification consumption, preserving
  pending jobs; it does not revoke the provisioned schema/grant profile
- Worker AI and notification capabilities are both true in the full profile
- `OPENAI_API_KEY` selects the configured named demo model policy; no key selects
  rules fallback. `DALA_MODEL_FORCE_OFF=true` is the explicit override
- Security/TTL/lease/budget time remains real UTC; optional accelerated demo
  clock proposals are not installed by this bundle

The priority hook runs only for a real notification channel. The old synthetic
channel retains compatibility with the four-migration base. API startup checks
the real-channel schema before admission. Shared service/main files were amended
directly; no stale dependency snapshot replaced them.

The photo-capacity correction excludes expired unattached stages after acquiring
the owner lock. Receipts and bytes remain retained; the physical byte cap still
bounds disk usage. Its existing PostgreSQL and restricted-role gates run again
on this integration.

Exact CI evidence belongs to the resulting commit/run. At source preparation,
live OpenAI, device Web Push, hosted Render and physical Android are NOT_RUN.
