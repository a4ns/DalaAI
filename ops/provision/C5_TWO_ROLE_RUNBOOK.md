# C5 handoff: two-role, two-session real browser lifecycle

Status: **SCRIPT PREPARED; BROWSER/PHONE RUN NOTRUN**. C5 performs the browser/device
work. A5/operator owns hosting, migration/fixture application and private credential
handoff. This file contains no account PIN or administrative credential.

## Before the rehearsal

- Use the exact accepted mounted build; record full SHA and verified HTTPS URL
- Frontend and `/api/v1` must share the configured exact HTTPS origin. A UI proxy
  path, DNS/TLS setup or live URL is not invented here; obtain it from A5/B0
- A5 readiness is actually 200 after successful restricted-role startup
- Operator-applied fixture is `dalaai-live-vertical-demo-v1`; obtain its safe JSON
  output from `provision_synthetic_demo.py` for reference IDs
- Two physical phones for the phone claim, or separate browser profiles for a
  browser-only run. Record which; two tabs sharing cookies are not two sessions
- Phone/profile A: master `DALA-DEMO-MASTER`; phone/profile B: executor
  `DALA-DEMO-EXECUTOR`. Enter each private PIN via the approved operator handoff
- Confirm the screen visibly identifies synthetic demo data. Do not use actual
  enterprise equipment, employees, pictures, badges, names or contacts
- Do not capture login payloads, cookies, CSRF values, owner consoles or secrets
  in the video/screenshots/public journal

The frontend URL, selectors and exact button labels depend on B0's accepted UI.
Below are actions and API oracles, not invented UI routes or browser automation.

## Main planned-work path, steps 1–5 for the early checkpoint

### 1. Separate real logins and scoped catalogues

Log in as master on A and executor on B. Refresh once to check `/me` restores the
session and CSRF safely. Each session must retain its own role. The dictionary
view should include the synthetic section/equipment/work code/material; the
executor must not gain a master's issue/review capability.

API oracles: login 200 + secure cookie; `/me` 200; `/dicts` 200. Do not copy the
returned tokens into evidence. If blocked, stop and record the actual 401/403/
429/503; do not substitute a seeded session or share one cookie between roles.

### 2. Master issues a fresh planned order on A

Use the synthetic section and equipment, responsible executor `DALA-DEMO-EXECUTOR`,
type `planned`, normal priority, 30-minute norm and a deadline strictly in the
future (for example, 30 minutes after the actual issue time). Description:
“Синтетическая плановая проверка демонстрационного стенда”. Comment:
“Только демонстрационные данные”. Before-photo is optional; omit it in this
baseline because the current gate does not claim physical photo validation.

Start timing before the first create action and stop at confirmed issue. Record
actual elapsed time and taps, including stated treatment of typing/pre-filled
data; do not assume the ≤1 minute/≤6 taps target passed.

API oracle: POST `/orders` → 201, status `issued`, version 1, one operation ID for
this intent, returned order ID and event IDs. Record the safe order ID. A spinner
or optimistic local card is not commit confirmation.

### 3. Executor discovers, accepts and starts on B

Find the same order via the real assigned-order list. Record time from confirmed
issue on A to first visible state on B. Accept, then Start. Master A must see the
committed changes. Measure actual propagation rather than inferring it from a
polling interval; >5 seconds is a failed/limited real-time gate.

API oracles: GET `/orders` contains the assigned ID; accept → 200 `accepted` v2;
start → 200 `in_progress` v3. Both roles' fresh detail GETs agree with current DB
state. No request body is allowed to choose actor/role.

### 4. Executor submits actual filled planned-work result on B

Work text: “Синтетическая плановая проверка выполнена, проведён пробный осмотр”.
Select `DALA-DEMO-WORK`; add `DALA-DEMO-MATERIAL`, quantity 1.25; use an explicit
empty photo list and comment “Требуется решение мастера”. Submit once and wait
for server confirmation.

API oracle without optional extra commands: submit expected_version 3 → 200,
status `ai_review`, version 4, immutable submission ID, two event IDs (`done`,
then `ai_review`) sharing version 4. No externally committed standalone `done`
snapshot. Planned result completeness is `complete`.

If events API is mounted in the accepted build, drain pages by returned sequence,
then reconcile detail. Sequence is not version: submit adds two events at one
version. Until actual app mounting is verified, event-page UI is NOTRUN.

Do not label pending/empty assessment data as a model review. Current runtime
supports a human decision with hard gates; no model/provider invocation or phone
notification is established by this path.

### 5. Master reviews and closes on A; executor verifies on B

Open the real current submission. Confirm work/code/materials and completeness.
Choose Close with reason “Синтетический плановый результат проверен мастером”.
Leave score unscored/null unless the operator deliberately supplies a documented
demo score. The executor must not be able to perform the master's decision.

API oracle: review uses the current submission ID and version 4 → 200 `closed`,
version 5. Fresh detail and immutable submission review show the authenticated
master's decision. Refresh both sessions; closed state and review persist.

These version numbers apply only to the five-step baseline. If an optional pause,
resume, priority change, reassignment or assessment occurs, use fresh actual
versions and record the additional events rather than forcing an old number.

## Separate mandatory failure drills

1. **Draft conflict:** on a new test order, keep a filled master draft open while
   the executor advances the version. Submit the old intent. Expect structured
   409 VERSION_CONFLICT/current_version, current-state reload, and visible
   preservation of entered values. No automatic overwrite/new-ID resend. The
   existing API harness proves the response contract; C5 must verify actual form
   retention and explicit resolution in the browser
2. **Unknown result / retry:** use C5's approved network-failure setup around one
   synthetic request. The UI must say the outcome is unconfirmed and retain the
   exact operation ID and payload. Retry must return the original receipt without
   another order/submission/event. Do not fake a successful response or count
   switching offline before sending as evidence of a lost committed response
3. **Incomplete unplanned result:** create a fresh `unplanned` order. Accept/start
   and submit without an after-photo. It must be explicitly incomplete; master
   Close must return 409 INCOMPLETE_SUBMISSION even with a high score. Rework with
   a reason is allowed; executor can restart. Do not claim a complete unplanned
   photo path until the accepted upload/private-blob validator actually exists
4. **Session isolation:** log out one device and verify `/me` becomes 401 and that
   device cannot continue writes. Do not run old queued work as the other user.
   Account-switch draft/cache behavior must follow B0's accepted UI policy
5. **Foreign-object 403:** the minimal two-account fixture contains no third
   executor. Use only C5's separately authorized synthetic third account/order
   fixture for this drill; never probe real or unrelated objects. Until supplied,
   this browser drill is NOTRUN. The real API acceptance harness already exercises
   an isolated foreign executor separately

## Evidence and stopping conditions

Record full build SHA, UTC/local timestamp and timezone, verified origin, physical
devices/browser versions/network, synthetic fixture version, safe order/submission
IDs, step outcomes, request status/version/event-count oracles, observed timing,
tap count and only redacted screenshots/video. Mark each requested gate PASS,
FAIL or NOTRUN. Backend process restart, browser refresh, physical DB restart,
hosted HTTPS and Android are distinct evidence levels.

Stop the affected path on unauthorized success, duplicated effects, lost draft,
cross-role/session data leak, false “sent/delivered”, unsafe close or missing
server commit confirmation. Preserve evidence and report the exact step/build to
A0/A5/B0. Do not reset demo data, broaden credentials/grants, disable protections,
invent UI success or begin competing provisioning without the responsible owner.

Completion of steps 1–5 is the early rehearsal checkpoint. It is not completion
of required phone notifications, image performance, reports, historical seed,
AI evaluation or the full submission package.
