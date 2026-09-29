"""Reference-fidelity comparison workflow.

Not a pytest test (the reference PDF was rendered from a *different*
consumer's data than ``input/sample.json`` - see the README - so their
text/page counts will never match exactly, and asserting otherwise would
be a meaningless test). Run this by hand after touching templates/CSS to
sanity-check that the generated report still carries every structural
element, and roughly the same typography, the reference PDF has:

    python tests/compare_reference.py

It regenerates ``tests/output/generated.pdf`` from ``input/sample.json``,
diffs its section headings/page geometry/typography against
``tests/reference/sample.pdf``, and writes comparison artifacts (page
renders, a pixel diff of page 1, a text report) under
``tests/output/comparison/`` for manual visual review. Exits non-zero if
a structural regression is detected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

REFERENCE_PDF = Path(__file__).parent / "reference" / "sample.pdf"
OUTPUT_PDF = Path(__file__).parent / "output" / "generated.pdf"
SAMPLE_JSON = ROOT / "input" / "sample.json"
COMPARISON_DIR = Path(__file__).parent / "output" / "comparison"

# Section headings the reference PDF is known to contain (see
# analysis/pdf_text.txt from the original reverse-engineering pass).
# Any of these missing from the generated PDF is a real fidelity bug;
# missing customer-data text (names, amounts, ...) is expected and fine.
EXPECTED_HEADINGS = [
    "CIBIL Score & Report",
    "PERSONAL DETAILS",
    "IDENTIFICATION DETAILS",
    "ADDRESS DETAILS",
    "CONTACT DETAILS",
    "EMAIL DETAILS",
    "EMPLOYMENT DETAILS",
    "ALL ACCOUNTS",
    "OPEN ACCOUNTS",
    "CLOSED ACCOUNTS",
    "ACCOUNT DETAILS",
    "PAYMENT STATUS",
    "Payment History",
    "STD: Standard",
    "SUB: Substandard",
    "DBT: Doubtful",
    "LSS: Loss",
    "SMA: Special Mention Account",
    "XXX: Not Reported",
    "Number of days past due",
    "ENQUIRY DETAILS",
    "End of report",
    "Disclaimer",
]

# Field-level *labels* (as opposed to section headings) the reference PDF
# uses - checked separately so a missing label is easy to distinguish from
# a missing whole section in the report.
EXPECTED_FIELD_LABELS = [
    "Name", "Date Of Birth", "Gender",
    "Identification Type", "ID Number", "Issue Date", "Expiry Date",
    "Address", "Category", "Residence Code", "Date Reported",
    "Telephone Number Type", "Telephone Number", "Telephone Extension",
    # "Email ID" deliberately excluded: input/sample.json's consumer has no
    # email data at all (subject.email == [], no BorrowerEmail in TLCR
    # either), so the Email Details section correctly renders its empty
    # state instead of an "Email ID" row - not a fidelity regression.
    "Account Type", "Occupation", "Income",
    "Member Name", "Account Number", "Ownership",
    "Credit Limit", "Sanctioned Amount", "Current Balance", "Cash Limit",
    "Amount Overdue", "Rate of Interest", "Repayment Tenure", "EMI Amount",
    "Payment Frequency", "Actual Payment Amount", "Date Opened / Disbursed",
    "Date Closed", "Date of Last Payment", "Date Reported And Certified",
    "Value of Collateral", "Credit Facility Status",
    "Written-off Amount (Total)", "Written-off Amount (Principal)",
    "Settlement Amount", "Payment Start Date", "Payment End Date",
    "Date Of Enquiry", "Enquiry Purpose", "Enquiry Amount",
]


def _font_sizes_by_text(doc, wanted: dict[str, str]) -> dict[str, float | None]:
    """Return {label: font_size_pt} for the first occurrence of each
    wanted[label] text string found via PyMuPDF's structured text dict.
    """
    found: dict[str, float | None] = {k: None for k in wanted}
    remaining = dict(wanted)
    for page in doc:
        if not remaining:
            break
        d = page.get_text("dict")
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    for label, needle in list(remaining.items()):
                        if text == needle:
                            found[label] = round(span.get("size", 0), 1)
                            del remaining[label]
    return found


def main() -> int:
    import fitz  # PyMuPDF

    from newadv_cibil_pdf_engine import generate_pdf

    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)

    with open(SAMPLE_JSON, encoding="utf-8") as f:
        data = json.load(f)
    generate_pdf(report_json=data, output_path=OUTPUT_PDF)

    ref = fitz.open(REFERENCE_PDF)
    gen = fitz.open(OUTPUT_PDF)

    report_lines: list[str] = []

    def out(line: str = "") -> None:
        print(line)
        report_lines.append(line)

    out(f"Reference: {len(ref)} pages, page size {ref[0].rect}")
    out(f"Generated: {len(gen)} pages, page size {gen[0].rect}")
    out(
        "(Page counts will differ - the reference and sample.json describe "
        "different consumers with different amounts of data. Page *size* "
        "should match: both A4.)"
    )
    out()

    gen_text = "\n".join(p.get_text() for p in gen)
    ref_text = "\n".join(p.get_text() for p in ref)

    # OPEN/CLOSED ACCOUNTS only render when the report has such accounts.
    from newadv_cibil_pdf_engine import parse_report

    parsed = parse_report(data)
    not_applicable = set()
    if not parsed.open_accounts:
        not_applicable.add("OPEN ACCOUNTS")
    if not parsed.closed_accounts:
        not_applicable.add("CLOSED ACCOUNTS")
    missing_headings = [h for h in EXPECTED_HEADINGS if h not in gen_text and h not in not_applicable]
    missing_labels = [lbl for lbl in EXPECTED_FIELD_LABELS if lbl not in gen_text]
    # Sanity: also confirm these labels are actually in the reference,
    # otherwise the "expected" list itself would be wrong.
    labels_not_even_in_reference = [lbl for lbl in EXPECTED_FIELD_LABELS if lbl not in ref_text]

    if missing_headings:
        out("MISSING section headings (fidelity regression):")
        for h in missing_headings:
            out(f"  - {h!r}")
    else:
        out("All expected section headings are present in the generated PDF.")

    if missing_labels:
        out("MISSING field labels (fidelity regression):")
        for lbl in missing_labels:
            out(f"  - {lbl!r}")
    else:
        out("All expected field labels are present in the generated PDF.")

    if labels_not_even_in_reference:
        out(f"NOTE: these expected labels aren't in the reference PDF either (test list bug?): {labels_not_even_in_reference}")

    out()
    ref_size = (round(ref[0].rect.width), round(ref[0].rect.height))
    gen_size = (round(gen[0].rect.width), round(gen[0].rect.height))
    size_mismatch = ref_size != gen_size
    out(f"Page size: reference={ref_size} generated={gen_size} {'MISMATCH' if size_mismatch else 'OK (A4 match)'}")

    # Typography spot-check: compare font sizes of a few shared labels.
    shared_labels = {"Name": "Name", "Member Name": "Member Name", "Category": "Category"}
    ref_sizes = _font_sizes_by_text(ref, shared_labels)
    gen_sizes = _font_sizes_by_text(gen, shared_labels)
    out()
    out("Font-size spot-check (label -> reference pt / generated pt):")
    for label in shared_labels:
        out(f"  {label}: {ref_sizes[label]} / {gen_sizes[label]}")

    # Render page 1 of each to PNG + a pixel diff (both are the
    # score-and-personal-details page, so this comparison is meaningful
    # despite the different underlying consumers).
    try:
        from PIL import Image, ImageChops

        mat = fitz.Matrix(1.5, 1.5)
        ref_png = COMPARISON_DIR / "reference_page1.png"
        gen_png = COMPARISON_DIR / "generated_page1.png"
        ref[0].get_pixmap(matrix=mat).save(str(ref_png))
        gen[0].get_pixmap(matrix=mat).save(str(gen_png))

        im_ref = Image.open(ref_png).convert("RGB")
        im_gen = Image.open(gen_png).convert("RGB")
        if im_ref.size != im_gen.size:
            im_gen_r = im_gen.resize(im_ref.size)
        else:
            im_gen_r = im_gen
        diff = ImageChops.difference(im_ref, im_gen_r)
        diff_path = COMPARISON_DIR / "page1_diff.png"
        diff.save(diff_path)

        bbox = diff.getbbox()
        histogram = diff.convert("L").histogram()
        nonzero_pixels = sum(histogram[1:])
        total_pixels = im_ref.size[0] * im_ref.size[1]
        out()
        out(f"Page 1 pixel diff saved to {diff_path}")
        out(f"  differing pixels: {nonzero_pixels}/{total_pixels} ({100*nonzero_pixels/total_pixels:.1f}%)")
        out(f"  diff bounding box: {bbox}")
        out(
            "  (a nonzero percentage is expected - different consumer name/"
            "score/dates/addresses - this is a coarse layout-drift signal, "
            "not a pass/fail check)"
        )
    except ImportError:
        out("Pillow not installed - skipping pixel-diff image generation.")

    (COMPARISON_DIR / "comparison_report.txt").write_text("\n".join(report_lines), encoding="utf-8")

    return 1 if (missing_headings or missing_labels or size_mismatch) else 0


if __name__ == "__main__":
    raise SystemExit(main())
