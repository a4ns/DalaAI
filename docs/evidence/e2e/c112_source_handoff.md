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
