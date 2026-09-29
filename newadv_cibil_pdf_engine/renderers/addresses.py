"""Address Details rendering support (Personal/Consumer Information page)."""

from __future__ import annotations

from ..models import Address


def addresses_context(addresses: list[Address]) -> list[dict]:
    return [
        {
            "lines": a.lines,
            "category_label": a.category_label,
            "residence_code_label": a.residence_code_label,
            "date_reported": a.date_reported,
        }
        for a in addresses
    ]
