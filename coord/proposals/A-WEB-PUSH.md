# A-WEB-PUSH contract proposal v1

Base reviewed source: main `fffaf2fdd36cab937399ec8507543d326da83442`. Additive proposal pending A0/A5/B0 handshake. No shared frontend or migration files changed.

## HTTP contract for B5

All routes are under `/api/v1/push`, private/no-store/Vary Cookie, current server session cookie required. Never accept employee_id, role, recipient, session id or signing credentials in request data.

GET `/config` returns 200:

```json
{"enabled":true,"application_server_key":"BASE64URL_PUBLIC_VAPID_KEY","delivery_semantics":"provider_acceptance_is_not_device_delivery","device_policy":"latest_registration_per_user"}
```

Disabled: `enabled:false`, `application_server_key:null`. No automatic browser permission prompt. Only an explicit user click should request notification permission and subscribe with `{userVisibleOnly:true,applicationServerKey:...}`. Secure HTTPS origin and service worker required.

POST `/subscriptions`: exact Origin, `X-CSRF-Token` from `/me`, JSON media type and current cookie. Request is browser `subscription.toJSON()`:

```json
{"endpoint":"https://fcm.googleapis.com/fcm/send/OPAQUE_BROWSER_TOKEN","expirationTime":null,"keys":{"p256dh":"BASE64URL_P256_PUBLIC_KEY","auth":"BASE64URL_16_BYTE_AUTH"}}
```

`expirationTime` is optional/null or a future UTC Unix timestamp in milliseconds. Other properties are rejected. Maximum 4096 bytes; no query parameters. Response 200 `{"enabled":true}`. This records a subscription only, never proves delivery.

POST `/subscriptions/remove`: same headers/session; body `{"endpoint":"EXACT_BROWSER_SUBSCRIPTION_ENDPOINT"}`. Response 204 empty, including an unknown/not-owned endpoint. Does not reveal another user's subscription or remove it.

Errors use existing `{code,message,request_id,retryable,current_version:null,field_errors:[]}` envelope:

- 401 UNAUTHENTICATED: missing/expired/revoked session or inactive employee
- 403 FORBIDDEN: bad Origin/CSRF/fetch-site
- 400 INVALID_REQUEST: duplicate headers/cookies or query parameters
- 413 PAYLOAD_TOO_LARGE; 415 UNSUPPORTED_MEDIA_TYPE
- 422 VALIDATION_FAILED: unknown fields, duplicate JSON keys, malformed endpoint/keys/expiry
- 409 SUBSCRIPTION_CONFLICT: endpoint is bound to another account; unsubscribe browser-side and create a fresh subscription
- 503 PUSH_DISABLED with retryable false: configuration absent
- 503 TEMPORARILY_UNAVAILABLE with retryable true: unconfirmed DB operation; retry is safe

## Device and shared-phone semantics

One row per employee: the newest successful registration replaces that employee's previous device. This deliberately does not pretend to implement durable multi-device fanout. Subscription is bound to the current login session. Logout, expiry, revoked session or inactive employee prevents future selection. The frontend must unsubscribe the old browser subscription on account change and refresh registration after a new login. An old endpoint cannot be reassigned between accounts through the API. Removal only matches the current authenticated employee and exact endpoint digest.

The lock-screen payload is always:

```json
{"v":1,"title":"НарядAI","body":"Есть обновление наряда. Откройте приложение.","url":"/","tag":"naryadai-update"}
```

No employee/order/equipment/deadline/work details or identifiers. Service worker should validate this small shape, use a fixed same-origin `/` destination and show a visible notification. Browser notification tag can coalesce repeated messages. A notification already accepted by a provider cannot be recalled by logout; TTL is 60 seconds and the generic payload limits stale/shared-screen disclosure. Click fetches the current authorized API; never cache prior-user protected responses.

## Integration

- HTTP: `PushService(connect,allowed_origin=...,settings=PushSettings.from_env(),real_clock=...)`; `create_push_router(service)`
- Worker: **production** `BoundedPostgresWebPushAdapter(database_url=...,database_schema=...,settings=...)`, explicit channel `web_push`, total bound 22s with default durable lease30s
- `WebPushAdapter` is the injected component/test seam; production must use the outer process-bounded wrapper so DNS and DB stalls cannot exceed the advertised lease budget
- Entry point launching processes must use normal Python `if __name__ == '__main__'` guard; worker must not itself be a daemonic multiprocessing child
- SQL proposal `backend/db/proposals/005_web_push_subscriptions.sql`; A5 owns acceptance, application and runtime grants/startup allowlist
- Runtime role SELECT+INSERT on push_subscriptions; UPDATE only session_hash, endpoint_hash, endpoint, p256dh, auth, expires_at, generation, active, updated_at, last_error_code. Never owner employee_id update, DELETE/TRUNCATE/DDL. Required trigger push_subscription_owner_immutable
- Dispatcher prerequisite is A3's reviewed web_push channel support; no new delivery-state semantics

## Configuration / morning bootstrap

Defaults disabled. No keys were created, persisted or printed during implementation. Human-only after explicit approval:

```sh
python ops/bootstrap_web_push.py --subject mailto:YOUR_APPROVED_CONTACT --approve-create-persistent-vapid-key
```

Writes only ignored `secrets/webpush.env`, directory0700/file0600, refuses existing files/symlinks. It does not deploy, subscribe a browser, grant permission or send anything. A5 must wire that file into worker/API runtime privately; public key alone is returned to browser. Never run `docker compose config` with expanded secrets in logs. Maintain the same approved key across restarts; rotation requires new browser subscriptions.

Environment: DALA_WEB_PUSH_ENABLED=true; DALA_VAPID_PUBLIC_KEY; DALA_VAPID_PRIVATE_KEY; DALA_VAPID_SUBJECT. Private key is raw P-256 base64url, validated against public key. Subject is a mailto contact disclosed to the push provider. Telegram remains independently disabled per latest user instruction.

## Safety / outcome policy

Only exact fcm.googleapis.com and updates.push.services.mozilla.com with reviewed endpoint paths. Other providers fail closed, including Apple/Windows pending separate review. URL userinfo, ports, query/fragment, dot traversal, percent-encoding and suffix hosts are rejected. DNS is checked at send time, entire mixed public/private answers are rejected, connection uses vetted numeric IP while TLS verifies original hostname/SNI/Host. No redirects, proxy credentials, automatic HTTP retries or provider response body reads. pywebpush/http-ece/py-vapid perform standards cryptography; no hand-written encryption or signing.

2xx 200..202 with response evidence means provider accepted, not displayed/delivered. 404/410 deactivates only the exact subscription generation; a late result cannot disable a new registration. 429 uses Retry-After without shortening a valid long wait. 401/403 means configuration rejection, not subscriber deletion. 5xx/timeouts/process termination/malformed result are ambiguous, never automatically replayed. This sacrifices uncertain notifications to avoid silent duplication; polling remains the canonical UI refresh path.

## Primary sources

- https://www.w3.org/TR/push-api/
- https://www.rfc-editor.org/rfc/rfc8030.html
- https://www.rfc-editor.org/rfc/rfc8291.html
- https://www.rfc-editor.org/rfc/rfc8292.html
- https://github.com/web-push-libs/pywebpush
- https://urllib3.readthedocs.io/en/stable/advanced-usage.html#custom-sni-hostname

## Evidence gates

Local tests use ephemeral in-memory non-production keys, fake HTTP and synthetic identities. Standards encryption/decryption is real; provider acceptance is mocked. Live DNS/TLS to push provider, actual external push, browser permission, service-worker notification display, physical Android, hosted HTTPS and production key bootstrap are NOT RUN. Real PostgreSQL gate is separately reported. No overnight deployment authorized.
