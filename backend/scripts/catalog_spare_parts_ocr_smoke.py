"""Offline OCR against a synthetic selected BOM page in the release image."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402
from app.catalog_admin.parts_extraction.process import configuration, extract  # noqa: E402
from app.settings import settings  # noqa: E402


def main() -> None:
    native = fitz.open()
    page = native.new_page(width=600, height=800)
    columns = (40, 120, 300, 520)
    for x, header in zip(columns, ("Pos", "Part No.", "Description", "Qty"), strict=True):
        page.insert_text((x, 100), header, fontsize=14)
    for number in range(1, 5):
        for x, value in zip(columns, (str(number), f"QA-OCR-{number}", "Synthetic seal", str(number)), strict=True):
            page.insert_text((x, 130 + number * 28), value, fontsize=14)
    image = page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png")
    scanned = fitz.open()
    selected = scanned.new_page(width=600, height=800)
    selected.insert_image(selected.rect, stream=image)
    result = extract(scanned.tobytes(), "page", 1, configuration(settings))
    native.close()
    scanned.close()
    if not result.get("ocr_used") or result.get("method") != "OCR" or len(result.get("rows", [])) != 4:
        raise RuntimeError("Selected-page offline OCR smoke failed")
    if not all(row["bbox"] and row["raw_text"] and "OCR_REQUIRES_REVIEW" in row["warnings"] for row in result["rows"]):
        raise RuntimeError("OCR evidence and human review are required")
    print(json.dumps({"method": "OCR", "rows": 4, "all_rows_require_review": True,
                      "languages": settings.catalog_ocr_languages}))


if __name__ == "__main__":
    main()
