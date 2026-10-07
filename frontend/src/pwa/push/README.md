# B-107: explicit WebPush setup

Base: `c2fbe6a5ce5dd584a6edbdb8e3abf3501e7d1bfd`. Only `frontend/src/pwa/push/**` and `frontend/public/sw.js` belong to this package. B4 owns mounting, shared API/auth integration and dependencies; B6 reviews independently.

Accepted additive shape: [A0-0031](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046265475), authored by `a4ns`. It does not change proposal.2 or generated core wire files. [A0-0036](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046630968), also verified as authored by `a4ns`, requires dropping malformed payloads and confirms logical idempotency of identical registration bytes in the same current session.

## Integration contract for B4

- Construct one `PushController({ browser: createPushBrowserPort(), backend, isCurrentContext })` per authenticated `sessionKey`. `isCurrentContext` must compare the captured client epoch and current active principal; include session expiry in the guard. It must become false synchronously when logout/identity invalidation begins, not only after a new account mounts. Dispose on unmount. The controller performs no operations during construction.
- Connect `controller.subscribe` and `controller.state` to React (`useSyncExternalStore` is suitable). Render the controlled `PushSettings` with `state`, `onPrepare`, `onEnable`, `onResetExisting`, `onRetry`, `onDisable`. The corresponding controller methods are bound arrow functions. Disable controls when parent session/auth is busy. Never invoke enable/reset/retry/disable from an effect.
- Backend port: `getConfig(): Promise<PushConfig>`, `register(body: string): Promise<void>`, `remove(endpoint: string): Promise<void>`.
- `getConfig` calls GET `/api/v1/push/config` with current same-origin session cookies. Its response is configuration, NEVER current binding status. Validate exact semantics and key through `assertPushConfig` or the shared adapter.
- `register` sends the provided immutable JSON string unchanged to POST `/api/v1/push/subscriptions`; require exact 200 `{enabled:true}`. Browser permission/subscription are separate from this confirmation; none proves delivery. No operation UUID exists in this additive contract, so do not invent one. Explicit unknown-result retry sends identical captured bytes within the same context; A0-0036 requires this to be logically idempotent on the backend. This source package does not prove that backend guarantee.
- `remove` sends POST `/api/v1/push/subscriptions/remove` with `{endpoint}` and requires exact 204 empty. Both POSTs use current cookie, same-origin mode, accepted Origin handling and in-memory X-CSRF-Token. The browser supplies Origin; do not invent a second auth channel.
- Reject malformed/wrong-status responses as outcome-unknown for mutation calls. Existing `ApiError.outcomeUnknown` and `problem.code` are understood; `PushOperationError(code, outcomeUnknown)` is also exported. Preserve shared cooldown/Retry-After and identity fences. Never expose raw error bodies or subscription data in UI/logs.
- Revocation order is server remove confirmation, then browser unsubscribe and absence check. Partial failure remains visible. Backend logout/session expiry makes delivery ineligible; UI disposal alone does not revoke backend delivery. The controller deliberately does not run async cleanup from unmount, which could race another identity.

UI mounting is optional for ordinary order work; no unavailable-push condition should block the workspace.

## User-action flow and limits

1. `Проверить настройки` checks configuration and prepares the root `/sw.js` worker, without requesting notification permission.
2. A previously existing browser subscription is always unconfirmed. The explicit `Удалить прежнюю подписку на этом устройстве` action clears it. This deliberately avoids silently rebinding a subscription whose account cannot be established after reload. A separate enable click then subscribes fresh.
3. `Включить уведомления` synchronously reaches native `pushManager.subscribe`, which may display browser permission UI. Preparation/configuration are already available; no asynchronous prerequisite precedes that native call. `userVisibleOnly:true` and the accepted public key are used. There is no mount prompt or automatic re-subscription.
4. A 200 registration result confirms this operation for this login. Latest registration replaces the user's previous device; logout/expiry disables eligibility. Another device's later replacement is not observable through GET config. The displayed confirmation is a local snapshot, not an ongoing binding-status or delivery guarantee.
5. Unknown requests preserve captured body/context in memory; reload loses this local knowledge and returns to unconfirmed setup. No secrets, subscription copy, API data, photos, personal data, offline queue or user identity are stored in localStorage/IndexedDB/cache.

Native subscription creation cannot be cancelled by the component. If the context changes while it is pending, the old completion is ignored, with no backend registration or automatic browser cleanup. A shared in-page browser-operation guard prevents a new port from racing that pending operation; explicit setup then discovers/clears the existing subscription. Cross-tab enforcement and session validity remain server responsibilities.

This initial browser port requires HTTPS and standard ServiceWorker/Push APIs. It does not claim Safari/provider support. Root worker ownership is checked; a different root service worker is not overwritten. Activation wait is bounded at 10 seconds, without security workarounds or forced takeover.

## Worker policy

The worker is notification-only: no fetch handler, caches, background sync, API calls, private data, telemetry, credentials, external assets or mutation actions. It displays only accepted fixed text: `НарядAI` / `Есть обновление наряда. Откройте приложение.` / tag `naryadai-update`. Incoming fields are never passed into options.

A0-0036 supersedes the candidate's initial fallback proposal: malformed/empty/unknown-version or unexpected-field payloads are dropped without showing a notification. The worker accepts exactly the five fixed v1 fields and values; parsing is bounded to 4096 characters. Rejection logs only the fixed `NARYADAI_PUSH_INVALID_PAYLOAD` marker, without raw/parsed content or error details. A valid message alone produces the accepted generic notification. There is no live provider/subscription invocation in this package's tests.

Click ignores incoming targets, closes the notification, focuses an existing same-origin app-root window without navigation (preserving memory-only drafts), or opens fixed validated HTTPS `/`. There is no order deep-link protocol. B4's normal visibility/session refresh owns authenticated page data. No `skipWaiting`/`clients.claim` or offline/installability promise is added.

## Focused source checks

```sh
node --experimental-strip-types --test frontend/src/pwa/push/push.test.ts frontend/src/pwa/push/browser-worker.test.mjs
node --check frontend/public/sw.js
```

The 38 tests use fake browser/backend ports and a Node VM worker harness. They cover permission states, missing/disabled config, explicit existing-subscription reset, repeated clicks, unknown/rejected results, identical retries, identity interruption, partial revocation, browser-operation races and hostile click/payload inputs. They never request actual permission, create a native subscription, show a desktop notification or contact a provider.

Author focused TypeScript strict check and oxlint can use B4's already installed toolchain. This scoped branch has no frontend package or React installation because those are B4-owned. Final assembled lint/typecheck/build and B6 independent review remain required; source-only tests do not prove browser rendering.

Real browser permission behavior, HTTPS registration, native installation, Android/locked-screen delivery, actual backend/provider effects and end-to-end logout eligibility: **NOT_RUN**. No runtime PASS or device-delivery claim.

Platform references: [Push API](https://w3c.github.io/push-api/), [Notifications](https://notifications.spec.whatwg.org/), [Service Workers](https://w3c.github.io/ServiceWorker/).
