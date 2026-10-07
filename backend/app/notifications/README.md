# Telegram synthetic-demo adapter

## What this package does

`TelegramAdapter.send(DeliveryEnvelope)` implements the shared `app.notify.models`
provider seam. It sends one plain-text Russian message through Telegram's official
`sendMessage` API. All seven existing delivery job kinds have fixed templates.
Only the synthetic order UUID is interpolated. Names, reports, photos, free text,
URLs, arbitrary HTML/Markdown and supplied `order_number` are never transmitted.
It neither creates jobs nor changes order statuses. Importing it starts nothing.

It adds no runtime dependencies and no migration or public HTTP endpoint. The
`app.notify` delivery worker and models are a separate, required integration.

## Secure opt-in settings

Default is disabled. The authorized host may inject the following settings only
after the owner has approved the credential use and precise recipient bindings:

- `TELEGRAM_MODE`: `disabled` (default), `dry_run`, or `live`
- `TELEGRAM_SYNTHETIC_DEMO`: must be exactly `1` for sending
- `TELEGRAM_BOT_TOKEN`: existing approved bot credential, injected securely only
  in live mode; never put it in source control, fixtures, chat, logs, traces or URLs
  returned to clients
- `TELEGRAM_DEMO_BINDINGS_JSON`: JSON object mapping approved synthetic employee
  UUIDs to approved positive integer private-chat IDs. No groups, channels,
  usernames, redirects, or inferred/discovered recipients
- `TELEGRAM_MAX_CALL_SECONDS`: positive real-clock budget at most 30 seconds;
  default 10, strictly below a fresh worker dispatch lease

A setting is not evidence of user permission. The owner/operator must establish
permission before injecting these settings. This implementation has not configured
any real token, persistent access, bot, webhook, chat binding or external send.
The recipient must already have an appropriate private conversation with the bot;
this module does not discover chats or start them on anyone's behalf.

Construct explicitly with `TelegramConfig.from_environment()` and inject the
result into `TelegramAdapter`. `TelegramAdapter()` alone remains disabled.
Neither disabled nor dry-run mode reads a token from the environment. Invalid
configuration fails closed with static error codes. Binding maps are copied and
immutable. Token and binding values are excluded from configuration repr.

## Outcome contract

- `accepted / TELEGRAM_API_ACCEPTED / telegram:<message_id>` means Telegram returned
  a validated sent-message receipt for the allowlisted private chat
- `retryable` means a definite pre-request failure, an in-flight transport guard,
  local throttling, or an explicit Telegram rejection that can be retried
- 429 `retry_after` is honored without shortening; absent delay defaults to 60
  seconds. Invalid or more than seven-day delays fail closed for operator review
- `permanent_failure` includes disabled/dry-run, unapproved recipient, invalid
  synthetic input, rejected credentials, blocked chat, bad request, or chat
  migration. Migration never silently changes a destination
- `ambiguous` includes timeout after possible dispatch, malformed/oversized
  response, inconsistent receipt and otherwise uncertain results. **No automatic
  retry**; manual reconciliation is required

A receipt is not evidence of phone notification, sound, display, delivery/read
receipt, or Android lock-screen behavior. Device evidence is a separate test.
Dry-run deliberately returns `permanent_failure / TELEGRAM_DRY_RUN`, with no
receipt. Use it to validate configuration/payload eligibility, not to drain a
live delivery queue or to claim successful delivery. The generic worker's separate
synthetic sink can test durable queue behavior without Telegram acceptance.

## Worker obligations and idempotency

Telegram `sendMessage` has no provider idempotency-key parameter. The job UUID is
not sent as a fictional idempotency header. The durable worker owns these gates:

1. Only claim the explicitly configured Telegram channel with a bounded lease
2. Recheck current order status, assignment/scheduling revisions, current authorized
   recipient, due threshold and lease ownership before committing dispatch intent
3. Commit dispatch intent before the adapter call; call the provider outside the
   database transaction, with a fresh lease longer than `max_call_seconds`
4. Store successful receipt once and never resend an accepted job. A crash after
   committed dispatch intent is ambiguous; never reclaim it as safe-to-resend
5. Persist retry delays using the real clock and respect provider delays. Record
   ambiguous outcomes for review without automatic repeat
6. A late API receipt may be retained for audit, but cannot revive a cancelled job,
   overwrite a new assignment or claim that a phone received the message

The adapter does not fake exactly-once delivery. It cannot make an already-started
remote request disappear if the order is cancelled while the API call is in flight.
The worker must preserve this distinction in evidence and operator status.

## Time and rate limits

The caller's overall budget covers DNS/TLS/send/response wait via a bounded daemon
transport call. A timeout returns ambiguous immediately. A transport that remains
active blocks subsequent transport calls; a late DNS/TLS completion cannot start
a request after its deadline. An already-started request may complete remotely,
but its late response never changes the returned ambiguous outcome into success.
Normal TLS certificate verification is mandatory. No redirects, proxy overrides,
endpoint overrides, or automatic transport retries are supported.

Run exactly **one Telegram adapter instance in one worker lane per bot** for the
MVP demo. It conservatively permits at most one request per second across all
allowlisted private chats and applies 429 cooldown across them. This local guard
is not a durable multi-process rate limiter and resets on process restart. The
worker persists individual job retry timing; deploying multiple Telegram lanes
requires a shared bot-wide rate gate first. Paid broadcasts are always disabled.
No incoming-update polling or public webhook is enabled. App screen polling is
independent of this outbound notification adapter.

## Offline verification

Run after the worker's shared models have been integrated:

    PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p test_telegram_adapter.py -v

Tests use only fake transports/fake HTTPS connections and an explicitly fictional
token. They cover opt-in/binding validation, plain synthetic payloads, all job
kinds, dry-run honesty, confirmed acceptance, 429/global throttling, explicit
failure classes, ambiguous outcomes, redirects, TLS verification, response size,
bounded wait, late-connect suppression and secret-free outputs.

No real Bot API request or Android notification has been tested by this package.
After authorized runtime integration, the demo owner should record new-order and
overdue notification observations on the intended phones, including app state,
notification permission, mute/DND setting, event time, observed time and exact
code version. Do not promote fake-transport tests to phone-delivery evidence.

## Official sources checked 2026-10-07

- Telegram Bot API request and response semantics:
  https://core.telegram.org/bots/api#making-requests
- `sendMessage`, plain text limit, receipt and paid-broadcast option:
  https://core.telegram.org/bots/api#sendmessage
- Flood-control `retry_after` and migrated-chat parameter:
  https://core.telegram.org/bots/api#responseparameters
- Telegram rate guidance:
  https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
