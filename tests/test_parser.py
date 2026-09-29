"""Tests for newadv_cibil_pdf_engine.parser: JSON -> NormalizedReport."""

from __future__ import annotations

import pytest

from newadv_cibil_pdf_engine.exceptions import MissingRequiredField, UnsupportedReportFormat
from newadv_cibil_pdf_engine.parser import (
    ParserOptions,
    _build_payment_history_rows_from_literal,
    _parse_tlcr_identifications,
    locate_report_root,
    parse,
)

from .conftest import tlcr_of


def test_locates_tlcr_inside_full_api_trace(sample_json):
    kind, root = locate_report_root(sample_json)
    assert kind == "tlcr"
    assert "Borrower" in root and "TradeLinePartition" in root


def test_locates_tlcr_wrapped_in_status_message_data(sample_json_copy):
    wrapped = {"status": "success", "message": "ok", "data": sample_json_copy}
    kind, _ = locate_report_root(wrapped)
    assert kind == "tlcr"


def test_valid_report_parses_core_fields(sample_json):
    report = parse(sample_json)
    assert report.consumer.name == "ELINKE VENKATESWARA RAO"
    assert report.consumer.date_of_birth == "01/04/1982"
    assert report.consumer.gender == "Male"
    assert report.score is not None
    assert report.score.value == 753
    assert len(report.accounts) == 10
    assert len(report.enquiries) == 35


def test_multiple_accounts_split_open_and_closed(sample_json):
    report = parse(sample_json)
    assert len(report.open_accounts) + len(report.closed_accounts) == len(report.accounts)
    assert len(report.closed_accounts) > 0


def test_multiple_enquiries_sorted_most_recent_first(sample_json):
    report = parse(sample_json)
    dates = [e._date_sort for e in report.enquiries]
    assert dates == sorted(dates, reverse=True)


def test_account_number_masking(sample_json):
    plain = parse(sample_json, ParserOptions(mask_account_numbers=False))
    masked = parse(sample_json, ParserOptions(mask_account_numbers=True))
    assert plain.accounts[0].account_number != masked.accounts[0].account_number
    assert masked.accounts[0].account_number.endswith(plain.accounts[0].account_number[-4:])
    assert set(masked.accounts[0].account_number[:-4]) <= {"X"}


def test_empty_accounts_does_not_crash(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    tlcr["TradeLinePartition"] = []
    report = parse(sample_json_copy)
    assert report.accounts == []


def test_empty_enquiries_does_not_crash(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    tlcr["InquiryPartition"] = []
    report = parse(sample_json_copy)
    assert report.enquiries == []


def test_missing_score_does_not_crash(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    del tlcr["Borrower"]["CreditScore"]
    report = parse(sample_json_copy)
    assert report.score is None


def test_missing_optional_fields_use_safe_defaults(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    tlcr["Borrower"]["BorrowerTelephone"] = []
    tlcr["Borrower"]["BorrowerAddress"] = []
    tlcr["Borrower"]["IdentifierPartition"]["Identifier"] = []
    # Also remove every source build_identification()/PAN-augmentation
    # would otherwise fall back to, so this stays a true "nothing at all
    # is available" case.
    if "report_summary" in sample_json_copy.get("data", {}):
        sample_json_copy["data"]["report_summary"]["pan"] = None
    if "identity_sent" in sample_json_copy.get("data", {}):
        sample_json_copy["data"]["identity_sent"]["pan_id"] = None
    report = parse(sample_json_copy)
    assert report.phones == []
    assert report.addresses == []
    assert report.identifications == []


def test_null_fields_do_not_crash(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    tlcr["Borrower"]["Birth"]["date"] = None
    tlcr["Borrower"]["Gender"] = None
    report = parse(sample_json_copy)
    assert report.consumer.date_of_birth == "-"


def test_long_customer_name_and_address_survive(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    long_name = "A VERY LONG CONSUMER NAME " * 5
    long_street = "A VERY LONG STREET ADDRESS LINE " * 8
    tlcr["Borrower"]["BorrowerName"]["Name"]["Forename"] = long_name
    tlcr["Borrower"]["BorrowerAddress"][0]["CreditAddress"]["StreetAddress"] = long_street
    report = parse(sample_json_copy)
    assert report.consumer.name == long_name.strip()
    assert long_street.strip().split()[0] in report.addresses[0].lines


def test_unrecognisable_json_raises_unsupported_format():
    with pytest.raises(UnsupportedReportFormat):
        parse({"totally": "unrelated"})


def test_tlcr_shape_without_borrower_raises_missing_required_field():
    with pytest.raises(MissingRequiredField):
        parse({"TrueLinkCreditReport": {"TradeLinePartition": [], "InquiryPartition": []}})


def test_raw_subject_shape_without_name_raises_missing_required_field():
    with pytest.raises(MissingRequiredField):
        parse({"subject": [{"account": [], "inquiry": []}], "ecn": 123})


def test_long_lender_name_and_long_account_number_survive(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    long_lender = "A VERY LONG LENDER NAME PRIVATE LIMITED " * 3
    long_account_number = "9" * 40
    tlcr["TradeLinePartition"][0]["Tradeline"]["creditorName"] = long_lender
    tlcr["TradeLinePartition"][0]["Tradeline"]["accountNumber"] = long_account_number
    report = parse(sample_json_copy)
    assert report.accounts[0].member_name == long_lender.strip()
    assert report.accounts[0].account_number == long_account_number


def test_zero_account_and_zero_enquiry_report_still_parses(sample_json_copy):
    tlcr = tlcr_of(sample_json_copy)
    tlcr["TradeLinePartition"] = []
    tlcr["InquiryPartition"] = []
    report = parse(sample_json_copy)
    assert report.accounts == []
    assert report.enquiries == []
    assert report.consumer.name  # unrelated fields still populate


# --------------------------------------------------------------------------
# _parse_tlcr_identifications - regression coverage for the AttributeError
# ('str' object has no attribute 'get') this engine used to raise when
# Borrower.IdentifierPartition.Identifier arrived as a bare dict (single
# entry collapsed from a list, as real TransUnion TLCR feeds do) instead of
# a list of dicts - iterating a bare dict yields its *keys* as strings.
# --------------------------------------------------------------------------

def test_identifications_entry_is_a_dict_parses_correctly():
    borrower = {
        "IdentifierPartition": {
            "Identifier": {"ID": {"IdentifierName": "UId", "Id": "123456789012"}}
        }
    }
    out = _parse_tlcr_identifications(borrower)
    assert len(out) == 1
    assert out[0].id_number == "123456789012"


def test_identifications_entry_is_a_string_does_not_crash():
    # The exact shape that used to crash: a bare dict for "Identifier"
    # (instead of a one-element list) makes plain iteration yield its keys
    # ("ID", "Source", ...) as strings.
    borrower = {"IdentifierPartition": {"Identifier": {"ID": "not-a-dict", "Source": {}}}}
    out = _parse_tlcr_identifications(borrower)
    assert out == []


def test_identifications_entry_is_none_does_not_crash():
    borrower = {"IdentifierPartition": {"Identifier": None}}
    assert _parse_tlcr_identifications(borrower) == []


def test_identifications_collection_missing_does_not_crash():
    assert _parse_tlcr_identifications({}) == []
    assert _parse_tlcr_identifications({"IdentifierPartition": {}}) == []


def test_identifications_list_with_mixed_entry_types_does_not_crash():
    borrower = {
        "IdentifierPartition": {
            "Identifier": [
                {"ID": {"IdentifierName": "UId", "Id": "999999999999"}},
                "a bare string entry",
                None,
                42,
            ]
        }
    }
    out = _parse_tlcr_identifications(borrower)
    assert len(out) == 1
    assert out[0].id_number == "999999999999"


def test_identifications_real_sample_no_longer_crashes(sample_json):
    # This is the exact shape shipped in input/sample.json today: a single
    # Identifier collapsed to a bare dict (IdentifierName "SocialId", which
    # is bureau bookkeeping and deliberately excluded from the rendered
    # list) - parsing it must not raise.
    report = parse(sample_json)
    assert isinstance(report.identifications, list)


def test_raw_subject_shape_parses_independently(sample_json):
    # The base64-embedded raw bureau payload, addressed directly (no TLCR
    # wrapper at all), should parse via the other code path.
    import base64
    import json as _json

    tlcr = tlcr_of(sample_json)
    blob = tlcr["Sources"]["Source"]["OriginalData"]
    decoded = _json.loads(base64.b64decode(blob))
    resp = decoded["ICRS_SubjectInquiryByTUEF_Response"]

    kind, _ = locate_report_root(resp)
    assert kind == "raw_subject"
    report = parse(resp)
    assert report.consumer.name == "ELINKE VENKATESWARA RAO"
    assert len(report.accounts) == 10


# --------------------------------------------------------------------------
# _build_payment_history_rows_from_literal - regression coverage for the
# real TransUnion TLCR MonthlyPayStatus structure(s). See the AttributeError
# ('str' object has no attribute 'get') this engine used to raise when
# MonthlyPayStatus arrived as a list of bare status strings instead of a
# list of {"date", "status"} dicts.
# --------------------------------------------------------------------------

def _cell(rows, year, month_abbr):
    """Look up a single cell across the list of PaymentHistoryRow for tests."""
    row = next(r for r in rows if r.year == year)
    from newadv_cibil_pdf_engine.parser import _MONTH_ABBR

    return row.cells[_MONTH_ABBR.index(month_abbr)]


def test_payment_history_list_of_dicts():
    history = [
        {"date": "2024-01-01+05:30", "status": "STD"},
        {"date": "2023-12-01+05:30", "status": "SUB"},
    ]
    rows = _build_payment_history_rows_from_literal(history, "2024-01-01+05:30")
    assert [r.year for r in rows] == [2024, 2023]
    assert _cell(rows, 2024, "Jan") == "STD"
    assert _cell(rows, 2023, "Dec") == "SUB"


def test_payment_history_list_of_bare_status_strings():
    # The real production shape that crashed the old parser: no per-entry
    # date at all, just status codes, one per month starting at startDate.
    history = ["STD", "STD", "SUB", "STD", "XXX", "STD"]
    rows = _build_payment_history_rows_from_literal(history, "2026-08-01+05:30")
    assert len(rows) == 1
    assert rows[0].year == 2026
    assert _cell(rows, 2026, "Aug") == "STD"
    assert _cell(rows, 2026, "Jul") == "STD"
    assert _cell(rows, 2026, "Jun") == "SUB"
    assert _cell(rows, 2026, "May") == "STD"
    assert _cell(rows, 2026, "Apr") == "XXX"
    assert _cell(rows, 2026, "Mar") == "STD"


def test_payment_history_empty_history_returns_no_rows():
    assert _build_payment_history_rows_from_literal([], "2026-08-01+05:30") == []
    assert _build_payment_history_rows_from_literal([], None) == []
    assert _build_payment_history_rows_from_literal(None, "2026-08-01+05:30") == []


def test_payment_history_none_entries_do_not_crash_and_stay_aligned():
    history = [
        {"date": "2024-03-01+05:30", "status": "STD"},
        None,
        "SUB",
    ]
    rows = _build_payment_history_rows_from_literal(history, "2024-03-01+05:30")
    assert _cell(rows, 2024, "Mar") == "STD"
    assert _cell(rows, 2024, "Feb") is None  # the None entry -> blank cell, not dropped
    assert _cell(rows, 2024, "Jan") == "SUB"  # still lands on the right month


def test_payment_history_mixed_valid_and_invalid_entries():
    # A bare string, a bogus int, a dict missing its own "date" (falls back
    # to the running position), and another bare string.
    history = ["STD", 12345, {"status": "SUB"}, "DBT"]
    rows = _build_payment_history_rows_from_literal(history, "2025-06-01+05:30")
    assert _cell(rows, 2025, "Jun") == "STD"
    assert _cell(rows, 2025, "May") is None  # the malformed int -> blank, not a crash
    assert _cell(rows, 2025, "Apr") == "SUB"
    assert _cell(rows, 2025, "Mar") == "DBT"


def test_payment_history_dict_wrapped_single_entry_is_normalised_to_list():
    # Some XML->JSON conversions collapse a single-element array to a bare
    # object instead of a one-item list.
    history = {"date": "2026-01-01+05:30", "status": "STD"}
    rows = _build_payment_history_rows_from_literal(history, "2026-01-01+05:30")
    assert _cell(rows, 2026, "Jan") == "STD"


def test_payment_history_no_placeable_entries_returns_no_rows():
    # No start_date and no per-entry dates at all - genuinely can't place
    # anything, so nothing is fabricated.
    assert _build_payment_history_rows_from_literal(["STD", "SUB"], None) == []


def test_payment_history_real_sample_structure_list_of_dicts(sample_json_copy):
    # The exact shape this repo's sample.json actually uses today.
    tlcr = tlcr_of(sample_json_copy)
    report = parse(sample_json_copy)
    gt = tlcr["TradeLinePartition"][0]["Tradeline"]["GrantedTrade"]
    expected_history = gt["PayStatusHistory"]["MonthlyPayStatus"]
    assert isinstance(expected_history, list) and isinstance(expected_history[0], dict)

    # Locate the same account in the parsed report by its account number.
    account_number = tlcr["TradeLinePartition"][0]["Tradeline"]["accountNumber"]
    account = next(a for a in report.accounts if a.account_number == account_number)
    assert account.payment_history  # populated, not silently dropped
    assert account.payment_start_date != "-"
    first_entry = expected_history[0]
    d = first_entry["date"][:7]  # "2026-08"
    year = int(d[:4])
    assert any(row.year == year for row in account.payment_history)


def test_payment_history_real_sample_structure_as_bare_strings_does_not_crash(sample_json_copy):
    # Reproduces the production AttributeError: MonthlyPayStatus arriving as
    # a list of bare status strings (no per-entry "date"/"status" dicts),
    # using this repo's own real sample TLCR account/dates as the source of
    # truth for what the correct month mapping should be.
    tlcr = tlcr_of(sample_json_copy)
    gt = tlcr["TradeLinePartition"][0]["Tradeline"]["GrantedTrade"]
    original_history = gt["PayStatusHistory"]["MonthlyPayStatus"]
    bare_statuses = [entry["status"] for entry in original_history]
    gt["PayStatusHistory"]["MonthlyPayStatus"] = bare_statuses

    report = parse(sample_json_copy)  # must not raise AttributeError

    account_number = tlcr["TradeLinePartition"][0]["Tradeline"]["accountNumber"]
    account = next(a for a in report.accounts if a.account_number == account_number)
    assert account.payment_history

    start_date = gt["PayStatusHistory"]["startDate"]
    for i, status in enumerate(bare_statuses):
        d = utils_parse_bureau_date_for_test(start_date, i)
        cell = _cell(account.payment_history, d[0], d[1])
        assert cell == status


def utils_parse_bureau_date_for_test(start_date: str, months_back: int) -> tuple[int, str]:
    """Step ``months_back`` calendar months before ``start_date`` and return
    ``(year, month_abbr)`` - a tiny test-only mirror of the parser's own
    positional cursor, used only to compute *expected* values above.
    """
    from newadv_cibil_pdf_engine.parser import _MONTH_NUM_TO_ABBR
    from newadv_cibil_pdf_engine.utils import parse_bureau_date

    start = parse_bureau_date(start_date)
    year, month = start.year, start.month
    for _ in range(months_back):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return year, _MONTH_NUM_TO_ABBR[month]
