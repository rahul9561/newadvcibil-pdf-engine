"""Contact / Email / Employment Details rendering support."""

from __future__ import annotations

from ..models import NormalizedReport


def contact_context(report: NormalizedReport) -> dict:
    return {
        "phones": [
            {"type_label": p.type_label, "number": p.number, "extension": p.extension}
            for p in report.phones
        ],
        "emails": [{"address": e.address} for e in report.emails],
        "employment": {
            "account_type_label": report.employment.account_type_label,
            "date_reported": report.employment.date_reported,
            "occupation": report.employment.occupation,
            "income": report.employment.income,
            "monthly_annual_income_indicator": report.employment.monthly_annual_income_indicator,
            "net_gross_income_indicator": report.employment.net_gross_income_indicator,
            "has_data": report.employment.has_data,
        },
    }
