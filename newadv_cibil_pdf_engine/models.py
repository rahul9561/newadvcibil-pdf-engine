"""The normalized, renderer-facing report model.

Nothing downstream of ``CibilReportParser.parse()`` ever touches raw JSON
again - every renderer/template works off these dataclasses, all of whose
fields carry safe defaults (empty string/list, or ``None``) so a report
missing large chunks of optional data still renders cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Consumer:
    name: str = ""
    date_of_birth: str = ""  # already display-formatted (DD/MM/YYYY) or "-"
    gender: str = ""


@dataclass
class Identification:
    id_type_label: str = ""
    id_number: str = ""
    issue_date: str = "-"
    expiry_date: str = "-"


@dataclass
class Address:
    lines: str = ""
    category_label: str = ""
    residence_code_label: str = "-"
    date_reported: str = "-"
    is_permanent: bool = False


@dataclass
class Phone:
    type_label: str = ""
    number: str = ""
    extension: str = "-"


@dataclass
class Email:
    address: str = ""


@dataclass
class Employment:
    account_type_label: str = ""
    date_reported: str = "-"
    occupation: str = "-"
    income: str = "-"
    monthly_annual_income_indicator: str = "-"
    net_gross_income_indicator: str = "-"
    has_data: bool = False


@dataclass
class ScoreFactor:
    text: str = ""


@dataclass
class Score:
    name: str = ""
    value: int | None = None
    date: str = "-"
    range_min: int = 300
    range_max: int = 900
    factors: list[ScoreFactor] = field(default_factory=list)

    @property
    def needle_fraction(self) -> float:
        """0..1 position of ``value`` along [range_min, range_max]."""
        if self.value is None:
            return 0.0
        span = max(self.range_max - self.range_min, 1)
        frac = (self.value - self.range_min) / span
        return min(max(frac, 0.0), 1.0)


@dataclass
class PaymentHistoryRow:
    year: int
    # 12 entries, December-first through January-last (matches reference
    # PDF column order), each a short display string ("0", "STD", "29",
    # ...) or None for "no data reported this month" (blank cell).
    cells: list[str | None] = field(default_factory=lambda: [None] * 12)


@dataclass
class Account:
    member_name: str = ""
    account_type_label: str = ""
    account_number: str = ""
    ownership_label: str = "-"
    is_open: bool = True

    credit_limit: str = "-"
    sanctioned_amount: str = "-"
    current_balance: str = "-"
    cash_limit: str = "-"
    amount_overdue: str = "-"
    rate_of_interest: str = "-"
    repayment_tenure: str = "-"
    emi_amount: str = "-"
    payment_frequency: str = "-"
    actual_payment_amount: str = "-"
    date_opened: str = "-"
    date_closed: str = "-"
    date_of_last_payment: str = "-"
    date_reported: str = "-"
    value_of_collateral: str = "-"
    credit_facility_status: str = "-"
    written_off_total: str = "-"
    written_off_principal: str = "-"
    settlement_amount: str = "-"

    payment_start_date: str = "-"
    payment_end_date: str = "-"
    payment_history: list[PaymentHistoryRow] = field(default_factory=list)

    # Additional (label, value) ACCOUNT DETAILS rows for fields a feed
    # carries beyond the reference PDF's fixed rows (e.g. the B2C feed's
    # account status / suit-filed status). Only populated when reported.
    extra_detail_rows: list[tuple[str, str]] = field(default_factory=list)

    # Sort key only, not rendered directly.
    _date_opened_sort: str = ""


@dataclass
class Enquiry:
    member_name: str = ""
    date_of_enquiry: str = "-"
    purpose_label: str = "-"
    amount: str = "-"

    _date_sort: str = ""


@dataclass
class ReportMeta:
    control_number: str = "-"
    report_date: str = "-"
    generated_at: str = ""


@dataclass
class NormalizedReport:
    meta: ReportMeta = field(default_factory=ReportMeta)
    consumer: Consumer = field(default_factory=Consumer)
    # Normalised identity/KYC fields (name, gender, date_of_birth, pan,
    # phone, email, address) pulled from whichever source actually carries
    # each one - see parser.build_identification(). Independent of
    # ``identifications`` below (the list of *document* identifiers, e.g.
    # Aadhaar/PAN card/Voter ID, parsed from IdentifierPartition); used to
    # decide whether there is any identifying information at all.
    identification: dict = field(default_factory=dict)
    identifications: list[Identification] = field(default_factory=list)
    addresses: list[Address] = field(default_factory=list)
    phones: list[Phone] = field(default_factory=list)
    emails: list[Email] = field(default_factory=list)
    employment: Employment = field(default_factory=Employment)
    score: Score | None = None
    accounts: list[Account] = field(default_factory=list)
    enquiries: list[Enquiry] = field(default_factory=list)

    @property
    def open_accounts(self) -> list[Account]:
        return [a for a in self.accounts if a.is_open]

    @property
    def closed_accounts(self) -> list[Account]:
        return [a for a in self.accounts if not a.is_open]
