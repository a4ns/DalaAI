# Optional executor advice: additive frontend handoff

Base: `064a7a3785a95d61d7150e7785ff17db892bc110`. A5 alone mounts the shared
client/form/workspace files. This feature does not issue, reserve or reassign
orders, and it does not call a model. It is a partial deterministic baseline;
missing specialty/qualification/permit/equipment-suitability data remain unknown.

## Accepted transport

`GET /api/v1/recommendations/assignees?section_id=<UUID>&limit=3` with optional
`work_code_id=<UUID>`. No body. Current create draft has no work-code field, so
use `work_code_id:null` locally and OMIT the query key. Do not send equipment,
free text, role, user, draftKey, dictionaryKey, token or session in URL/body.

A5 adds a shared ApiClient method taking `AssigneeRecommendationRequest` plus
optional signal. Capture/check epoch, active master/real session expiry and
selected authorized section. Use existing same-origin GET `#request` with
`validate:isAssigneeRecommendations`, max512KiB and Retry-After handling, then
`decodeAssigneeRecommendations(value,request)` to bind section/work-code/limit
and reject expired snapshots. Keep failures as errors, not empty success.
`protocol.ts` matches the backend author's `assignee-contract.md` v1.

## Minimal existing-form slot for A5

Add an optional `renderAssigneeRecommendations` to `MasterScreenProps`:

`(context:{draft:MasterCreateDraft;disabled:boolean})=>ReactNode`

Render it immediately after the executor select, inside the existing create
fieldset. Pass `draft` and `disabled:createLocked || !createReady`. All new
feature buttons explicitly use `type="button"`; none submits the parent form.

Workspace supplies an `AssigneeRecommendations` component using:

- Existing `client`, `isAuthReady`, and current master dictionaries
- `context:null` unless dictionaries are complete/fresh/ready and a currently
  authorized section is selected
- Otherwise `{sectionId:draft.sectionId,workCodeId:null,brigadeId:draft.brigadeId,
  draftKey,dictionaryKey}`. `dictionaryKey` is the current confirmed dictionary
  generation/stamp. `draftKey` is a local fingerprint of draft generation,
  section, equipment, type, brigade, task description, priority, due time and
  norm; never include a provider prompt or send this fingerprint to server
- `executors`: current authorized dictionary rows with fields
  `{id,label,sectionIds,brigadeId,onShift}`; existing MasterExecutor fits
- `request:(query,signal)=>client.<new advice method>(query,signal)`
- `disabled`: the slot's disabled flag OR authBusy/offline/stale dictionaries
- `isDraftCurrent`: a synchronous callback checking session readiness, current
  dictionary/fingerprint and that create is not pending/unresolved. Read
  current refs/controller state at action time, not only a stale render value
- `onChoose(id)`: update ONLY `executorId` through the existing guarded
  `changeCreateDraft({...currentDraft,executorId:id})`; recheck create lock and
  current authorized section/on-shift/brigade dictionary eligibility first
- `onAccessLost`: invalidate/purge the current dictionary on401/403/404 before
  a future choice; existing refresh can re-establish it

Do not key the component by executorId or auto-select rank1. Choice is an
explicit click and only fills the existing select. Final issuance stays the
separate existing button and authoritative backend command validation.

The controller rejects returned candidates absent/ineligible in the current
section dictionary. Selected brigade filters the returned shortlist locally;
`eligible_count` remains the server's total SECTION count and is labelled so.
An empty brigade shortlist does not claim no one else exists. One demo candidate
is shown as one; unknown human quality is never substituted with0. Equal rank
is a rules tie, not a personnel rating. Evidence includes dated current work
and human-close references, scoped to server-authorized areas.

Responses are discarded on context/dictionary change, failed refresh, auth loss,
real session expiry and server recommendation expiry. The ready TTL is bounded
by30 real seconds even if the client clock lags. Action-time expiry checking
also covers a delayed background timer. No polling or automatic re-request.

## Verification

See `../aiReports/README.md`. Focused source/SSR checks are synthetic and do not
prove actual browser choice, API/DB authorization or final mounted behavior.
No live provider call, publication, dependency, cache or storage is introduced.
