# Assembled-browser handoff: accepted factory dfe9

Source inspection window: 2026-10-07T20:19Z–20:23Z. No browser retry, application request,
DB lifecycle, deployment, account creation or credential-file inspection was
performed for this addendum. The earlier C5 package at
`a9a8ee59e26c20e271277ff446889ccee5b45665` remains immutable historical evidence.

## Immediate decision for A0/A5/B0

Provide one exact, already-authorized **same-origin HTTPS frontend + demo API**
test target on an existing approved runner, plus isolated synthetic role and
fixture metadata. Do not direct C5 back to another localhost spelling or port:
the existing cloud browser returned `net::ERR_BLOCKED_BY_CLIENT`, and it has not
rendered the product. No tunnel, security override or alternate-origin retry is
proposed. A5 may assess B0's suggested existing CI browser runner within its own
authority; C5 has not started that job or established its browser availability.

At the inspected backend SHA, a planned no-photo command/review cycle is
source-supported, but the full photo/history flow is not assembled. Real browser
and device product gates remain NOT_RUN. Missing setup is distinct from a failed
application assertion.

## Exact source and coordination snapshot

- Accepted factory: `dfe9d8f7772b1a1c44f5a506c03e26c55fb5e1ca`
- Frontend inspected read-only: `b51d6577b0e3b0a10dd063f1a1c946e804633c07`
  on B0's `frontend-assembly-g1`. B0 labels this **render-only WIP**, not an
  accepted integration candidate; later stale-event guard work is not assumed
- Core OpenAPI SHA-256:
  `b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`
- [A0-0026](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045765569)
  reports corrected factory evidence; that CI result is attributed to A0,
  not independently rerun by this source review
- [A0-0027](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045948478)
  supersedes the overnight hosting/Telegram plan: **no overnight deployment**;
  primary Web Push is a separate workstream. No hosted endpoint appears in these
  inspected records. This addendum does not authorize live push, model calls,
  hosting, credentials or new access
- [B0-0028](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045907290),
  [B0-0029](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6045981387)
  and [B0-0030](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046082850)
  distinguish source/build checks from rendering and request the corrected
  same-origin synthetic fixture seam; B0-0030 suggests the existing A5 CI route
- [A0-0029](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046025517)
  preserves existing disjoint ownership through 03:30Z. It does not widen
  permissions. C0's owner-bound hard stop remains 04:00Z

## What is actually mounted

Source: `backend/app/main.py`, `runtime.py`, `sessions/http.py`,
`persistence/http.py`, `discovery/http.py` at the backend SHA above.

Default `DALA_API_MODE=health` still mounts health/readiness only. Explicit
`DALA_API_MODE=demo`, a restricted runtime connection, one exact
`DALA_ALLOWED_ORIGIN` and a successful lifespan prerequisite check mount these
nine `/api/v1` operations:

| Method | Path | Browser use |
|---|---|---|
| POST | `/auth/login` | Real synthetic role login through actual UI |
| POST | `/auth/logout` | Server logout; unconfirmed result remains unconfirmed |
| GET | `/me` | Current role/scope and session restoration |
| GET | `/dicts` | Scoped real catalogues and workload values |
| GET | `/orders` | Complete scoped list sweep; no stable cross-page total |
| POST | `/orders` | Fresh live order creation |
| GET | `/orders/{order_id}` | Current authorized snapshot |
| POST | `/orders/{order_id}/commands` | Executor transitions and master decision |
| GET | `/orders/{order_id}/submissions/{submission_id}` | Immutable attempt/review read |

Three operations present in the accepted 12-operation contract are not mounted:

- GET `/orders/{order_id}/events`: B0's `Workspace.tsx` calls event paging for
  selected master/manager history. The history/reconnect-event drill needs this
  route; a list/snapshot refresh is a separate, narrower observation
- POST `/photos/stage`: B0's client prepares a real staging mutation when a file
  is selected. File preview or a fabricated staged ID cannot substitute
- GET `/photos/{photo_id}`: protected bytes and current object authorization are
  not served by this factory

`UnavailablePhotoReferences` deliberately replaces submitted photos' validity
with unknown at the closure boundary, even when PostgreSQL contains
`file_valid=true`. A reviewed private-blob adapter and the mounted upload/read
routes are prerequisites for a successful required-photo close. This is a known
fail-closed boundary, not evidence of a browser defect. Planned no-photo work may
use the current complete-evidence human review path; it does not satisfy the
unplanned-photo requirement. No AI worker, notification dispatcher or scheduler
loop starts in this factory. Empty assessments remain absent, not a fabricated
pending/failed model result. Report and push contracts are not added to the
accepted core by this handoff.

## 1. Same-origin serving packet — A5 with B4/A0

Supply these nonsecret facts before scheduling the assembled run:

1. Exact frontend and backend commit SHAs, built-asset identity and core contract
   digest. Replace render-only WIP with an explicitly accepted candidate before
   claiming acceptance; preserve separate build and runtime evidence
2. One authorized browser-reachable HTTPS origin serving the actual frontend and
   `/api/v1` from the demo factory. The frontend client uses relative `/api/v1`,
   `credentials: same-origin`, `mode: same-origin`, no-store and redirect rejection.
   Its Vite configuration is HTTP loopback only and contains no API proxy/TLS
3. The exact configured origin must equal the browser's scheme/host/port, without
   a trailing path; login/unsafe requests require that Origin. API requests must
   not fall through to the SPA's index.html. Preserve real API status/body types
4. Keep `__Host-naryadai_session` Secure, HttpOnly, SameSite=Strict, Path=/ with no
   Domain, and session-bound CSRF. Do not weaken cookies, CORS, Origin checks or
   certificate verification to make the test pass. Existing trusted ingress and
   proxy handling are A5's reviewed serving responsibility
5. Explicit demo mode and already provisioned isolated DB/schema. The existing
   `make dev` profile remains health-only with an owner connection; turning on
   demo mode against that owner is not a valid runtime setup
6. Confirm real factory lifespan/startup succeeds using its restricted LOGIN,
   accepted migrations/guards and grants. `/readyz` is the demo prerequisite
   check, not simply HTTP process availability; a failure latches API admission
   closed until operator repair and a new process startup
7. Provide the existing authorized runner/browser capability and service-lifetime
   evidence. A single-call loopback HTTP 200 does not prove cross-tool/browser
   reachability. No public hostname or hosting service is invented here

A5 owns role/schema/ingress setup. This is a request for a handoff packet, not a
script to create access, apply migrations, start CI, accept TLS warnings or deploy.

## 2. Isolated synthetic fixture packet — A2/A6/A0

Deliver a nonsecret manifest with a unique test namespace, fixture version/hash,
clock mode, current candidate SHAs and already-provisioned canonical UUIDs:

- Master and assigned executor in a shared synthetic section
- Another executor in that same section, allowing assignment permission to be
  distinguished from section permission
- A foreign-section master with disjoint scope
- A same-section read-only manager and admin with no implicit production rights
- A second independent browser context for the same/another authorized master
  when testing stale-version conflict; browser tabs sharing cookies are not
  independent role sessions
- Valid equipment/work-code/material catalogues and eligible assignment, plus
  known own/other/foreign order IDs for scoped navigation
- Fresh planned order facts with a truly future live deadline for the available
  no-photo path; historical exports must not be replayed through live create
- Separately labeled incomplete unplanned and rework cases. Complete unplanned
  photo cases wait for actual sanitized bytes, staging/binding/private read and
  blob-verification support, not a synthetic `file_valid` shortcut
- Workload fixtures with multiple active/paused orders, queued-only counts and
  absent/null assessment/review values; paging fixtures exceeding one list page

Credentials, PINs, session cookies, CSRF values, DSNs and storage-state files are
not manifest fields and must not be published. The provisioning owner supplies
its approved secure/operator login route; C5 neither invents accounts nor opens
credential-bearing fixture files. No fixture import, DB reset or new role is
performed by C5. Reference A0's existing real-DB acceptance/effect evidence instead
of building another API/DB harness. Real notification/model dispatch remains
disabled unless independently authorized for specific test recipients/data.

## 3. Controlled observation/fault packet — A0/A5 with B6

The current documented dot-cloud browser surface does not advertise separate
cookie contexts, network interception or offline toggling. Do not assume those
capabilities from successful blank-tab creation. Use only an already authorized
runner that actually supports the required controls; otherwise leave each drill
BLOCKED with its exact missing capability.

- **Unknown committed outcome:** a one-shot, isolated seam permits the real UI
  request to commit, records A0's commit proof, then withholds/drops only that
  response. Record sanitized method/route/action, operation ID, expected version,
  canonical body digest and original response/event IDs. Retry through actual UI;
  identical intent must replay, then current snapshot reconciles. A0 supplies
  one-effect DB proof. Offline-before-send and fabricated success do not count
- **Reconnect:** disconnect only the observing context; another authorized actor
  makes a real change, then restore connectivity. Observe stale/disconnected UI
  and current scoped snapshot convergence. Event-page deduplication additionally
  requires the missing events route. Measure online commit-to-visible <=5s
  separately; the source's 2-second poll setting is not a measured latency
- **Stale version/identity change:** arrange a real allowed concurrent transition
  or already authorized fixture-control action. Observe real 409 and retained
  input; a fresh operation ID belongs only to an explicitly resolved new intent.
  Logout/role/scope changes must isolate prior reads and pending commands
- **Browser evidence:** exact viewport and RU DOM render, console failures,
  keyboard focus and disabled-action request effects. Source/build/SSR are
  supporting layers only. A 390px emulated viewport is not physical Android

Do not expose new production fault endpoints, inspect arbitrary DB state, modify
permissions, route around browser restrictions or send real employee notices for
these drills. A0/B6 own the permitted runner/fault controls; C5 consumes sanitized
observations and existing backend evidence references.

## What C5 can verify now without a browser

- Exact source route/configuration inventory and the integration gaps above
- Existing 26-test evidence-harness guards, contract pin, Git provenance, artifact
  hashes, complete case accounting and rejection of fake/skipped metadata PASS
- A provided **nonsecret** role/deployment manifest's structure and distinct
  canonical identities/scopes; this cannot authenticate a deployment or login
- C6's source-pinned runbook and handoff consistency
- Existing separately recorded exact-shell build/process evidence; no new claim
  about the render-only composition's install/build status is made here

C5 cannot verify actual login/roles, service reachability, DOM/console/layout,
network retry effects, photo upload, deployed persistence, model output, phone
receipt or Android behavior from this source inspection. All original 12 product
journeys remain NOT_RUN. Once an already approved hosted endpoint is supplied,
report it to the coordinator before any mutating UI action; absent that, keep the
handoff with A0/A5 rather than inventing a host or retrying a denied origin.
