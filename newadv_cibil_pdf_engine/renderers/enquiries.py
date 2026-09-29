"""Enquiry Details rendering support."""

from __future__ import annotations

from ..models import Enquiry


def enquiries_context(enquiries: list[Enquiry]) -> list[dict]:
    return [
        {
            "member_name": e.member_name,
            "date_of_enquiry": e.date_of_enquiry,
            "purpose_label": e.purpose_label,
            "amount": e.amount,
        }
        for e in enquiries
    ]
