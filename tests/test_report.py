"""End-to-end tests: JSON -> PDF, through the public API surface."""

from __future__ import annotations

import copy

import pytest
from pypdf import PdfReader

from newadv_cibil_pdf_engine import (
    GenerateOptions,
    generate_pdf,
    generate_pdf_bytes,
    generate_pdf_from_api_response,
    render_report_html,
    validate_report_json,
)
from newadv_cibil_pdf_engine.exceptions import CibilPdfEngineError

from .conftest import tlcr_of


def _page_count(pdf_bytes: bytes) -> int:
    return len(PdfReader(__import__("io").BytesIO(pdf_bytes)).pages)


def test_generate_pdf_bytes_produces_a_pdf(sample_json):
    pdf_bytes = generate_pdf_bytes(sample_json)
    assert pdf_bytes.startswith(b"%PDF")
    assert _page_count(pdf_bytes) > 1


def test_generate_pdf_writes_a_file(sample_json, tmp_path):
    out = tmp_path / "report.pdf"
    result_path = generate_pdf(sample_json, out)
    assert result_path == out
    assert out.exists()
    assert out.stat().st_size > 1000


def test_generate_pdf_creates_missing_parent_directories(sample_json, tmp_path):
    out = tmp_path / "nested" / "dir" / "report.pdf"
    generate_pdf(sample_json, out)
    assert out.exists()


def test_generate_pdf_from_api_response_unwraps_envelope(sample_json, tmp_path):
    envelope = {"status": "success", "message": "OK", "data": sample_json}
    out = tmp_path / "from_envelope.pdf"
    result_path = generate_pdf_from_api_response(envelope, out)
    assert result_path == out
    assert out.stat().st_size > 1000


def test_generate_pdf_accepts_json_string(sample_json):
    import json

    pdf_bytes = generate_pdf_bytes(json.dumps(sample_json))
    assert pdf_bytes.startswith(b"%PDF")


def test_masking_changes_account_number_in_html(sample_json):
    html_plain = render_report_html(sample_json)
    html_masked = render_report_html(sample_json, {"mask_account_numbers": True})
    assert "00000045011400956" in html_plain
    assert "00000045011400956" not in html_masked


def test_include_footer_false_removes_page_number_markup(sample_json):
    html_with_footer = render_report_html(sample_json, {"include_footer": True})
    html_without_footer = render_report_html(sample_json, {"include_footer": False})
    assert "@bottom-right" in html_with_footer
    assert "@bottom-right" not in html_without_footer


def test_include_disclaimer_false_removes_disclaimer(sample_json):
    html = render_report_html(sample_json, {"include_disclaimer": False})
    assert "End of report" not in html


def test_zero_accounts_report_still_generates_pdf(sample_json_copy):
    tlcr_of(sample_json_copy)["TradeLinePartition"] = []
    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")


def test_one_account_report_generates_pdf(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    tlcr["TradeLinePartition"] = tlcr["TradeLinePartition"][:1]
    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")


def test_many_accounts_report_generates_pdf(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    base = tlcr["TradeLinePartition"]
    tlcr["TradeLinePartition"] = [copy.deepcopy(base[i % len(base)]) for i in range(60)]
    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")
    assert _page_count(pdf_bytes) > 10


def test_invalid_json_raises_engine_error():
    with pytest.raises(CibilPdfEngineError):
        generate_pdf_bytes({"nothing": "recognisable"})


def test_unknown_option_raises_type_error(sample_json):
    with pytest.raises(TypeError):
        generate_pdf_bytes(sample_json, {"not_a_real_option": True})


def test_generate_options_dataclass_accepted_directly(sample_json):
    options = GenerateOptions(mask_account_numbers=True)
    pdf_bytes = generate_pdf_bytes(sample_json, options)
    assert pdf_bytes.startswith(b"%PDF")


def test_validate_report_json_true_for_real_report(sample_json):
    assert validate_report_json(sample_json) is True


def test_validate_report_json_false_for_garbage():
    assert validate_report_json({"nothing": "here"}) is False


def test_repeated_generation_is_deterministic_in_structure(sample_json):
    # Two independent renders of the same input should have the same page
    # count (content is deterministic; only the generated-at timestamp in
    # the header differs).
    pdf1 = generate_pdf_bytes(sample_json)
    pdf2 = generate_pdf_bytes(sample_json)
    assert _page_count(pdf1) == _page_count(pdf2)


def test_many_enquiries_report_generates_pdf(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    base = tlcr["InquiryPartition"]
    tlcr["InquiryPartition"] = [copy.deepcopy(base[i % len(base)]) for i in range(50)]
    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")


def test_zero_enquiries_report_generates_pdf(sample_json_copy):
    tlcr_of(sample_json_copy)["InquiryPartition"] = []
    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    assert pdf_bytes.startswith(b"%PDF")


def test_report_json_works_without_api_wrapper(sample_json):
    # sample_json here IS already the full {"data": {"steps": [...]}}
    # transcript, not a {status,message,data} envelope - this proves the
    # engine also accepts report JSON that was never wrapped that way.
    pdf_bytes = generate_pdf_bytes(sample_json)
    assert pdf_bytes.startswith(b"%PDF")


def test_modified_customer_data_actually_appears_in_output(sample_json_copy):
    """Proves the engine is genuinely data-driven: change every kind of
    customer-specific field and confirm the *rendered PDF text* reflects
    every single change (and none of the original values survive).
    """
    from io import BytesIO

    tlcr = tlcr_of(sample_json_copy)
    borrower = tlcr["Borrower"]

    original_name = borrower["BorrowerName"]["Name"]["Forename"]
    original_pan = next(
        e["ID"]["Id"] for e in borrower["IdentifierPartition"]["Identifier"] if e["ID"]["IdentifierName"] == "TaxId"
    )
    original_mobile = borrower["BorrowerTelephone"][0]["PhoneNumber"]["Number"]
    original_street = borrower["BorrowerAddress"][0]["CreditAddress"]["StreetAddress"]
    original_score = borrower["CreditScore"]["riskScore"]
    original_account_number = tlcr["TradeLinePartition"][0]["Tradeline"]["accountNumber"]
    original_lender = tlcr["TradeLinePartition"][0]["Tradeline"]["creditorName"]
    original_amount = tlcr["TradeLinePartition"][0]["Tradeline"]["highBalance"]
    original_enquiry_member = tlcr["InquiryPartition"][0]["Inquiry"]["subscriberName"]

    new_name = "SURESH KUMAR PATEL"
    new_pan = "ZZZPP9999Z"
    new_mobile = "919999988888"
    new_street = "PLOT NO 77 GREEN VALLEY ENCLAVE NEW TOWN"
    new_score = 611
    new_account_number = "00000099999999999"
    new_lender = "TOTALLY DIFFERENT BANK LTD"
    new_amount = 4242424
    new_enquiry_member = "COMPLETELY NEW LENDER"
    new_open_date = "20200101"

    borrower["BorrowerName"]["Name"]["Forename"] = new_name
    for e in borrower["IdentifierPartition"]["Identifier"]:
        if e["ID"]["IdentifierName"] == "TaxId":
            e["ID"]["Id"] = new_pan
    borrower["BorrowerTelephone"][0]["PhoneNumber"]["Number"] = new_mobile
    borrower["BorrowerAddress"][0]["CreditAddress"]["StreetAddress"] = new_street
    borrower["CreditScore"]["riskScore"] = str(new_score)
    tlcr["TradeLinePartition"][0]["Tradeline"]["accountNumber"] = new_account_number
    tlcr["TradeLinePartition"][0]["Tradeline"]["creditorName"] = new_lender
    tlcr["TradeLinePartition"][0]["Tradeline"]["highBalance"] = new_amount
    tlcr["TradeLinePartition"][0]["Tradeline"]["dateOpened"] = new_open_date
    tlcr["InquiryPartition"][0]["Inquiry"]["subscriberName"] = new_enquiry_member

    pdf_bytes = generate_pdf_bytes(sample_json_copy)
    raw_text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(pdf_bytes)).pages)
    # Wrapped lines extract with a newline where the PDF only had a normal
    # space, so collapse all whitespace before substring-matching multi-
    # word values (e.g. a long lender name that wraps across two lines).
    text = " ".join(raw_text.split())

    # every modified value is present in the rendered output
    assert new_name in text
    assert new_pan in text
    assert new_mobile in text
    assert "PLOT NO 77" in text
    assert str(new_score) in text
    assert new_account_number in text
    assert new_lender in text
    assert "42,42,424" in text  # Indian-grouped
    assert "01/01/2020" in text
    assert new_enquiry_member in text

    # none of the original *replaced* values leak through. (original_lender
    # and original_enquiry_member are deliberately not checked here: both
    # are "SBI", which several *other*, untouched accounts/enquiries in
    # the sample legitimately still carry - that's correct, not a leak.)
    assert original_name not in text
    assert original_pan not in text
    assert original_mobile not in text
    assert original_street not in text
    assert original_score not in text
    assert original_account_number not in text


def test_cli_generates_pdf(sample_json, tmp_path):
    import json
    import subprocess
    import sys

    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.pdf"
    input_path.write_text(json.dumps(sample_json), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "newadv_cibil_pdf_engine", "--input", str(input_path), "--output", str(output_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert output_path.read_bytes().startswith(b"%PDF")


def test_cli_reports_error_on_bad_json(tmp_path):
    import subprocess
    import sys

    input_path = tmp_path / "bad.json"
    output_path = tmp_path / "out.pdf"
    input_path.write_text("{not valid json", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "newadv_cibil_pdf_engine", "--input", str(input_path), "--output", str(output_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert not output_path.exists()


def test_cli_masking_flag(sample_json, tmp_path):
    import json
    import subprocess
    import sys

    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.pdf"
    input_path.write_text(json.dumps(sample_json), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "newadv_cibil_pdf_engine",
            "--input", str(input_path), "--output", str(output_path),
            "--mask-account-numbers",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    text = "\n".join(p.extract_text() for p in PdfReader(str(output_path)).pages)
    assert "00000045011400956" not in text
