"""Bounded native layout and selective offline OCR for a known list page."""

import fitz

from . import ocr
from .schema import SCHEMA_VERSION
from .tables import layout_rows, ruled_rows


def extract_page(page, config: dict) -> dict:
    warnings = []
    textpage = page.get_textpage(flags=3)
    native = page.get_text("words", textpage=textpage)
    method = "NATIVE"
    # A short title over a scan does not make a page native-text reliable.
    image_regions = page.get_image_info() if len(native) < 40 else []
    image_area = sum(fitz.Rect(image["bbox"]).get_area() for image in image_regions)
    native_text = " ".join(word[4] for word in native)
    damaged_text = native_text.count("\ufffd") > max(3, len(native_text) // 5)
    needs_ocr = (len(native) < 3 or len(native) < 12 and bool(image_regions)
                 or image_area > .7 * page.rect.get_area() and len(native) < 40 or damaged_text)
    if needs_ocr:
        if not config["ocr_enabled"]:
            warnings.append("OCR_DISABLED")
        elif (page.rect.width * page.rect.height * (config["ocr_dpi"] / 72) ** 2
              > config["ocr_max_pixels"]):
            warnings.append("OCR_PIXEL_LIMIT")
        else:
            try:
                textpage = ocr.textpage(page, {**config, "ocr_full": len(native) < 3})
                method = "OCR"
                warnings.append("OCR_REQUIRES_REVIEW")
            except Exception:
                warnings.append("OCR_UNAVAILABLE")
    raw_words = page.get_text("words", textpage=textpage)
    if len(raw_words) > config["max_words"]:
        raise ValueError("PAGE_WORD_LIMIT")
    words = [{"text": word[4], "bbox": list(word[:4]), "block": word[5],
              "line": word[6], "word": word[7]} for word in raw_words]
    raw_text = page.get_text("text", textpage=textpage)
    if len(raw_text) > 500000:
        raise ValueError("PAGE_TEXT_LIMIT")
    # Prefer actual cell borders; coordinate columns work for borderless and OCR tables.
    rows, tables = [], []
    if method == "NATIVE":
        try:
            rows, tables = ruled_rows(page, continuation=config.get("continuation_tables"))
        except Exception:
            warnings.append("TABLE_DETECTION_FAILED")
    if not tables:
        rows, tables = layout_rows(words, page.cropbox.width, continuation=config.get("continuation_tables"))
    for table in tables:
        warnings.extend(table.get("geometry", {}).get("warnings", []))
        if table["schema"]["state"] != "RESOLVED":
            warnings.extend(table["schema"]["warnings"])
    if method == "OCR":
        for row in rows:
            row["method"] = "OCR_WORD_LAYOUT"
            row["warnings"].append("OCR_REQUIRES_REVIEW")
            row["confidence"] = min(row["confidence"], .7)
    return {"raw_text": raw_text, "words": words, "width": page.rect.width, "height": page.rect.height,
        "unrotated_width": page.cropbox.width, "unrotated_height": page.cropbox.height,
        "rotation": page.rotation, "rotation_matrix": list(page.rotation_matrix),
        "tables": tables, "rows": rows, "method": method, "ocr_used": method == "OCR",
        "warnings": sorted(set(warnings)), "schema_version": SCHEMA_VERSION}
