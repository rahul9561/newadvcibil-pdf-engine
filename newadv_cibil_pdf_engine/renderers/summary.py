"""Computed account/enquiry statistics.

NOTE: the reference PDF this engine was built against has no distinct
"Summary" page/section (its account and enquiry counts are only implicit
in the "ALL ACCOUNTS" / "ENQUIRY DETAILS" listings) - so this module's
output is not wired into any template today. It is kept as a reusable,
independently testable building block: a caller embedding this engine in
a larger app can use ``summary_context()`` to power something else (an API
response, a different report layout, a dashboard) without recomputing the
same aggregates, and a future template can opt into rendering it without
touching the parser.
"""

from __future__ import annotations

from ..models import Account, Enquiry
from ..utils import as_int


def summary_context(accounts: list[Account], enquiries: list[Enquiry]) -> dict:
    open_accounts = [a for a in accounts if a.is_open]
    closed_accounts = [a for a in accounts if not a.is_open]

    def _sum(values: list[str]) -> int:
        total = 0
        for v in values:
            n = as_int(v.replace("₹", "").replace(",", "")) if isinstance(v, str) else None
            if n is not None:
                total += n
        return total

    return {
        "total_accounts": len(accounts),
        "open_accounts": len(open_accounts),
        "closed_accounts": len(closed_accounts),
        "total_current_balance": _sum([a.current_balance for a in accounts]),
        "total_enquiries": len(enquiries),
    }
