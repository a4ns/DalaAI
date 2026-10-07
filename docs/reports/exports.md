# PDF / XLSX reports (C5)

## Integration contract

This package adds real binary exports over C111's `RuntimeReportService` and typed
`AnalyticsFacts`. It does not introduce a second serializer, authentication method,
repository, grant, migration, source query, or provider call.

A5 owns mounting, exact dependency locks and API/managed image changes. Mount
`create_c_export_router(report_service)` **before** `create_c_runtime_router`:
otherwise C4's generic `/reports/orders/{order_id}` consumes a UUID with its suffix.
Keep both routers on the same already configured report service.

Authenticated GET routes:

- `/api/v1/reports/shift.pdf`
- `/api/v1/reports/shift.xlsx`
- `/api/v1/reports/orders/{order_id}.pdf`
- `/api/v1/reports/orders/{order_id}.xlsx`

Send required `start` and `end` as timezone-aware ISO datetimes. C111's unchanged
parser owns period bounds (at most 93 days, end no later than domain time), UUID
validation, duplicate and unknown parameter rejection. `format=json` is accepted
by that existing parser but does not change the fixed route's binary format.
`format=pdf`, `format=xlsx` and `format=html` are rejected: use the fixed URL without
a format query. Actor, role, section, token and arbitrary export configuration
parameters are not accepted.

Only the existing single session cookie authenticates these routes. C111 currently
permits the active master in their current sections; this package does not widen
the role set. Existing object scoping and consistent snapshot reads remain in
C111. Rendering is inside its `capture(project=...)`, and the complete response
body is prepared before C111's final real-time session/role/membership recheck and
transaction completion. No partial stream is returned if that check fails.

Downloads use fixed ASCII names with a server-normalized UUID, never an order
number or query string. Responses carry private/no-store, Vary: Cookie, nosniff,
no-referrer and attachment headers. Errors use the existing JSON shape and no
attachment header. Unavailable rendering returns 503/Retry-After: 1; size/data
limits return 422/REPORT_LIMIT_EXCEEDED. Raw exceptions are not returned.

## Data semantics

Both formats show Russian labels, explicit synthetic/source mode, authorized
scope, source reference, domain snapshot time, actual capture time, period,
Asia/Almaty time zone, completeness and limitations.

- An order export contains just that authorized order, all captured attempts,
  separate human decisions and AI recommendations, material declarations and
  photo references. It contains no scope-wide totals or other orders.
- The shift export uses the metric values and cohorts already computed by C3,
  including denominators, missing/excluded records, small-sample flags, source
  identifiers, executor components and declared materials of closed attempts.
  It does not recompute business formulas or invent a composite ranking.
- Missing human/AI values remain empty XLSX cells and `нет данных` in PDF. Numeric
  zero remains zero. There are explicit human-score-present and decision-present
  fields. An AI score never fills an absent human score.
- Incomplete provenance suppresses all totals even when attached arrays exist.
- C111 historical missing-photo evidence is visibly disclosed. Only approved
  count fields are copied from its auxiliary evidence dictionary. Historical
  completeness does not prove photo validity, AI execution or a live closure.
- Photo identifiers are text, not links. Neither renderer reads/embeds images,
  object-store URLs, EXIF, credentials, session handles or raw SQL. Source free
  text remains authorized report content and is never interpreted as instructions.

XLSX has real numeric, boolean and date cells. Dates are converted to naive
Asia/Almaty display values because Excel cells do not carry time-zone offsets;
the zone is labeled. Exact decimal values are retained in adjacent text columns
because Excel numeric precision is limited. No formulas, macros, external
relationships or hyperlinks are created. Every string is explicitly stored as
literal text with quotePrefix, including formula/DDE/error-looking text.
Overlong or XML-invalid text fails instead of being silently truncated.

PDF uses ReportLab's literal canvas text methods, with no HTML/XML interpretation,
images, clickable links, scripts or attachments. It embeds the DejaVu Sans font
subsets and Unicode mapping for Cyrillic. Long words/text wrap and paginate.

## Runtime/dependency requirements and limits

Approved direct packages: `reportlab==4.4.9`, `openpyxl==3.1.5`. A5 pins the full
closure (including `et_xmlfile==2.0.0`) in the existing locks. Runtime fonts from
official Debian `fonts-dejavu-core` must exist at:

- `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`
- `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`

Missing fonts fail closed. No download/fallback/font path is request-controlled.
The current subprocess envelope targets the Linux/Python 3.12 runtime.

- Maximum output: 8 MiB; maximum trusted worker input pickle: 16 MiB
- Maximum rendered cells: 120,000; source text: 1,000,000 characters total;
  maximum one text cell: 30,000 characters; maximum PDF: 200 pages
- Two in-flight export captures per API process, with immediate 503 when full
- Fresh Python renderer process; six-second wall-time limit, six CPU seconds,
  512 MiB address-space limit; process is killed and reaped on timeout
- Child receives bounded facts, output selector, normalized order ID and approved
  evidence only. It gets a minimal import-path/locale environment, not inherited
  DATABASE_URL/provider credentials, session state or open PostgreSQL descriptors.
- `communicate` reads/writes pipes together, avoiding join-before-read deadlocks
- No temporary artifact files are created by the renderers. The worker reads only
  installed code/fonts and imports. No renderer network operation is implemented.

These are render limits, not a claim of total HTTP latency. Database capture keeps
C111's existing bounded row/byte/period extraction and per-statement/lock timeouts.
Mixed API/worker/export load capacity is **unmeasured**. There is no queue, retry,
artifact cache, download token or background artifact retention. Large scopes can
fail. A narrower period may reduce rendered cohorts, but C111 still captures the
whole authorized scope; an order export also reduces source capture. Nothing is
silently truncated.

Long Excel cells preserve all text, but native Excel's row-height limit may require
opening a cell or using its formula bar. PDF is a paginated evidence report, not a
one-page executive dashboard. It is not tagged PDF/PDF-A and contains no digital
signature. Native Microsoft Excel/LibreOffice, actual deployed process limits and
actual PostgreSQL export-route tests remain integration acceptance gates.

## Verification

Candidate was assembled against final C111 source
`2945e3d3b6ba187a510cfb715e22d9feb70c4408` (mounted by A5 on
`f101e4320b59b0a7dc81bdcb8b28c73849d4a747`), with existing C108/C109 facts.
No shared source was modified in this package.

Run in a complete installed backend:

```sh
PYTHONPATH=backend:backend/tests python -m unittest test_c5_exports -v
PYTHONPATH=backend:backend/tests python -m unittest \
  test_c3_facts test_c4_render test_c_runtime_routes test_c5_exports -v
```

Local synthetic verification on 2026-10-07:

- 17 C5 tests passed; 84 combined C3/C4/C111/C5 tests passed
- Real subprocess PDF and XLSX generation succeeded for both order and shift
- Order PDF: 9 pages with two intentionally very long hostile-text attempts;
  shift PDF: 4 pages; all 13 pages rasterized with Poppler and visually inspected
- Cyrillic extraction with pypdf succeeded; zero PDF image objects and annotations
- XLSX reopened with openpyxl: values/types, null versus zero, human versus AI,
  timezone conversion, exact decimal text, no formulas/external links/macros,
  long text preservation and literal formula/DDE/XML/error payloads verified
- HTTP tests exercise actual SessionService with C111's mock database transport:
  missing/duplicate/expired/revoked cookie, current roles, scope, foreign ID,
  query/date bounds, final expiry/role/membership change during serialization,
  historical missing-photo disclosure, capacity and no-partial-output failures
- Worker timeout cleanup and credential-free environment verified by focused mock;
  actual successful subprocesses also run in the suite
- Separate 540-order synthetic rendering-envelope check: PDF 82 pages / 175,885
  bytes in 0.407 s; XLSX 149,898 bytes in 1.696 s. All metric source IDs remain
  in PDF text. This is neither a database benchmark nor mixed-load capacity proof

No actual database or deployed route evidence is claimed by these focused tests.
A5 runs the integration/aggregate gate; the designated security reviewer separately
reviews this candidate. Source documentation:
[ReportLab canvas](https://docs.reportlab.com/reportlab/userguide/ch2_graphics/),
[openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html).
