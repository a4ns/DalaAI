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

- Independent source project:70 tests of request replay, session epochs, expiry, old logout races, multipart retries and pre-cache staged-receipt context binding, route cooldown, safe event cursors, same-user authorization/CSRF fences, scoped photo busy guards, sticky unknown retry outcomes and pending-first/conflict-resolution guards, atomic published membership with concurrent receipt preservation, partial/stale snapshots, master close gates, executor validation, panel history/workload and photo preflight.
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
