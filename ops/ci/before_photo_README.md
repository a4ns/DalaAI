# Executor before-photo mounted browser gate

Product: `bbe897514e58a4b8f8b6d4f580e5273e34cb5c75`, based on
`5947af4c9999bbc95f6dd0542c132e528206bce3`. Corrected test source:
`cebdda9b225f8544854dcc2efafdeb400e2f592d`, with identical product bytes.
The test source matches reviewed author `955f872c966de163c964066455bf529f961ef256`
and v3 archive `fb2c6e13c6252ddc4cddfa4581392fe64b8910cdd05619bf4f99c06e46026d59`.

This isolated gate runs the author's exact twenty-one source cases and eight mounted
App cases with pinned Playwright1.63.0 Pixel 9 Android emulation. Its contract
records the immutable source, eight changed product/test blobs, seven unchanged
dependencies and exact unique test titles. Missing source approval blocks input
validation. Only `validation/before-photo-browser-20261008` triggers the workflow.

The browser scenarios decode a fixed one-pixel PNG, keep reads tied to the
selected assigned order, exercise403/404, delayed old selection, lost session
scope and assignment, logout-start cleanup, repeated commands/retries and quiet
polling. HTTP responses and identities are intercepted synthetic fixtures. The
source suite also tests bounded concurrency and explicit recovery after a newer
authorized confirmation. This is component/App acceptance; backend authorization,
stored attachments, real cameras and physical Android are separate evidence.

The runner first builds the production app, then serves that build through
loopback-only Vite preview. Exact request counts concern this production mount;
development StrictMode effect replay is outside this gate.

The configuration checks the installed Pixel 9 descriptor (360×732, DPR3,
mobile/touch, Android14), uses one browser project, zero retries, and disables
trace/video/screenshots. The runner requires all29 exact cases with no skips,
filters live inputs and execution overrides, verifies a clean immutable source
before and after execution, and uploads only a bounded summary. Private raw
browser errors and output are discarded. Original C journeys remain separate.

```sh
python ops/ci/before_photo_tests.py
python ops/ci/before_photo_gate.py --source .ci-before-photo --check-inputs
python ops/ci/before_photo_gate.py --source .ci-before-photo
```

The first [run37753273867](https://github.com/a4ns/DalaAI/actions/runs/37753273867)
on `b2cf92b6e215f372352688494ba9af9c3df0ed99` failed at the initial duplicate
heading locator, before mounted photo acceptance. Artifact11538364082 has SHA256
`39bf87bbe74fd26753b306a542d6f436df9b203c4ca43c629869526eb48b7649`.
That attempt used development mode. Its later generic diagnostic entries did
not establish failures in unreached cases after maxFailures stopped the suite.
The corrected author spec selects the h1 and polls the unchanged decoded-width
assertion. The runner now reports execution counts separately and only projects
actual failed result locations. All21 source and8 browser cases are still required.
