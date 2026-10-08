# Quiet-refresh geometry CI

Exact product `6fa27276f14ef31757cb0da5ee9d7acc15789111`, exact three-file test source
`f50dcd8e34bde095581ff3e97ece4e5b7b0f5ba0`. The reviewed fixture was prepared on
`adb93d07c9430f66d5565c7ca367f769f2b72da6`; all eight component/config dependencies
remain identical on the final product. Original preparation archive SHA256:
`5b58d7f8dfbe90d4de7560a20608f731700a08bdb92ea677cb8ab15e6f2e5084`.

Only `validation/poll-geometry-20261008` runs this workflow. One Chromium
project executes 33 unique cases: eleven at each of 320×800, 390×844 and 768×1024.
The scenarios mount actual MasterScreen, ExecutorScreen and PanelScreen with
synthetic resource states, compare populated/empty geometry and nonzero scroll
over three unchanged loading/ready cycles, check error/offline/incomplete/stale
feedback and mutation guards, and exercise executor receipt versions. The test
footer supplies scroll height for short screens. Viewport and DPR 1 are asserted
in-browser. Native mobile devices, polling stores, network timing, API/DB,
providers and the original C gates are outside this evidence.

The runner verifies immutable source and dependency hashes, requires zero skips
and retries, filters live inputs and overrides, and discards private raw output.
Only a bounded summary is uploaded. A successful geometry gate does not repair
or replace preserved C113 binary-capture failures.

Commands on the assembled isolated branch:

```sh
python ops/ci/poll_geometry_tests.py
python ops/ci/poll_geometry_gate.py --source .ci-poll-geometry --check-inputs
python ops/ci/poll_geometry_gate.py --source .ci-poll-geometry
```
