# WebPush assembled acceptance addendum

Source: [A0-0031, author a4ns, 2026-10-07T20:29Z](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046265475).
A0 approves the additive shape for implementation and asks consumers to ACK
compatibility. This is not a claim that a backend/worker is mounted or tested.
The accepted core OpenAPI bytes remain unchanged. The exact recorded shape is
`tests/e2e/push-protocol.json`, separately SHA-256 pinned by the V2 journey matrix
and report provenance. No private key or usable subscription credential is stored.

## Scope and authority

This addendum executes **source/metadata checks only**. Real permission prompts,
browser subscription, registration/removal, provider dispatch and physical phone
delivery are NOT_RUN and are not authorized by this artifact. A future operator
must have specific authorization and safe provisioned test targets before those
steps. No new account, key, access, deployment, browser permission or notification
is created here. The existing local-origin browser denial is not retried.

C5 specifies assembled UI plus real-backend observations. B6 owns component and
synthetic worker tests; A owns API/schema/ownership/eligibility and sender tests.
Their exact-SHA evidence is referenced rather than duplicated. A controlled
synthetic service-worker event can test rendering/click handling when authorized,
but cannot establish provider or phone delivery.

## Six new journeys, all NOT_RUN

| ID | Assembled boundary |
|---|---|
| C5-P01 | Disabled/unconfigured versus configured versus delivered; current-session config; visible one-device/session limitation; user-click permission only |
| C5-P02 | Latest registration replaces prior device, belongs to current login; 200 enabled=true means configured only; stale callback cannot confirm current state |
| C5-P03 | Logout/expiry makes registration ineligible; fresh login and session changes do not inherit stale configuration or pending actions |
| C5-P04 | Account switch clears old browser subscription before fresh registration; 409 SUBSCRIPTION_CONFLICT remains explicit, with no silent ownership takeover |
| C5-P05 | POST removal has exact endpoint/current auth; 204 empty and own-user idempotency; no other-account removal or fabricated confirmation |
| C5-P06 | Exact generic v1 worker payload, fixed same-origin root click; no employee/order details, API/photo cache or offline outbox |

The physical C5-D03 gate remains separate. The matrix now contains 18 cases:
12 earlier product/device cases plus these 6. Version V2 prevents silently treating
old 12-case reports as a full current run. All 18 initially remain NOT_RUN.

### Protocol points that must not drift

- GET `/api/v1/push/config` requires current session cookie. Disabled config has
  `enabled=false` and `application_server_key=null`; delivery/device semantics
  remain `provider_acceptance_is_not_device_delivery` and
  `latest_registration_per_user`
- POST `/api/v1/push/subscriptions` requires exact Origin, current cookie, CSRF
  and JSON subscription.toJSON shape. `expirationTime` is optional and null when
  present. No domain operation ID or expected-version field is invented
- POST `/api/v1/push/subscriptions/remove` uses JSON exact endpoint and the same
  current authentication protections. It is not DELETE; success is 204 empty,
  idempotent and own-user-only. The shape does not specify a separate foreign
  removal response, so the matrix asserts ownership protection without inventing it
- 409 SUBSCRIPTION_CONFLICT is never configured success. 503 PUSH_DISABLED is
  nonretryable; TEMPORARILY_UNAVAILABLE is retryable. Both share the standard error
  envelope with null current_version. Query/ambiguous input, wrong MIME, oversized
  (>4096-byte) or invalid bodies are A-owned API tests, not a second C5 HTTP suite
- A registration is tied to its login session. An extant browser subscription or
  public application-server key is not proof of current backend eligibility
- Payload is exactly v1, title НарядAI, generic update body, url `/`, tag
  `naryadai-update`. Private VAPID keys stay server-only. Evidence never includes
  real endpoint/auth/p256dh/session material
- Initial provider support is Chrome/Firefox HTTPS endpoints. Do not infer Safari
  support or universal sound/background delivery

## Concise A5 CI handoff

ACK [A0-0030's existing authorized CI/container browser direction](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6046140400).
Use B0's published, source-reviewed assembled frontend
`2beb2244c4639c09004e4cdb5a7598d447ad68f6`, or its explicitly accepted successor,
with the exact A0-selected backend and additive push implementation SHAs. A0 has
since reported core events and photo/CLOSE integration; the earlier dfe9 missing
route inventory is historical, not a claim about newer main. Exact-main gate
completion and the push implementation must be supplied, never presumed.

The execution packet needs:

1. Immutable frontend/backend/worker/build identities, core and additive protocol
   pins, plus the approved runner's actual browser availability
2. Trusted same-origin HTTPS serving and real demo factory lifespan, isolated
   pre-provisioned synthetic accounts, canonical role/scope IDs and an approved
   secure/operator login route; no credentials in public fixtures or C5 artifacts
3. A-owned enabled/disabled/current-session/expired-session/foreign-endpoint
   fixture states and read-only registration eligibility/effect references
4. Supported separate contexts for distinct accounts and same-user devices,
   current-session response-hold/conflict observation controls, and explicit
   disclosure of synthetic event/transport fixtures versus real delivery
5. Dispatch disabled for setup/source tests. Any later actual permission,
   subscription or specific-device delivery gets its separate authorization

Do not route around the blocked local origin, provision a host, disable cookie or
TLS protections, inspect secrets or start a competing API/DB pipeline. This is an
execution handoff to the existing authorized A5 runner, not a new CI job launch by
C5. The available evidence harness can check pins, case completeness, metadata and
artifact hashes; it cannot prove a browser observation or grant permission.
