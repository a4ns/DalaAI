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
# Worker integration increment, 2026-10-07

The optional fresh `history` fixture is explicitly bound into its bootstrap
receipt. Minimal-profile receipt hashes stay unchanged. History initialization,
canonical import and final live-account receipt are separate durable stages;
the worker capability marker is complete only after the final receipt returns.
The stored local fixture choice survives repeat starts and cannot silently switch.

The full operator launcher now composes the reviewed worker overlay. Its API and
worker database capability profiles are independent from provider activation.
Web Push remains paused without configured keys; durable work is not consumed by
a disabled adapter. Key absence chooses rules fallback; an operator-supplied
OpenAI key selects the named interactive-demo policy, sharing the persistent
budget ledger. The worker-free base remains the manual C-110 fixture. No host
deployment, live provider call or physical-phone pass is implied by publication.

2026-10-07: PDF/XLSX exports reuse the authenticated consistent report capture and
final session recheck. Fixed routes precede generic order reports; both API images
include pinned DejaVu Cyrillic fonts. Existing B optional push settings and
conditional model-processing disclosure are imported at exact3ef269, with C110
strictly rebound at67496. Actual new-head image/browser/PG gates are mandatory;
source tests do not substitute for those gates.
