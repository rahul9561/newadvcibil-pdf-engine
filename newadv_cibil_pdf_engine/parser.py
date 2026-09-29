"""JSON -> NormalizedReport.

Credit report JSON is seen, in practice, in more than one shape
depending on which part of an upstream integration produced it. This
parser locates and understands three of them, searching for whichever is
present anywhere in the input (at any nesting depth, so it does not matter
whether you pass the whole upstream API transcript, a ``{status, message,
data}`` wrapper, or the bureau object on its own):

1. **Normalised** - a ``TrueLinkCreditReport`` object (``Borrower``,
   ``TradeLinePartition``, ``InquiryPartition``, ...), where most coded
   fields are already ``{"symbol", "description", "abbreviation"}``
   objects and payment-history status is a literal ``"STD"``/``"SUB"``/...
   string. This is what a ``GetCustomerAssets``-style API step returns and
   is the primary, best-supported shape.
2. **Raw bureau** - an ``ICRS_SubjectInquiryByTUEF_Response``-shaped
   ``subject`` object, where every coded field is a bare numeric/short
   string code and payment history is a numeric sentinel array. This is
   what you get if you feed the engine the bureau's raw wire response
   directly (or its embedded, base64-encoded ``OriginalData`` payload).
   Decoded purely via the static code tables in ``data/codes.py``.
3. **B2C-REPORT** - a ``{"B2C-REPORT": {"HEADER-SEGMENT", "REQUEST-DATA",
   "REPORT-DATA"}}`` object (``data.result_json.parsed_data`` in the API
   response - the current upstream format, see ``input/sample.json``).
   Parsed by :mod:`.parser_b2c`; it takes priority over the other two.

When both are present in the same document (as in the sample JSON, where
the raw payload is embedded as base64 inside the normalised one) the
normalised shape is used as the primary source and the raw shape is
consulted only to fill in the handful of fields the normalised shape does
not carry (currently: an account's "date of last payment"), matched by
account number.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections import deque
from typing import Any, Mapping

from . import utils
from .data import codes
from .exceptions import MissingRequiredField, UnsupportedReportFormat
from .parser_b2c import ROOT_KEY as _B2C_ROOT_KEY, parse_b2c
from .models import (
    Account,
    Address,
    Consumer,
    Email,
    Employment,
    Enquiry,
    Identification,
    NormalizedReport,
    Phone,
    ReportMeta,
    Score,
    ScoreFactor,
    PaymentHistoryRow,
)

_MONTH_ABBR = ("Dec", "Nov", "Oct", "Sep", "Aug", "Jul", "Jun", "May", "Apr", "Mar", "Feb", "Jan")


# --------------------------------------------------------------------------
# Locating the report inside arbitrary wrapper JSON
# --------------------------------------------------------------------------

def _find_key_anywhere(obj: Any, key: str, max_nodes: int = 200_000) -> Any:
    """Breadth-first search for the first dict containing ``key``, at any
    depth, returning its value. Bounded so a pathological/huge document
    can't hang the parser.
    """
    dq: deque[Any] = deque([obj])
    visited = 0
    while dq:
        cur = dq.popleft()
        visited += 1
        if visited > max_nodes:
            break
        if isinstance(cur, dict):
            if key in cur:
                return cur[key]
            dq.extend(cur.values())
        elif isinstance(cur, list):
            dq.extend(cur)
    return None


def _find_dict_with_keys(obj: Any, keys: tuple[str, ...], max_nodes: int = 200_000) -> dict | None:
    dq: deque[Any] = deque([obj])
    visited = 0
    while dq:
        cur = dq.popleft()
        visited += 1
        if visited > max_nodes:
            break
        if isinstance(cur, dict):
            if all(k in cur for k in keys):
                return cur
            dq.extend(cur.values())
        elif isinstance(cur, list):
            dq.extend(cur)
    return None


def locate_report_root(data: Any) -> tuple[str, dict] | tuple[None, None]:
    """Find the bureau report object inside arbitrary wrapper JSON.

    Returns ``("b2c", obj)``, ``("tlcr", obj)``, ``("raw_subject", obj)``
    or ``(None, None)`` if nothing recognisable was found anywhere in the
    input.
    """
    b2c = _find_key_anywhere(data, _B2C_ROOT_KEY)
    if isinstance(b2c, dict):
        return "b2c", b2c

    tlcr = _find_key_anywhere(data, "TrueLinkCreditReport")
    if isinstance(tlcr, dict):
        return "tlcr", tlcr
    if isinstance(data, dict) and "TradeLinePartition" in data and "Borrower" in data:
        return "tlcr", data

    resp = _find_dict_with_keys(data, ("subject", "ecn"))
    if resp and isinstance(resp.get("subject"), list) and resp["subject"]:
        return "raw_subject", resp
    if (
        isinstance(data, dict)
        and isinstance(data.get("subject"), list)
        and data.get("subject")
        and "ecn" in data
    ):
        return "raw_subject", data

    # A bare subject object (no surrounding response envelope), or one
    # nested somewhere inside the input without an "ecn" sibling.
    bare_subject = _find_dict_with_keys(data, ("account", "name"))
    if bare_subject:
        return "raw_subject", bare_subject
    if isinstance(data, dict) and "account" in data and "name" in data:
        return "raw_subject", data

    return None, None


def _try_decode_embedded_raw_subject(data: Any) -> dict | None:
    """Best-effort: find a base64-encoded ``OriginalData`` blob anywhere in
    the input and, if it decodes to JSON containing an
    ``ICRS_SubjectInquiryByTUEF_Response.subject[0]``, return that subject
    dict. Used only to enrich the normalised (TLCR) parse with the couple
    of fields it doesn't carry - never required, and any failure along the
    way (missing key, bad base64, not JSON, unexpected shape) is swallowed
    and treated as "not available".
    """
    blob = _find_key_anywhere(data, "OriginalData")
    if not isinstance(blob, str) or not blob:
        return None
    try:
        decoded = base64.b64decode(blob, validate=False)
        parsed = json.loads(decoded.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    icrs = _find_key_anywhere(parsed, "ICRS_SubjectInquiryByTUEF_Response")
    subjects = None
    if isinstance(icrs, dict):
        subjects = icrs.get("subject")
    elif isinstance(parsed, dict):
        subjects = parsed.get("subject")
    if isinstance(subjects, list) and subjects and isinstance(subjects[0], dict):
        return subjects[0]
    return None


# --------------------------------------------------------------------------
# Parser options
# --------------------------------------------------------------------------

class ParserOptions:
    """Tunables for :func:`parse`. All optional; every field has a safe
    default matching the reference PDF's behaviour.
    """

    def __init__(
        self,
        mask_account_numbers: bool = False,
        payment_history_sentinel_map: Mapping[int, str] | None = None,
        score_range: tuple[int, int] = (300, 900),
    ) -> None:
        self.mask_account_numbers = mask_account_numbers
        self.payment_history_sentinel_map = dict(
            payment_history_sentinel_map or codes.PAYMENT_HISTORY_SENTINEL
        )
        self.score_range = score_range


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def parse(data: Any, options: ParserOptions | None = None) -> NormalizedReport:
    options = options or ParserOptions()
    if not isinstance(data, (dict, list)):
        raise UnsupportedReportFormat(
            "Input JSON must be an object or array; got "
            f"{type(data).__name__}."
        )

    kind, root = locate_report_root(data)
    if kind is None:
        raise UnsupportedReportFormat(
            "Could not locate a credit report (no 'B2C-REPORT' object, "
            "no 'TrueLinkCreditReport' object and no raw bureau "
            "'subject' array found anywhere in the supplied JSON)."
        )

    # The report *shape* was recognised (kind is not None), but the one
    # thing every CIBIL report must have to be worth rendering at all - a
    # consumer/borrower record - is missing. This is distinct from
    # UnsupportedReportFormat (shape not recognised at all): here the
    # envelope is right, but it's an empty shell. Every other field is
    # genuinely optional and never raises - see MissingRequiredField's
    # docstring.
    if kind == "tlcr" and "Borrower" not in root:
        raise MissingRequiredField(
            "TrueLinkCreditReport was found but has no 'Borrower' object - "
            "there is no consumer record to render."
        )
    if kind == "raw_subject":
        subject = root["subject"][0] if "subject" in root and isinstance(root.get("subject"), list) else root
        if "name" not in subject:
            raise MissingRequiredField(
                "A raw bureau 'subject' object was found but it has no "
                "'name' object - there is no consumer record to render."
            )

    if kind == "b2c":
        report = parse_b2c(root, options)
    elif kind == "tlcr":
        raw_subject = _try_decode_embedded_raw_subject(data)
        report = _parse_tlcr(root, options, raw_subject)
    else:
        report = _parse_raw_subject(root, options)

    report_summary = _find_key_anywhere(data, "report_summary")
    identity_sent = _find_key_anywhere(data, "identity_sent")
    report.identification = build_identification(
        report,
        report_summary if isinstance(report_summary, Mapping) else None,
        identity_sent if isinstance(identity_sent, Mapping) else None,
    )
    _augment_identifications_with_pan(report)
    return report


# --------------------------------------------------------------------------
# Normalised identification (identity/KYC) object
# --------------------------------------------------------------------------
#
# This is distinct from ``NormalizedReport.identifications`` (the list of
# *document* identifiers - Aadhaar/PAN card/Voter ID/... - parsed from
# ``IdentifierPartition`` / raw ``subject.id``). It answers a different
# question ("is there any identifying information about this person at
# all") and is built from whichever source actually carries each field,
# in priority order, reusing the report's own already-parsed consumer/
# phone/email/address data rather than re-walking raw bureau JSON.

def build_identification(
    report: NormalizedReport,
    report_summary: Mapping[str, Any] | None,
    identity_sent: Mapping[str, Any] | None,
) -> dict:
    """Normalise name/gender/date_of_birth/pan/phone/email/address from
    (in priority order) the API envelope's ``report_summary`` and
    ``identity_sent`` siblings, falling back to the bureau record already
    parsed onto ``report`` (``consumer``, ``phones``, ``emails``,
    ``addresses``). Every field is ``None`` if genuinely unavailable
    everywhere - never an empty/whitespace string.
    """
    report_summary = report_summary if isinstance(report_summary, Mapping) else {}
    identity_sent = identity_sent if isinstance(identity_sent, Mapping) else {}

    def clean_or_none(value: Any) -> str | None:
        return utils.clean_text(value) or None

    def consumer_field(value: str) -> str | None:
        return value if value and value != "-" else None

    name = (
        clean_or_none(report_summary.get("name"))
        or clean_or_none(
            utils.join_nonblank([identity_sent.get("forename"), identity_sent.get("surname")], sep=" ")
        )
        or consumer_field(report.consumer.name)
    )

    gender = (
        clean_or_none(report_summary.get("gender"))
        or clean_or_none(identity_sent.get("gender"))
        or consumer_field(report.consumer.gender)
    )

    date_of_birth = (
        clean_or_none(report_summary.get("date_of_birth"))
        or clean_or_none(identity_sent.get("date_of_birth"))
        or consumer_field(report.consumer.date_of_birth)
    )

    pan = (
        clean_or_none(report_summary.get("pan"))
        or clean_or_none(identity_sent.get("pan_id"))
        or next(
            (i.id_number for i in report.identifications if i.id_type_label == codes.ID_TYPE["01"] and i.id_number),
            None,
        )
    )

    phone = clean_or_none(identity_sent.get("phone_number")) or (
        clean_or_none(report.phones[0].number) if report.phones else None
    )

    email = clean_or_none(report.emails[0].address) if report.emails else None

    address = None
    if report.addresses:
        address = consumer_field(report.addresses[0].lines)

    return {
        "name": name,
        "gender": gender,
        "date_of_birth": date_of_birth,
        "pan": pan,
        "phone": phone,
        "email": email,
        "address": address,
    }


def has_identification_details(identification: Mapping[str, Any] | None) -> bool:
    """True if at least one meaningful field (name, gender, date_of_birth,
    pan, phone, email, or address) is present in a normalised
    identification object built by :func:`build_identification` (or any
    dict of the same shape). ``None``, blank/whitespace-only strings, and
    empty containers never count as "present".
    """
    if not isinstance(identification, Mapping):
        return False
    return any(utils.has_meaningful_value(v) for v in identification.values())


def _augment_identifications_with_pan(report: NormalizedReport) -> None:
    """The reference PDF's Identification Details section lists document
    identifiers (Aadhaar/PAN card/Voter ID/...), but PAN is frequently only
    available via ``identity_sent.pan_id`` / ``report_summary.pan`` rather
    than as a proper ``IdentifierPartition`` entry (the bureau's own
    'SocialId' bookkeeping entry is deliberately excluded there - see
    ``codes.IDENTIFIER_NAME_SKIP``). If a PAN was found by
    :func:`build_identification` and isn't already listed, add it so the
    section reflects the PAN that genuinely is available instead of
    showing "No identification details are available."
    """
    pan = report.identification.get("pan")
    if not pan:
        return
    pan_label = codes.ID_TYPE["01"]  # "Income Tax ID Number (PAN)"
    if any(i.id_type_label == pan_label for i in report.identifications):
        return
    report.identifications.append(
        Identification(id_type_label=pan_label, id_number=pan, issue_date="-", expiry_date="-")
    )


# --------------------------------------------------------------------------
# Normalised (TrueLinkCreditReport) shape
# --------------------------------------------------------------------------

def _sym(coded: Any) -> str:
    if isinstance(coded, Mapping):
        return str(coded.get("symbol") or "").strip()
    return ""


def _parse_tlcr(tlcr: dict, options: ParserOptions, raw_subject: dict | None) -> NormalizedReport:
    report = NormalizedReport()
    borrower = tlcr.get("Borrower") or {}

    report.meta = ReportMeta(
        control_number=str(tlcr.get("ReferenceKey") or "-"),
        report_date=utils.format_date(
            utils.safe_get(borrower, "CreditScore", "Source", "InquiryDate")
            or utils.safe_get(borrower, "Birth", "Source", "InquiryDate")
        ),
        generated_at=utils.format_datetime_now(),
    )

    name = utils.safe_get(borrower, "BorrowerName", "Name", "Forename")
    report.consumer = Consumer(
        name=utils.clean_text(name) or "-",
        date_of_birth=utils.format_date(utils.safe_get(borrower, "Birth", "date")),
        gender=utils.clean_text(borrower.get("Gender")) or "-",
    )

    report.identifications = _parse_tlcr_identifications(borrower)
    report.addresses = _parse_tlcr_addresses(borrower)
    report.phones = _parse_tlcr_phones(borrower)
    report.emails = _parse_tlcr_emails(borrower)
    report.employment = _parse_tlcr_employment(borrower)
    report.score = _parse_tlcr_score(borrower, options)

    raw_accounts_by_number: dict[str, dict] = {}
    if raw_subject:
        for acc in raw_subject.get("account") or []:
            num = str(acc.get("accountNumber") or "").strip()
            if num:
                raw_accounts_by_number[num] = acc

    report.accounts = _parse_tlcr_accounts(tlcr, options, raw_accounts_by_number)
    report.enquiries = _parse_tlcr_enquiries(tlcr)
    return report


def _parse_tlcr_identifications(borrower: dict) -> list[Identification]:
    """``Borrower.IdentifierPartition.Identifier`` is documented as a list
    of ``{"ID": {...}, "Source": {...}, "dateIssued": ..., ...}`` records,
    but real TransUnion feeds collapse it to a bare (single) dict instead
    of a one-element list when there's exactly one identifier -
    :func:`utils.ensure_list` normalises that back to a list first.

    Even so, each *element* of that list is still handled defensively
    (``dict``/other) rather than assumed to always be a well-formed
    record: a non-dict entry carries no ``ID``/``IdentifierName`` this
    schema can resolve to an identifier type or number, so - since there
    is nothing meaningful to extract from it - it is skipped rather than
    guessed at, exactly as every other genuinely-unresolvable field in
    this parser degrades to "not available" instead of raising.
    """
    out: list[Identification] = []
    for entry in utils.ensure_list(utils.safe_get(borrower, "IdentifierPartition", "Identifier")):
        if not isinstance(entry, Mapping):
            continue
        id_obj = entry.get("ID")
        if not isinstance(id_obj, Mapping):
            id_obj = {}
        name = str(id_obj.get("IdentifierName") or "").strip()
        if not name or name in codes.IDENTIFIER_NAME_SKIP:
            continue
        label = codes.IDENTIFIER_NAME_LABEL.get(name, name)
        out.append(
            Identification(
                id_type_label=label,
                id_number=utils.clean_text(id_obj.get("Id")) or "-",
                issue_date=utils.format_date(entry.get("dateIssued")),
                expiry_date=utils.format_date(entry.get("dateExpired")),
            )
        )
    return out


def _parse_tlcr_addresses(borrower: dict) -> list[Address]:
    out: list[Address] = []
    for entry in utils.ensure_list(borrower.get("BorrowerAddress")):
        if not isinstance(entry, Mapping):
            continue
        addr = entry.get("CreditAddress") or {}
        street = utils.clean_text(addr.get("StreetAddress"))
        city = utils.clean_text(addr.get("City"))
        region = utils.clean_text(addr.get("Region"))
        postal = utils.clean_text(addr.get("PostalCode"))
        lines = utils.join_nonblank([street, city, region, postal])
        category_raw = addr.get("AddressType") or entry.get("AddressCategory")
        category_label = utils.coded_label(
            category_raw, codes.ADDRESS_CATEGORY, raw_label="Address Category", default="Residence Address"
        )
        out.append(
            Address(
                lines=lines or "-",
                category_label=category_label,
                residence_code_label=utils.coded_label(
                    entry.get("Dwelling"), codes.DWELLING, raw_label="Residence Code"
                ),
                date_reported=utils.format_date(entry.get("dateReported")),
                is_permanent="permanent" in category_label.lower(),
            )
        )
    return out


def _parse_tlcr_phones(borrower: dict) -> list[Phone]:
    out: list[Phone] = []
    for entry in utils.ensure_list(borrower.get("BorrowerTelephone")):
        if not isinstance(entry, Mapping):
            continue
        number = utils.safe_get(entry, "PhoneNumber", "Number")
        if not number:
            continue
        out.append(
            Phone(
                type_label=utils.coded_label(entry.get("PhoneType"), codes.TELEPHONE_TYPE, raw_label="Type"),
                number=str(number),
                extension=utils.clean_text(entry.get("extension")) or "-",
            )
        )
    return out


def _parse_tlcr_emails(borrower: dict) -> list[Email]:
    # BorrowerEmail/EmailAddress is normally a list of {"Email": "..."}
    # records (or a bare one collapsed by ensure_list), but some feeds are
    # seen to report it as a bare list of email strings instead - handled
    # by falling back to the entry itself when it isn't a Mapping, rather
    # than assuming every entry is a dict.
    out: list[Email] = []
    for entry in utils.ensure_list(borrower.get("BorrowerEmail") or borrower.get("EmailAddress")):
        addr = entry.get("Email") if isinstance(entry, Mapping) else entry
        addr = utils.clean_text(addr) if isinstance(addr, (str, int, float)) else ""
        if addr:
            out.append(Email(address=addr))
    return out


def _parse_tlcr_employment(borrower: dict) -> Employment:
    emp = borrower.get("Employer") or {}
    has_data = any(
        not utils.is_blank(emp.get(k)) for k in ("name", "account", "dateReported")
    )
    return Employment(
        account_type_label=utils.coded_label(emp.get("account"), codes.ACCOUNT_TYPE, raw_label="Type"),
        date_reported=utils.format_date(emp.get("dateReported")),
        occupation=utils.clean_text(emp.get("name")) or "-",
        income="-",
        monthly_annual_income_indicator=utils.coded_label(emp.get("IncomeFreqIndicator"), default="-"),
        net_gross_income_indicator=utils.coded_label(emp.get("NetGrossIndicator"), default="-"),
        has_data=has_data,
    )


def _parse_tlcr_score(borrower: dict, options: ParserOptions) -> Score | None:
    cs = borrower.get("CreditScore")
    if not cs:
        return None
    value = utils.as_int(cs.get("riskScore"))
    factors = []
    for f in utils.ensure_list(cs.get("CreditScoreFactor")):
        if not isinstance(f, Mapping):
            continue
        texts = f.get("FactorText") or []
        text = next((t for t in texts if not str(t).lower().startswith("factor:")), None)
        if text is None and texts:
            text = texts[0]
        if text:
            text = str(text).split(":", 1)[-1].strip() if str(text).lower().startswith("explain:") else str(text)
            factors.append(ScoreFactor(text=text))
    return Score(
        name=utils.clean_text(cs.get("scoreName")) or "CIBIL TransUnion Score",
        value=value,
        date=utils.format_date(utils.safe_get(cs, "Source", "InquiryDate")),
        range_min=options.score_range[0],
        range_max=options.score_range[1],
        factors=factors,
    )


def _parse_tlcr_accounts(
    tlcr: dict, options: ParserOptions, raw_accounts_by_number: dict[str, dict]
) -> list[Account]:
    out: list[Account] = []
    for entry in utils.ensure_list(tlcr.get("TradeLinePartition")):
        if not isinstance(entry, Mapping):
            continue
        t = entry.get("Tradeline") or {}
        gt = t.get("GrantedTrade") or {}
        account_number = utils.clean_text(t.get("accountNumber"))
        is_open = utils.is_blank(t.get("dateClosed"))

        raw_acc = raw_accounts_by_number.get(account_number)
        date_of_last_payment = "-"
        if raw_acc and not utils.is_blank(raw_acc.get("dateOfLastPayment")):
            date_of_last_payment = utils.format_date(raw_acc.get("dateOfLastPayment"))

        account = Account(
            member_name=utils.clean_text(t.get("creditorName")) or "-",
            account_type_label=utils.coded_label(gt.get("AccountType"), codes.ACCOUNT_TYPE, raw_label="Type"),
            account_number=(
                utils.mask_account_number(account_number)
                if options.mask_account_numbers
                else (account_number or "-")
            ),
            ownership_label=utils.coded_label(t.get("AccountDesignator"), codes.OWNERSHIP_INDICATOR),
            is_open=is_open,
            credit_limit=utils.format_currency(gt.get("CreditLimit")),
            sanctioned_amount=utils.format_currency(t.get("highBalance")),
            current_balance=utils.format_currency(t.get("currentBalance")),
            cash_limit=utils.format_currency(gt.get("CashLimit")),
            amount_overdue=utils.format_currency(gt.get("amountPastDue")),
            rate_of_interest=utils.format_percent(gt.get("interestRate")),
            repayment_tenure=utils.format_optional_number(gt.get("termMonths")),
            emi_amount=utils.format_currency(gt.get("EMIAmount")),
            payment_frequency=utils.coded_label(gt.get("PaymentFrequency"), codes.PAYMENT_FREQUENCY),
            actual_payment_amount=utils.format_currency(gt.get("actualPaymentAmount")),
            date_opened=utils.format_date(t.get("dateOpened")),
            date_closed=utils.format_date(t.get("dateClosed")),
            date_of_last_payment=date_of_last_payment,
            date_reported=utils.format_date(t.get("dateReported")),
            value_of_collateral=utils.format_currency(gt.get("collateral")),
            credit_facility_status=utils.coded_label(t.get("AccountCondition"), codes.CREDIT_FACILITY_STATUS),
            written_off_total=utils.format_currency(t.get("writtenOffAmtTotal")),
            written_off_principal=utils.format_currency(t.get("writtenOffPrincipal")),
            settlement_amount=utils.format_currency(t.get("settlementAmount")),
        )
        account._date_opened_sort = str(t.get("dateOpened") or "")

        history = utils.safe_get(gt, "PayStatusHistory", "MonthlyPayStatus", default=[]) or []
        history_start_date = utils.safe_get(gt, "PayStatusHistory", "startDate")
        account.payment_start_date = utils.format_date(history_start_date)
        account.payment_end_date = utils.format_date(utils.safe_get(gt, "PayStatusHistory", "endDate"))
        account.payment_history = _build_payment_history_rows_from_literal(history, history_start_date)

        out.append(account)

    out.sort(key=lambda a: a._date_opened_sort, reverse=True)
    return out


def _parse_tlcr_enquiries(tlcr: dict) -> list[Enquiry]:
    out: list[Enquiry] = []
    for entry in utils.ensure_list(tlcr.get("InquiryPartition")):
        if not isinstance(entry, Mapping):
            continue
        i = entry.get("Inquiry") or {}
        enq = Enquiry(
            member_name=utils.clean_text(i.get("subscriberName")) or "-",
            date_of_enquiry=utils.format_date(i.get("inquiryDate")),
            purpose_label=utils.coded_label(i.get("inquiryType"), codes.ENQUIRY_PURPOSE, default="Other"),
            amount=utils.format_currency(i.get("amount")),
        )
        enq._date_sort = str(i.get("inquiryDate") or "")
        out.append(enq)
    out.sort(key=lambda e: e._date_sort, reverse=True)
    return out


def _build_payment_history_rows_from_literal(
    history: Any, start_date: Any = None
) -> list[PaymentHistoryRow]:
    """Build one :class:`PaymentHistoryRow` per calendar year from the TLCR
    shape's ``PayStatusHistory.MonthlyPayStatus``, in reverse-chronological
    order (most recent month first, matching the reference PDF's grid).

    Two element shapes are seen in practice from real TransUnion TLCR feeds,
    and both are accepted here, entry-by-entry:

    * ``{"date": "2026-08-01+05:30", "status": "STD"}`` - the fully
      self-describing form (what the sample JSON in this repo uses).
    * a bare status string (``"STD"``) - some upstream feeds report
      ``MonthlyPayStatus`` as a plain list of status codes with no
      per-entry date at all, the same information the raw bureau shape
      carries positionally in its numeric sentinel array (see
      :func:`_build_payment_history_rows_from_sentinels`). Each such
      entry's month is inferred positionally: the first entry is
      ``start_date`` (``PayStatusHistory.startDate``), the next is one
      calendar month earlier, and so on - entries with an explicit
      ``date`` reset this running cursor, so a list can freely mix both
      shapes without losing alignment.

    ``history`` itself may also arrive as a single dict rather than a
    list (a common XML->JSON collapse for a single-element array) - that
    is normalised to a one-element list.

    Any entry whose month can't be determined at all (no explicit date,
    no ``start_date``, and no earlier dated entry to count on from) is
    the only kind skipped - this function never calls ``.get()`` on
    anything but a real mapping, and never raises.
    """
    if isinstance(history, Mapping):
        history = [history]
    if not isinstance(history, list) or not history:
        return []

    cursor = utils.parse_bureau_date(start_date)
    year = cursor.year if cursor else None
    month = cursor.month if cursor else None

    rows_by_year: dict[int, PaymentHistoryRow] = {}
    for item in history:
        if isinstance(item, Mapping):
            d = utils.parse_bureau_date(item.get("date"))
            status = utils.clean_text(item.get("status")) or None
        elif isinstance(item, str):
            # Bare status code, e.g. "STD" - no per-entry date; position
            # comes from the running (year, month) cursor below.
            d = None
            status = utils.clean_text(item) or None
        else:
            # None, or any other genuinely unexpected element type (int,
            # list, ...) - no status to extract, but if a position can
            # still be inferred it's treated as "no data reported this
            # month" (blank cell) rather than dropped, so it doesn't
            # shift every later entry's month out of alignment.
            d = None
            status = None

        if d is not None:
            year, month = d.year, d.month
        elif year is None or month is None:
            # No explicit date on this entry, and nothing (start_date or
            # an earlier dated entry) to infer a position from yet -
            # genuinely can't place it. Skip without advancing the
            # cursor, since there is no cursor yet to advance.
            continue

        if status is not None:
            row = rows_by_year.setdefault(year, PaymentHistoryRow(year=year))
            col = _MONTH_ABBR.index(_MONTH_NUM_TO_ABBR[month])
            row.cells[col] = status

        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return [rows_by_year[y] for y in sorted(rows_by_year, reverse=True)]


# --------------------------------------------------------------------------
# Raw bureau (ICRS_SubjectInquiryByTUEF_Response.subject) shape
# --------------------------------------------------------------------------

def _parse_raw_subject(subject_root: dict, options: ParserOptions) -> NormalizedReport:
    # subject_root may be the response wrapper (has "subject": [...] and
    # "ecn") or already the subject dict itself.
    if "subject" in subject_root and isinstance(subject_root["subject"], list):
        control_number = str(subject_root.get("ecn") or "-")
        report_date = utils.format_date(subject_root.get("timestamp"))
        subject = subject_root["subject"][0]
    else:
        control_number = "-"
        report_date = "-"
        subject = subject_root

    report = NormalizedReport()
    report.meta = ReportMeta(
        control_number=control_number,
        report_date=report_date,
        generated_at=utils.format_datetime_now(),
    )

    name_obj = subject.get("name") or {}
    report.consumer = Consumer(
        name=utils.clean_text(name_obj.get("name1")) or "-",
        date_of_birth=utils.format_date(name_obj.get("dob")),
        gender=utils.coded_label(name_obj.get("gender"), codes.GENDER, default="-"),
    )

    report.identifications = [
        Identification(
            id_type_label=utils.coded_label(entry.get("idType"), codes.ID_TYPE, raw_label="ID Type"),
            id_number=utils.clean_text(entry.get("idNumber")) or "-",
        )
        for entry in subject.get("id") or []
    ]

    report.addresses = [
        Address(
            lines=utils.join_nonblank(
                [
                    entry.get("line1"),
                    entry.get("line2"),
                    entry.get("line3"),
                    entry.get("line4"),
                    entry.get("line5"),
                    entry.get("pinCode"),
                ]
            )
            or "-",
            category_label=utils.coded_label(
                entry.get("addressCategory"), codes.ADDRESS_CATEGORY, raw_label="Address Category"
            ),
            residence_code_label=utils.coded_label(
                entry.get("residenceCode"), codes.DWELLING, raw_label="Residence Code"
            ),
            date_reported=utils.format_date(entry.get("reportedDate")),
            is_permanent=str(entry.get("addressCategory")) == "02",
        )
        for entry in subject.get("address") or []
    ]

    report.phones = [
        Phone(
            type_label=utils.coded_label(entry.get("telephoneType"), codes.TELEPHONE_TYPE, raw_label="Type"),
            number=utils.clean_text(entry.get("telephoneNumber")) or "-",
        )
        for entry in subject.get("telephone") or []
    ]

    report.emails = [
        Email(address=utils.clean_text(entry)) for entry in subject.get("email") or [] if utils.clean_text(entry)
    ]

    report.employment = _parse_raw_employment(subject)
    report.score = _parse_raw_score(subject, options)
    report.accounts = _parse_raw_accounts(subject, options)
    report.enquiries = _parse_raw_enquiries(subject)
    return report


def _parse_raw_employment(subject: dict) -> Employment:
    emp = subject.get("employment") or {}
    has_data = bool(emp)
    return Employment(
        account_type_label=utils.coded_label(emp.get("accountType"), codes.ACCOUNT_TYPE, raw_label="Type"),
        date_reported=utils.format_date(emp.get("reportedDate")),
        has_data=has_data,
    )


def _parse_raw_score(subject: dict, options: ParserOptions) -> Score | None:
    scores = subject.get("scores") or []
    if not scores:
        return None
    s = scores[0]
    value = utils.as_int(s.get("score"))
    return Score(
        name=utils.clean_text(s.get("scoreName")) or "CIBIL TransUnion Score",
        value=value,
        date=utils.format_date(_ddmmyyyy_to_date(s.get("scoreDate"))),
        range_min=options.score_range[0],
        range_max=options.score_range[1],
    )


def _ddmmyyyy_to_date(value: Any) -> str | None:
    """The raw subject's ``scoreDate`` is ``DDMMYYYY`` (unlike every other
    date field, which is ``YYYYMMDD``) - normalise to ``YYYYMMDD`` so
    ``utils.format_date`` can parse it, or return ``None`` if malformed.
    """
    text = str(value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    dd, mm, yyyy = text[:2], text[2:4], text[4:]
    return f"{yyyy}{mm}{dd}"


def _parse_raw_accounts(subject: dict, options: ParserOptions) -> list[Account]:
    out: list[Account] = []
    for a in subject.get("account") or []:
        account_number = utils.clean_text(a.get("accountNumber"))
        is_open = utils.is_blank(a.get("dateClosed"))
        account = Account(
            member_name=utils.clean_text(a.get("memberShortName")) or "-",
            account_type_label=utils.coded_label(a.get("accountType"), codes.ACCOUNT_TYPE, raw_label="Type"),
            account_number=(
                utils.mask_account_number(account_number)
                if options.mask_account_numbers
                else (account_number or "-")
            ),
            ownership_label=utils.coded_label(a.get("ownershipIndicator"), codes.OWNERSHIP_INDICATOR),
            is_open=is_open,
            credit_limit=utils.format_currency(a.get("creditLimit")),
            sanctioned_amount=utils.format_currency(a.get("highCreditAmount")),
            current_balance=utils.format_currency(a.get("currentBalance")),
            cash_limit=utils.format_currency(a.get("cashLimit")),
            amount_overdue=utils.format_currency(a.get("amountOverdue")),
            rate_of_interest=utils.format_percent(a.get("rateOfInterest")),
            repayment_tenure=utils.format_optional_number(a.get("repaymentTenure")),
            emi_amount=utils.format_currency(a.get("EMIAmount")),
            payment_frequency=utils.coded_label(a.get("paymentFrequency"), codes.PAYMENT_FREQUENCY),
            actual_payment_amount=utils.format_currency(a.get("actualPaymentAmount")),
            date_opened=utils.format_date(a.get("dateOpened")),
            date_closed=utils.format_date(a.get("dateClosed")),
            date_of_last_payment=utils.format_date(a.get("dateOfLastPayment")),
            date_reported=utils.format_date(a.get("reportedDate")),
            value_of_collateral=utils.format_currency(a.get("valueOfCollateral")),
            credit_facility_status=utils.coded_label(a.get("creditFacilityStatus"), codes.CREDIT_FACILITY_STATUS),
            written_off_total=utils.format_currency(a.get("writtenOffAmtTotal")),
            written_off_principal=utils.format_currency(a.get("writtenOffAmtPrincipal")),
            settlement_amount=utils.format_currency(a.get("settlementAmount")),
        )
        account._date_opened_sort = str(a.get("dateOpened") or "")
        account.payment_start_date = utils.format_date(a.get("paymentHistStartDate"))
        account.payment_end_date = utils.format_date(a.get("paymentHistEndDate"))
        account.payment_history = _build_payment_history_rows_from_sentinels(
            a.get("paymentHistory") or [],
            a.get("paymentHistStartDate"),
            options.payment_history_sentinel_map,
        )
        out.append(account)

    out.sort(key=lambda a: a._date_opened_sort, reverse=True)
    return out


def _build_payment_history_rows_from_sentinels(
    values: list[int], start_date: Any, sentinel_map: Mapping[int, str]
) -> list[PaymentHistoryRow]:
    """``values`` is one entry per month, most-recent-first, starting at
    ``start_date``. Negative values mean "no data reported" (blank cell);
    values >=900 are asset-classification sentinels (see
    ``codes.PAYMENT_HISTORY_SENTINEL``); everything else is a literal
    days-past-due count.
    """
    start = utils.parse_bureau_date(start_date)
    if start is None or not values:
        return []

    rows_by_year: dict[int, PaymentHistoryRow] = {}
    year, month = start.year, start.month
    for raw in values:
        n = utils.as_int(raw)
        if n is None or n < 0:
            display = None
        elif n in sentinel_map:
            display = sentinel_map[n]
        else:
            display = str(n)

        row = rows_by_year.setdefault(year, PaymentHistoryRow(year=year))
        col = _MONTH_ABBR.index(_MONTH_NUM_TO_ABBR[month])
        row.cells[col] = display

        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return [rows_by_year[y] for y in sorted(rows_by_year, reverse=True)]


_MONTH_NUM_TO_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def _parse_raw_enquiries(subject: dict) -> list[Enquiry]:
    out: list[Enquiry] = []
    for i in subject.get("inquiry") or []:
        enq = Enquiry(
            member_name=utils.clean_text(i.get("memberShortName")) or "-",
            date_of_enquiry=utils.format_date(i.get("dateOfInquiry")),
            purpose_label=utils.coded_label(i.get("inquiryPurpose"), codes.ENQUIRY_PURPOSE, default="Other"),
            amount=utils.format_currency(i.get("inquiryAmount")),
        )
        enq._date_sort = str(i.get("dateOfInquiry") or "")
        out.append(enq)
    out.sort(key=lambda e: e._date_sort, reverse=True)
    return out
