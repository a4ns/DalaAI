# Executor feature (B-103, generation 1)

`ExecutorScreen.tsx` exports `ExecutorScreen` and `ExecutorScreenProps`. The screen is a controlled React feature; it has no fetch calls, endpoint definitions, operation-ID generator, browser storage or synthetic success transport. View models and intents are camelCase presentation types in `types.ts`. The shared adapter maps them to the accepted proposal.2 schema (SHA-256 `b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`).

## Integration obligations

- Provide only the authenticated executor's authorized order snapshot. Change `sessionKey` on every login/identity generation and clear or isolate controlled snapshots/drafts at that boundary. The keyed subtree prevents prior-session local feedback from returning; the shell must also suppress stale network results.
- Provide complete resource states. `lastConfirmedAt` is the confirmation time of a successful fresh fetch, not the order's unchanged `updated_at`. Incomplete, stale, offline and failed results cannot become a confirmed empty list or unlock commands.
- Retain drafts per order in the shell. Feature inputs do not reset on rejection, conflict or unknown outcome. The displayed copy promises only current-session retention, not reload persistence.
- `onIntent` synchronously reserves one pending intent before starting transport. Allocate one operation ID in the shared client and freeze the complete original route/body/version. `onRetry` takes no payload and replays that stored operation exactly. Do not allocate a new ID, merge current draft values or automatically resend on reconnect.
- Keep `mutation` and `pendingIntent` across feature navigation. Unknown results freeze draft editing and new commands. Only a confirmed response unlocks the command result. `onResolveConflict` discards/resets the failed intent only after the user has refreshed and explicitly reviewed current state. It never sends a replacement command.
- `onIntent`/`onRetry` return the actual `MutationOutcome`, not optimistic confirmation. An uncaught adapter exception is treated as unknown. A confirmed command still needs a fresh order snapshot with a newer version before the next command.
- Map submit payload fields to `work_description`, `work_code_id`, `materials[].material_id`, `after_photo_ids`, and `comment`. Empty work/invalid quantities/unknown or duplicate materials are rejected. Missing work code and missing unplanned after-photo remain explicitly incomplete, reviewable submissions.
- Set selected-order `photoBusy` while preparation/staging is in progress or its outcome is unknown; optional `photoBusyReason` explains the exact blocking step. This disables result submission without inventing a pending order command. Scope the flag to session/order/assignment and enforce the same guard inside the adapter before transport. Retain staging results independently until they can be safely reflected in the draft.
- `renderPhotoPicker` is an optional adapter-owned hook. Its callback must contain only IDs from confirmed stage responses; local B5 `PreparedPhoto` files do not count as uploaded evidence. Carry order ID, section ID and assignment revision in the staging adapter. No upload implementation is claimed by this feature.

## Selection accessibility

Assignment cards are native `type="button"` controls. Deliberate pointer or keyboard activation focuses the selected detail heading and brings it into view, including below long mobile lists. The heading has `tabIndex=-1` and a visible focus outline. Initial selection, polling and draft updates do not request focus. Focus dispatch is covered by synthetic hook tests; actual browser scrolling and Android assistive technology remain unverified.

## Checks

After assembling shared dependencies, from `frontend`:

```sh
node --test src/mobile/executor/executor.test.cjs
```

For an isolated feature checkout, set `EXECUTOR_DEPENDENCY_ROOT` to the frontend directory containing B4's installed dependencies. The test loader reads those dependencies; it does not install or edit them.

The suite covers model validation, actual React server rendering, and a deliberately minimal synthetic hook/event harness for double-click, retained draft, conflict, unknown replay, stale snapshot and late response cases. The hook simulator is not a React DOM/browser acceptance test. Typecheck/lint/build must also run on the assembled application. Real API persistence, authorization, photo upload, Android behavior, camera/push permissions and physical-device timing require independent evidence and are not established by this suite.
