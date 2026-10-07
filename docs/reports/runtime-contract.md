# Runtime order and shift presentation

## Boundary

C4 renders the single internal C3 `app.analytics.c3_types.AnalyticsFacts`
DTO, serialized by `app.analytics.c3_facts.facts_to_dict`. It does not accept
ORM rows, browser payloads, offline C4 fixture dictionaries,
or a second report-input contract. This is presentation code, not an HTTP API.
The required C3 source checkpoint is
`b3bf7ef5ed5dae0f2e39ef5037c304e709fea0fb`, including the coverage-policy
hardening of `AnalyticsFacts.totals_available` and serialization.
A5 owns protected endpoint integration. The caller must authenticate, authorize and
load only the current caller's permitted facts before calling C4.

The public offline C4 checkpoint
`4a5184fd5caa3c1be35fea5ff55d534967c191bf` is an independent behavior oracle:
escaped text, explicit synthetic provenance, missing human scores kept separate
from AI recommendations, and no totals inferred from incomplete keyset pages.
The runtime implementation never opens that checkout, invokes Git, reads fixture
files, or loads historical export data.

## Deliverables

- `order_report_data(facts, order_id)` returns a JSON-safe projection containing
  one observed order, its attempts, provenance and source limitations
- `shift_report_data(facts)` returns JSON-safe C3 metric/rating/material facts
  with source IDs, denominators, missing/excluded records and coverage limits
- `render_order_html(facts, order_id)` and `render_shift_html(facts)` return
  standalone Russian HTML text, not files, PDF, XLSX or protected routes

No renderer computes a new rating, fills a missing score with zero or an AI
score, fetches photos, performs an AI call, calculates hidden-scope totals, reads
the filesystem, or accesses a database. Exact decimal values remain JSON strings
according to C3 serialization; nullable values remain JSON null.

## Display invariants

1. Every source string appears only in an escaped text node. There are no source
   URLs, scripts, forms, images, iframe embeds, dynamic attributes or external
   resources. The document's fixed content-security policy also denies network
   access and script execution. HTML is an inert view, not a sanitizer for later
   use of JSON strings in other HTML contexts.
2. The report identifies synthetic mode, source reference, authorized scope,
   coverage, source domain time and real capture time. A synthetic flag is never
   a claim of real DB, model, photo or device verification.
3. The selected period is half-open `[start, end)`. Display time uses the DTO's
   stated time zone. The renderer does not change cohort boundaries or recalculate
   C3 metrics from displayed rows.
4. An absent assessment means no assessment in the source; the AI job state is
   unknown. It does not mean pending or failed. Every recorded assessment retains
   its mode, model metadata, source IDs, score, fallback reason and stale flag.
   A recommendation recorded after the human review is explicitly labeled as
   later than the decision; an earlier timestamp does not prove it was viewed.
5. A missing human score is displayed as «не оценено». Zero stays zero. AI scores
   remain separate recommendations. A composite rating lacking supported inputs
   is not fabricated from an average human score.
6. Current and historical attempts stay distinct. Attempt materials are declared
   quantities, not confirmed warehouse writeoffs. Photo IDs are references only;
   no image bytes or physical evidence are verified here. Attempts and reviews
   are not a complete OrderEvent history.
7. Partial or moving source coverage cannot produce complete shift totals. An
   observed-order count is never relabeled as a scope-wide total. An order view
   never includes other orders, executor rankings or shift-wide metrics.

## Verification limits

Focused tests use declared C3 DTO instances with synthetic values. Those tests
exercise presentation behavior only. DB persistence, HTTP authorization, browser
layout/printing, actual model output, real photos and real devices need separate
integration evidence. A source-only C4 checkout without the C3 dependency is
BLOCKED, not PASS and not silently skipped. The integration handoff must identify
both immutable code SHAs and the assembly command used for the focused tests.

## Function contracts

`order_report_data` returns `report_kind`, `fact_schema_version`, `provenance`,
`period`, `unavailable_reasons`, `limitations` and one `order` in the unchanged C3
OrderFact wire shape. A missing or duplicate selected ID raises `ValueError`.
No list of other IDs is disclosed by that error. This failure is not an HTTP
status; the protected route owns its own response and authorization policy.

`shift_report_data` returns the same common metadata and `totals_available`,
`metrics`, `ratings`, `closed_materials`. Availability is obtained from the C3
DTO property, not independently inferred from a number of observed rows.
Unavailable aggregate fields are all null, even if a directly constructed test
DTO incorrectly contains metric values with partial coverage. Available metric
facts are passed through without rounding, regrouping or recomputing values.

The dictionaries are fresh detached JSON projections. Source strings remain
literal JSON strings, so other clients must use their own contextual escaping.
The HTML functions escape them as text and never embed JSON in executable script.
There is no HTML-to-PDF or spreadsheet export behind these function names.

Run focused presentation tests only after assembling the exact C3 dependency:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend \
  python3 -m unittest discover -s backend/tests -p 'test_c4_render.py' -v
```

Do not replace missing `app.analytics.c3_types` or `c3_facts` with local mocks,
conditional fallback classes, or test skips. The source-only package deliberately
fails import until its real C3 dependency has been assembled.
