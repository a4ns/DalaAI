# DalaAI → Render: 15-minute operator checklist

**Actual managed-image CI passed. No hosted deployment was performed. Humans choose the platform and approve charges in the morning.**

[Exact managed-image CI](https://github.com/a4ns/DalaAI/actions/runs/37712260125/job/113100631476) passed the full runtime and restart checks. Leave `DALA_MANAGED_START_APPROVED=false` until the operator also verifies the selected host, database, disk and credentials. Disposable CI does not establish hosted readiness.

## Before timing

Have account/repository access, owner approval of recurring costs, resources, exact candidate image/SHA, working HTTPS hostname, operator-managed credentials/roles, and a private administrative environment ready. Signup, DNS, provisioning, build queues and new approvals are outside these 15 minutes. The [technical guide](README.md) has prerequisites, commands and failure gates.

Chosen profile: one **paid 2 GB** web instance containing separate Caddy/API/worker processes, paid 2 GB private disk, private PostgreSQL 17 with paid 1 GB RAM/5 GB disk. The API and worker share the photo disk and UID trust boundary. No free-plan adequacy or mixed-load capacity claim is made. [Review current prices](https://render.com/pricing) before any import: a Blueprint can provision paid resources even with automatic deploys off.

## 0–4 min: accepted schema and roles

- Verify exact SHA, A5 migration map and accepted first-run launcher; old001–004-only initialization is insufficient
- Before running any initializer, choose clock-off `enable_worker_capabilities.py` or fresh clock-enabled `enable_demo_clock.py`; the latter needs the explicit clock capability flag and one fixed instance ID. Run only the chosen helper with `--backend backend --schema dalaai_demo --expected-database naryadai --bootstrap --apply` and the documented private inputs. The clock wrapper cannot adopt a schema already initialized by the clock-off helper
- Validate distinct restricted API/worker LOGINs and matching full AI+notification+push capability grants; keep AI/notification flags true and live Web Push false until configured. No runtime owner credentials or PINs
- Before first initialization, explicitly choose `DALA_DEMO_FIXTURE_MODE=history`
  for 540 canonical orders plus the two live accounts, or leave the default
  `minimal`. Keep that same choice on repeat. The existing schema is never adopted
  or widened when the mode differs. Historical actors remain disabled and their
  placeholder photos are disclosed as unavailable physical evidence

- After clock-enabled initialization, forward the same enabled flag and fixed instance ID to API and worker

## 4–7 min: secrets and durable storage

- Review `render.yaml.example`, verified resource names/region and internal PostgreSQL host; keep public DB access blocked
- Operator sets `DATABASE_URL`, `DALA_WORKER_DATABASE_URL` and one exact `DALA_ALLOWED_ORIGIN=https://<host>` privately
- Confirm disk mount `/var/lib/naryadai`; photos 0700/UID 10001, 1 GiB quota; durable budget ledger under `budget/`
- Keep the OpenAI key absent and Web Push/Telegram disabled for baseline; prepare the named model policy once, then the key alone enables the accepted model path

## 7–11 min: explicit start

- After every prerequisite passes, operator sets start approval true and manually deploys only the approved SHA
- Build context repository root; Dockerfile `ops/managed/Dockerfile`; fixed command `python ops/managed/supervise.py`
- Require worker preflight success, all three processes alive and `/readyz` 200. Readiness is not proof of queue progress

## 11–15 min: actual acceptance

- Check frontend/API same HTTPS origin, anonymous API 401, correct Secure/HttpOnly/SameSite=Strict cookie and wrong-Origin/CSRF denial
- Use two synthetic roles: upload photo → submit → actual rules-fallback worker assessment → master decision
- Restart once; verify photo, DB state, pending work and ledger persist. Save SHA/deployment ID and actual results without secrets
- If unfinished after 15 minutes, record the blocker; do not declare a pass

## Stop/rollback

Disk-backed deploys have downtime. Keep the same DB/disk; return only to a schema-compatible image or use a reviewed forward fix. Never reset seed, spend or ambiguous delivery history. Coordinate backups before destructive recovery. Do not delete resources merely to stop the app.

Live model calls, device push and mixed-load memory remain separate approved acceptance gates. A 20 MP decoder alone measured about 401 MiB; keep at least 1 GiB for backend workload and measure the combined 2 GB envelope before promising capacity. Details and exact NOT_RUN stages: [technical guide](README.md).
