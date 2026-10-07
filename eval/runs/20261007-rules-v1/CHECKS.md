# C-102 v1 evidence

- Base: `f3b3ffd00d8bb59e55d539e2321196bf18c30d7d`
- Fixture freeze commit, before first inference: `1f925fb4207e565a421a6c655ff6089206b97cf6`
- Measured implementation SHA: `10c8e4d859190c3ad6b6241388aace7e00b69884`
- Actual environment: Python 3.12.14, local synthetic inputs, no model/DB/browser/device
- Evaluation time: `2026-10-07T19:16:11.951998Z`

## Reproduction and outcome

`PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s eval/tests -p 'test_*.py' -v`

PASS: 22 tests, including the hand-calculated eight-episode metric oracle,
input/label isolation, missing/invalid/abstaining outputs, and synthetic provider
branches. The adjacent log is a rerun on the same unchanged implementation SHA.
Synthetic provider tests do not constitute a real model run.

`PYTHONDONTWRITEBYTECODE=1 python -m eval.run --output eval/runs/20261007-rules-v1`

PASS: dev mandatory expectations 24/24; holdout mandatory expectations 24/24.
Each split has six expected permits and 18 expected blocks. Critical false permit
is 0/18 on each split. Mandatory macro-F1 is 1.0 on these authored fixtures.
Rules semantic abstention is 24/24 on each split; semantic macro-F1 is 0.0.
Fallback is 24/24 on each split. Invalid and missing outputs are 0/24 on each.

PASS: all `eval/**/*.py` files parsed with Python `ast.parse`.

PASS: `git diff f3b3ffd00d8bb59e55d539e2321196bf18c30d7d --check`.

## Not measured

Real model: NOT_RUN. No paid provider calls. USD cost: null / NOT_MEASURED.
Photo content, repair safety, real HTTP/DB close locking, permissions, deployed
latency, notifications and physical devices: NOT_RUN. See report.json for full
counts and measured local latency. Gate permission is never production acceptance.

The later commit that adds this directory is evidence-only. It does not replace
the measured SHA above. This finite non-blinded synthetic conformance suite cannot
establish industrial accuracy or zero future critical risk. Holdout was frozen
before first evaluation but is now exposed and reusable only as a regression set.
