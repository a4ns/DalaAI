# Anonymous WebKit request-Origin comparison

This isolated branch runs the reviewed eight-case anonymous fixture once using
locked Playwright 1.63.0 and its official WebKit package on Ubuntu 24.04.
The source contract binds the exact candidate client, package/lock files and
unchanged author fixture. The baseline is main348b; its client bytes match
hosted7985. No application authentication or real account input is exercised.

The document supplies `Referrer-Policy: no-referrer`. Native browser POSTs
compare inherited policy against explicit origin-only policy. Fixed cases
require candidate Origin, origin-only Referer without path/query, retention of
synthetic cookie/CSRF values, allowed fetch metadata, and refusal of cross-origin
requests and both redirect destinations. Zero downstream hits are required.
All eight statuses remain visible. An unreproduced baseline stays inconclusive,
even when candidate checks pass. Candidate failure remains failure.

The wrapper filters execution overrides and live inputs, creates a short fresh
0700 temporary parent for the child HOME and TMPDIR, and enforces a ninety-second outer deadline. On timeout
it terminates/reaps the owned process group. Raw stdout/stderr remain private;
only fixed categories, case IDs, bounded version and exact source hashes publish.
Missing output or timeout is inconclusive, with cleanup explicitly UNVERIFIED.
A normal completed process reports the fixture finalizer separately. The
forced-final path never claims the detached browser was confirmed closed.
No unchanged retry is requested.

The fixture uses HTTP loopback, synthetic values and raw native transport options
matching the pinned client. It does not run the ApiClient itself, a hosted login,
TLS transport, a physical iPhone, or the original C110/C112/C113 acceptance tests.

```sh
python ops/ci/request_origin_tests.py
python ops/ci/request_origin_gate.py --source .ci-request-origin --check-inputs
python ops/ci/request_origin_gate.py --source .ci-request-origin
```

Reviewed product: `c219957c0ea8abe8c1c3291c66117074de380946`. Author fixture SHA256:
`f2d2a144aa028917f59bf73f32bb1694d1793e81f0bf5bb3ec3f0b2a27637f67`. Exact source inputs are in the adjacent contract.
