# Per-order event history integration

Adds the unchanged reviewed A6 event source (six-file content SHA256
f1ed90bf762e462a6c26e416723af18261e0aa22e8c020e51efb1cb79375ca16) and mounts
GET /api/v1/orders/{order_id}/events in the explicit demo app.main factory.
No new migration, dependency, credential, role grant or background worker.

Event sequence is per order, not order version; a submission can produce two
events at the same order version. Poll using after_sequence and the returned
next_after_sequence/has_more. Access is checked from current session, role,
section and assignment on every page and again after lock waits. Unknown or
invalid stored event data fails closed. Responses are private/no-store.

Exact-head gates:27 author local cases,16 independent local probes,10 author
PostgreSQL cases,7 unchanged independent PostgreSQL scenarios,10 restricted-login
cases, separate two-process event HTTP lifecycle, and actual app.main event
pagination/foreign403. All prior mounted/runtime/session/discovery/command gates
remain required. This is polling, not SSE/WebSocket delivery or measured
phone-to-phone latency. No notification delivery or provider execution is implied.

Source/probe hashes and frozen harness hashes are captured under backend/review/events
and backend/acceptance/events_delta. Reviewer probes run against a temporary copy
of the integrated backend including004, not the old standalone snapshot. The
restricted-role fixture routes service connections through the already tested
nonowner LOGIN and preserves owner-only fixture administration.
