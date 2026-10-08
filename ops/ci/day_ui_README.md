# Combined UI synthetic viewport gate

Exact product: a880371589aa1dd117dde9e80936c687d146f919. Branch only:
`validation/day-ui-viewports-20261008`. The gate runs218 existing source cases
once and the18 unchanged browser cases at320×800,390×844 and768×1024. Each
viewport includes all five authored AI-assistance mount cases. Runtime viewport
observations from the existing shell case must match each fixed size.

This is responsive Chromium rendering with synthetic intercepted HTTP fixtures.
The five mounted AI cases check explicit requests, draft-only choice, denied
access, original-request retry and persistent review feedback. Existing shell
and executor fixtures also check their authored overflow/focus/error behavior.
It does not directly test the new PhotoPicker cancel/deletion focus or executor
scroll-ownership interaction; their source cases remain a separate evidence level.

No C110/C112/C113 invocation or acceptance change, actual API/DB/model/provider,
physical Android or native-save claim follows. No deployment occurs. Existing
candidate source and tests are unchanged. A CI-owned configuration selects only
the existing source/browser directories with no retry, no skipped-test promotion
and exact count/title checks. Live credentials and runner overrides are filtered.
Vite listens on127.0.0.1; no browser warning bypass or insecure-origin flags.

Raw JSON, screenshots and assertion output stay inside temporary private output
and are deleted. Only a bounded summary and fixed failure source locations are
published. Run with `python ops/ci/day_ui_gate.py --source .ci-day-ui` after the
workflow installs locked dependencies and official Chromium. Source-only checks:
`python ops/ci/day_ui_tests.py` and `node --check ops/ci/day_ui_playwright.cjs`.
