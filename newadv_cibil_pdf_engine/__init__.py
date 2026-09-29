"""newadv_cibil_pdf_engine - a reusable, framework-agnostic JSON -> PDF rendering
engine for TransUnion CIBIL consumer credit reports.

    from newadv_cibil_pdf_engine import generate_pdf
    generate_pdf(report_json=data, output_path="report.pdf")

See the package README for the full public API, JSON->PDF field mapping,
and integration examples (Django, FastAPI, Celery, Docker).
"""

from __future__ import annotations

from .engine import (
    GenerateOptions,
    generate_pdf,
    generate_pdf_bytes,
    generate_pdf_from_api_response,
    parse_report,
    render_report_html,
    validate_report_json,
)
from .exceptions import (
    CibilPdfEngineError,
    IdentificationDataUnavailable,
    InvalidReportJSON,
    MissingRequiredField,
    PDFGenerationError,
    UnsupportedReportFormat,
)
from .models import NormalizedReport
from .parser import build_identification, has_identification_details

__version__ = "2.0.0"

__all__ = [
    "generate_pdf",
    "generate_pdf_bytes",
    "generate_pdf_from_api_response",
    "render_report_html",
    "validate_report_json",
    "parse_report",
    "build_identification",
    "has_identification_details",
    "GenerateOptions",
    "NormalizedReport",
    "CibilPdfEngineError",
    "InvalidReportJSON",
    "UnsupportedReportFormat",
    "MissingRequiredField",
    "IdentificationDataUnavailable",
    "PDFGenerationError",
    "__version__",
]
