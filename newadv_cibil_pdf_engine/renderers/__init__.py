"""Section renderers: NormalizedReport -> template context dicts.

Each module here owns one reference-PDF section. ``build_context`` is the
only function ``engine.py`` calls - it composes the individual section
renderers into the single context dict handed to the Jinja2 templates.
"""

from __future__ import annotations

from ..models import NormalizedReport
from .accounts import accounts_context
from .common import RenderOptions, build_header_footer_context
from .consumer import consumer_context
from .contact import contact_context
from .enquiries import enquiries_context
from .score import score_gauge_context

__all__ = ["build_context", "RenderOptions"]


def build_context(report: NormalizedReport, options: RenderOptions | None = None) -> dict:
    options = options or RenderOptions()
    return {
        **build_header_footer_context(report),
        "consumer": consumer_context(report),
        "score": score_gauge_context(report.score),
        "contact": contact_context(report),
        "accounts": accounts_context(report.accounts),
        "enquiries": enquiries_context(report.enquiries),
        "include_footer": options.include_footer,
        "include_disclaimer": options.include_disclaimer,
    }
