"""Tests for the B2C-REPORT format (input/sample.json - the current upstream
feed): parsing, account/payment-history normalisation, null handling, and
the rendered PDF itself (content, logo, fonts, layout invariants).
"""

from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

from newadv_cibil_pdf_engine import generate_pdf, generate_pdf_bytes, parse_report, render_report_html
from newadv_cibil_pdf_engine import utils
from newadv_cibil_pdf_engine.data import codes
from newadv_cibil_pdf_engine.engine import LOGO_PATH, logo_data_uri
from newadv_cibil_pdf_engine.parser import locate_report_root
from newadv_cibil_pdf_engine.parser_b2c import build_payment_history_rows

from .conftest import b2c_of, standard_of

REPO_ROOT = Path(__file__).parent.parent


def _pdf_text(pdf_bytes: bytes) -> str:
    return " ".join("\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf_bytes)).pages).split())


@pytest.fixture(scope="module")
def b2c_pdf(b2c_json) -> bytes:
    return generate_pdf_bytes(b2c_json)


# --------------------------------------------------------------------------
# Format detection
# --------------------------------------------------------------------------

def test_b2c_report_is_detected_inside_api_envelope(b2c_json):
    kind, root = locate_report_root(b2c_json)
    assert kind == "b2c"
    assert "REPORT-DATA" in root


# --------------------------------------------------------------------------
# Header / personal information
# --------------------------------------------------------------------------

def test_header_and_consumer_fields(b2c_json):
    report = parse_report(b2c_json)
    assert report.meta.control_number == "CCR260928CR551261426"
    assert report.meta.report_date == "28/09/2026"
    # Most recently reported NAME-VARIATION wins over the request's name.
    assert report.consumer.name == "BOLLA VARAM YOGANANDA REDDY"
    assert report.consumer.date_of_birth == "29/07/2004"
    assert report.consumer.gender == "Male"


def test_identification_contact_and_employment(b2c_json):
    report = parse_report(b2c_json)
    assert [(i.id_type_label, i.id_number) for i in report.identifications] == [
        ("Income Tax ID Number (PAN)", "GBCPR0299M")
    ]
    assert report.identification["pan"] == "GBCPR0299M"
    assert [p.number for p in report.phones] == ["9392590067"]
    assert [e.address for e in report.emails] == ["yogireddy1233@gmail.com"]
    # Addresses newest first, ", ," padding runs collapsed.
    assert [a.date_reported for a in report.addresses] == ["31/08/2026", "23/08/2026", "15/02/2026", "31/01/2026"]
    assert ", ," not in report.addresses[1].lines
    assert report.employment.has_data
    assert report.employment.occupation == "SELF EMPLOYED"
    assert report.employment.date_reported == "31/08/2026"  # latest of the two records


def test_score_and_enquiry(b2c_json):
    report = parse_report(b2c_json)
    assert report.score.value == 775
    assert report.score.date == "28/09/2026"
    assert len(report.score.factors) == 3
    assert len(report.enquiries) == 1
    enq = report.enquiries[0]
    assert (enq.member_name, enq.date_of_enquiry, enq.purpose_label, enq.amount) == (
        "HDFC BANK LTD",
        "18/09/2026",
        "Credit Card",
        "₹10,000",
    )


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def test_all_tradelines_become_accounts(b2c_json):
    report = parse_report(b2c_json)
    tradelines = standard_of(b2c_json)["TRADELINES"]
    assert len(report.accounts) == len(tradelines) == 5
    assert {a.account_number for a in report.accounts} == {t["ACCT-NUMBER"] for t in tradelines}
    # All five are closed in the sample.
    assert report.open_accounts == []
    assert len(report.closed_accounts) == 5


def test_account_field_mapping(b2c_json):
    report = parse_report(b2c_json)
    acc = next(a for a in report.accounts if a.account_number == "KB250917UNDAV")
    assert acc.member_name == "KRAZYBEE SERVICES PRIVATE LIMITED"
    assert acc.account_type_label == "Short Term Personal Loan"
    assert acc.ownership_label == "Individual"
    assert acc.sanctioned_amount == "₹1,400"
    assert acc.current_balance == "₹0"
    assert acc.amount_overdue == "₹0"
    assert acc.emi_amount == "₹194"  # from "194/Monthly"
    assert acc.payment_frequency == "Monthly"
    assert acc.repayment_tenure == "8"
    assert acc.date_opened == "17/09/2025"
    assert acc.date_closed == "24/01/2026"
    assert acc.date_of_last_payment == "24/01/2026"
    assert acc.date_reported == "31/01/2026"
    assert acc.written_off_total == "₹0"
    assert acc.written_off_principal == "₹0"
    # Not reported in the feed -> reference placeholder.
    assert acc.credit_limit == "-"
    assert acc.cash_limit == "-"
    assert acc.settlement_amount == "-"
    assert ("Account Status", "Closed") in acc.extra_detail_rows


def test_account_extra_rows_only_when_reported(b2c_json):
    report = parse_report(b2c_json)
    by_number = {a.account_number: a for a in report.accounts}
    oxyzo = dict(by_number["OXYTL01S0KKY"].extra_detail_rows)
    assert oxyzo["Security Type"] == "No Collateral"
    assert oxyzo["Last Paid Amount"] == "₹1,893"
    assert by_number["OXYTL01S0KKY"].actual_payment_amount == "₹1,893"
    assert dict(by_number["90039981319878"].extra_detail_rows)["Suit Filed / Wilful Default"] == "No Suit filed"
    assert "Security Type" not in dict(by_number["KB250917UNDAV"].extra_detail_rows)
    # PAYU has no OVERDUE-AMT key at all.
    assert by_number["LPPLUS31212168"].amount_overdue == "-"
    assert by_number["LPPLUS31212168"].rate_of_interest == "36%"


def test_accounts_sorted_newest_opened_first(b2c_json):
    report = parse_report(b2c_json)
    opened = [utils.parse_bureau_date(a.date_opened.replace("/", "-")) for a in report.accounts]
    assert opened == sorted(opened, reverse=True)


def test_open_account_detection(b2c_json_copy):
    t = standard_of(b2c_json_copy)["TRADELINES"][0]
    t["CLOSED-DT"] = ""
    t["ACCOUNT-STATUS"] = "Active"
    report = parse_report(b2c_json_copy)
    assert [a.account_number for a in report.open_accounts] == [t["ACCT-NUMBER"]]


def test_account_number_masking(b2c_json):
    report = parse_report(b2c_json, {"mask_account_numbers": True})
    acc = next(a for a in report.accounts if a.account_number.endswith("NDAV"))
    assert acc.account_number == "XXXXXXXXXNDAV"


# --------------------------------------------------------------------------
# Payment history / DPD
# --------------------------------------------------------------------------

def test_payment_history_grid_positions(b2c_json):
    report = parse_report(b2c_json)
    acc = next(a for a in report.accounts if a.account_number == "KB250917UNDAV")
    # Jan:2026 .. Sep:2025, all "000/STD".
    assert [r.year for r in acc.payment_history] == [2026, 2025]
    row_2026, row_2025 = acc.payment_history
    # Columns are Dec..Jan.
    assert row_2026.cells == [None] * 11 + ["0"]
    assert row_2025.cells == ["0", "0", "0", "0"] + [None] * 8
    assert acc.payment_start_date == "01/01/2026"
    assert acc.payment_end_date == "01/09/2025"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("000/STD", "0"),
        ("030/STD", "30"),
        ("000/XXX", "0"),
        ("090/SUB", "90/SUB"),
        ("000/DBT", "0/DBT"),
        ("000/LSS", "0/LSS"),
        ("000/SMA", "0/SMA"),
        ("XXX/XXX", "XXX"),
        ("XXX/SUB", "SUB"),
        ("XXX/", "XXX"),
        ("STD", "STD"),
        ("000", "0"),
        ("DDD/ZZZ", "ZZZ"),  # unknown codes pass through, not reinterpreted
        ("", None),
        (None, None),
    ],
)
def test_payment_status_normalisation(raw, expected):
    assert utils.format_payment_status(raw, codes.ADVERSE_ASSET_CLASSIFICATION) == expected


def test_long_payment_history_spans_years_in_order():
    months = []
    year, month = 2026, 8
    for _ in range(40):
        months.append(((year, month), "0"))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    rows = build_payment_history_rows(months)
    assert [r.year for r in rows] == [2026, 2025, 2024, 2023]
    assert rows[0].cells[:4] == [None, None, None, None]  # Dec..Sep 2026 not yet reported
    assert all(c == "0" for c in rows[1].cells)


def test_payment_history_blank_and_misaligned_values(b2c_json_copy):
    t = standard_of(b2c_json_copy)["TRADELINES"][0]
    hist = next(h for h in t["HISTORY"] if h["NAME"] == "COMBINED-PAYMENT-HISTORY")
    hist["DATES"] = "Aug:2026|bogus|Jun:2026|"
    hist["VALUES"] = "|000/STD|"  # shorter than DATES
    report = parse_report(b2c_json_copy)
    acc = next(a for a in report.accounts if a.account_number == t["ACCT-NUMBER"])
    row = acc.payment_history[0]
    assert row.year == 2026
    # Aug blank, "bogus" skipped (its value not shifted onto Jul), Jun has no value.
    assert row.cells[4] is None and row.cells[5] is None and row.cells[6] is None


def test_missing_payment_history_is_safe(b2c_json_copy):
    for t in standard_of(b2c_json_copy)["TRADELINES"]:
        t["HISTORY"] = None
    report = parse_report(b2c_json_copy)
    assert all(a.payment_history == [] for a in report.accounts)
    assert all(a.payment_start_date == "-" for a in report.accounts)
    html = render_report_html(b2c_json_copy)
    assert '<table class="payment-grid">' not in html


# --------------------------------------------------------------------------
# Null / missing data robustness
# --------------------------------------------------------------------------

def test_nulls_everywhere_do_not_crash(b2c_json_copy):
    std = standard_of(b2c_json_copy)
    for t in std["TRADELINES"]:
        for key in list(t):
            if key != "ACCT-NUMBER":
                t[key] = None
    std["INQUIRY-HISTORY"] = None
    std["EMPLOYMENT-DETAILS"] = None
    std["SCORE"] = None
    report = parse_report(b2c_json_copy)
    assert len(report.accounts) == 5
    acc = report.accounts[0]
    assert acc.member_name == "-" and acc.sanctioned_amount == "-" and acc.date_opened == "-"
    assert report.enquiries == []
    assert report.score is None
    assert not report.employment.has_data
    assert generate_pdf_bytes(b2c_json_copy).startswith(b"%PDF")


def test_no_accounts_no_enquiries(b2c_json_copy):
    std = standard_of(b2c_json_copy)
    std["TRADELINES"] = []
    std["INQUIRY-HISTORY"] = []
    html = render_report_html(b2c_json_copy)
    assert "No credit accounts are reported" in html
    assert "No enquiries are reported" in html


def test_unexpected_formats_degrade_to_placeholder(b2c_json_copy):
    t = standard_of(b2c_json_copy)["TRADELINES"][0]
    t["DISBURSED-DT"] = "2026/13/45"
    t["DISBURSED-AMT"] = "N/A"
    t["INSTALLMENT-AMT"] = "abc/"
    t["ACCT-TYPE"] = "Some Brand New Loan Type"
    report = parse_report(b2c_json_copy)
    acc = next(a for a in report.accounts if a.account_number == t["ACCT-NUMBER"])
    assert acc.date_opened == "-"
    assert acc.sanctioned_amount == "-"
    assert acc.emi_amount == "-"
    assert acc.account_type_label == "Some Brand New Loan Type"


def test_demographics_fall_back_to_request_data(b2c_json_copy):
    b2c_of(b2c_json_copy)["REPORT-DATA"]["STANDARD-DATA"]["DEMOGS"] = None
    report = parse_report(b2c_json_copy)
    assert report.consumer.name == "VARAM YOGANANDA REDDY BOLLA"
    assert [p.number for p in report.phones] == ["9392590067"]
    assert report.identifications == []


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [("28-09-2026", "28/09/2026"), ("2026-09-28+05:30", "28/09/2026"), ("20260928", "28/09/2026"),
     ("31-02-2026", "-"), ("", "-"), (None, "-"), ("garbage", "-")],
)
def test_format_date(value, expected):
    assert utils.format_date(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("1,400", "₹1,400"), ("4000000", "₹40,00,000"), ("0.0", "₹0"), ("₹16,000", "₹16,000"),
     ("", "-"), (None, "-"), ("-1", "-"), ("abc", "-")],
)
def test_format_currency(value, expected):
    assert utils.format_currency(value) == expected


def test_parse_month_year():
    assert utils.parse_month_year("Jan:2026") == (2026, 1)
    assert utils.parse_month_year("dec:2025") == (2025, 12)
    assert utils.parse_month_year("Foo:2025") is None
    assert utils.parse_month_year(None) is None


def test_split_pipe_keeps_interior_blanks():
    assert utils.split_pipe("a||c|") == ["a", "", "c"]
    assert utils.split_pipe("") == []
    assert utils.split_pipe(None) == []


# --------------------------------------------------------------------------
# Rendered output
# --------------------------------------------------------------------------

def test_logo_is_the_repository_svg():
    assert LOGO_PATH.is_file()
    assert LOGO_PATH.name == "cibil-logo.svg"
    uri = logo_data_uri()
    assert uri.startswith("data:image/svg+xml;base64,")
    import base64

    assert base64.b64decode(uri.split(",", 1)[1]) == LOGO_PATH.read_bytes()


def test_html_embeds_logo_and_no_external_urls(b2c_json):
    html = render_report_html(b2c_json)
    assert logo_data_uri() in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html


def test_pdf_contains_new_json_data(b2c_pdf):
    text = _pdf_text(b2c_pdf)
    for expected in [
        "CIBIL Score & Report",
        "CCR260928CR551261426",
        "BOLLA VARAM YOGANANDA REDDY",
        "GBCPR0299M",
        "yogireddy1233@gmail.com",
        "KRAZYBEE SERVICES PRIVATE LIMITED",
        "OXYTL01S0KKY",
        "90039981319878",
        "₹16,000",
        "HDFC BANK LTD",
        "CLOSED ACCOUNTS",
        "Payment History",
        "End of report",
    ]:
        assert expected in text, expected
    # Values from the design reference must not leak into the output.
    for reference_only in ["ANAND VARDHAN GOYAL", "11564110328", "ICICI BANK", "CAZPG3241C"]:
        assert reference_only not in text


def test_pdf_page_geometry_and_fonts(b2c_pdf):
    reader = PdfReader(BytesIO(b2c_pdf))
    box = reader.pages[0].mediabox
    assert round(float(box.width), 1) == 595.3 and round(float(box.height), 1) == 841.9  # A4
    fonts = set()
    for page in reader.pages:
        for font in (page["/Resources"].get("/Font") or {}).values():
            fonts.add(str(font.get_object()["/BaseFont"]).split("+")[-1])
    for family in ("Roboto", "Montserrat", "Poppins"):
        assert any(f.startswith(family) for f in fonts), fonts


def test_pdf_has_page_numbers_on_every_page(b2c_pdf):
    reader = PdfReader(BytesIO(b2c_pdf))
    n = len(reader.pages)
    for i, page in enumerate(reader.pages, start=1):
        assert f"{i}/{n}" in page.extract_text()


def test_nothing_drawn_outside_the_page_content_box(b2c_pdf):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open(stream=b2c_pdf, filetype="pdf")
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    x0, _, x1, _ = span["bbox"]
                    assert x0 >= 42 and x1 <= 553.5, (page.number, span["text"])


def test_generate_from_other_working_directory(tmp_path):
    out = tmp_path / "out.pdf"
    result = subprocess.run(
        [sys.executable, "-m", "newadv_cibil_pdf_engine", "-i", str(REPO_ROOT / "input" / "sample.json"), "-o", str(out)],
        cwd=tmp_path,
        env={**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.read_bytes().startswith(b"%PDF")


def test_generate_pdf_writes_file(b2c_json, tmp_path):
    out = generate_pdf(b2c_json, tmp_path / "nested" / "report.pdf")
    assert out.exists() and out.stat().st_size > 10_000


# --------------------------------------------------------------------------
# Project-name migration
# --------------------------------------------------------------------------

def test_no_stale_old_package_references():
    old = "adv" + "_cibil_pdf_engine"  # split so this file doesn't match itself
    offenders = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or any(p in path.parts for p in (".git", "analysis", "__pycache__", ".pytest_cache")):
            continue
        if path.suffix.lower() not in {".py", ".toml", ".md", ".txt", ".cfg", ".html", ".css", ""} and path.name != "Dockerfile":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in (old, old.replace("_", "-")):
            idx = text.find(token)
            while idx != -1:
                if not text[max(0, idx - 3):idx].endswith("new"):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
                    break
                idx = text.find(token, idx + 1)
    assert offenders == []


def test_package_metadata_uses_new_name():
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "newadv-cibil-pdf-engine"' in pyproject
    assert "newadv_cibil_pdf_engine.__main__:main" in pyproject
    import newadv_cibil_pdf_engine

    assert Path(newadv_cibil_pdf_engine.__file__).parent.name == "newadv_cibil_pdf_engine"
