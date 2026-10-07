# B-101 shell verification through C5

Observed window: 2026-10-07T19:28:35Z–2026-10-07T19:31:02Z
Frontend source: `633beec6de954b45160361c2ea2bc41c1e99fae6`
Source branch: `night/20261008/B0/B-101-g1`
Reviewed C5 harness: `8b03e18e23ebd7224afe7af282fd910155d0b8fd`
Coordination records supplied by parent: A0 authorization comment 6045066297;
B0 handoff comment 6045153920.

## Executed, bounded scope

A separate `git archive` of the exact published frontend commit was used. No B
worktree/branch or frontend source was edited. Existing declared dependencies only;
no package, lock, root configuration, browser installation or security change.

Environment: Node 24.19.0, npm 11.9.0, isolated writable npm cache, Linux execution
workspace and separately supported existing dot-cloud browser.

Commands from the isolated archive's frontend directory:

```sh
npm ci --ignore-scripts --no-audit --no-fund --cache ../npm-cache
npm run check
npm run dev -- --port 4171
```

- PASS: 33 locked packages installed with lifecycle scripts disabled
- PASS: `oxlint --deny-warnings src vite.config.ts`
- PASS: `tsc -b`
- PASS: Vite 8.3.3 production build, 17 modules transformed
- PASS: all 15 tracked frontend files remained byte-identical to the immutable source
- PASS: package-lock SHA-256 remained
  `35f3230f1beee0391af72fcd94fc6af1d858cebc8af5d6cdb320bfebe8c3c99f`

Build output:

```text
dist/index.html                   0.59 kB | gzip 0.39 kB
dist/assets/index-CCQ_YV7J.css    3.13 kB | gzip 1.25 kB
dist/assets/index-HRJGXsyX.js   222.44 kB | gzip 69.98 kB
```

The Vite development process reported ready at `http://127.0.0.1:4171/`.
A later separate shell HTTP probe returned `ECONNREFUSED`; therefore the startup
message alone did not establish continued availability across tool calls.
A bounded follow-on local process invocation started the same npm command,
obtained HTTP 200 containing HTML on loopback, then stopped its own process group.
That is process-only evidence. Both owned development-process attempts were
stopped; no server was intentionally left running.

## Browser access blocker

The existing documented cloud-browser API was used to open exactly
`http://127.0.0.1:4171/`. At 2026-10-07T19:29Z it returned:

```text
Browser Use cannot open http://127.0.0.1:4171.
Browser reported: net::ERR_BLOCKED_BY_CLIENT
```

This is the actual browser-navigation result, not a confirmed application defect
or site bot challenge. No alternate host, network tunnel, security override,
local-user browser or new access was attempted. The local process's HTTP 200
cannot establish reachability from this browser. No rendered page or screenshot
was obtained, and neither console health nor layout can be inferred from build.

| Gate | Result | Evidence limit |
|---|---|---|
| Locked dependency install | PASS | Existing declared dependency set; no lifecycle scripts |
| Lint/typecheck/production build | PASS | Exact archived source; no browser |
| Local loopback HTTP within one invocation | PASS | HTML response only; not rendered UI |
| Existing cloud browser reaches local origin | BLOCKED | `net::ERR_BLOCKED_BY_CLIENT` |
| Actual Russian UI rendering | NOT_RUN | Page navigation blocked |
| Fatal browser console check | NOT_RUN | No loaded application context |
| 390px horizontal overflow | NOT_RUN | No viewport/layout observation |
| Keyboard focus traversal | NOT_RUN | No rendered UI interaction |
| Disabled actions produce no fake mutation | NOT_RUN | Source has disabled controls, but no browser interaction proof |
| API/auth/persistence/mobile/device readiness | NOT_RUN | Outside this shell check; no real backend integration claimed |

C5's 12 assembled-product/device journeys remain NOT_RUN. C6's approval of the
manual evidence harness does not approve this unexecuted browser run. A supported,
explicitly authorized way for the browser to reach an immutable hosted target is
still required; this package does not request or perform deployment.
