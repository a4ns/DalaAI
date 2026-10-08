# Grounded report controls: additive frontend handoff

Base: `064a7a3785a95d61d7150e7785ff17db892bc110`. Only new feature files and
`frontend/tests/node/ai-assistance.spec.ts` belong to this package. A5 owns the
shared client, App/Workspace/AnalyticsScreen/MasterScreen mounts and publication.
No package, lockfile, generated wire, existing controller or core form edits.

## Accepted backend seam

`POST /api/v1/reports/ai-summary` with JSON exactly
`{operation_id,start,end,report_kind:'shift'|'history'}`. Shift ≤24h, history ≤93
days. End must not exceed server domain time. Use the existing same-origin
session/CSRF path. `protocol.ts` defines the agreed decoder and request type.
The server captures a NEW current-authorized C111 snapshot; local `sourceRef`
selects/fences the dashboard source but is deliberately not sent as authority.

Response modes: `openai` selects grounded facts/actions; the server constructs
text and numbers. `recorded_fixture` is not a live call. `deterministic_fallback`
is useful factual output and never claimed as model success. Missing key,
policy or provider failure can return this successful factual fallback.
`reserved_upper_bound_microusd` is a reservation upper bound, not billed cost;
`actual_billed_cost` must remain null. Recommendations reference selected facts.

## Small shared-client patch for A5

Add one public method taking `Readonly<AiReportRequest>` and optional
`AbortSignal`, returning `Promise<AiReport>` (assignable to injected transport):

1. Validate `validAiReportRequest`, capture epoch, enforce existing current
   active master/real expiry check, and assert epoch before/after transport
2. Use existing `#request('/reports/ai-summary', ...)`: POST, exact JSON body,
   content type JSON, existing cookie + CSRF, `mutation:true`, current epoch,
   supplied signal, `maxBytes:1048576`, `validate:isAiReport`, `analytics:true`
3. After response call `decodeAiReport(value,request)` to bind operation/period/
   kind; preserve malformed success or interrupted/5xx POST as unknown outcome
4. No direct fetch, provider key, new storage, automatic retry or polling

The controller creates the operation UUID and freezes this body once. Unknown
retry uses the same object and operation ID. A new report action is blocked
while loading or unresolved. Backend retry can return freshly captured
`operation_already_attempted` fallback; it is not a replay of model text.

## AnalyticsScreen mount for A5

Import `AiReportControls` and add it next to the current analytics/report
controls, NOT in a polling effect. Keep it mounted for the current session:

- `client`: existing ApiClient
- `selection`: when `state.facts.status==='ready'`, the loaded facts' period
  `{start,end,sourceRef: facts.provenance.source_ref}`; otherwise null
- `request`: `(body,signal)=>client.<new report method>(body,signal)`
- `isAuthReady`: existing synchronous App auth/logout guard
- `isSelectionCurrent`: callback checking the captured facts object is still
  `controller.getSnapshot().facts.data`, facts are ready, and this selection is
  still the selected period; it must read the controller at call time
- `disabled`: existing `authBusy` plus any loss of current authorized source
- `onAccessLost`: clear analytics facts/report and new controls for401/403/404;
  A5 may add a narrow analytics `clearAccess` method. Do not retain old private
  facts beside a denied report

Mount under the authenticated session key already used for Workspace. A
changed selection calls `setSelection` and immediately hides former output;
late responses must not restore it. Controller timers only expire session data,
never make provider requests. Real session expiry is separate from domain time.

The view renders only React text, no HTML/Markdown execution or untrusted links.
It includes new snapshot dates, evidence UUIDs, missing historical photo counts,
source limitations, and human decision responsibility. The existing Provenance
view is reused rather than introducing a second analytics application.

## Verification boundary

`npm run check`, `npx tsc -p tests/tsconfig.json`, and focused Playwright
`UI_TEST_NO_SERVER=1 npm run test:ui -- ai-assistance.spec.ts --project independent-source`.
Tests inject synthetic transport and use static React SSR. They do not prove
HTTP/DB effects, browser events/layout, live OpenAI, mobile devices, final
mounts, or hosting. A production build before mounting excludes these new leaf
components from its bundle; TypeScript/lint still check their source. A5 must
run the assembled exact-SHA checks after wiring. Sole independent reviewer:
`review_dalaai_session_security`.

Pinned `__fixtures__/serializer-response.json` is produced by the backend
`render_summary` serializer from synthetic C111 fixture rows with deterministic
UUIDs. It is neither a model response capture nor PostgreSQL/HTTP evidence.
The related recommendation fixture is copied from the backend's frozen v1
contract example. Tests check both exact decoders as well as adversarial shapes.
