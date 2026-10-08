# Executor before-photo mounted browser gate

Product and test source: `bbe897514e58a4b8f8b6d4f580e5273e34cb5c75`, based on
`5947af4c9999bbc95f6dd0542c132e528206bce3`. This public tree matches the
reviewed author source `77740a1eb67f3297da17cac9fa3d9865012aad62` and v2 archive
`62e3fdca1963fecce654c815283272dd85b2ebc5a92e47f16f76e6bc62f4666d`.

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
