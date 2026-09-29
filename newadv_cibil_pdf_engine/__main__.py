"""CLI entry point.

    python -m newadv_cibil_pdf_engine --input sample.json --output sample.pdf
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import GenerateOptions, generate_pdf
from .exceptions import CibilPdfEngineError


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="newadv-cibil-pdf-engine",
        description="Render a TransUnion CIBIL JSON report to PDF.",
    )
    p.add_argument("--input", "-i", required=True, help="Path to the input JSON file.")
    p.add_argument("--output", "-o", required=True, help="Path to write the output PDF file.")
    p.add_argument(
        "--mask-account-numbers",
        action="store_true",
        help="Mask all but the last 4 digits of every account number.",
    )
    p.add_argument(
        "--no-footer",
        action="store_true",
        help="Omit the page footer (running header/footer text and page numbers).",
    )
    p.add_argument(
        "--no-disclaimer",
        action="store_true",
        help="Omit the closing disclaimer block.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    input_path = Path(args.input)
    try:
        report_json = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: could not read {input_path}: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {input_path} is not valid JSON: {exc}", file=sys.stderr)
        return 2

    options = GenerateOptions(
        mask_account_numbers=args.mask_account_numbers,
        include_footer=not args.no_footer,
        include_disclaimer=not args.no_disclaimer,
    )

    try:
        output_path = generate_pdf(report_json, args.output, options)
    except CibilPdfEngineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
