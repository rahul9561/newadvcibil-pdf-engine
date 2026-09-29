"""Shared helpers used by more than one section renderer."""

from __future__ import annotations

from ..models import NormalizedReport


class RenderOptions:
    """Presentation-only toggles (as opposed to ``ParserOptions``, which
    control how JSON is normalised). Kept separate so masking - which must
    happen during parsing, not templating, since a masked account number
    should never round-trip through the model unmasked - lives in one
    place only.
    """

    def __init__(self, include_footer: bool = True, include_disclaimer: bool = True) -> None:
        self.include_footer = include_footer
        self.include_disclaimer = include_disclaimer


def build_header_footer_context(report: NormalizedReport) -> dict:
    return {
        "generated_at": report.meta.generated_at,
        "control_number": report.meta.control_number,
        "report_date": report.meta.report_date,
    }
