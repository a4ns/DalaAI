# НарядAI frontend

Russian React/TypeScript/Vite shell. The first shell has no fake data, auth or business success. Unconnected features are visibly unavailable. Draft policy is memory-only; no service worker, offline outbox, persistent personal cache, external CDN or telemetry.

## Reproduce

Use Node 24.19.0 / npm 11.9.0 (Node engine requirement is in package.json).

```sh
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run dev
```

Default development and preview address: http://127.0.0.1:4171, fixed strict port. B6 browser tests use their own port 4176; test configuration/tests arrive independently. `test:ui` must not be claimed PASS before that package exists.

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
