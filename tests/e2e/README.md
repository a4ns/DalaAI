# Assembled-browser acceptance, C5

This is a **manual browser-journey plan and evidence harness**, not an automated
browser test suite. It does not launch a browser, contact a service, sign in,
provision accounts, reset a database, send notifications or call a model. It
never supplies credentials, guessed UI selectors, invented endpoints or mock
successes. Its runnable commands prepare and check evidence; only an operator's
real browser execution can establish the product outcomes.

The V2 matrix has 18 product journeys, including 6 additive WebPush journeys.
All 18 remain **NOT_RUN** in this package; historical 12-case evidence stays historical. See
[the historical core blocker ledger](../../docs/evidence/e2e/gaps.json). The absence of an
assembled frontend is not a passing skip.

## Boundaries

- A0 owns real API/DB acceptance, transactional/fault-injection inspection and
  lifecycle. C5 references that evidence for the exact backend candidate rather
  than introducing a second API/DB harness
- B6 owns component/frontend and UX checks. C5 exercises assembled pages against
  a real persistent backend with separate browser identities
- B4/A5 own dependencies, selectors/client integration, browser-driver packaging
  and root CI. This package changes none of those files. A future automated
  driver needs an explicit task after the frontend exists
- C6 independently reviews evidence, and C2 can independently review this
  harness. A structurally valid JSON report is not independent verification
- Physical Android camera, background behavior, notification receipt and timing
  remain separate gates. Desktop viewport emulation cannot satisfy them

## Pinned contract and sources

[journeys.json](journeys.json) contains the cases, steps, check IDs, required
observation kinds, numerical limits and source links. It pins the accepted
proposal.2 OpenAPI bytes to SHA-256
`b8b5b855eb8fffd4607473a4e878a3c64820030820cabb1b0c92d70928730f97`.
The A0-0031 additive WebPush shape is separately pinned in
[push-protocol.json](push-protocol.json); it does not change those core bytes.
V2 reports pin the additive document as well as the harness/matrix; an older
report must be checked with its matching historical harness. See the
[WebPush handoff](../../docs/evidence/e2e/webpush-a0-0031.md) for authorization
and delivery limits.

The artifact's historical PROPOSED labels must be read with the current A0
RUN_OPEN/GRANT acceptance, not silently rewritten by C5. Journal A0-0004/0006
clarifications govern moving pages, representative active order, queued-only
counts, role scope and absent/null values. The suite fails closed if the pinned
contract changes; updating the pin requires the contract-owner handshake.

The accepted surface does not specify report or WebSocket APIs. C5-B08 is a
tracked continuation gap. Reconnect uses accepted authorized HTTP event pages
and current snapshots; no WS protocol is invented. Source requirements in
AGENTS.md are repository mappings to the case, not measured device results.

## Safe preparation

Use Python 3.12+ standard library from the repository root. No install is needed.

```sh
PYTHONDONTWRITEBYTECODE=1 python tests/e2e/browser_evidence.py plan
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/e2e -p 'test_*.py' -v
```

`plan` reports NOT_RUN. The tests exercise only the metadata validator using
clearly fabricated, local unit fixtures. They do not start a browser or network.

For a later **authorized, assembled, isolated deployment**, copy
`deployment.example.json` into a new run directory under
`docs/evidence/e2e/`. The example is intentionally invalid until real deployment
and provisioning details are supplied. Put only nonsecret attestations in it:

- Explicit HTTPS origin with no embedded credentials, route, query or fragment
- Exact frontend and backend commit SHAs, deployment proof and isolated namespace
- Real persistent backend and synthetic-only target; domain-clock mode and actual
  browser/network conditions
- Distinct master and executor UUIDs, role, section scope, already-provisioned
  status and distinct browser context labels. All UUIDs use canonical lowercase
  hyphenated form so alternate spelling cannot bypass identity/scope comparison. Two tabs in the same profile share
  cookies and do not establish separate sessions
- Optional `other_executor`, `foreign_master`, `manager`, `admin` aliases for their
  negative cases. Missing roles remain visible NOT_RUN; they are never skipped
- `physical_android: true` only on a real device, with `device_model`,
  `android_version`, and a nonpersonal `device_operator` label
- Notification/provider safety settings reflect separately authorized test
  recipients/budget or disabled dispatch. Setting a string does not grant consent

The human operator signs into the actual browser and handles login/permission
prompts. This harness never reads password files, browser storage state, PINs,
cookies or CSRF values. Do not put those values in config, HAR, traces, reports or
screenshots. Files known to contain passwords need the owner's permission before
opening; use a separately sanitized evidence copy instead. Provisioning is owned
by A2/A6, not inferred from illustrative UUIDs in this package.

After the harness and matrix are committed:

```sh
python tests/e2e/browser_evidence.py prepare \
  --config docs/evidence/e2e/RUN/deployment.json \
  --output docs/evidence/e2e/RUN/report.json
```

`RUN` is an operator-chosen new evidence directory, not a supplied deployment.
The command requires valid configuration, pins committed harness/matrix bytes
and creates every check as NOT_RUN. It refuses to overwrite an existing report.
It does **not** verify target availability or the truth of provisioning claims.
A prepared manifest is not an execution receipt or permission to mutate a target.

## Executing and recording the journeys

Read each case's `steps` and `dependencies`. The operator uses the assembled
browser UI; do not satisfy the flow with direct API-created results. Capture real
browser requests/responses for the UI action. A service worker/MSW/mock server
fulfilling domain requests invalidates the assembled-backend claim. Fault
injection may drop/delay real traffic under separate approval, never fabricate a
successful server response. A0 controls any database inspection and process
restart; this package contains no lifecycle commands.

For each case record `executed_at` in UTC, a nonpersonal operator label, status,
reason if blocked, and each check's observation. Add local, sanitized artifacts:

```json
{
  "id": "issue-observation",
  "kind": "browser_network",
  "path": "issue-observation.json",
  "sha256": "<actual 64-hex SHA-256 of the reviewed file>",
  "sanitized": true
}
```

Artifact kinds are `ui`, `browser_network`, `backend_reference`, `device`.
Paths are relative to the report directory, with no `..`, absolute paths or
symlinks. The file must exist with the supplied digest. A `backend_reference`
artifact identifies the A0 evidence link, exact tested backend SHA, relevant
observations and limits; it is not an invented DB count. A `device` artifact
identifies actual model/OS/browser, network, operator method, capture and timing
conditions. Review/redact bytes before setting `sanitized`; the tool cannot
recognize all secrets or confidential images automatically.

Each check references artifact IDs via `artifacts` and records a factual
`observation`. All required kinds must be attached for an executed check. Numeric
targets use `measurements` with the exact keys in the matrix (`online_visible_ms`,
`create_ms`, `ui_taps`, `upload_ms`). Include raw samples, sample count, boundaries
and conditions in the underlying artifact. Unmeasured, skipped or Boolean values
cannot satisfy a numeric target. A passing single sample establishes only that
trial, not a population performance guarantee.

Record FAIL for observed product failure. Use BLOCKED with an exact dependency
when execution cannot continue, and NOT_RUN if it never ran. A failure cannot be
hidden by relabeling the case BLOCKED. An executed partial check still needs time
and operator metadata. A case cannot be PASS with any unexecuted check, missing
role or unmet physical-device condition.

```sh
python tests/e2e/browser_evidence.py validate --report docs/evidence/e2e/RUN/report.json
python tests/e2e/browser_evidence.py gate --report docs/evidence/e2e/RUN/report.json
```

- `validate` exits 0 only for consistent metadata, pinned Git provenance and
  matching artifact hashes; output says EVIDENCE_STRUCTURE_VALID, **not product PASS**
- `gate` exits 0 only if all 18 cases carry complete evidenced PASS records;
  otherwise exits 1, with counts including NOT_RUN/BLOCKED/FAIL
- Invalid JSON/provenance/evidence exits 2. Neither command contacts the deployment
- The harness verifies the report commit actually contains the claimed harness
  and matrix bytes. Run the matching pinned harness version for an older report
- Both commands still require independent human/reviewer assessment of observation
  truth, deployment linkage and whether the artifacts establish the assertions

Do not publish raw captures. Publish only authorized synthetic, redacted evidence
with no secret, personal name, private local path or runtime/session identifier.
The coordinator serializes publication. Existing evidence is retained when a
later candidate changes; create a new run and rerun affected browser journeys.

## Important drill distinctions

**Lost response:** a request must commit before its response is dropped. Capture
original operation/body digest and original response from the permitted seam.
Retry via UI using exactly the original intent; distinguish the receipt's old
snapshot from a later current snapshot. An offline-before-send check proves a
different behavior and cannot close C5-B04. A0 supplies one-effect DB evidence.

**Reconnect:** drain event pages by the returned sequence cursor, dedupe event
identity, then reconcile a current authorized snapshot. Do not claim stable totals
or a cross-page snapshot from scoped keyset paging. Measure online status latency
against the <=5s case target separately from reconnect recovery duration.

**Required evidence:** unplanned missing after-photo or null work code may create
an incomplete attempt, but master close is blocked. Empty `assessments` is absence;
null human score is unscored. Rules fallback/manual/model modes remain explicit.

**Physical device:** actual camera permission, locked-phone notification delivery,
sound and mobile lifecycle need a real Android. Provider acceptance is not phone
receipt. No universal sound/DND bypass is claimed or tested.
