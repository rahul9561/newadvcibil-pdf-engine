"""B2C-REPORT JSON -> NormalizedReport.

This is the bureau shape delivered as ``data.result_json.parsed_data`` by
the upstream API (see ``input/sample.json``)::

    B2C-REPORT
      HEADER-SEGMENT        report id, date of issue
      REQUEST-DATA
        APPLICANT-SEGMENT   name/gender/phones as submitted in the request
      REPORT-DATA
        STANDARD-DATA
          SCORE[]           score value, name, factors
          DEMOGS.VARIATIONS[]  bureau-held name/DOB/PAN/phone/email/address
          TRADELINES[]      accounts, incl. pipe-delimited monthly HISTORY
          INQUIRY-HISTORY[] enquiries
          EMPLOYMENT-DETAILS[]
        ACCOUNTS-SUMMARY    (aggregates - not part of the reference layout)

Every field is optional: blank strings, ``null`` and missing keys all
degrade to the reference PDF's ``"-"`` placeholder. Values are displayed
as reported - nothing is recomputed or reinterpreted.
"""

from __future__ import annotations

from typing import Any, Mapping

from . import utils
from .data import codes
from .models import (
    Account,
    Address,
    Consumer,
    Email,
    Employment,
    Enquiry,
    Identification,
    NormalizedReport,
    PaymentHistoryRow,
    Phone,
    ReportMeta,
    Score,
    ScoreFactor,
)

ROOT_KEY = "B2C-REPORT"

# Column order of the payment-history grid (reference PDF: Dec .. Jan).
_GRID_MONTHS = (12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)

PAYMENT_HISTORY_NAME = "COMBINED-PAYMENT-HISTORY"


def _text(value: Any) -> str:
    return utils.clean_text(value)


def _or_dash(value: Any) -> str:
    return _text(value) or utils.PLACEHOLDER


def _date_sort_key(value: Any) -> str:
    d = utils.parse_bureau_date(value)
    return d.isoformat() if d else ""


def _dicts(value: Any) -> list[Mapping]:
    return [v for v in utils.ensure_list(value) if isinstance(v, Mapping)]


def parse_b2c(root: Mapping, options: Any) -> NormalizedReport:
    """``root`` is the object stored under the ``"B2C-REPORT"`` key."""
    header = root.get("HEADER-SEGMENT") or {}
    applicant = utils.safe_get(root, "REQUEST-DATA", "APPLICANT-SEGMENT") or {}
    report_data = root.get("REPORT-DATA") or {}
    standard = report_data.get("STANDARD-DATA") or {}
    variations = _variations_by_type(utils.safe_get(standard, "DEMOGS", "VARIATIONS"))

    report = NormalizedReport()
    report_date = utils.format_date(header.get("DATE-OF-ISSUE") or header.get("DATE-OF-REQUEST"))
    report.meta = ReportMeta(
        control_number=_or_dash(header.get("REPORT-ID")),
        report_date=report_date,
        generated_at=utils.format_datetime_now(),
    )
    report.consumer = _parse_consumer(applicant, variations)
    report.identifications = _parse_identifications(variations, applicant)
    report.addresses = _parse_addresses(variations.get("ADDRESS-VARIATIONS", []))
    report.phones = _parse_phones(variations.get("PHONE-VARIATIONS", []), applicant)
    report.emails = _parse_emails(variations.get("EMAIL-VARIATIONS", []), applicant)
    report.employment = _parse_employment(standard.get("EMPLOYMENT-DETAILS"))
    report.score = _parse_score(standard.get("SCORE"), report_date, options)
    report.accounts = _parse_accounts(standard.get("TRADELINES"), options)
    report.enquiries = _parse_enquiries(standard.get("INQUIRY-HISTORY"))
    return report


# --------------------------------------------------------------------------
# Demographics
# --------------------------------------------------------------------------

def _variations_by_type(groups: Any) -> dict[str, list[Mapping]]:
    """``{"PAN-VARIATIONS": [entry, ...], ...}``, each list sorted most
    recently reported first, entries without a VALUE dropped.
    """
    out: dict[str, list[Mapping]] = {}
    for group in _dicts(groups):
        vtype = _text(group.get("TYPE")).upper()
        if not vtype:
            continue
        entries = [e for e in _dicts(group.get("VARIATION")) if _text(e.get("VALUE"))]
        out.setdefault(vtype, []).extend(entries)
    for entries in out.values():
        entries.sort(key=lambda e: _date_sort_key(e.get("REPORTED-DT")), reverse=True)
    return out


def _latest_value(entries: list[Mapping]) -> str:
    return _text(entries[0].get("VALUE")) if entries else ""


def _parse_consumer(applicant: Mapping, variations: dict[str, list[Mapping]]) -> Consumer:
    # Bureau-held data (most recently reported variation) wins over what
    # was typed into the request - the report describes the bureau record.
    requested_name = utils.join_nonblank(
        [applicant.get("FIRST-NAME"), applicant.get("MIDDLE-NAME"), applicant.get("LAST-NAME")], sep=" "
    )
    name = _latest_value(variations.get("NAME-VARIATIONS", [])) or requested_name
    dob_raw = _latest_value(variations.get("DOB-VARIATIONS", [])) or applicant.get("DOB")
    return Consumer(
        name=name or utils.PLACEHOLDER,
        date_of_birth=utils.format_date(dob_raw),
        gender=_or_dash(applicant.get("GENDER")),
    )


def _variation_type_label(vtype: str) -> str:
    label = codes.B2C_ID_VARIATION_LABEL.get(vtype)
    if label:
        return label
    base = vtype[: -len("-VARIATIONS")] if vtype.endswith("-VARIATIONS") else vtype
    return base.replace("-", " ").title()


def _parse_identifications(variations: dict[str, list[Mapping]], applicant: Mapping) -> list[Identification]:
    out: list[Identification] = []
    seen: set[tuple[str, str]] = set()
    for vtype, entries in variations.items():
        if vtype in codes.B2C_NON_ID_VARIATIONS:
            continue
        label = _variation_type_label(vtype)
        for e in entries:
            number = _text(e.get("VALUE"))
            if (label, number) in seen:
                continue
            seen.add((label, number))
            out.append(Identification(id_type_label=label, id_number=number))

    # IDs submitted with the request, when the bureau returned none.
    if not out:
        for entry in _dicts(applicant.get("IDS")):
            number = _text(entry.get("VALUE"))
            if number:
                out.append(Identification(id_type_label=_or_dash(entry.get("TYPE")), id_number=number))
    return out


def _parse_addresses(entries: list[Mapping]) -> list[Address]:
    out: list[Address] = []
    for e in entries:
        # Feeds pad address fragments with ", ," runs and trailing spaces;
        # collapse those without changing the words themselves.
        parts = [p.strip() for p in _text(e.get("VALUE")).split(",")]
        lines = ", ".join(p for p in parts if p)
        out.append(
            Address(
                lines=lines or utils.PLACEHOLDER,
                category_label=utils.PLACEHOLDER,
                residence_code_label=utils.PLACEHOLDER,
                date_reported=utils.format_date(e.get("REPORTED-DT")),
            )
        )
    return out


def _parse_phones(entries: list[Mapping], applicant: Mapping) -> list[Phone]:
    out = [Phone(type_label=utils.PLACEHOLDER, number=_text(e.get("VALUE"))) for e in entries]
    if not out:
        for p in _dicts(applicant.get("PHONES")):
            number = _text(p.get("VALUE"))
            if number:
                out.append(Phone(type_label=utils.PLACEHOLDER, number=number))
    return out


def _parse_emails(entries: list[Mapping], applicant: Mapping) -> list[Email]:
    values = [_text(e.get("VALUE")) for e in entries]
    if not values:
        values = [
            _text(e.get("VALUE") if isinstance(e, Mapping) else e)
            for e in utils.ensure_list(applicant.get("EMAILS"))
            if isinstance(e, (Mapping, str))
        ]
    return [Email(address=v) for v in values if v]


def _parse_employment(details: Any) -> Employment:
    records = []
    for entry in _dicts(details):
        detail = entry.get("EMPLOYMENT-DETAIL", entry)
        if isinstance(detail, Mapping):
            records.append(detail)
    if not records:
        return Employment()
    latest = max(records, key=lambda r: _date_sort_key(r.get("LAST-REPORTED-DT")))
    return Employment(
        account_type_label=_or_dash(latest.get("ACCT-TYPE")),
        date_reported=utils.format_date(latest.get("LAST-REPORTED-DT")),
        occupation=_or_dash(latest.get("OCCUPATION")),
        income=utils.format_currency(latest.get("INCOME") or latest.get("INCOME-AMOUNT")),
        monthly_annual_income_indicator=_or_dash(latest.get("INCOME-FREQUENCY")),
        net_gross_income_indicator=_or_dash(latest.get("NET-GROSS-INDICATOR")),
        has_data=any(_text(latest.get(k)) for k in ("ACCT-TYPE", "OCCUPATION", "LAST-REPORTED-DT")),
    )


def _parse_score(scores: Any, report_date: str, options: Any) -> Score | None:
    entries = _dicts(scores)
    if not entries:
        return None
    s = entries[0]
    return Score(
        name=_text(s.get("NAME")) or "Score",
        value=utils.as_int(s.get("VALUE")),
        date=report_date,
        range_min=options.score_range[0],
        range_max=options.score_range[1],
        factors=[ScoreFactor(text=_text(f.get("DESC"))) for f in _dicts(s.get("FACTORS")) if _text(f.get("DESC"))],
    )


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------

def _is_open(t: Mapping) -> bool:
    if not utils.is_blank(t.get("CLOSED-DT")):
        return False
    return _text(t.get("ACCOUNT-STATUS")).lower() != "closed"


def _split_installment(t: Mapping) -> tuple[Any, str]:
    """``INSTALLMENT-AMT`` is reported as ``"<amount>/<frequency>"``
    (``"194/Monthly"``); ``INSTALLMENT-FREQUENCY`` repeats the frequency on
    its own when present.
    """
    amount, _, freq = _text(t.get("INSTALLMENT-AMT")).partition("/")
    return amount, _text(t.get("INSTALLMENT-FREQUENCY")) or freq.strip()


def _collateral(t: Mapping) -> tuple[str, str]:
    """(total valuation, comma-joined security types) over SECURITY-DETAILS."""
    total = None
    types: list[str] = []
    for sec in _dicts(t.get("SECURITY-DETAILS")):
        value = utils.as_int(sec.get("SECURITY-VALUATION"))
        if value is not None and value >= 0:
            total = (total or 0) + value
        stype = _text(sec.get("SECURITY-TYPE"))
        if stype and stype not in types:
            types.append(stype)
    return utils.format_currency(total), ", ".join(types)


# Account-level fields the B2C feed carries beyond the reference PDF's 19
# fixed ACCOUNT DETAILS rows. Appended below those rows, only when present.
_EXTRA_TEXT_FIELDS = (
    ("Account Status", "ACCOUNT-STATUS"),
    ("Security Status", "SECURITY-STATUS"),
    ("Suit Filed / Wilful Default", "SUIT-FILED-WILFUL-DEFAULT-STATUS"),
    ("Account Remarks", "ACCOUNT-REMARKS"),
    ("Account in Dispute", "ACCT-IN-DISPUTE"),
)
_EXTRA_DATE_FIELDS = (
    ("Suit Filed Date", "SUIT-FILED-DT"),
    ("Date Written-off", "WRITE-OFF-DT"),
)


def _extra_rows(t: Mapping, security_types: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for label, key in _EXTRA_TEXT_FIELDS:
        if _text(t.get(key)):
            rows.append((label, _text(t.get(key))))
    if security_types:
        rows.append(("Security Type", security_types))
    for label, key in _EXTRA_DATE_FIELDS:
        if utils.parse_bureau_date(t.get(key)):
            rows.append((label, utils.format_date(t.get(key))))
    if utils.as_int(t.get("LAST-PAID-AMOUNT")) is not None:
        rows.append(("Last Paid Amount", utils.format_currency(t.get("LAST-PAID-AMOUNT"))))
    return rows


def _parse_accounts(tradelines: Any, options: Any) -> list[Account]:
    out: list[Account] = []
    for t in _dicts(tradelines):
        number = _text(t.get("ACCT-NUMBER"))
        emi, frequency = _split_installment(t)
        collateral_value, security_types = _collateral(t)
        account = Account(
            member_name=_or_dash(t.get("CREDIT-GRANTOR")),
            account_type_label=_or_dash(t.get("ACCT-TYPE")),
            account_number=(
                utils.mask_account_number(number) if options.mask_account_numbers and number else (number or "-")
            ),
            ownership_label=_or_dash(t.get("OWNERSHIP-TYPE")),
            is_open=_is_open(t),
            credit_limit=utils.format_currency(t.get("CREDIT-LIMIT")),
            sanctioned_amount=utils.format_currency(t.get("DISBURSED-AMT")),
            current_balance=utils.format_currency(t.get("CURRENT-BAL")),
            cash_limit=utils.format_currency(t.get("CASH-LIMIT")),
            amount_overdue=utils.format_currency(t.get("OVERDUE-AMT")),
            rate_of_interest=utils.format_percent(t.get("INTEREST-RATE")),
            repayment_tenure=utils.format_optional_number(t.get("REPAYMENT-TENURE")),
            emi_amount=utils.format_currency(emi),
            payment_frequency=frequency or utils.PLACEHOLDER,
            actual_payment_amount=utils.format_currency(t.get("ACTUAL-PAYMENT")),
            date_opened=utils.format_date(t.get("DISBURSED-DT")),
            date_closed=utils.format_date(t.get("CLOSED-DT")),
            date_of_last_payment=utils.format_date(t.get("LAST-PAYMENT-DT")),
            date_reported=utils.format_date(t.get("REPORTED-DT")),
            value_of_collateral=collateral_value,
            credit_facility_status=_or_dash(t.get("WRITTEN-OFF-SETTLED-STATUS")),
            written_off_total=utils.format_currency(t.get("WRITE-OFF-AMT")),
            written_off_principal=utils.format_currency(t.get("PRINCIPAL-WRITE-OFF-AMT")),
            settlement_amount=utils.format_currency(t.get("SETTLEMENT-AMT")),
        )
        account.extra_detail_rows = _extra_rows(t, security_types)
        account._date_opened_sort = _date_sort_key(t.get("DISBURSED-DT"))

        months = _payment_history_months(t.get("HISTORY"))
        account.payment_history = build_payment_history_rows(months)
        if months:
            first, last = months[0][0], months[-1][0]
            account.payment_start_date = f"01/{first[1]:02d}/{first[0]}"
            account.payment_end_date = f"01/{last[1]:02d}/{last[0]}"
        out.append(account)

    out.sort(key=lambda a: a._date_opened_sort, reverse=True)
    return out


def _payment_history_months(histories: Any) -> list[tuple[tuple[int, int], str | None]]:
    """``[((year, month), cell), ...]`` from the COMBINED-PAYMENT-HISTORY
    series, in feed order (most recent month first). Months whose label
    can't be parsed are skipped; their value is not shifted onto a
    neighbouring month.
    """
    series = next(
        (h for h in _dicts(histories) if _text(h.get("NAME")).upper() == PAYMENT_HISTORY_NAME),
        None,
    )
    if series is None:
        return []
    dates = utils.split_pipe(series.get("DATES"))
    values = utils.split_pipe(series.get("VALUES"))
    out = []
    for i, label in enumerate(dates):
        ym = utils.parse_month_year(label)
        if ym is None:
            continue
        raw = values[i] if i < len(values) else ""
        out.append((ym, utils.format_payment_status(raw, codes.ADVERSE_ASSET_CLASSIFICATION)))
    return out


def build_payment_history_rows(months: list[tuple[tuple[int, int], str | None]]) -> list[PaymentHistoryRow]:
    """One grid row per calendar year (newest first), cells Dec..Jan.
    A year appears if any of its months was reported at all, even blank.
    """
    rows: dict[int, PaymentHistoryRow] = {}
    for (year, month), cell in months:
        row = rows.setdefault(year, PaymentHistoryRow(year=year))
        if cell is not None:
            row.cells[_GRID_MONTHS.index(month)] = cell
    return [rows[y] for y in sorted(rows, reverse=True)]


# --------------------------------------------------------------------------
# Enquiries
# --------------------------------------------------------------------------

def _parse_enquiries(inquiries: Any) -> list[Enquiry]:
    out: list[Enquiry] = []
    for i in _dicts(inquiries):
        purpose = _text(i.get("CREDIT-INQ-PURPS-TYPE")) or _text(i.get("LOAN-TYPE"))
        enq = Enquiry(
            member_name=_or_dash(i.get("LENDER-NAME")),
            date_of_enquiry=utils.format_date(i.get("INQUIRY-DT")),
            purpose_label=purpose or "Other",
            amount=utils.format_currency(i.get("AMOUNT")),
        )
        enq._date_sort = _date_sort_key(i.get("INQUIRY-DT"))
        out.append(enq)
    out.sort(key=lambda e: e._date_sort, reverse=True)
    return out
