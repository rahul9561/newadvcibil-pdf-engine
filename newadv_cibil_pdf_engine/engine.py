"""Orchestration layer: JSON -> HTML -> PDF.

This is the only module that imports Jinja2/WeasyPrint - everything above
it (parser, models, renderers) is pure Python with no rendering-engine
dependency, and everything below it (templates, CSS) is inert data until
this module renders it. That separation is what lets ``render_report_html``
exist as a debugging aid independent of PDF generation.
"""

from __future__ import annotations

import base64
import datetime as _dt
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from .exceptions import IdentificationDataUnavailable, InvalidReportJSON, PDFGenerationError
from .models import NormalizedReport
from .parser import ParserOptions, has_identification_details, parse
from .renderers import RenderOptions, build_context


@dataclass
class GenerateOptions:
    """Everything :func:`generate_pdf` (and friends) accept via
    ``options=``. Every field has a safe default matching the reference
    PDF's own behaviour.
    """

    mask_account_numbers: bool = False
    include_footer: bool = True
    include_disclaimer: bool = True
    score_range: tuple[int, int] = (300, 900)
    payment_history_sentinel_map: dict[int, str] | None = None

    @classmethod
    def from_mapping(cls, options: "GenerateOptions | dict | None") -> "GenerateOptions":
        if options is None:
            return cls()
        if isinstance(options, GenerateOptions):
            return options
        if isinstance(options, dict):
            known = {f for f in cls.__dataclass_fields__}
            unknown = set(options) - known
            if unknown:
                raise TypeError(f"Unknown option(s): {', '.join(sorted(unknown))}")
            return cls(**options)
        raise TypeError(f"options must be a dict or GenerateOptions, got {type(options).__name__}")


PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
LOGO_PATH = STATIC_DIR / "logo" / "cibil-logo.svg"
FONTS_DIR = STATIC_DIR / "fonts"

# (family, weight, file) - the typefaces the reference PDF embeds. Bundled
# under static/fonts (SIL OFL, licences alongside) so output does not
# depend on what is installed on the host and needs no network access.
_FONT_FACES = (
    ("Roboto", 400, "Roboto-Regular.ttf"),
    ("Roboto", 500, "Roboto-Medium.ttf"),
    ("Roboto", 700, "Roboto-Bold.ttf"),
    ("Montserrat", 600, "Montserrat-SemiBold.ttf"),
    ("Montserrat", 700, "Montserrat-Bold.ttf"),
    ("Poppins", 700, "Poppins-Bold.ttf"),
)


@lru_cache(maxsize=1)
def _font_face_css() -> str:
    rules = []
    for family, weight, filename in _FONT_FACES:
        path = FONTS_DIR / filename
        if path.is_file():
            rules.append(
                f"@font-face {{ font-family: '{family}'; font-weight: {weight}; "
                f"font-style: normal; src: url('{path.as_uri()}'); }}"
            )
    return "\n".join(rules)


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    """The repository-provided CIBIL logo (static/logo/cibil-logo.svg) as a
    ``data:`` URI, so the rendered HTML is self-contained: it renders the
    same from any working directory, in WeasyPrint or a browser.
    """
    try:
        svg = LOGO_PATH.read_bytes()
    except OSError as exc:
        raise PDFGenerationError(f"CIBIL logo not found at {LOGO_PATH}: {exc}") from exc
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")


@lru_cache(maxsize=1)
def _jinja_env():
    # Imported lazily so importing newadv_cibil_pdf_engine never requires
    # Jinja2/WeasyPrint unless you actually call a rendering function.
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    templates_dir = PACKAGE_DIR / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(["html"]),
    )
    return env


@lru_cache(maxsize=1)
def _report_css() -> str:
    css_path = STATIC_DIR / "css" / "report.css"
    return _font_face_css() + "\n" + css_path.read_text(encoding="utf-8")


def _extract_report_json(report_json: Any) -> Any:
    if report_json is None:
        raise InvalidReportJSON("report_json must not be None.")
    if isinstance(report_json, (str, bytes)):
        import json

        try:
            return json.loads(report_json)
        except (ValueError, TypeError) as exc:
            raise InvalidReportJSON(f"report_json is not valid JSON: {exc}") from exc
    return report_json


def _unwrap_api_response(payload: Any) -> Any:
    """Unwrap a ``{"status": ..., "message": ..., "data": ...}``-style API
    envelope if present; otherwise return ``payload`` unchanged. Safe to
    call on either shape - :func:`generate_pdf` uses this internally too,
    so passing the full API response to it just works.
    """
    if isinstance(payload, dict) and "data" in payload and ("status" in payload or "message" in payload):
        return payload["data"]
    return payload


def parse_report(report_json: Any, options: GenerateOptions | dict | None = None) -> NormalizedReport:
    """Parse arbitrary CIBIL report JSON (or an API envelope around it)
    into a :class:`~newadv_cibil_pdf_engine.models.NormalizedReport`, without
    rendering anything. Useful if you want the structured data (e.g. for
    an API response) rather than a PDF.
    """
    opts = GenerateOptions.from_mapping(options)
    data = _unwrap_api_response(_extract_report_json(report_json))
    parser_options = ParserOptions(
        mask_account_numbers=opts.mask_account_numbers,
        payment_history_sentinel_map=opts.payment_history_sentinel_map,
        score_range=opts.score_range,
    )
    return parse(data, parser_options)


def _render_html(report: NormalizedReport, opts: GenerateOptions) -> str:
    context = build_context(
        report,
        RenderOptions(include_footer=opts.include_footer, include_disclaimer=opts.include_disclaimer),
    )
    context["report_css"] = _report_css()
    context["copyright_year"] = _dt.datetime.now().year
    context["logo_src"] = logo_data_uri()
    template = _jinja_env().get_template("report.html")
    return template.render(**context)


def render_report_html(report_json: Any, options: GenerateOptions | dict | None = None) -> str:
    """Render the full report to a standalone HTML string, without
    invoking WeasyPrint. Handy for debugging the template/CSS in a regular
    browser before generating a PDF.
    """
    opts = GenerateOptions.from_mapping(options)
    report = parse_report(report_json, opts)
    return _render_html(report, opts)


def generate_pdf_bytes(report_json: Any, options: GenerateOptions | dict | None = None) -> bytes:
    """Render ``report_json`` (bureau JSON, or an API envelope containing
    it) straight to PDF bytes - no disk I/O.

    Raises :class:`~newadv_cibil_pdf_engine.exceptions.IdentificationDataUnavailable`
    - without writing anything - if, once ``report_summary``,
    ``identity_sent`` and the bureau record itself are all normalised and
    checked, there is no meaningful identification data (name, gender,
    date of birth, PAN, phone, email, or address) anywhere in the report.
    A missing PAN alone never triggers this - any one of the other fields
    is enough.
    """
    opts = GenerateOptions.from_mapping(options)
    report = parse_report(report_json, opts)
    if not has_identification_details(report.identification):
        raise IdentificationDataUnavailable(
            "No meaningful identification data (name, gender, date of birth, "
            "PAN, phone, email, or address) was found anywhere in the report "
            "after normalisation; PDF generation was skipped."
        )
    html = _render_html(report, opts)
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - environment issue, not a bug
        raise PDFGenerationError(
            "WeasyPrint is not installed. Install it with `pip install weasyprint` "
            "(see this package's README for system dependencies)."
        ) from exc
    try:
        return HTML(string=html, base_url=str(PACKAGE_DIR)).write_pdf()
    except Exception as exc:  # WeasyPrint raises a variety of exception types
        raise PDFGenerationError(f"PDF rendering failed: {exc}") from exc


def generate_pdf(
    report_json: Any,
    output_path: str | Path,
    options: GenerateOptions | dict | None = None,
) -> Path:
    """Render ``report_json`` to a PDF file at ``output_path``. Returns the
    resolved output path.
    """
    pdf_bytes = generate_pdf_bytes(report_json, options)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)
    return output_path


def generate_pdf_from_api_response(
    api_response: Any,
    output_path: str | Path,
    options: GenerateOptions | dict | None = None,
) -> Path:
    """Same as :func:`generate_pdf`, but explicit about accepting a full
    ``{"status", "message", "data": <report>}`` API envelope. (In practice
    :func:`generate_pdf` already unwraps this shape automatically, so the
    two are interchangeable - this alias exists purely for call-site
    clarity in code that receives an API response object.)
    """
    return generate_pdf(api_response, output_path, options)


def validate_report_json(report_json: Any) -> bool:
    """Return ``True`` if ``report_json`` contains a recognisable CIBIL
    report, ``False`` otherwise. Never raises for "just not a report" -
    raises :class:`~newadv_cibil_pdf_engine.exceptions.InvalidReportJSON` only if
    the input is not JSON/JSON-able at all.
    """
    data = _unwrap_api_response(_extract_report_json(report_json))
    from .parser import locate_report_root

    kind, _ = locate_report_root(data)
    return kind is not None
