# C-104 generation 1: evidence

Latest implementation tested: `a7c8b9a3668aac8a9dbf1d90103bfc3e31baf8ec`.
Initial implementation: `9e1ea741a22fa4c8ac356fe5513b10c3924fc7d0`; initial ledger: `e780f4dce45b876e70b8bf2b7a20d6c3cd5c0bca`.
Base: `f3b3ffd00d8bb59e55d539e2321196bf18c30d7d`.
Latest author run: `2026-10-07T19:29:43Z`. Initial author/schema run: `2026-10-07T19:26:28Z`.
Environment: isolated local Python process; synthetic in-file facts; no DB, network, credentials, provider, notification or physical device.

| Check | Status | Evidence and limit |
|---|---|---|
| `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s docs/reports -p 'test_c4_report_examples.py' -v` | PASS | 19 synthetic data/render unit tests; 0 failures. Independent expected JSON; no live system claim |
| `PYTHONDONTWRITEBYTECODE=1 python docs/reports/c4_report_examples.py --output-dir /tmp/c4-report-preview` | PASS | Generated order.html, shift.html, summary.json; markup/text generation only |
| Accepted-core object schema check below | PASS | Initial SHA check; fixture bytes unchanged at latest implementation. 13 objects: 6 Order, 5 Submission (nested Assessment/Review included), 2 MaterialItem. Schema/type check, not authorization or business transition proof |
| `git diff --check` | PASS | No whitespace errors; clean worktree after implementation commit |
| Runtime report route, DB query, full lifecycle history and RBAC | NOT_RUN | No report contract/backend scope; these docs do not implement that seam |
| Real model, phone, notifications, visual browser/PDF/print, CSV/XLSX | NOT_RUN | No invocation/device/export implementation; no performance/quality claim |
| Independent C3 review | PASS | C3 re-review at `2026-10-07T19:29:06Z` on `a7c8b9a3668aac8a9dbf1d90103bfc3e31baf8ec`: 19 tests plus duplicate-review rejection, input ordering, AI isolation, mean=0/scored=1/unscored=1, timeliness=1/2 and exact material arithmetic |

Reproduce the optional schema check with already available PyYAML/jsonschema (no dependency installation required by this package):

```python
from pathlib import Path
import json, yaml, jsonschema
root = yaml.safe_load(Path('coord/proposals/a6-contract-v1/contracts/openapi.yaml').read_text())
data = json.loads(Path('docs/reports/c4-report-cases.json').read_text())
for key, kind in [('orders', 'Order'), ('submissions', 'Submission'), ('materials', 'MaterialItem')]:
    schema = {'$ref': f'#/components/schemas/{kind}', 'components': root['components']}
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    for row in data[key]:
        validator.validate(row)
```

Raw fixture SHA-256:

- `c4-report-cases.json`: `3f4aca32a90311cc6d7bbd9d3112d3787f0d447e7b869444413a7a6942d48b78`
- `c4-report-expected.json`: `704c1f7470c9b2c6024f86dcb427f3b8769f69cbc86c0bad4eef264c874d678b`

This ledger is added after the tested implementation SHA. It changes only evidence prose, not fixtures, renderer, tests or definitions. The final handoff must name both implementation and evidence commit. Parent owns publication; this evidence does not claim remote publication, CI, integration, release or R06 acceptance. Recovery is omission/revert of this docs-only package; there is no schema/data migration.

## Review correction

C3 found that the initial fixture validator accepted two different Review IDs for the same immutable submission, inflating rework counts. Commit `a7c8b9a3668aac8a9dbf1d90103bfc3e31baf8ec` adds the one-review invariant, negative regression and definition wording. Original independent probe now rejects with `submission.multiple_immutable_reviews`; C3 reported no remaining blocking finding within the declared offline scope. Runtime/full domain validation is still NOT_RUN.
