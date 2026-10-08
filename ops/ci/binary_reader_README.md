# Public synthetic binary reader diagnostic

This branch-only gate compares the unchanged `06877ab2502f8d91061fb2722a91084377b31dca`
manual binary reader with the separately reviewed experimental bounded Transform
consumer. The experiment is not installed into the product. Its signature-only
public byte sequences are not valid PDF/XLSX documents.

The unchanged author sources are preserved as siblings under
`ops/ci/binary_reader_sources/`. Driver SHA256 `5661c981699786197e5c422242926080531a066ceb25ef1832adb31a7ddd8634`;
candidate `02a844899e5490776d32558fdf9891701cd1ca8854d32aa20c821f6abdc1fa83`;
eight source probes `f42801eb3fd6479e9d64aff383695bf10972a66dab349eacef26de86d47fbf47`.
The original complete reportFiles source is pinned to
`73705ba4545e795ab3a59fa1a71de4638c1100457b606296538eb161fd0b0639`.

One run on `validation/binary-reader-probe-20261008` executes six flows per arm:
PDF signature, XLSX signature, unknown-length 8 MiB + 1 overflow, truncated body,
caller cancellation and invalid signature. Exactly one original request per
flow/arm is required. App results, original CDP capture and request completion
are recorded separately. There is no clone, tee, retry or second capture.

The official locked Chromium runs with public loopback bytes and a disposable
profile. The wrapper filters inherited inputs and execution overrides, verifies
source cleanliness, runs fresh dummy-output checks, retains raw output privately
and publishes only bounded categories, booleans, byte counts and hashes. The
outer process bound is 180 seconds; timeout or incomplete execution is
INCONCLUSIVE. A completed comparison can contain failed app checks or unavailable
CDP bytes. Workflow success means the controlled comparison completed, not that
either consumer or the original C acceptance passed. Existing C failures remain
preserved. No API/DB, provider, deployment or physical-device operation occurs.

```sh
python ops/ci/binary_reader_tests.py
python ops/ci/binary_reader_gate.py --source .ci-binary-reader --check-inputs
python ops/ci/binary_reader_gate.py --source .ci-binary-reader
```

The first supported run, [37745783006](https://github.com/a4ns/DalaAI/actions/runs/37745783006)
on harness `a7373350e667233def9aaedd048c7a1586232de3`, ended INCONCLUSIVE during
launch: TARGET_CLOSED, no recorded browser version and all twelve request counts
zero. Artifact `11535119077`, SHA256
`0b2ba4bb9ecef5008e14fa9fd47ecb10123f2f485f9f80a60c0b2ba1afb74384`, preserves
that result. It contains no byte-consumer observations.

The wrapper now uses a short fresh `/tmp/db-XXXXXXXX` parent with mode0700 and
owned cleanup. Its previous long parent could put a normal Chromium singleton
socket path beyond Linux's 108-byte pathname capacity. This is a source-derived
launch hypothesis, not an exact diagnosis of the discarded private error.
[Chromium's socket construction and length check](https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/process_singleton_posix.cc#290)
and a deterministic path-budget/ownership/cleanup test motivate the narrow
layout change. Producer, browser flags, isolation and both readers are unchanged.
