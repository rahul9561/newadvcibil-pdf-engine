"""Exception hierarchy for newadv_cibil_pdf_engine.

All exceptions raised deliberately by this package inherit from
``CibilPdfEngineError`` so callers can catch everything the engine might
raise with a single ``except CibilPdfEngineError``.
"""

from __future__ import annotations


class CibilPdfEngineError(Exception):
    """Base class for every exception raised by this package."""


class InvalidReportJSON(CibilPdfEngineError):
    """The input is not valid JSON / not a JSON object at all."""


class UnsupportedReportFormat(CibilPdfEngineError):
    """The input is valid JSON but no recognisable CIBIL report structure
    (a ``TrueLinkCreditReport``-shaped bureau object, or a raw
    ``ICRS_SubjectInquiryByTUEF_Response``-shaped subject object) could be
    located anywhere in it.
    """


class MissingRequiredField(CibilPdfEngineError):
    """A field that has no safe default and is required to render a
    minimally useful report is missing (e.g. there is no borrower/subject
    record at all). Missing *optional* fields never raise this - they fall
    back to blank/"-" values instead.
    """


class PDFGenerationError(CibilPdfEngineError):
    """The HTML was built successfully but the PDF rendering step
    (WeasyPrint) failed.
    """


class IdentificationDataUnavailable(CibilPdfEngineError):
    """The report was parsed successfully but, once every known source
    (report_summary, identity_sent, and the bureau record itself) was
    normalised and checked, it carries no meaningful identification data
    at all (no name, gender, date of birth, PAN, phone, email, or
    address). PDF generation is deliberately skipped rather than
    producing a report with an empty identity - no PDF file is written.
    """
