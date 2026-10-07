# Master analytics and protected reports

Optional lane on exact frontend base `3ef269bba80dbd6eafaff0d5e557da21f2d96244`; earlier assembly remains unchanged. Accepted assignment: [A0-0051](https://github.com/a4ns/DalaAI/issues/2#issuecomment-6048410059).

The adapter consumes only C111 `2945e3d3b6ba187a510cfb715e22d9feb70c4408` JSON routes, over C108 `711e2fbd69598d06f43da9ff47de60d2c569634c` and C109 `e999232014be8b16717058c6d9b70b41dec75c89`:

- GET `/api/v1/analytics/shift?start=...&end=...&format=json`
- GET `/api/v1/reports/shift?start=...&end=...&format=json`
- GET `/api/v1/reports/orders/{id}?start=...&end=...&format=json`

Only active master sessions with a section reach these reads. The backend remains authoritative for current role, membership, completeness and capture limits. Cookie/session handling uses the existing same-origin client; no token URLs or second authentication mechanism. Current-session and latest-request fences suppress old period/order responses. Starting another query hides previous results. Failures are errors rather than empty snapshots; authorization loss purges the displayed data. No localStorage, IndexedDB, offline cache, export or provider action is added.

Date inputs are explicit UTC+5, half-open `[start,end)`, at most 93 days. Quick 12/24-hour intervals are conveniences, not an asserted official shift schedule. Existing order `domain_now` or successful report `provenance.domain_as_of` may provide the last known upper bound, which is never advanced using the device clock. With no such timestamp, fields remain empty and the server validates the user's explicit period. A smaller period can still exceed capture limits because the backend reads complete authorized history.

The internal C3 Order projection differs from the core wire Order. Runtime guards validate the separate additive shape, safe integers, relational attempt bindings and the requested period/order. Decimal metrics and material quantities remain strings. Snapshot stocks are separated from period flows. Human null scores remain missing, separate from zero and AI recommendations. No composite ranking, pattern detection, warehouse deduction, physical-photo validation, model execution or full event-history claim is inferred. Historical unavailable-evidence counts come from each response, never constants.

`Reports.tsx` and `AnalyticsView.tsx` are controlled React presentation exports. Arbitrary source descriptions/reasons are literal text nodes; no raw HTML, iframe, image resource, external link or uncontrolled URL is opened. Reports re-fetch the protected JSON and show their own provenance.

Verification uses pinned pure C3/C4 projections from labelled synthetic typed rows and injected transport, plus source/type/lint/build checks. Those fixtures are not HTTP/PostgreSQL/browser/device evidence. Actual mounted journey validation remains a separate runner gate.
