# НарядAI frontend

Russian React/TypeScript/Vite shell. The first shell has no fake data, auth or business success. Unconnected features are visibly unavailable. Draft policy is memory-only; no service worker, offline outbox, persistent personal cache, external CDN or telemetry.

## Reproduce

Use Node 24.19.0 / npm 11.9.0 (Node engine requirement is in package.json).

```sh
npm --prefix frontend ci
npm --prefix frontend run check
npm --prefix frontend run dev
```

Default development and preview address: http://127.0.0.1:4171, fixed strict port. B6 browser tests use their own port 4176; test configuration/tests arrive independently. `test:ui` must not be claimed PASS before that package exists.

The API is same-origin `/api/v1` only; A5 owns HTTPS/session-serving integration. A Vite page without the API must show an honest connection failure. No API proxy or second auth protocol is configured here.

Exact planned dependency versions were verified against the npm registry on 2026-10-07; package-lock records the resolved closure. Browser/real API/device evidence is separate from lint/typecheck/build. Real Android, camera, push, persistence and end-to-end latency are not established by this shell.

## Ownership

B4 owns package/lock, app composition and shared code. Feature components expose UI view models and callbacks. Generated wire DTOs live separately under shared/api. B6 owns tests/configuration and independently reviews UI. No feature imports are added until the files exist in the assembled source.
