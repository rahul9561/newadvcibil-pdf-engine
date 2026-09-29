# newadv-cibil-pdf-engine

A reusable, framework-agnostic **JSON → PDF** rendering engine for
CIBIL-style consumer credit reports. Give it bureau JSON (or the
`{"status", "message", "data": ...}` API envelope that wraps it), get back
a PDF that reproduces the layout of the reference report
`pdfsample/sample.pdf`.

**Quick start** - render the bundled sample:

```bash
pip install -e ".[test]"
python -m newadv_cibil_pdf_engine --input input/sample.json --output output/sample.pdf
```

The package is `newadv_cibil_pdf_engine` (console script
`newadv-cibil-pdf-engine`); it supersedes the engine's earlier package name.

```python
from newadv_cibil_pdf_engine import generate_pdf

generate_pdf(report_json=data, output_path="report.pdf")
```

No Django/Flask/FastAPI/Celery/database/AWS/HTTP dependency - the package
only ever takes JSON in and hands PDF bytes (and optionally a file) back.
It works equally well inside a Django view, a Celery task, a FastAPI
endpoint, or a plain script.

---

## 1. How this was built (read this first)

This engine was reverse-engineered from a sample bureau JSON payload
(`input/sample.json`) and a reference PDF (`pdfsample/sample.pdf`).
**The reference PDF was generated from a different consumer's data than
the sample JSON** - it is a *style/layout* reference only, not a
byte-for-byte target. The engine reproduces the reference's sections,
tables, typography, colours and pagination behaviour generically, driven
entirely by whatever data is present in the input JSON. It never hardcodes
the sample person's name, PAN, accounts, or any other customer-specific
value - see `tests/test_parser.py` and `tests/test_report.py` for edge
cases (zero accounts, 60 accounts, long names/addresses, masking, etc.)
proving that, in particular
`test_report.py::test_modified_customer_data_actually_appears_in_output`,
which mutates every kind of customer field (name, PAN, mobile, address,
score, account number, lender, amount, enquiry, dates) and asserts the
new values appear in the rendered PDF text while the replaced originals
do not.

**`docs/FIELD_MAPPING.md`** has the complete field-by-field table (every
row cites the exact `parser.py` JSON path); the table below is the
condensed version.

### The JSON shapes this engine understands

**Current format - `B2C-REPORT` (`input/sample.json`).** The upstream API
now returns `{"data": {"result_json": {"parsed_data": {"B2C-REPORT":
{...}}}}, "status": ..., "message": ...}`. It is parsed by
`newadv_cibil_pdf_engine/parser_b2c.py` and takes priority over the two
legacy shapes below. Key structures:

| B2C-REPORT path | Used for |
|---|---|
| `HEADER-SEGMENT.REPORT-ID` / `DATE-OF-ISSUE` | Control Number / Date |
| `REPORT-DATA.STANDARD-DATA.SCORE[0]` (`VALUE`, `FACTORS`) | Score gauge |
| `STANDARD-DATA.DEMOGS.VARIATIONS[]` (`NAME-`, `DOB-`, `PAN-`, `PHONE-`, `EMAIL-`, `ADDRESS-VARIATIONS`) | Personal / Identification / Address / Contact / Email |
| `REQUEST-DATA.APPLICANT-SEGMENT` | Gender; fallback name/phones when the bureau returned none |
| `STANDARD-DATA.EMPLOYMENT-DETAILS[].EMPLOYMENT-DETAIL` | Employment (latest `LAST-REPORTED-DT`) |
| `STANDARD-DATA.TRADELINES[]` | Accounts (one block each) |
| `TRADELINES[].HISTORY[NAME=COMBINED-PAYMENT-HISTORY]` | Payment History grid (`DATES` `Mon:YYYY`, `VALUES` `DPD/CLASS`, pipe-delimited) |
| `STANDARD-DATA.INQUIRY-HISTORY[]` | Enquiry Details |

`docs/FIELD_MAPPING.md` has the field-by-field B2C table. Payment-history
cells: `"000/STD"` → `0`, `"045/STD"` → `45`, an adverse class keeps both
parts (`"090/SUB"` → `90/SUB`), a non-numeric DPD shows the class
(`"XXX/XXX"` → `XXX`), blank → empty cell; unknown codes are shown
verbatim. B2C fields beyond the reference's 19 ACCOUNT DETAILS rows
(Account Status, Security Status/Type, Suit Filed / Wilful Default,
remarks, dispute, write-off/suit dates, Last Paid Amount) are appended as
extra rows only when reported.

**Legacy formats.** The previous sample (now `tests/fixtures/tlcr_sample.json`)
turned out to be a full upstream API transaction trace
(`{"data": {"steps": [FulfillOffer, GetAuthenticationQuestions,
GetCustomerAssets, GetProductWebToken]}}`), not report JSON on its own.
Digging into the `GetCustomerAssets` step revealed the actual bureau data
in **two different shapes**, nested inside each other:

1. **Normalised** - `Asset.TrueLinkCreditReport`, with `Borrower`,
   `TradeLinePartition` (accounts), `InquiryPartition` (enquiries).
   Most coded fields are `{"symbol": "05", "description": "", ...}`
   objects, and payment-history status is a literal `"STD"`/`"SUB"`/...
   string per month. This is the primary, best-supported shape - it is
   what a `GetCustomerAssets`-style API step returns in practice, and it
   carries the richest, already-partially-decoded data.
2. **Raw bureau** - base64-encoded inside
   `TrueLinkCreditReport.Sources.Source.OriginalData`, an
   `ICRS_SubjectInquiryByTUEF_Response.subject[0]` object where every
   coded field is a bare numeric/short-string code (`"accountType":
   "05"`) and payment history is a numeric array (`[901, 901, 29, -2,
   ...]`). This is the bureau's raw wire format.

The parser (`newadv_cibil_pdf_engine/parser.py`) **searches the input for either
shape at any nesting depth** - it does not care whether you hand it the
full 4-step API trace, a `{status, message, data}` wrapper around it, the
`TrueLinkCreditReport` object on its own, or the raw
`ICRS_SubjectInquiryByTUEF_Response`/`subject` object on its own. Whichever
one is found is used; if the normalised shape is found, its raw sibling
(if also present) is opportunistically decoded and consulted only for the
one field the normalised shape doesn't carry (`dateOfLastPayment`).

### JSON path → PDF section → PDF field

| PDF Section | Source (normalised shape) | Source (raw shape) |
|---|---|---|
| Header (name/date/control number) | `Borrower.BorrowerName.Name.Forename`; `ReferenceKey`; `Borrower.CreditScore.Source.InquiryDate` | `subject.name.name1`; `ecn`; `timestamp` |
| CIBIL Score gauge | `Borrower.CreditScore.riskScore` (range 300-900 is a fixed property of the CIBIL score system, not customer data) | `subject.scores[0].score` |
| Personal Details | `Borrower.BorrowerName`, `Borrower.Birth.date`, `Borrower.Gender` | `subject.name.{name1,dob,gender}` |
| Identification Details | `Borrower.IdentifierPartition.Identifier[].ID.{IdentifierName,Id}` | `subject.id[].{idType,idNumber}` |
| Address Details | `Borrower.BorrowerAddress[].{CreditAddress,Dwelling,dateReported}` | `subject.address[]` |
| Contact Details | `Borrower.BorrowerTelephone[].{PhoneType,PhoneNumber}` | `subject.telephone[]` |
| Email Details | `Borrower.BorrowerEmail` / `EmailAddress` (not present in the sample) | `subject.email[]` |
| Employment Details | `Borrower.Employer.{account,dateReported,name}` | `subject.employment` |
| All Accounts (open/closed) | `TradeLinePartition[].Tradeline` (open = no `dateClosed`) | `subject.account[]` (open = no `dateClosed`) |
| Account Details | `Tradeline.{highBalance,currentBalance,...}`, `.GrantedTrade.{CreditLimit,EMIAmount,interestRate,termMonths,...}` | `subject.account[].{highCreditAmount,currentBalance,...}` |
| Payment Status / History grid | `GrantedTrade.PayStatusHistory.{startDate,endDate,MonthlyPayStatus[]}` (literal `STD`/`SUB`/... per month) | `subject.account[].{paymentHistStartDate,paymentHistEndDate,paymentHistory[]}` (numeric, see decoding note below) |
| Enquiry Details | `InquiryPartition[].Inquiry.{subscriberName,inquiryDate,inquiryType,amount}` | `subject.inquiry[]` |

Full per-field mapping lives in `parser.py::_parse_tlcr_*` and
`parser.py::_parse_raw_*` - every dataclass field in `models.py` traces
back to exactly one JSON path in one of those functions.

### Coded-field decoding, and what could **not** be verified

Coded fields are resolved through `data/codes.py`, which documents, for
every table, exactly how confident the mapping is and why (RBI standard
table citation, direct cross-check against the reference PDF, cross-check
between the JSON's own two shapes for the same person, or best-effort
default). Read the module docstring for the full breakdown; the short
version:

* **High confidence** (RBI Uniform Credit Reporting Format, cross-checked
  against the reference PDF and/or the sample JSON's own two
  representations of the same person): Account Type, Ownership Indicator,
  Asset Classification (STD/SUB/DBT/LSS/SMA/XXX), Identifier Type/Name,
  Gender code.
* **Medium confidence**: the raw shape's numeric payment-history sentinel
  values (900-905 standing in for STD/SUB/DBT/LSS/SMA/XXX) - inferred from
  the *distribution* of values in the sample, not from documentation,
  because the reference PDF's underlying JSON isn't available to
  cross-check directly. Override via
  `GenerateOptions.payment_history_sentinel_map` if your feed disagrees.
* **Low confidence / best effort, explicitly flagged**: Address Category
  (Residence/Permanent/Office) and Dwelling/Residence-Code. The reference
  PDF shows these as plain English ("Residence Address", "Owned") but its
  underlying JSON isn't available, and the sample JSON's own two
  representations don't cross-corroborate every value.
* **Fields visible in the reference PDF that could not be located in
  either JSON shape at all** - not guessed, always rendered as `"-"`:
  - `Employment Details → Occupation` (reference shows "Self Employed
    Professional"; neither JSON shape has an occupation-category field -
    `Employer.name`, which is what's mapped, was blank in the sample).
  - `Employment Details → Income` (no income amount field exists in
    either shape).
  - `Identification Details → Issue Date / Expiry Date` (no
    `dateIssued`/`dateExpired` field exists on identifiers in either
    shape; both are inspected by the parser in case a future feed adds
    them, but render as `-` for this sample).
  - The normalised shape has no `dateOfLastPayment`/`fileSinceDate` field
    at all (only the raw shape does) - the parser opportunistically
    enriches from the raw shape by matching on account number when both
    are present in the same document, and falls back to `-` otherwise.

---

## 2. Why WeasyPrint

Three PDF-rendering approaches were evaluated:

| | WeasyPrint | Playwright/Chromium | ReportLab |
|---|---|---|---|
| CSS3 Paged Media (running headers/footers, `counter(page)`) | Native | Emulated via `page.pdf(header_template=...)` | Manual, per-page Python code |
| Table support (repeat headers, avoid mid-row splits) | Native CSS | Native CSS | Manual `Table`/`TableStyle` |
| Page-break control | `break-inside`/`break-before` CSS, well-supported | Same CSS, plus real browser layout | Manual flowable/frame math |
| Deployment | Pure Python + a handful of native libs (Pango/Cairo) | Ships/downloads a full Chromium binary | Pure Python, no native deps |
| Docker image size/complexity | Small (`apt install` a few `.so`s) | Larger (Chromium + its own deps) | Smallest |
| Fits this task | Declarative, matches "reverse-engineer a *layout*" well | Overkill for a fixed print layout | Would mean hand-coding every table/card in Python - the "one-off script" anti-pattern the brief explicitly warns against |

WeasyPrint won: it renders the templates/CSS in this repo with native
CSS Paged Media support (the reference PDF's running header/footer and
page-number pattern maps directly onto `@page { @top-left {...}
@bottom-right {...} }`), it needs no browser binary in the deployment
image, and - critically for "don't hand-draw the layout" - the
account-detail cards, payment-history grid, and section headers are all
just CSS, not per-report Python drawing code.

---

## 3. Architecture

```
JSON (any of the shapes above)
  │
  ▼
parser.py            locate_report_root() finds the bureau object anywhere
                      in the input, then _parse_tlcr()/_parse_raw_subject()
                      normalise it - every coded field resolved, every date/
                      currency formatted, every missing field defaulted.
  │
  ▼
models.py             NormalizedReport dataclasses (display-ready strings,
                      never raw JSON) - the only thing renderers/templates
                      ever see.
  │
  ▼
renderers/            One module per reference-PDF section (consumer,
                      score, accounts, enquiries, addresses, contact,
                      summary) turning the model into a template context
                      dict. renderers/__init__.py::build_context()
                      composes them.
  │
  ▼
templates/*.html      Jinja2 templates, one per section, included into
static/css/report.css report.html. Pure presentation - no business logic.
  │
  ▼
engine.py             Renders the Jinja2 template to an HTML string
                      (render_report_html - useful standalone for
                      debugging in a browser) and feeds it to WeasyPrint
                      (generate_pdf_bytes / generate_pdf).
  │
  ▼
PDF
```

```
newadv_cibil_pdf_engine/
├── __init__.py          public API re-exports
├── engine.py             JSON -> HTML -> PDF orchestration
├── parser.py             JSON -> NormalizedReport
├── models.py              NormalizedReport dataclasses
├── exceptions.py          exception hierarchy
├── utils.py               date/currency/masking/coded-label helpers
├── data/codes.py          bureau code tables (see docstring for provenance)
├── renderers/              NormalizedReport -> template context, per section
├── templates/*.html       Jinja2 templates
└── static/css/report.css  all visual styling
tests/
├── test_parser.py, test_renderer.py, test_report.py   pytest suite
├── compare_reference.py   manual fidelity-check workflow (see below)
├── reference/sample.pdf   the reference PDF this engine targets
└── output/generated.pdf   latest render of input/sample.json
```

---

## 4. Installation

```bash
pip install -e .
# or, without an editable install:
pip install -r requirements.txt
```

**System dependency**: WeasyPrint needs Pango/Cairo/GDK-Pixbuf.

* Debian/Ubuntu: `apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-dejavu-core`
* macOS: `brew install pango`
* Windows: `pip install weasyprint` alone works on recent versions (as
  used to build/verify this package); if you hit a `libgobject`-not-found
  error, install the GTK3 runtime.

## 5. Basic usage

```python
from newadv_cibil_pdf_engine import generate_pdf, generate_pdf_bytes

# to a file
generate_pdf(report_json=data, output_path="report.pdf")

# to bytes (no disk I/O)
pdf_bytes = generate_pdf_bytes(report_json=data)

# with options
generate_pdf(
    report_json=data,
    output_path="report.pdf",
    options={"mask_account_numbers": True, "include_footer": True},
)
```

Other entry points:

```python
from newadv_cibil_pdf_engine import (
    render_report_html,       # HTML string only, for debugging in a browser
    validate_report_json,     # bool: does this JSON contain a report?
    generate_pdf_from_api_response,  # explicit alias for the {status,message,data} shape
)
from newadv_cibil_pdf_engine.engine import parse_report  # JSON -> NormalizedReport, no rendering
```

`generate_pdf`/`generate_pdf_bytes` already auto-detect and unwrap a
`{"status": ..., "message": ..., "data": <report>}` API envelope, so you
can pass either the full API response or just the report JSON - both work
identically. `generate_pdf_from_api_response` is a same-behaviour alias
kept for call-site clarity.

## 6. Django integration

```python
# views.py
from django.http import HttpResponse
from newadv_cibil_pdf_engine import generate_pdf_bytes

def cibil_report_view(request, report_id):
    report_json = fetch_report_json(report_id)  # your own lookup
    pdf_bytes = generate_pdf_bytes(report_json)
    return HttpResponse(pdf_bytes, content_type="application/pdf")
```

No Django settings, models, or apps required - the engine has zero
Django imports.

## 7. FastAPI integration

```python
from fastapi import FastAPI
from fastapi.responses import Response
from newadv_cibil_pdf_engine import generate_pdf_bytes

app = FastAPI()

@app.post("/reports/{report_id}/pdf")
def get_report_pdf(report_id: str):
    report_json = fetch_report_json(report_id)
    pdf_bytes = generate_pdf_bytes(report_json)
    return Response(content=pdf_bytes, media_type="application/pdf")
```

## 8. Celery integration

```python
from celery import shared_task
from newadv_cibil_pdf_engine import generate_pdf

@shared_task
def render_cibil_report_task(report_json: dict, output_path: str):
    generate_pdf(report_json=report_json, output_path=output_path)
    return output_path
```

The engine does no logging of report content and writes no temp files of
its own (see §11 Security), so it's safe to call from a worker process
with no extra cleanup.

## 9. Docker

```bash
docker build -t newadv-cibil-pdf-engine .
docker run --rm \
  -v "$PWD/input:/data/in" -v "$PWD/output:/data/out" \
  newadv-cibil-pdf-engine --input /data/in/sample.json --output /data/out/sample.pdf
```

## 10. CLI

```bash
python -m newadv_cibil_pdf_engine --input input/sample.json --output output/sample.pdf
python -m newadv_cibil_pdf_engine --input input/sample.json --output output/sample.pdf --mask-account-numbers
# after `pip install .`:
newadv-cibil-pdf-engine --input input/sample.json --output output/sample.pdf
```

All assets (templates, CSS, the CIBIL logo `static/logo/cibil-logo.svg`,
fonts) are resolved relative to the installed package, so the command
works from any working directory and needs no network access.

## 11. Configuration / options

All of `generate_pdf`, `generate_pdf_bytes`, `generate_pdf_from_api_response`
and `render_report_html` accept `options=` as either a plain `dict` or a
`GenerateOptions` instance:

| Option | Default | Effect |
|---|---|---|
| `mask_account_numbers` | `False` | Masks all but the last 4 characters of every account number (`0000004501140→XXXXXXXXXXXXX0956`), applied during parsing so a masked report never carries the unmasked number anywhere. |
| `include_footer` | `True` | Include the running footer (source label + page X/Y). |
| `include_disclaimer` | `True` | Include the closing "End of report" + legal disclaimer block. |
| `score_range` | `(300, 900)` | The CIBIL score scale's min/max, used for the gauge and its labels. |
| `payment_history_sentinel_map` | see `data/codes.py` | Override the raw shape's numeric-sentinel-to-status-code mapping (medium confidence by default - see §1). |

An unknown key raises `TypeError` immediately (fails loud, not silently
ignored).

### Account number masking

```python
generate_pdf(report_json=data, output_path="report.pdf",
             options={"mask_account_numbers": True})
```

Masking preserves the account number's length and keeps the last 4
characters visible (matches common PCI-style masking conventions), e.g.
`00000045011400956` → `XXXXXXXXXXXXX0956`.

## 12. Error handling

```python
from newadv_cibil_pdf_engine import generate_pdf
from newadv_cibil_pdf_engine.exceptions import (
    CibilPdfEngineError,      # base class - catch this for "anything went wrong"
    InvalidReportJSON,        # input isn't JSON at all
    UnsupportedReportFormat,  # valid JSON, but no CIBIL report shape found in it
    MissingRequiredField,     # a report shape was found, but its consumer/
                               # borrower record is missing - an empty shell
    PDFGenerationError,       # HTML built fine, WeasyPrint failed
)

try:
    generate_pdf(report_json=data, output_path="report.pdf")
except CibilPdfEngineError as exc:
    log.error("report generation failed: %s", exc)
```

Missing *optional* fields never raise - they render as `"-"` or an empty
section with a muted "No ... are available" message (see
`docs/FIELD_MAPPING.md`'s Required/Optional column for the full,
field-by-field list). Exactly two things do raise:
`UnsupportedReportFormat` when no recognisable report shape exists
anywhere in the input at all, and `MissingRequiredField` when a shape
*was* recognised (`TrueLinkCreditReport` or a raw `subject` object) but
it's an empty shell with no `Borrower`/`name` record to render.

## 13. Customization / adding a new report section

1. Add fields to the relevant dataclass in `models.py` (or a new one).
2. Populate them in `parser.py` (both `_parse_tlcr_*` and
   `_parse_raw_subject` if the field exists in both shapes).
3. Add/extend a renderer in `renderers/` that turns the model into a
   template context dict.
4. Add a template under `templates/`, wire its context key in
   `renderers/__init__.py::build_context`, and `{% include %}` it from
   `templates/report.html`.
5. Style it in `static/css/report.css`, reusing the existing
   `.detail-grid`/`.field-table`/`.subsection-heading` components where
   possible for visual consistency.

`renderers/summary.py` ships as a worked example of a section that's
*computed* (open/closed account counts, balance totals) rather than
lifted directly from JSON, and is deliberately not wired into any
template yet (the reference PDF has no summary page) - a good starting
point if you want to add one for a different report layout.

## 14. Testing

```bash
pip install -e ".[test]"
pytest tests/ -v
```

Fixtures: `input/sample.json` (current B2C-REPORT format, `tests/test_b2c.py`),
`tests/fixtures/tlcr_sample.json` and `tests/fixtures/tlcr_identity_sample.json`
(legacy TrueLink transcripts used by the parser/report/identification tests).

Covers: B2C parsing, multiple accounts, payment history/DPD codes, logo
and font embedding, output geometry, CWD-independent CLI runs, the
package-name migration, a valid full report, missing optional fields, empty/one/many
(60) accounts, multiple enquiries, long name/address, missing score, null
fields, both JSON shapes (normalised and raw), account masking, PDF
generation to file and to bytes, envelope unwrapping, and error paths.

`tests/compare_reference.py` is a separate, manual fidelity-check
workflow (not part of the pytest suite, since the reference PDF and
`input/sample.json` describe different consumers and can never match
byte-for-byte): it regenerates `tests/output/generated.pdf` and diffs its
section headings and page geometry against `tests/reference/sample.pdf`.
Run it after any template/CSS change:

```bash
python tests/compare_reference.py
```

## 15. Security

* Never logs the input JSON, PAN, full account numbers, or full phone
  numbers - `utils.py`'s formatting/masking helpers are the only place
  that ever look at those values, and nothing in the engine calls
  `logging`/`print` on report content.
* No calls to any external/AI service - purely local template rendering.
* No automatic persistence of input JSON.
* No temp files: `generate_pdf_bytes` renders entirely in memory;
  `generate_pdf` writes only the one PDF file you asked for, at the path
  you gave it.
* Exceptions never embed full report content (see `exceptions.py`) -
  messages describe *what* was missing/malformed structurally, not the
  values themselves.

## 16. Performance

* Jinja2 environment and template compilation, and the CSS file read, are
  both cached (`functools.lru_cache`) - safe and fast for repeated calls
  in a long-lived process (Django/FastAPI worker, Celery worker).
* `generate_pdf_bytes` does no disk I/O at all.
* Parsing is a single bounded-depth walk over the input JSON (capped at
  200,000 visited nodes) - safe against pathological/huge documents.

**Measured** (this machine, single process, WeasyPrint 69.0):

| Input | Pages | Time | Peak Python heap |
|---|---|---|---|
| `input/sample.json` (10 accounts, 35 enquiries) | 25 | ~4-5s | - |
| Synthetic: 100 accounts (36-month payment history each) + 50 enquiries | 206 | ~139s | ~410 MiB |

**Known bottleneck, not (yet) optimized**: generation time scales
super-linearly with page count, not linearly - the 206-page synthetic
report took ~30x longer than the 25-page real sample for ~8x the pages.
This is WeasyPrint's layout engine, not this package's Python code (the
parser/renderer stage is a small fraction of total time at any size); the
prime suspects are the rounded-corner `overflow: hidden` cards and
`break-inside: avoid` blocks used throughout `report.css`; both are
well-documented WeasyPrint performance costs at scale. A 100-account
report is far larger than the reference PDF or any realistic single CIBIL
CIR (`input/sample.json`'s own 10 accounts is typical), so this was **not**
optimized further per this audit's "don't optimize prematurely" guidance -
but if you expect routinely large reports, generate them from a background
worker with a generous timeout rather than inline in a request handler,
and profile before changing `report.css`'s use of rounded corners/`avoid`.

## 17. Known limitations (see §1 for the full, field-level breakdown)

* Address Category ("Residence Address" vs "Permanent Address" vs other)
  and Dwelling/Residence-Code labels are best-effort, not verified against
  bureau documentation.
* `Employment Details → Occupation` and `→ Income` cannot be populated -
  no such field exists in either JSON shape this engine has seen.
* Identifier Issue/Expiry Date always render as `-` - no such field exists
  in either JSON shape this engine has seen.
* The reference PDF has no distinct "Summary" page; `renderers/summary.py`
  exists as a computed-aggregate building block but isn't rendered into
  the current template set.
* The reference PDF's typefaces (Roboto 400/500/700, Montserrat 600/700,
  Poppins 700) are bundled in `newadv_cibil_pdf_engine/static/fonts/`
  under the SIL Open Font License (licence texts alongside) and loaded via
  `@font-face`, so output matches the reference typography on any host.
* B2C-REPORT carries no address category, residence code, phone type or
  ID issue/expiry dates - those cells render `-`. Interest rate is shown
  as reported (`0.0` renders `0%`, not `-`).
* The score section keeps the reference's CIBIL wording ("Your CIBIL
  Score is ..."), whatever the feed's `SCORE[0].NAME`.
* The bureau feed's `ACCOUNTS-SUMMARY` block is not rendered - the
  reference layout has no summary section.
* Generation time scales super-linearly with report size for very large
  reports (100+ accounts) - see the measured numbers in §16.


<!-- python -m newadv_cibil_pdf_engine --input input/sample.json --output output/sample.pdf -->