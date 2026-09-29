"""Personal / Identification / Address Details rendering support."""

from __future__ import annotations

from ..models import NormalizedReport
from .addresses import addresses_context


def consumer_context(report: NormalizedReport) -> dict:
    return {
        "name": report.consumer.name,
        "date_of_birth": report.consumer.date_of_birth,
        "gender": report.consumer.gender,
        "identifications": [
            {
                "id_type_label": i.id_type_label,
                "id_number": i.id_number,
                "issue_date": i.issue_date,
                "expiry_date": i.expiry_date,
            }
            for i in report.identifications
        ],
        "addresses": addresses_context(report.addresses),
    }
