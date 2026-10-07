# Executor feature (B-103, generation 1)

`ExecutorScreen.tsx` exports `ExecutorScreen` and `ExecutorScreenProps`. The screen is a controlled React feature; it has no fetch calls, endpoint definitions, operation-ID generator, browser storage or synthetic success transport. View models and intents are camelCase presentation types in `types.ts`. The shared adapter maps them to the accepted proposal.2 schema (SHA-256 `b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`).

## Integration obligations

- Provide only the authenticated executor's authorized order snapshot. Change `sessionKey` on every login/identity generation and clear or isolate controlled snapshots/drafts at that boundary. The keyed subtree prevents prior-session local feedback from returning; the shell must also suppress stale network results.
- Provide complete resource states. `lastConfirmedAt` is the confirmation time of a successful fresh fetch, not the order's unchanged `updated_at`. Incomplete, stale, offline and failed results cannot become a confirmed empty list or unlock commands.
- Retain drafts per order in the shell. Feature inputs do not reset on rejection, conflict or unknown outcome. The displayed copy promises only current-session retention, not reload persistence.
- `onIntent` synchronously reserves one pending intent before starting transport. Allocate one operation ID in the shared client and freeze the complete original route/body/version. `onRetry` takes no payload and replays that stored operation exactly. Do not allocate a new ID, merge current draft values or automatically resend on reconnect.
- Keep `mutation` and `pendingIntent` across feature navigation. Without `operationScopeKey`, legacy unknown-result locking remains screen-wide. With a scope key, unknown results freeze only the affected scope; navigation to other authorized orders remains available. Only a confirmed response unlocks the command result. `onResolveConflict` discards/resets the failed intent only after the user has explicitly requested a refresh and explicitly reviewed current state. It never sends a replacement command.
- Opt into per-order operation isolation with a stable `operationScopeKey` identifying the order and assignment. Bind `mutation`, `pendingIntent`, `onRetry` and `onResolveConflict` to that exact key. Keep authoritative pending tokens and drafts outside the screen, indexed by scope; an unresolved older assignment must also block new intents for the same order. A different authorized order may proceed. Local feedback and late callbacks are fenced to the committed scope.
- When access to an order changes, remove its rows and private draft projection from visible props while retaining the original unknown token/draft in the controller. Supply `quarantinedIntentCount` for the generic notice; no inaccessible order name, number, description or raw error belongs in it. An inaccessible selected order can use an idle `none` scope. Never clear an unknown outcome or create a replacement ID merely because retry returns 403. Recheck only on explicit user action with normal server authorization.
- Every emitted `ExecutorIntent` includes `expectedAssignmentRevision`, and `onDraftChange` includes the selected assignment revision as its third argument. Validate these against current assignment before acting/updating a scoped draft. `expectedAssignmentRevision` is a UI-only fence and must not be added to the accepted wire command.
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
node_modules/.bin/oxlint --config .oxlintrc.json --deny-warnings src/mobile/executor
```

For an isolated feature checkout, set `EXECUTOR_DEPENDENCY_ROOT` to the frontend directory containing B4's installed dependencies. The test loader reads those dependencies; it does not install or edit them.

The suite covers model validation, actual React server rendering, and a deliberately minimal synthetic hook/event harness for double-click, retained draft, conflict, unknown replay, stale snapshot and late response cases. The hook simulator is not a React DOM/browser acceptance test. Typecheck/lint/build must also run on the assembled application. Real API persistence, authorization, photo upload, Android behavior, camera/push permissions and physical-device timing require independent evidence and are not established by this suite.

## Optional result-analysis disclosure (A0-0041)

`ResultAnalysisDisclosure` is a read-only component. `ExecutorScreen` accepts an optional `resultAnalysisDisclosure` ReactNode slot, rendered once inside the selected authorized detail: immediately before the in-progress result form, or beside done/review/rework/closed notices. It is absent in pause/reject forms and when no authorized order is selected. Omitting the slot preserves existing behavior. The approved initial composition supplies `<ResultAnalysisDisclosure />` with unknown defaults only; it is not connected to an API/config source. A separately approved A5 evidence seam and composition change are required before mode-specific or per-assessment wiring. The controller must bind any future result-specific disclosure to the current authorized scope, just as it does drafts. Pinned C110 behavior remains separate from this additive source delta.

Its optional `state` separates `configuredMode` (`unknown`, `openai`, `rules_fallback`) from `assessment.status` (`unknown`, `pending`, `completed`, `failed`) and the actual `assessment.method` (`unknown`, `openai`, `rules_fallback`). Missing input defaults to unknown for both. The caller must use server-confirmed assessment evidence, bind it to the current authorized order/submission attempt and discard stale identities; no provider completion may be inferred from configured mode, missing assessment payload, or a generic `model` result without verified provider identity.

The disclosure conditionally explains the OpenAI transfer of the work description and before/after photos. It does not identify specific files as sent, claim original unprocessed bytes were sent, enable a provider, or make network calls. Completed rules fallback explicitly does not confirm model analysis of photo contents. Unknown/pending/failed states never claim completed analysis, image verification, work correctness or safety. The final decision remains with the master.
