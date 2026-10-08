# Healthy polling and explicit command acceptance

Product and test source: `d78b9c3b7cabbcbd05b01df77f2a7ec57739afe5`,
based on `5368cdc73b7d602e26d2ee4aa8cc29ea1561b96d`. Exact author archive:
`a48e2fd84a296cc41a3ced4a62628d80ef613e09da297c317d7117ca3141ac5e`.
Seven changed files and eight unchanged toolchain/support inputs are pinned.
The exact matrix is twelve source cases and seven mounted App cases.
Only `validation/healthy-poll-commands-20261008` triggers the workflow.

The required source checks build the production App before loopback-only Vite
preview. The exact authored source and mounted App scenarios then run once, with
no retries, skips or unreached-case promotion. The pinned Playwright 1.63.0
Chromium project uses 390×844, DPR 1, desktop mode and no touch.
HTTP responses and identities are synthetic intercepted fixtures; this does not
establish actual backend authorization, physical-device or provider behavior.

The source-bound gate checks clean product/test bytes before and after the run.
It filters live inputs and execution overrides and disables trace/video/screenshots.
Raw output stays private. The public summary contains fixed execution counts,
case identities and bounded failure classes/source locations. The original
C110/C112/C113 journeys and their historical evidence remain separate.

```sh
python ops/ci/healthy_poll_tests.py
python ops/ci/healthy_poll_gate.py --source .ci-healthy-poll --check-inputs
python ops/ci/healthy_poll_gate.py --source .ci-healthy-poll
```

The three positive mounted cases require one master-close, master-rework or
executor-accept POST before a held healthy GET is released, with the original
expected version. The remaining cases require zero deferred commands after
failed polling, offline invalidation/late completion, explicit manual refresh
joining a background read, and the synchronous logout latch. Source tests also
cover the whole-sweep fifteen-second bound, pagination, higher versions, scope
and epoch loss, local expiry and sticky unknown operations. All nineteen cases
must pass; full 298-case source evidence is a separate author/integrator check.
These controlled held-request scenarios do not measure production network timing.
