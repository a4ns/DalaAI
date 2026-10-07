# Master mobile create and review

`MasterScreen.tsx` exports `MasterScreen`, `MasterScreenProps`, all lane view models and empty draft factories. The screen performs no network requests. All wire DTO conversion, session handling, operation IDs, receipts and retries belong to the shared adapter.

## Integration requirements

- Supply controlled `createDraft` and per-order `reviewDrafts`. Keep drafts for the authenticated user only. Mount with a user identity key, never reuse a previous user's draft or mutation adapter.
- `onCreate` and `onReview` return the shared `MutationOutcome`. A fulfilled promise alone is not success. `confirmed` must come from a validated command response. Rejected transport/callback promises conservatively become an unknown outcome.
- `onRetryCreate` and `onRetryReview(orderId)` must replay the exact captured operation ID, expected version and immutable request body. They must not construct a new command from current form state. The screen freezes the draft during unknown outcomes and prevents in-flight double clicks.
- Preserve the mounted screen through ordinary tab changes, or restore pending adapter state before permitting new work. The adapter must refuse fresh operations while a prior receipt outcome is unresolved, including after a remount. The screen has no durable offline outbox and makes no persistence claim after page close/reload.
- A conflict preserves the draft. Another confirmed resource load and explicit user resolution are needed before a new intent is submitted. Do not treat a generic list refresh as confirmation of an unknown command result.
- Use dictionary labels in the view model. `dueLocal` is a UTC+5 wall time; `dueLocalToIso` validates and converts it without using device timezone. Omit `domainNow` until the server's domain time is known; the server remains authoritative for future-deadline validation.
- Populate `submission` only from an authorized submission response. Unknown details/completeness block closing. Missing work code or mandatory after-photo blocks closing even with a high AI score. Rework is permitted with a reason for the current loaded attempt; null/pending AI does not block otherwise complete manual review.
- Connect `renderBeforePhotos` to the PWA staged-upload adapter. Only completed stage IDs belong in `beforePhotoIds`; uploading/error states must be exposed by that control. Set `beforePhotosBusy` while selected photos are processing/staging; the screen then prevents issuing. Delayed photo callbacks patch the latest controlled draft only while the original section/form generation is still current and the screen is mounted and unlocked. Without that control the screen explicitly says upload is not connected. `renderAfterPhotos` displays only authorized evidence.
- `activeOrderId=null` and `queueCount=0` do not prove availability. The screen labels that state “Занятость не подтверждена”.

## Verification

All tests in this folder are synthetic. The render smoke uses real React server rendering of locally transpiled source, with CSS ignored; it does not execute events, effects or browser layout. They do not prove live API behavior, authorization, database persistence, phone camera access, notification delivery, Android usability or the one-minute/six-tap target.

From repository root with Node 24:

    node --test frontend/src/mobile/master/masterModel.test.mjs

After assembly under B4's frontend, use its package commands for TypeScript/lint/build and B6's independent interaction harness. An isolated checkout can run the scoped check using a read-only dependency tree and shared source:

    node frontend/src/mobile/master/verify.mjs /path/to/B4/frontend

The scoped checker writes ignored temporary files only below this feature's `.verification` folder. It does not install dependencies or edit the shared checkout.
