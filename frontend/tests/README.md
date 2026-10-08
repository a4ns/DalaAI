# Independent B6 acceptance

This suite separates real shell rendering, synthetic feature rendering and independent source tests. None proves a business API, database, physical Android, camera permissions, push delivery, or model quality.

## Run after assembling the feature commits

```sh
cd frontend
npm ci
UI_REVIEW_SHA=$(git rev-parse HEAD) npm run test:ui
```

Use `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium` only where that browser is installed and permitted. The browser command starts a dedicated strict loopback server on port 4176. `UI_TEST_PORT` can choose a different reserved port. The configuration never reuses an unknown running server and never changes browser security flags.

For source-only tests without starting a browser/server:

```sh
UI_TEST_NO_SERVER=1 UI_REVIEW_SHA=$(git rev-parse HEAD) npm run test:ui -- --project independent-source
```

`UI_REVIEW_ROOT` optionally points to the frontend directory of an immutable exact-commit archive. It must not point to another writer's changing checkout when reporting exact-SHA evidence. It does not change ownership or authorize writes there. Missing modules and failed assertions fail the suite; they are never silently skipped or counted as a pass.

Artifacts are local in `tests/.artifacts/`. Reports must record reviewed source SHA, harness SHA, command, environment, UTC execution time, counts and PASS/FAIL/NOT_RUN/BLOCKED. Screenshots from a synthetic feature fixture are labelled synthetic and cannot be presented as product integration. No unexecuted test or fixture is evidence of a passing check.

B4 independently reviews these tests. B6 reviews product code, not its own test implementation. Re-run the affected checks after any source change or integration conflict resolution.

## Current coverage

- Independent source project: 153 tests of request replay, session epochs, expiry, old logout races, multipart retries, pre-cache staged-receipt context binding and UUID-case consistency, route cooldown, safe event cursors, same-user authorization/CSRF fences, scoped photo busy guards, executor order/assignment quarantine and late-response isolation, login ambiguity and incomplete-evidence feedback, additive push transport and session-lifecycle fences, conditional result-disclosure copy without inferred provider success, protected analytics/report periods, response fences and literal provenance rendering, explicit binary-download handoff and cleanup, demo-clock CAS and unresolved-effect locks, sticky unknown retry outcomes and pending-first/conflict-resolution guards, atomic published membership with concurrent receipt preservation, partial/stale snapshots, master close gates, executor validation, panel history/workload and photo preflight.
- Browser cases:13 per project (desktop Chromium and Android emulation). Three real React fixtures use explicitly synthetic responses or controlled callbacks. They cover Russian shell/keyboard/390px overflow/console, repeated login, expired identity, preserved409 drafts, unknown-result retries and interrupted identity/photo callbacks. Run these on the assembled code; they are not evidence of server effects.
- Browser execution in the initial B6 environment was BLOCKED: installed Chromium aborted with `process_singleton_posix.cc:297 socket() failed: Operation not permitted`; one supported reviewed escalation had the same failure. No screenshots were generated, no security workaround was used, and no browser pass is claimed.

Test code can be typechecked after assembly with `npx tsc -p tests/tsconfig.json`. The package's normal app typecheck does not include this test tree. `playwright test --list` only verifies discovery, never execution. Run `npm run test:ui -- client.spec.ts order-store.spec.ts --project=independent-source` for a client-only checkout; a full source run deliberately fails if required feature modules are absent.


## Android emulation gate

The existing `chromium-390` project remains desktop Chromium with a 390×844 viewport. The separate `android-emulation-pixel-9` project uses the actual `devices['Pixel 9']` descriptor verified in installed `@playwright/test` 1.63.0: Android 14 user-agent, Chromium, 360×732 viewport, 360×808 screen, device scale factor3, `isMobile:true`, and `hasTouch:true`. It does not run a physical Android device.

```sh
cd frontend
UI_REVIEW_SHA=$(git rev-parse HEAD) npm run test:ui -- --project=android-emulation-pixel-9
```

Use the same permitted Playwright Chromium installation as the desktop project. No extra dependency, account, device permission or security-setting change is required by this configuration. The shell test records observed user-agent, viewport, touch points and scale in an attachment and asserts Android emulation settings. Screenshots are named by project rather than implying every viewport is390px.

Discovery only, without starting a server or browser:

```sh
UI_TEST_NO_SERVER=1 npm run test:ui -- --project=android-emulation-pixel-9 --list
```

Both browser projects remain NOT_RUN/BLOCKED until an authorized runner produces a real result for the exact source SHA. Discovery and configuration validation are not browser acceptance, and Android emulation is not physical-device, camera, notification or installability evidence.

The optional result-disclosure checks render its leaf component with actual React static server rendering. The helper compiles JSX with the installed TypeScript React runtime because Playwright transforms JSX into browser-component descriptors. This exercises copy and configured-mode/assessment-state combinations; it does not execute browser effects, verify an API evidence mapping, or contact a provider. A missing component fails rather than being skipped. The previously published 95-case core harness remains its own immutable checkpoint.

Analytics fixtures are labelled synthetic outputs of the pinned C108/C109 pure projections using C111 internal model types. They are not captured HTTP/DB evidence. The analytics cases exercise master-only reads, half-open UTC+5 periods up to 93 days, query and identity races, lost-access data clearing, cap errors, human-score null/zero separation from AI recommendations, scoped historical evidence, literal escaping and exact decimal strings. Static SSR ignores CSS and does not establish mobile layout, keyboard behavior or a successful live report request.

Run the final included suite from the complete assembled `frontend` directory with its own `package.json` and `playwright.config.ts`. An external configuration run is a useful preliminary check, but does not validate that package's ESM loader context. JSON fixture imports explicitly use `with { type: 'json' }`. Keep verification copies outside `.artifacts` when running their own config: archived test copies under that directory are deliberately excluded from discovery.

Download checks use signature-only synthetic byte buffers and injected URL/save/timer ports. They do not produce valid renderer artifacts, create native downloads, contact the report backend or duplicate PDF/XLSX renderer verification. They cover accepted suffix paths and fixed attachment names, status/MIME/signature/stream-size refusal, explicit prepare/save separation, stale/auth/expiry fences, access-loss clearing, anchor cleanup and object-URL revocation. The 60-second ready deadline is checked even when a background timer is delayed.

The 16 demo-clock checks use synthetic response fixtures, injected fetch and static React rendering. They reflect the CAS-only GET/POST contract inspected at backend `d4a2932ad064807246332980b9db9888dc40efa1`: instance/version binding, scale0–60 and forward advance1–3600, with no operation ID or receipt/replay contract. An uncertain POST stays locked after GET and controller reattachment; known409 requires a later explicit read and acknowledgement before a new intent. Tests cover immutable bodies, duplicate sends, wrong response binding, read races, capability refusal, session/expiry fences and business-time versus real-time copy. They make no real clock request, database mutation or browser claim. The App mount outside Workspace access gates is independently source-reviewed, not represented as a browser lifecycle pass.

Final clock source `a181c52aea225d197c90b0454969fda33b2394da` plus this harness passed153 source tests, shared lint, app/test TypeScript and production build in a complete ESM package on2026-10-08. The malformed-storage and expired-session interaction regressions failed on prior source `f5459523524858783bb50685180b020c03ec2664` and pass the corrected candidate. The previously published137-case download harness remains a separate immutable checkpoint.
