# Public synthetic JSON reader comparison

Run once on `validation/json-reader-probe-20261008`, isolated from main and all
C suites. Exact original product a880371589aa1dd117dde9e80936c687d146f919 supplies
the pre-compatibility reader. The unchanged reviewed standalone producer has
SHA256670fad19f7837ca4e98999530301950a626a15077acf3a368aa2a5d8bbd3f5ae.

The source and dummy-output checks precede runtime. Official locked Playwright
1.63.0/Chromium and TypeScript6.0.3 are used with a filtered environment. The
producer serves fixed public175949-byte UTF-8 JSON on ephemeral127.0.0.1 and
performs one request in each arm: native text parsing and the exact streaming
reader. App and original CDP observer results remain separate, including failures.
An overall comparison result never becomes C110/C112/C113 or actual-app acceptance.

The runtime has a120-second outer bound; timeout is inconclusive, followed by
bounded owned-process termination. The producer's20-second inner bounds and
no-retry behavior are unchanged. No private inputs, application mutations,
provider calls, original C edits or deployment occur. Raw stdout/stderr/error
text remains private; only fixed categories, hashes, bounded byte/row counts and
one-request counts are published. A difference is a completed diagnostic outcome,
not an instruction to retry until green.

The prior local attempt was BLOCKED at Chromium launch, before either arm:
counts0/0. Its separate result SHA256 is
0507919a3cdfac804bb2713ab210544f40b1edca666eae7c4c2c12633c185a08.
No runtime cause or reader behavior was inferred from that local result.

Source checks: `python ops/ci/json_reader_tests.py`,
`node --check ops/ci/json_reader_probe.cjs` and
`python ops/ci/json_reader_gate.py --source .ci-json-reader --check-inputs`.
The branch workflow installs dependencies, then runs the same gate without
`--check-inputs` once. Only `json-reader-summary.json` is an upload target.
