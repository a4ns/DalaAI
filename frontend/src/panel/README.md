# Read-only panel integration

`PanelScreen.tsx` exports `PanelScreen` and `PanelScreenProps`. Presentation models are in `types.ts`; no wire DTOs, API requests, commands or fixtures are shipped in the component. B4 owns API mapping and polling. B1 owns the master review mutation screen.

## Required parent behavior

- Supply authorized snapshot arrays through shared `ResourceState<T>`. Do not label initial failures as empty. Mark stale/offline/error/incomplete states accurately.
- Each poll/reconnect must perform a fresh complete authorized list sweep, including older reassigned orders. Keep the server's immutable-number descending keyset order and pinned upper bound. Replace membership only after the complete sweep succeeds. On partial failure retain the last successful snapshot, mark it stale/incomplete, and do not mix pages into a purported complete snapshot.
- Set `lastConfirmedAt` from successful real-clock confirmation, not a render or poll attempt. The panel makes no live-latency claim and does not invent total counts.
- Pass server `is_overdue` unchanged. The panel never derives deadlines from the browser clock or uses overdue as a status.
- Clear all resources and selected order on account/scope changes. Immediately pass `access="unauthenticated"` or `access="forbidden"` on session/panel authorization loss. Clear history on an order-specific 403/404 and do not retain a previously permitted audit response. Do not persist private snapshots in public caches.
- `history.snapshot.orderId` must identify its actual response. A mismatched response and a selected order absent from the accessible list are suppressed. Drain all event pages, set `incomplete` until successful, and reconcile the current authorized snapshot. Events display newest sequence first, deduplicated by ID.
- Translate dictionary IDs into labels/codes in B4. `activeOrderId` is only one representative active order; `queueCount` counts only `queued` orders. Zero queue plus no representative never implies free/available.
- Use `dataOrigin="synthetic"` when rendering a synthetic demo dataset. No demo data is a component default.
- Reports, exports, ratings and analytics are unavailable in the accepted API. Assessment is explicitly not loaded here; no invented pending verdict, score, model mode or human decision is shown.

## Verification

After B4 installs the approved frontend dependencies, from the repository root:

```sh
node frontend/src/panel/panel.test.mjs
```

For isolated worktrees without copied dependencies, pass the B4 frontend directory as the only argument. It is read-only dependency resolution. The script runs synthetic pure-function and React server-rendered checks, then a strict no-emit typecheck. No HTTP, database, browser, screen-reader or physical Android behavior is implied. B6 owns independent browser/a11y review. CSS is scoped to the panel and uses responsive layouts, non-color state text, labeled native controls and 64px buttons; actual browser/device behavior must still be measured.
