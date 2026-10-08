# C112 source-only evidence handoff

- Task: C112, generation 1, C-owned separate read-only historical analytics gate
- Base: `4d38c71164a56b0eeefa9eb0430eb9100bcd7a3d`
- Reviewed UI: `9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c`
- Scope: new `tests/e2e/c112_*` and this `docs/evidence/e2e/c112_*` file only
- Existing C110, package/lockfiles, frontend/backend, runner, workflow and Compose:
  unchanged

## Verification level

PASS: source syntax and 50 Node source/mock contracts plus 5 Python source-only
observer contracts. Tests cover the actual offline public_manifest schema,
canonical UTC/UI period mapping, forbidden manifest extras, secret-free browser
environment, exact-one-run gate rejection paths, independent source/run-bound
preflight validation, sanitized failures, observer environment containment and
absence of fake network responses in the actual journey source.

NOT_RUN in C0: actual dummy failure-output browser proof; actual UI/API journey;
actual PostgreSQL observer; trusted TLS; physical Android; camera; push;
provider model; export. No passing runtime evidence is committed in this file.
A5 alone owns the authorized actual execution and source-bound final receipt.

The public fixture is history-only: 540 orders, 568 attempts, 444 unavailable
photo references, 17 disabled historical actors; live master four sections,
live executor one. The canonical interval is July 1 00:00Z through October 1
00:00Z, represented by 05:00 local UI values at both ends. IDs come from the
public manifest and observed API response; none are guessed.

Read `tests/e2e/c112_README.md` for the exact one-scenario title/project,
independent preflight, required new run ID/receipt, A-owned observer two-ID
adapter contract, inputs, launch and fail-closed gate commands. No dependency or
access expansion is authorized by this handoff.

Observer architecture follows A0-0059: existing accepted C110 restricted runtime
LOGIN, enforced READ ONLY transaction, unchanged-data corroboration; no
SELECT-only-role claim and no new credentials/grants/access.

## Forward diagnostic delta after A0-0062

A's actual run 37705017534 on main
`b2eda8c2537f1f0ed78583038d69964ee23b6107` reported database corroboration and
both sessions PASS, then failed the master analytics stage. Its empty complete
observations list does not localize the failure, because that record is added
only after the stage's API and DOM checks. No specific defect is claimed yet.

The additive diagnostics are fixed source-defined substep/status categories only,
with no exception, body, URL, header or DOM text. The mandatory secrecy preflight
exercises the new source-bound helper. Existing acceptance predicates, selectors,
counts, periods, protected response requirements and exact-one gate remain
unchanged. Source verification after this delta: 55 Node and 5 Python tests PASS;
actual rerun belongs to A and remains NOT_RUN here.

## Canonical date-fill correction

Delta base: `ad5b03c7bcee16f989cb2122b6074394340d70eb` (diagnostic source).
A0's run `d4a293` was reported to stop at the first `datetime-local` fill.
The zero-second inputs are replaced with canonical minute-only values
`2026-07-01T05:00` and `2026-10-01T05:00`. Both actual field values must match
after filling and before the analytics request. The UTC interval remains exactly
`[2026-07-01T00:00:00Z, 2026-10-01T00:00:00Z)`; all existing counts, provenance,
security requirements, source binding, timeouts and exact-one gate are unchanged.

Source verification after this delta: 57 Node and 5 Python source-only tests PASS,
plus C112 JavaScript syntax checks. Regression checks require minute-only inputs,
both field assertions before the request, and rejection of shifted or stale UI
period evidence. These are source/mock checks, not a browser reproduction or an
actual acceptance pass. Browser normalization remains the suspected cause until
A's rerun verifies it. Browser, preflight, UI/API and PostgreSQL execution remain
NOT_RUN in C0. A must regenerate the source-bound preflight receipt on the exact
newly accepted HEAD and run with a fresh C112 run ID.

## Semantic order-selector correction

Delta base: published `edd109d2111e798db0440c7d3050e7e4fca80e42`, tree-identical
to local `dc8cd90e712c4d1d7e5df2b33f92e62323b686c0`.
A0 reported run `37710664206`, job `113095586236`, on main `2471afde` passed
the first four stages, including real analytics and the shift report, then
timed out at stage 5's exact `getByLabel` order selector.

Pinned UI `9a1d6109ab06ea8cbc379d46e2b6ebfcf23dd28c` has a wrapping label
around the select and its options in `AnalyticsView.tsx:26`. Playwright 1.63.0
source uses raw label element text for `getByLabel`, including option text.
Its role-name computation marks the target select visited before traversing
the associated label, excluding that select subtree from its accessible name.
The correction uses the exact `Наряд для отчёта` combobox role/name within the
exact `Аналитика и отчёты` region. No product accessibility defect is claimed.

The matching control must be unique. Selection still uses only the ID returned
by the actual analytics response; both the selected-values return and the actual
field value are asserted before requesting that same ID's protected report.
All counts, report comparisons, security checks, timeouts and gates are unchanged.

Source verification: 63 Node source/mock tests and 5 Python observer tests PASS,
plus C112 JavaScript syntax checks and `git diff --check`. Six new regressions
exercise the actual selection-source fragment with mocks, including missing or
duplicate controls, empty/wrong returned IDs and a wrong actual field value.
These checks are not a browser reproduction or an actual acceptance pass.
Browser, preflight, UI/API and PostgreSQL execution remain NOT_RUN in C0.
A must produce a fresh exact-HEAD secrecy preflight receipt and C112 run ID.
