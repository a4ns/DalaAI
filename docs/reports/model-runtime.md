# Optional grounded report model

The normal API returns a factual, server-grounded summary without OpenAI. The
closure worker keeps its existing key-presence behavior. Selecting a model for
reports is a separate explicit operator configuration; it does not happen merely
because a closure key or closure-only policy already exists.

This source supplies the loader and optional deployment configuration. No real
key, provider call, hosted deployment or billed-cost measurement was used to
validate it. Recorded-response tests and local shared-ledger tests are distinct
from live model quality or availability.

## Before enabling

- Use an accepted release and an explicitly isolated synthetic demo. Keep real
  employee/production data outside this profile.
- Confirm the operator-approved scope includes closure text, verified before/after
  photos and grounded report facts. Display the processing disclosure printed by
  the policy builder. Reports send bounded, server-derived aggregate facts and
  allowed category codes; no names, free-text comments, photo bytes or record IDs.
- Preserve the existing project, instance, approval ID and persistent SQLite
  ledger. API and worker must share the same file and UID 10001. The budget parent
  must already be a private 0700 directory owned by that UID; the loader does not
  create/chown directories. It rejects symlink ledger paths and policy/key leaf
  files; operator-mounted parent directories must remain trusted.
- Configure the existing credential only through the approved private host
  secret mechanism. Do not put keys in commands, Git, browser settings or reports.
  Credential setup, external network activation and hosted costs require the
  operator's appropriate approval. This document does not perform those actions.

The same conservative budget limits closure and report calls together: $50 total,
at most $10 for starts before 2026-10-08T04:00Z, one concurrent call and five starts
per minute. Reservations are upper bounds, never refunds or billed-cost claims.
The default policy expires at 2026-10-08T18:59Z. The report operation fence shares
that SQLite file, has 4096 permanent attempt slots and never deletes unknown
attempts to permit another call. Retrying the same operation returns factual
fallback if it was already attempted; a changed binding is rejected.

## Create a separate policy

Read the existing named project/instance from the approved private configuration.
Prepare a **new** policy filename with the same values:

```sh
python scripts/prepare_interactive_demo_policy.py \
  --backend backend \
  --project-id "$DALA_MODEL_PROJECT_ID" \
  --instance-id "$DALA_MODEL_INSTANCE_ID" \
  --output "$DALA_REPORT_MODEL_POLICY_FILE" \
  --confirm-owner-authorized-demo-processing \
  --include-grounded-reports
```

The builder exclusively creates the output. It cannot overwrite or silently
upgrade the existing closure-only policy. Keep the old policy intact for rollback
of configuration, and keep the **same** budget file in both configurations.
Do not edit a purpose string manually: purpose and disclosure must match exactly.

## Compose opt-in

Normal `ops/demo/run.sh` remains unchanged and never selects the report overlay.
After the existing isolated stack/configuration has been prepared, an approved
operator may select the additional file explicitly. Use the same Compose project,
volume names, private environment files and stored fixture/clock settings; changing
directories or checking out another release alone does not isolate Docker volumes.

If clock mode is enabled, export its original `DALA_DEMO_CLOCK_ENABLED` and
`DALA_DEMO_CLOCK_INSTANCE_ID` from the existing private `clock_mode` and
`clock_instance` files, exactly as `run.sh` does. Preserve the stored
`DALA_DEMO_FIXTURE_MODE`. Set `DALA_REPORT_MODEL_POLICY_FILE` to the absolute new
policy path. The existing approved private environment supplies the key; the
command below contains no credential value:

```sh
docker compose \
  --env-file ops/demo/.local/env \
  --env-file ops/demo/.local/workers.env \
  -f ops/demo/compose.yaml \
  -f ops/demo/compose.workers.yaml \
  -f ops/demo/compose.reports.yaml \
  up --build --detach --wait --wait-timeout 180
```

The overlay gives the API the worker's existing egress network, shared budget
volume and same new combined-purpose policy; the worker also selects that policy.
It adds no SQL grant or identity. Database ports remain unpublished. Caddy has no
model credential. Removing the overlay restores default report fallback, with
the budget history preserved. `DALA_MODEL_FORCE_OFF=true` disables model use in
both processes, without resetting receipts or counters.

## Managed image opt-in

The default supervisor still forwards model inputs only to the worker. After
operator approval, setting `DALA_AI_REPORT_MODEL_ENABLED=true` forwards the same
`OPENAI_API_KEY` or exclusive `OPENAI_API_KEY_FILE`, `DALA_MODEL_APPROVAL_FILE`,
project/instance and fixed `/var/lib/naryadai/budget/openai.sqlite3` to the API too.
The policy must be the separate combined-purpose file under `/etc/secrets` and
readable by UID 10001. API and worker already share that application principal and
persistent disk; this is not a secret boundary between those two processes.
The edge process receives none of these fields. Existing managed startup approval,
role checks, HTTPS and persistent-disk prerequisites still apply.

## Observable behavior and checks

The API loads the optional adapter once, after its database startup gate and
before accepting requests. A keyless/default/force-off profile does not read any
key, policy or ledger. A closure-only policy reports `report_purpose_not_approved`;
expired policy reports `provider_policy_expired`; malformed or unavailable enabled
configuration reports `provider_policy_unavailable`. All use the same factual
fallback, without provider calls. Health-only mode never loads the adapter.

After operator configuration, validate the exact image, normal auth/scope/CSRF,
an on-demand report, its explicit provenance/fallback label, shared reservation
counters and process restart. Do not infer live activation from a key's presence
or source tests. Do not reset the ledger, retry unknown provider outcomes with a
new operation ID, or label deterministic output as a model response.
