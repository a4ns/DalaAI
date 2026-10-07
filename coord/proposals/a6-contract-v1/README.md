# A6: thin vertical slice contract proposal

Status: PROPOSAL ONLY, not frozen, not an implementation or integration pass.
Author: A6. Acceptance owner: A0 / human A, pending. Consumer handshake: B0 pending; C0 pending.
Authored against source baseline supplied by A0: `1a73343342ed98ed55f7df8f37408cea492358e2` (docs/team-bootstrap). The supplied local source directory contains no Git metadata, so that SHA has not been independently resolved here. Sources read: AGENTS.md, START_HERE.md, docs/REQUIREMENTS.md.

## Initial boundary for approval

1. One origin and `/api/v1`; OpenAPI 3.1.0; proposed contract version `1.0.0-proposal.1`. A0+B0+C0 approval is required before freezing or generated-client work.
2. Secure HttpOnly `__Host-naryadai_session` cookie; same-origin mutation checks plus a session-bound `X-CSRF-Token`. No bearer token in a URL. Demo employee-code/PIN sign-in is isolated and rate limited, never production authentication.
3. Every order write has client UUID `operation_id`, integer `expected_version`, `action`, and typed `payload`. Create uses expected_version=0; updates use the last server version. Receipt scope is actor+operation_id, including canonical route/action/payload. Replay returns the original committed snapshot after CURRENT object authorization. It is not automatically the newest snapshot.
4. P0 path: create issued v1 → accept v2 → start v3 → submit result v4 (done + ai_review events in one transaction) → human close/rework v5. AI may complete asynchronously and increment version first; callers use returned/current version. Model failure does not block human review.
5. Every submission is immutable and bound to assignment_revision; missing required after-photo is accepted as incomplete for review, but blocks closing. Ill-typed/malformed data, unknown material IDs, negative quantities, or foreign photo IDs are errors. Human decision requires a reason; a score cannot waive missing evidence.
6. Staged before-photo upload does not require an order ID. Owner+TTL and all-or-nothing attachment protect create retries. After-photo staging requires the order ID and current assignment revision. A reassigned order cannot consume an old stage.
7. Durable delivery rows are created in the same transaction as state/events/receipt. The worker rechecks recipient, assignment_revision, scheduling_revision and current state before send. Provider acceptance is distinct from observed device delivery.
8. Initial realtime boundary is authorized HTTP event polling plus snapshots. No WebSocket protocol is promised by this thin slice. The <=5 second UI target and real phone notification remain runtime/device gates.

## Artifacts

- `contracts/openapi.yaml`: HTTP schemas and operation IDs
- `contracts/examples/`: synthetic request/response/event fixtures, indexed in `manifest.json`
- `CONTRACT.md`: authorization, transitions, idempotency, clocks, outbox and failure semantics
- `backend/db/proposals/001_vertical_slice.sql`: proposed PostgreSQL DDL, not applied
- `MIGRATION_PLAN.md`: approval and runtime verification gates
- `scripts/validate_contract.py`: offline syntax, reference and fixture validation
- `evidence/validation.json`: actual local validation output only

No shared checkout changes, pushes, merges, installed services, live network tests, paid calls or real personal data are part of this preparation.

A0 subsequently reported the accepted bootstrap merge SHA as `cca50de1094feb4c6571f8255ebc154f111b45dc` at 2026-10-07 17:20 UTC. This does not approve this proposal. No local Git metadata exists here to independently resolve either SHA.
