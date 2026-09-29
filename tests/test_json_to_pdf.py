"""Standalone smoke test: JSON -> PDF engine -> PDF file.

Loads input/sample.json, runs it through the real public
newadv_cibil_pdf_engine.generate_pdf() function, and checks that a non-empty
PDF file was actually written to disk.

Run with:
    python -m pytest tests/test_json_to_pdf.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

from newadv_cibil_pdf_engine import generate_pdf

REPO_ROOT = Path(__file__).parent.parent
INPUT_JSON_PATH = REPO_ROOT / "input" / "sample.json"
OUTPUT_PDF_PATH = REPO_ROOT / "tests" / "output" / "test_report.pdf"


def test_json_to_pdf_generates_non_empty_pdf():
    # load JSON
    with open(INPUT_JSON_PATH, encoding="utf-8") as f:
        report_json = json.load(f)

    # PDF engine -> generate PDF
    generate_pdf(report_json, OUTPUT_PDF_PATH)

    # verify PDF exists
    assert OUTPUT_PDF_PATH.exists()

    # verify PDF is not empty
    assert OUTPUT_PDF_PATH.stat().st_size > 0
