"""Tests for newadv_cibil_pdf_engine.renderers: NormalizedReport -> template context."""

from __future__ import annotations

from newadv_cibil_pdf_engine.models import Score
from newadv_cibil_pdf_engine.parser import parse
from newadv_cibil_pdf_engine.renderers import RenderOptions, build_context
from newadv_cibil_pdf_engine.renderers.score import score_gauge_context
from newadv_cibil_pdf_engine.renderers.summary import summary_context


def test_build_context_has_all_top_level_sections(sample_json):
    report = parse(sample_json)
    ctx = build_context(report)
    for key in ("consumer", "score", "contact", "accounts", "enquiries", "control_number", "report_date"):
        assert key in ctx


def test_score_gauge_context_none_for_missing_score():
    assert score_gauge_context(None) is None


def test_score_gauge_needle_position_scales_with_value():
    low = score_gauge_context(Score(value=300, range_min=300, range_max=900))
    high = score_gauge_context(Score(value=900, range_min=300, range_max=900))
    # Needle for the minimum score points left (large x delta from centre
    # is negative-ish / small x); for the maximum score it points right.
    assert low["needle_x"] < high["needle_x"]


def test_accounts_context_splits_open_and_closed(sample_json):
    report = parse(sample_json)
    ctx = build_context(report)
    assert ctx["accounts"]["total_count"] == len(report.accounts)
    assert len(ctx["accounts"]["open_accounts"]) + len(ctx["accounts"]["closed_accounts"]) == len(report.accounts)


def test_render_options_toggle_footer_and_disclaimer(sample_json):
    report = parse(sample_json)
    ctx = build_context(report, RenderOptions(include_footer=False, include_disclaimer=False))
    assert ctx["include_footer"] is False
    assert ctx["include_disclaimer"] is False


def test_summary_context_computes_aggregates(sample_json):
    report = parse(sample_json)
    summary = summary_context(report.accounts, report.enquiries)
    assert summary["total_accounts"] == len(report.accounts)
    assert summary["open_accounts"] + summary["closed_accounts"] == len(report.accounts)
    assert summary["total_enquiries"] == len(report.enquiries)
