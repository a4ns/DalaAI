# Explicit durable worker runtime, canonical model-policy revision

This revision supersedes the earlier runtime implementation for integration. The earlier artifact `b3b37312…` remains frozen separately. It uses the final reviewed model stack `7a02fab2e89c8b9086ce6a53ad0994a19cf9d0e43247475ce75d6706fc683f0f` from `dalaai-model-ready.tar.gz`; install its six source files together. No model migration is added.

## Worker process and core settings

`PYTHONPATH=backend python -m app.worker_runtime`

Import is inert. Default `DALA_WORKER_ENABLED=false` exits without reading secrets, connecting to a database or claiming jobs. `--check` assembles/validates without processing jobs or invoking providers; disabled `--check` exits 2. Enabled model assembly may initialize the local budget ledger, which contains no credentials or raw content.

- `DALA_WORKER_ENABLED=true` explicitly enables the process
- `DALA_WORKER_DATABASE_URL` OR `DALA_WORKER_DATABASE_URL_FILE`: separate existing restricted worker LOGIN, never API/owner and no `DATABASE_URL` fallback
- `DALA_DATABASE_SCHEMA`: target isolated schema
- `DALA_WORKER_AI_ENABLED=true` by default
- `DALA_WORKER_NOTIFY_ENABLED=false` by default
- `DALA_WORKER_CHANNEL=web_push` by default; Telegram needs `DALA_WORKER_TELEGRAM_ENABLED=true`
- `DALA_PHOTO_STORAGE_ROOT`: same durable 0700 private store and UID as human CLOSE, mounted read-only for the worker
- `DALA_PHOTO_MAX_TOTAL_BYTES=1073741824`, bounded 8 MiB–10 GiB

After the full seven-file bootstrap, A5 must explicitly configure `DALA_WORKER_NOTIFY_ENABLED=true` and channel `web_push` to match its granted scope, even while `DALA_WEB_PUSH_ENABLED=false` pauses delivery. The general conservative default above is for an independently configured AI-only profile.

The worker and API are separate processes. A5 must pair the API notification channel with the worker channel. Existing synthetic jobs are not relabeled or replayed.

## Normal bootstrap, then key-only OpenAI activation

The normal isolated-demo configuration supplies:

- Actual `DALA_API_MODE=demo`
- `DALA_MODEL_APPROVAL_FILE`: the one-time owner-authorized named interactive demo policy
- `DALA_MODEL_PROJECT_ID` and `DALA_MODEL_INSTANCE_ID`: the actual trusted host project/instance
- `DALA_MODEL_BUDGET_PATH`: one durable persistent SQLite ledger shared by all closure/vision/future report callers; do not rotate/reset it
- The current private-photo store above

After that setup, adding the human-provided `OPENAI_API_KEY` OR `OPENAI_API_KEY_FILE` automatically selects authorized OpenAI processing. There is no additional model-enable flag, per-order hash manifest or image-selection file required. With no key, the actual rules worker runs and no provider transport or budget ledger is created. Optional explicit `DALA_MODEL_FORCE_OFF=true` keeps rules fallback and does not read the key. The old `DALA_WORKER_OPENAI_ENABLED` switch is not used.

The runtime calls the final A4 loader:

`load_interactive_demo_policy(policy, settings=settings, ledger=ledger, project_context=DemoProjectContext(project, instance), runtime_mode=actual_mode)`

`policy` uses the same strict JSON parser as A4's `read_demo_policy`, operating on the already bounded regular-file/no-symlink read. The path is not reopened after validation.

It passes `demo_project` to `ProviderAssessmentWorker` and automatically uses `CameraAssetsFactory(PhotoIntegrityVerifier(the_same_store).read)`. Wrong project/instance, missing policy, non-demo mode, expired policy, invalid budget or absent physical verifier fails closed. Policy authorization is rechecked for each authenticated persisted submission; uploads are not automatically labeled synthetic. Photo originals are unchanged. Current source/binding/derived-image proof and the real unexpired job fence are rechecked at completion.

A5 must surface the policy's processing disclosure: text and selected demo photos go to OpenAI; uploaded content is not automatically proven synthetic; the model recommends and the master decides. Configured OpenAI readiness is not evidence of a completed live model request.

The frozen profile pins `gpt-4.1-mini-2025-04-14`, max400 output tokens, eight-second timeout, no tools/redirects/retries, bounded responses. Reservations are $0.42 per call, five/minute, one active client call, $50 lifetime and at most $10 for starts before Oct8 09:00 UTC+5 (04:00Z). After that cutoff only the same $50 total cap remains; old reservations are retained. Actual billed cost is unknown. Policy default expiry is Oct8 23:59 UTC+5 (18:59Z), independent of the night budget cutoff. No live provider call was made by this package.

## Notification channels

Web Push uses the actual hard-bounded `BoundedPostgresWebPushAdapter` (22-second bound including database/network/cleanup), within the existing 30-second worker lease. Configure existing operator-supplied `DALA_WEB_PUSH_ENABLED=true`, `DALA_VAPID_PUBLIC_KEY`, `DALA_VAPID_SUBJECT`, and `DALA_VAPID_PRIVATE_KEY` OR `_FILE`.

Telegram is optional: `DALA_WORKER_TELEGRAM_ENABLED=true`, channel `telegram`, `TELEGRAM_MODE=live`, `TELEGRAM_SYNTHETIC_DEMO=1`, approved `TELEGRAM_DEMO_BINDINGS_JSON`, and `TELEGRAM_BOT_TOKEN` OR `_FILE`. No automatic cross-channel fallback or fanout occurs.

Disabled push or disabled/dry-run Telegram never reconciles/claims that channel's jobs. Explicit invalid live config fails startup before claims. With AI enabled, a disabled notification lane remains paused while AI proceeds; a notification-only process without a configured live adapter refuses startup. Provider acceptance never claims phone display/read/sound/vibration.

## Bounds, clocks and shutdown

One process works sequentially with no prefetch or parallel provider fanout. Reconciliation pages contain one order; restart begins a deduplicated sweep. First-lane order rotates for fairness.

- `DALA_WORKER_TICK_SECONDS=1`, range 0.1–60
- `DALA_WORKER_TICK_ADMISSION_SECONDS=25`, range 1–60
- `DALA_WORKER_AI_LIMIT=1`, range 1–20
- `DALA_WORKER_RECONCILE_LIMIT=25`, range 1–1000
- `DALA_WORKER_DISPATCH_LIMIT=1`, range 1–20
- `DALA_WORKER_MAX_CONSECUTIVE_ERRORS=5`, range 1–20

The admission bound stops new units, not in-flight SQL. Fresh connections have two-second connect/statement timeouts and one-second lock timeout. SIGINT/SIGTERM stop admission and finish the current bounded unit. Unknown interrupted dispatch keeps its durable no-blind-resend fence. Every tick sleeps; errors back off to at most60 seconds and eventually exit nonzero. A5 owns external supervision and stop grace.

Real leases/retries/approval/session expiry use a dedicated UTC wall clock. Domain time uses a separate wall clock. This candidate does not read `TIME_SCALE`/`DEMO_NOW`; the separate demo-clock proposal remains unmounted. Status logs contain fixed codes and aggregate counts, not secrets, raw exceptions, prompts, photos or person/job identifiers.

## Provisioning and evidence

See `docs/worker-capabilities.md` for the fresh-only explicit001/002/003/004/005/011/012 bootstrap, separate capability-completion marker and three existing roles. The old render-only `worker_profile.py` remains available. Startup validates exact grants and guards, including true-only NOT NULL photo lock permission; no credential or grant is created by the worker runtime itself.

Tests:

`PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_worker_runtime.py -v`

`PYTHONPATH=backend python -m unittest discover -s ops/provision/tests -p test_worker_capabilities.py -v`

Current local: 26 runtime/config/assembly tests and 7 bootstrap-source tests PASS, plus existing profile tests. Mock catalog/source tests are not PostgreSQL or hosted evidence. Disposable bootstrap PG, actual worker processing, Compose/managed deployment, provider/model quality, mobile Playwright and real phones remain NOT_RUN here. No remote writes, live grants, credential creation, provider sends or deployment occurred.

Assessment `created_at` is business/domain time, sampled once after the locked
snapshot and lease checks and reused for the order/event occurrence. This matches
submission and human-review chronology. Event `recorded_at`, lease completion,
retry/backoff, provider budgets/approvals and duration remain real/monotonic.
A business clock earlier than the locked snapshot fails the completion; no
existing immutable timestamp is rewritten. Paused/advanced clock acceptance
includes protected JSON/binary report capture.
