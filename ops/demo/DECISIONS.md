# Demo packaging decisions — 2026-10-07

- No overnight deployment or host/account setup. Prepare source and disposable CI;
  the human selects a host in the morning.
- Caddy and the frontend share one origin with /api. PostgreSQL is private and the
  API has a separate nonowner LOGIN. Owner/PIN inputs exist only in setup.
- Private photos are one persistent UID10001 volume, never static-served. Human
  CLOSE reads the same physical store and fails closed on corruption/unavailability.
- WebPush is the primary planned notification lane; Telegram remains optional.
  Missing credentials must pause consumption, not fail pending work as delivered.
- Rules fallback remains truthful when OpenAI is absent. Normal future model
  bootstrap installs one named-demo policy; adding the approved key selects model
  processing within the fixed50USD lifetime/10USD night budgets, without per-order
  reapproval. That worker wiring is not claimed by the baseline Compose smoke.
- Browser CI uses ordinary certificate/hostname verification and isolated
  disposable trust. No tunnel, certificate-warning bypass or ignored TLS errors.
- Physical Android, real delivery, semantic model quality and a deployed URL are
  separate evidence gates. Source/build/synthetic browser checks cannot prove them.
