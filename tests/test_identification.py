"""Tests for identification-details extraction, normalization, validation,
and the PDF-generation skip rule.

Covers: newadv_cibil_pdf_engine.parser.build_identification /
has_identification_details, and the corresponding gate in
newadv_cibil_pdf_engine.engine.generate_pdf_bytes / generate_pdf.
"""

from __future__ import annotations

import copy
import json

import pytest

from newadv_cibil_pdf_engine import (
    generate_pdf,
    generate_pdf_bytes,
    has_identification_details,
    parse_report,
    render_report_html,
)
from newadv_cibil_pdf_engine.exceptions import IdentificationDataUnavailable
from newadv_cibil_pdf_engine.parser import build_identification, parse

from .conftest import FIXTURES_DIR, tlcr_of

FALLBACK_TEXT = "No identification details are available."


# These tests were written against a different TLCR transcript than
# test_parser/test_report (a consumer whose PAN is only available via
# report_summary / identity_sent, and whose Borrower collapses single-entry
# lists to bare objects), so they use that transcript as their fixture.
@pytest.fixture(scope="module")
def sample_json() -> dict:
    with open(FIXTURES_DIR / "tlcr_identity_sample.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def sample_json_copy(sample_json) -> dict:
    return copy.deepcopy(sample_json)


def _blank_everything_identification_could_come_from(data: dict) -> None:
    """Strip every source build_identification()/PAN-augmentation reads
    from, leaving a report that genuinely has no identifying information.
    """
    data["data"]["report_summary"]["pan"] = None
    data["data"]["report_summary"]["name"] = None
    data["data"]["report_summary"]["gender"] = None
    data["data"]["report_summary"]["date_of_birth"] = None
    data["data"]["identity_sent"]["pan_id"] = None
    data["data"]["identity_sent"]["forename"] = None
    data["data"]["identity_sent"]["surname"] = None
    data["data"]["identity_sent"]["gender"] = None
    data["data"]["identity_sent"]["date_of_birth"] = None
    data["data"]["identity_sent"]["phone_number"] = None

    tlcr = tlcr_of(data)
    borrower = tlcr["Borrower"]
    borrower["BorrowerName"] = {}
    borrower["Gender"] = None
    borrower["Birth"] = {}
    borrower["BorrowerTelephone"] = []
    borrower["BorrowerAddress"] = []
    borrower["EmailAddress"] = []
    borrower["IdentifierPartition"]["Identifier"] = []


# --------------------------------------------------------------------------
# 1. Identification data exists -> normalized correctly, PDF generated,
#    fallback text is not shown.
# --------------------------------------------------------------------------

def test_identification_is_normalized_from_report_summary_and_identity_sent(sample_json):
    report = parse(sample_json)
    ident = report.identification

    assert ident["name"] == "BASHEER K S/O ABDUL KAREEM"
    assert ident["gender"] == "Male"
    assert ident["date_of_birth"] == "01/01/1984"
    assert ident["pan"] == "GUGPK1335G"
    assert ident["phone"] == "7907335300"
    assert ident["email"] == "FAISNAJU@GMAIL.COM"
    assert ident["address"]
    assert has_identification_details(ident)


def test_pdf_is_generated_and_shows_identification_not_fallback(sample_json):
    html = render_report_html(sample_json)
    assert FALLBACK_TEXT not in html

    idx = html.find("Identification Details")
    section = html[idx : idx + 800]
    assert "Income Tax ID Number (PAN)" in section
    assert "GUGPK1335G" in section

    pdf_bytes = generate_pdf_bytes(sample_json)
    assert pdf_bytes.startswith(b"%PDF")


# --------------------------------------------------------------------------
# 2. Identification data completely missing -> PDF generation is skipped,
#    no PDF file is written.
# --------------------------------------------------------------------------

def test_completely_missing_identification_skips_pdf_generation(sample_json_copy, tmp_path):
    _blank_everything_identification_could_come_from(sample_json_copy)

    report = parse_report(sample_json_copy)
    assert not has_identification_details(report.identification)

    out = tmp_path / "should_not_exist.pdf"
    with pytest.raises(IdentificationDataUnavailable):
        generate_pdf(sample_json_copy, out)
    assert not out.exists()

    with pytest.raises(IdentificationDataUnavailable):
        generate_pdf_bytes(sample_json_copy)


# --------------------------------------------------------------------------
# 3. Identification object contains only empty/null values -> skipped.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "identification",
    [
        {},
        {"name": None, "gender": None, "date_of_birth": None, "pan": None, "phone": None, "email": None, "address": None},
        {"name": "", "gender": "   ", "date_of_birth": "", "pan": None, "phone": "", "email": "", "address": ""},
        {"name": {}, "address": []},
    ],
)
def test_empty_or_blank_identification_fields_are_not_meaningful(identification):
    assert has_identification_details(identification) is False


def test_has_identification_details_rejects_non_mapping_input():
    assert has_identification_details(None) is False
    assert has_identification_details("not a dict") is False


# --------------------------------------------------------------------------
# 4. PAN missing but other fields available -> PDF IS generated.
# --------------------------------------------------------------------------

def test_missing_pan_alone_does_not_block_pdf_generation(sample_json_copy):
    sample_json_copy["data"]["report_summary"]["pan"] = None
    sample_json_copy["data"]["identity_sent"]["pan_id"] = None

    report = parse_report(sample_json_copy)
    assert report.identification["pan"] is None
    assert has_identification_details(report.identification) is True

    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")


def test_field_priority_report_summary_beats_identity_sent_beats_borrower(sample_json_copy):
    """report_summary.name should win even when identity_sent and Borrower
    carry a different value (per the documented field priority order)."""
    sample_json_copy["data"]["report_summary"]["name"] = "REPORT SUMMARY NAME"
    sample_json_copy["data"]["identity_sent"]["forename"] = "IDENTITY"
    sample_json_copy["data"]["identity_sent"]["surname"] = "SENT"
    tlcr = tlcr_of(sample_json_copy)
    tlcr["Borrower"]["BorrowerName"]["Name"]["Forename"] = "BORROWER NAME"

    report = parse(sample_json_copy)
    assert report.identification["name"] == "REPORT SUMMARY NAME"

    ident_without_summary = build_identification(report, None, {"forename": "IDENTITY", "surname": "SENT"})
    assert ident_without_summary["name"] == "IDENTITY SENT"


# --------------------------------------------------------------------------
# 5. Identification available only inside the nested Borrower object
#    (report_summary/identity_sent both absent) -> PDF IS generated.
# --------------------------------------------------------------------------

def test_identification_from_nested_borrower_only(sample_json_copy):
    del sample_json_copy["data"]["report_summary"]
    del sample_json_copy["data"]["identity_sent"]

    tlcr = tlcr_of(sample_json_copy)
    borrower = tlcr["Borrower"]

    parsed = parse(sample_json_copy)
    ident = parsed.identification

    assert ident["name"] == utils_forename(borrower)
    assert ident["gender"] == borrower["Gender"]
    assert ident["phone"] == borrower["BorrowerTelephone"]["PhoneNumber"]["Number"]
    assert ident["email"] == borrower["EmailAddress"]["Email"]
    assert ident["address"]
    assert has_identification_details(ident) is True

    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")


def utils_forename(borrower: dict) -> str:
    return borrower["BorrowerName"]["Name"]["Forename"]


# --------------------------------------------------------------------------
# 6. Existing report sections remain unaffected by the identification fix.
# --------------------------------------------------------------------------

def test_other_report_sections_unaffected(sample_json):
    report = parse(sample_json)

    assert report.score is not None
    assert report.score.value == 728
    assert len(report.accounts) == 1
    assert report.enquiries == []
    assert report.accounts[0].payment_history != [] or report.accounts[0].payment_start_date != "-"
    assert report.addresses
    assert report.score.factors is not None  # credit factors list, may be empty but must exist
