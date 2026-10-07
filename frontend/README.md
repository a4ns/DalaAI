# НарядAI frontend

Russian React/TypeScript/Vite shell. The first shell has no fake data, auth or business success. Unconnected features are visibly unavailable. Draft policy is memory-only; no service worker, offline outbox, persistent personal cache, external CDN or telemetry.

## Reproduce

Use Node 24.19.0 / npm 11.9.0 (Node engine requirement is in package.json).

```sh
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run dev
```

Default development and preview address: http://127.0.0.1:4172, fixed strict port. B6 browser tests use their own port 4176; test configuration/tests arrive independently. `test:ui` must not be claimed PASS before that package exists.

The API is same-origin `/api/v1` only; A5 owns HTTPS/session-serving integration. A Vite page without the API must show an honest connection failure. No API proxy or second auth protocol is configured here.

Exact planned dependency versions were verified against the npm registry on 2026-10-07; package-lock records the resolved closure. Browser/real API/device evidence is separate from lint/typecheck/build. Real Android, camera, push, persistence and end-to-end latency are not established by this shell.

## Ownership

B4 owns package/lock, app composition and shared code. Feature components expose UI view models and callbacks. Generated wire DTOs live separately under shared/api. B6 owns tests/configuration and independently reviews UI. No feature imports are added until the files exist in the assembled source.

## Accepted client and state boundary

The next increment restores a session with `/me`, logs in/out with same-origin session cookies and in-memory CSRF, and reads complete order-list sweeps. Unavailable business screens remain explicitly labelled. No live API integration is claimed by source/build checks.

Wire generation is deterministic and fails if the accepted contract SHA-256 differs:

```sh
python frontend/src/shared/api/generate_wire.py
```

It reads `coord/proposals/a6-contract-v1/contracts/openapi.yaml` (SHA-256 `b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`), using the existing contract-validation PyYAML dependency. Do not hand-edit `wire.ts` or `wire-schema.json`. The JSON validator covers the vocabulary used here; server authorization, semantic date validation and transactional business rules remain server responsibilities.

`ApiClient.prepareCreate/prepareCommand/preparePhoto` capture one operation ID and an immutable request body. `execute` shares a pending promise on double-click, preserves exact JSON/multipart body across unknown-result retries, rejects requests from an old session epoch and honors `Retry-After`. It never automatically creates replacement intent IDs. Tokens, PINs and payloads are not logged or stored in browser persistence.

`OrderStore` starts a fresh cursor sweep on each refresh, replaces list membership only after complete success, retains data with stale/incomplete labels on partial failure, and merges by nondecreasing order version. A replay receipt never overwrites a newer observed snapshot. Polling every two seconds is an implementation setting, not proof of the five-second end-to-end target. Workload `queue_count` represents explicit queued orders only, never all work or proof that a person is free.

`App.renderWorkspace` is the composition slot for independently delivered feature screens; it supplies the authenticated session, sessionKey, client and order store. Feature view models remain separate from DTOs. Before handing off a shared device after an unconfirmed logout, server revocation must be checked.

Read/session requests also honor `Retry-After` by method and normalized route, so polling does not bypass a server cooldown. Event sequence and aggregate version are different: event paging uses ascending sequence and the returned cursor. All decoded schema integers must pass `Number.isSafeInteger`; cursors/versions beyond JavaScript's safe integer range are rejected rather than rounded. Outgoing event cursors and photo assignment revisions have the same safe-integer guard. No lossless int64 parser is claimed.

## Assembled role workspace

The import ledger is `src/app/assembly-manifest.json`. Feature snapshots remain byte-identical to their reviewed source commits; app/shared adapters own transport and cross-screen state.

Master sessions can prepare creation and current-submission review requests; executor sessions can queue/accept/reject/start/pause/resume/submit. Manager sessions are read-only. Panel history drains authorized event pages and then reconciles the current order. These are real same-origin callbacks, never default synthetic success. A working HTTPS API/session/upload service must still be supplied by the backend/runtime lane; no credentials or runtime success are fabricated.

Photo preparation, upload pending/unknown/failed and confirmed staged IDs are separate. Selecting a file starts its staging intent; pending intent is reserved synchronously. Only confirmed, unexpired, context-matching IDs enter a command. Local preparation busy does not disable/cancel its own picker. Unknown command/upload outcomes stay unresolved even if a later retry is blocked offline or by a cooldown. Draft/photo state is memory-only and session-scoped; master tab switching preserves mounted state. A best-effort beforeunload warning is not a reload/Android recovery guarantee.

Session revalidation fences a changed CSRF handle, principal, role, active state or effective section scope. Mere section ordering, shift-status or expiry refresh does not invent an identity change. Command receipts and order/submission/history reads are checked against their requested object IDs before display or confirmation.

Current local evidence: aggregate lint/typecheck/build and independent synthetic source checks. Actual browser rendering, live API/database effects, Android capture, upload latency, notifications and deployment remain separately unverified. A manifest link alone does not prove installability or offline support.

## Executor operation quarantine

Executor operation tokens and drafts are retained per order/assignment inside the current authenticated session. A lost response followed by a403 remains unknown; it is not converted into a known failure. Inaccessible order details and drafts are excluded from the rendered list/form, while unrelated currently authorized orders remain usable. A newer assignment of the same order does not bypass its older unresolved operation. Retry is explicit and reuses the original token/body; nothing is resent automatically.

Only a new successful authorized list sweep can clear a per-order access fence. An unrelated receipt cannot clear that fence. A late receipt for an order omitted by a newer complete sweep can resolve the old operation without restoring the old order's visible data. Callback drafts and photos are keyed by assignment; late A callbacks do not update B.

Author-side synthetic controller probes: `node frontend/src/app/executorController.test.cjs`. These are in-process injected transport tests, not browser/API/database evidence.

## Optional device notifications

The settings panel is inert on mount. Its explicit buttons use the accepted additive [A0-0031 contract](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046265475); proposal.2 generated files are unchanged. Configuration, native subscription, backend binding and actual device delivery are separate states. Registration retries reuse the captured JSON bytes without an invented domain operation UUID. Logout starts a synchronous UI fence; expired/changed sessions cannot bind a late native subscription.

Only the reviewed notification worker is included: no API/photo cache, offline queue, background mutations or automatic permission request. Malformed push payloads are dropped with a fixed content-free marker per A0-0036. Existing subscriptions require an explicit clear and a separate fresh enable action. Settings failure does not block order work.

Synthetic integration check: `node frontend/src/app/pushSession.test.cjs` from repository root. Browser permission, HTTPS service-worker lifecycle, provider acceptance, real Android and locked-screen delivery remain NOT_RUN/BLOCKED; source tests do not establish those results.
