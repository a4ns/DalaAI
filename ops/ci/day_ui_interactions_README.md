# Focused component interaction gate

Product8081a2984b2f27b909fa2b86cd9f10ffd01d1e11 is unchanged. Immutable test
source cbc8fd64764a7dcb8fe0dc45e2f8ce737fe0a3a9 adds only the three reviewed
fixture/spec files. The branch-only workflow runs one Chromium project and one
exact spec. That spec owns six cases at each320×800,390×844,768×1024:18 total.
It is not an18-case suite multiplied by another three-project matrix.

The fixed cases observe deliberate command/retry scrolling, stale or polling
responses that must not scroll, actual photo-preparation cancellation, deletion
focus return, and delayed/redirected focus that must not be stolen. Scroll calls
delegate to the browser; the deterministic bitmap boundary delegates to its native
decoder when released. Parent callbacks are synthetic and images are generated
by Canvas2D. This does not establish API/DB/provider, physical-device, camera,
actual upload, original C acceptance or uninstrumented timing behavior.

Exact source/history comparison permits only the three fixture additions over
the product. Five reviewed component dependencies are independently hash-pinned.
All18 cases, viewport suites and titles must pass once; skips, retries, missing
cases or extra projects fail. Raw report/screenshot/error output stays temporary.
Only bounded fixed case/category/line diagnostics and summary are published.

This gate does not cover the forthcoming quiet-polling/model product adb93d07.
The earlier generic a88018×3 viewport result stays separate historical evidence.
No product or original C source is edited by this workflow.

Checks: `python ops/ci/day_ui_interactions_tests.py`,
`node --check ops/ci/day_ui_interactions_playwright.cjs`, and
`python ops/ci/day_ui_interactions_gate.py --source .ci-interactions --check-inputs`.
The reviewed branch runs that gate without `--check-inputs` once after installing
the locked frontend packages and official Chromium.
