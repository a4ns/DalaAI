# Isolated body-capture diagnostic wiring

Branch only: `validation/body-capture-probe-20261008`. No main, pull-request or
workflow-dispatch trigger. A5 publishes the reviewed assembly; this wiring makes
no change to product064a7a37, frontend1594a930 or any existing C113 acceptance file.

The immutable probe is 74f164e19c87a1569889b21e0e1f6be4c4bdd40d. The input
manifest pins every probe file and all reused CI files. Full checkout history is
required so the probe can compare product trees against064a7a37. Staged, working
and non-ignored untracked source changes block execution. The installed Chromium
locator is explicit; the probe keeps it in its permitted Node-driver environment.

The runner reuses the reviewed six-service history/clock Compose profile with a
fresh owned private directory, unique project and normal localhost TLS/NSS trust.
Worker/provider services remain inactive, PostgreSQL stays internal and unpublished,
and the original observer still runs READ ONLY in its restricted sidecar.

A separate source-bound dummy privacy preflight runs before actual PIN/DB fixture
generation. It cannot reuse a C113 receipt. The fixed private observer adapter is
rendered with root/private/project/clock/source values, validates the frozen script
and two manifest actors, and constructs a minimal Docker environment. It does not
forward the child DSN, PIN inputs, DALA_CI values or loader/network overrides.
The independent inspector receives the original probe's credential-free environment.

Only the producer's strictly validated safe evidence and bounded summary are
published. Raw CLI output, Playwright artifacts, PDF, private inputs and browser
profiles remain temporary; both the probe and runner clean their owned resources.
The original C113 failure remains unchanged. Every result is
INSTRUMENTED_DIAGNOSTIC_ONLY with c113_acceptance=NOT_ESTABLISHED. A successful
diagnostic process is never a C113 pass, deployment or provider/device proof.

Source checks: `python ops/ci/body_probe_tests.py`,
`python ops/ci/body_probe_runner.py --check-inputs`, and
`node --test tests/e2e/body_capture_probe/*.test.cjs`.
Actual execution is the reviewed branch workflow's `python ops/ci/body_probe_runner.py`.
