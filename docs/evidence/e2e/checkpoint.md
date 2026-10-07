# C-105 generation 1 checkpoint

Implementation tested: `ac9e7330ed828ebd0a0e435bbc5f8ce4f04aa381`
Common base: `f3b3ffd00d8bb59e55d539e2321196bf18c30d7d`
Branch: `night/20261008/C0/C-105-g1`
Observed: 2026-10-07T19:18:31Z

## What was tested

| Check | Result | Scope |
|---|---|---|
| `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests/e2e -p 'test_*.py' -v` | PASS, 24 tests | Pure stdlib evidence-validator unit tests; fabricated metadata, no browser/network |
| `PYTHONDONTWRITEBYTECODE=1 python tests/e2e/browser_evidence.py plan` | PASS as plan command | Emits NOT_RUN for 12 product journeys |
| `PYTHONDONTWRITEBYTECODE=1 python tests/e2e/browser_evidence.py prepare --config tests/e2e/deployment.example.json --output docs/evidence/e2e/should-not-exist.json` | PASS as negative guard | Exit 2, invalid absent HTTPS target; no output file created |
| `PYTHONDONTWRITEBYTECODE=1 python -c "import sys; sys.path.insert(0,'tests/e2e'); import browser_evidence as h; h.verify_provenance(h.fingerprint())"` | PASS | Committed harness and matrix bytes match the implementation SHA |
| `git diff --check` | PASS | No whitespace errors; implementation checkout clean after checks |
| Browser lifecycle/roles/reconnect/unknown outcome | NOT_RUN | No assembled target or approved synthetic sessions supplied |
| Real DB/device/model/phone delivery | NOT_RUN | No claim from validator tests or illustrative metadata |

The follow-on commit adding this checkpoint file is documentation-only. It does
not alter the tested implementation, matrix or tests. An exact integrated
candidate needs its own applicable test rerun and independent review.

## Supported cloud-browser availability, separate from product evidence

At 2026-10-07T19:18Z, the already available cloud-browser interface reported a
running cloud Chromium/Chrome instance. Creating and observing `about:blank`
succeeded through its documented browser API. No site was opened; no account,
security setting, installation, credential, device connection or deployment was
changed. This is only a browser availability check. It does not prove target
reachability, independent authentication contexts, network-fault injection,
physical Android behavior or any C5 product journey. Browser capability details
must be verified against the eventual authorized task before execution.

The B0-reported Chromium `socket() EPERM`/SIGABRT in a different executor is not
reclassified as a pass. That executor remains blocked as reported. The existing
cloud browser is a separately available supported surface, not a sandbox change
or a bypass of an access denial.

## Limits and next ownership

- All 12 product cases remain NOT_RUN in `gaps.json`
- This package is a manual journey/evidence harness, not an automated browser driver
- A0 supplies accepted mounted API, real DB/fault proof and lifecycle authority;
  B0/B4 supply assembled frontend and verified navigation; A2/A6 supply provisioned
  synthetic roles; B6/human operator supply physical Android measurements
- No dependency, lock, root CI, contract, backend or frontend change
- No external publication, deployment, real notification, paid call or secret access
- Independent reviewer: C6 for evidence; C2 for harness when available
- Coordinator owns serialized publication; this checkpoint is not integration approval
