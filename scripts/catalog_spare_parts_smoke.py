"""Read-only, DB-free selected-page extraction with the production process boundary."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.catalog_admin.parts_extraction.process import (  # noqa: E402
    configuration,
    continuation_configuration,
    extract,
)
from app.catalog_admin.parts_extraction.service import EXTRACTOR_VERSION  # noqa: E402
from app.settings import settings  # noqa: E402


def extract_pages(path: Path, pages: list[int], *, no_ocr: bool = False) -> dict:
    if path.stat().st_size > settings.catalog_pdf_max_bytes:
        raise ValueError("CATALOG_PDF_MAX_BYTES")
    with path.open("rb") as stream:
        content = stream.read(settings.catalog_pdf_max_bytes + 1)
    if len(content) > settings.catalog_pdf_max_bytes:
        raise ValueError("CATALOG_PDF_MAX_BYTES")
    if not content.startswith(b"%PDF-"):
        raise ValueError("catalog_source_invalid_pdf")
    config = {**configuration(settings), "ocr_enabled": not no_ocr and settings.catalog_ocr_enabled}
    validated = extract(content, "validate", 0, config)
    if validated.get("error"):
        raise ValueError(validated["error"])
    if (not pages or len(pages) > 100 or len(set(pages)) != len(pages)
            or any(not 1 <= page <= validated["page_count"] for page in pages)):
        raise ValueError("catalog_visual_page_invalid")
    result, previous, last = [], None, None
    for number in pages:
        selected = dict(config)
        if previous and last + 1 == number:
            selected["continuation_tables"] = continuation_configuration(previous["tables"])
        layout = extract(content, "page", number, selected)
        if layout.get("error"):
            raise ValueError(layout["error"])
        result.append({"page_number": number, **layout})
        previous, last = layout, number
    return {"sha256": hashlib.sha256(content).hexdigest(), "extractor_version": EXTRACTOR_VERSION,
        "document_pages": validated["page_count"], "selected_pages": pages,
        "extracted_parts": sum(len(page["rows"]) for page in result),
        "ocr_pages": sum(page["ocr_used"] for page in result), "pages": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--page", type=int)
    selection.add_argument("--pages", help="Comma-separated physical PDF page numbers")
    parser.add_argument("--no-ocr", action="store_true")
    args = parser.parse_args()
    try:
        pages = [args.page] if args.page is not None else [int(value) for value in args.pages.split(",")]
        report = extract_pages(args.pdf, pages, no_ocr=args.no_ocr)
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except Exception:
        # No private filenames, native parser diagnostics or host paths in errors.
        print(json.dumps({"error": "catalog_source_invalid_pdf"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
