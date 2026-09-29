"""Account (tradeline) rendering support: open/closed grouping and the
payment-history calendar grid.
"""

from __future__ import annotations

from ..models import Account

MONTH_HEADERS = ("Dec", "Nov", "Oct", "Sep", "Aug", "Jul", "Jun", "May", "Apr", "Mar", "Feb", "Jan")

ACCOUNT_DETAIL_FIELDS = (
    ("Credit Limit", "credit_limit"),
    ("Sanctioned Amount", "sanctioned_amount"),
    ("Current Balance", "current_balance"),
    ("Cash Limit", "cash_limit"),
    ("Amount Overdue", "amount_overdue"),
    ("Rate of Interest", "rate_of_interest"),
    ("Repayment Tenure", "repayment_tenure"),
    ("EMI Amount", "emi_amount"),
    ("Payment Frequency", "payment_frequency"),
    ("Actual Payment Amount", "actual_payment_amount"),
    ("Date Opened / Disbursed", "date_opened"),
    ("Date Closed", "date_closed"),
    ("Date of Last Payment", "date_of_last_payment"),
    ("Date Reported And Certified", "date_reported"),
    ("Value of Collateral", "value_of_collateral"),
    ("Credit Facility Status", "credit_facility_status"),
    ("Written-off Amount (Total)", "written_off_total"),
    ("Written-off Amount (Principal)", "written_off_principal"),
    ("Settlement Amount", "settlement_amount"),
)


# Payment-history legend, two columns per row as in the reference PDF.
LEGEND_ROWS = (
    ("STD: Standard", "SUB: Substandard"),
    ("DBT: Doubtful", "LSS: Loss"),
    ("SMA: Special Mention Account", "XXX: Not Reported"),
    ("###: Number of days past due", ""),
)


def account_context(account: Account) -> dict:
    return {
        "member_name": account.member_name,
        "account_type_label": account.account_type_label,
        "account_number": account.account_number,
        "ownership_label": account.ownership_label,
        "is_open": account.is_open,
        "detail_rows": [(label, getattr(account, attr)) for label, attr in ACCOUNT_DETAIL_FIELDS]
        + list(account.extra_detail_rows),
        "payment_start_date": account.payment_start_date,
        "payment_end_date": account.payment_end_date,
        "payment_rows": [(row.year, row.cells) for row in account.payment_history],
        "month_headers": MONTH_HEADERS,
        "has_payment_history": bool(account.payment_history),
    }


def accounts_context(accounts: list[Account]) -> dict:
    open_accounts = [account_context(a) for a in accounts if a.is_open]
    closed_accounts = [account_context(a) for a in accounts if not a.is_open]
    return {
        "open_accounts": open_accounts,
        "closed_accounts": closed_accounts,
        "total_count": len(accounts),
        "legend_rows": LEGEND_ROWS,
    }
