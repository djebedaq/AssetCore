"""Independent native strategies, selective local OCR and coverage evidence."""

import subprocess
import time

import fitz

from . import context, ocr, quality, raster, region_ocr
from .schema import SCHEMA_VERSION
from .tables import layout_rows, ruled_rows

PIPELINE_VERSION = "ADAPTIVE_PDF_2"


def words_for(page, textpage, maximum):
    raw = page.get_text("words", textpage=textpage)
    if len(raw) > maximum:
        raise ValueError("PAGE_WORD_LIMIT")
    return [{"text": w[4], "bbox": list(w[:4]), "block": w[5], "line": w[6], "word": w[7]} for w in raw]


def extract_page(page, config: dict) -> dict:
    started = time.monotonic()
    deadline = started + config.get("timeout", 45) - 2
    warnings, strategies = [], []
    textpage = page.get_textpage(flags=3)
    words = words_for(page, textpage, config["max_words"])
    raw_text = page.get_text("text", textpage=textpage)
    if len(raw_text) > 500000:
        raise ValueError("PAGE_TEXT_LIMIT")
    continuation = config.get("continuation_tables")
    native_tables = []
    try:
        rows, tables = ruled_rows(page, continuation=continuation)
        native_tables = tables
        rows, tables = context.resolve(rows, tables, config)
        strategies.append(("NATIVE_TABLE", rows, tables))
    except Exception:
        warnings.append("TABLE_DETECTION_FAILED")
    # Always run independent layout, even if find_tables found only metadata.
    layout_continuation = continuation if not native_tables or any(t.get("continuation_inferred") for t in native_tables) else None
    rows, tables = layout_rows(words, page.cropbox.width, continuation=layout_continuation)
    rows, tables = context.resolve(rows, tables, config)
    if not tables and config.get("context_profiles"):
        rows, tables = context.borderless(words, page.cropbox.width, config)
    strategies.append(("NATIVE_LAYOUT", rows, tables))
    rows, tables, coverage, summaries = quality.choose(strategies)
    images = page.get_image_info()
    uncovered_image = any(fitz.Rect(i["bbox"]).get_area() > page.rect.get_area() * .15
        and not any(quality.overlap(i["bbox"], t["bbox"]) > .7 for t in tables
                    if t["quality"]["state"] == "COMPLETE_CANDIDATES") for i in images)
    damaged = raw_text.count("\ufffd") > max(3, len(raw_text) // 5)
    needs_ocr = uncovered_image or damaged or not rows and len(words) < 3
    ocr_used = False
    if needs_ocr:
        if not config["ocr_enabled"]:
            warnings.append("OCR_DISABLED")
        else:
            try:
                image_rows, image_tables = raster.extract(page, config, deadline=deadline)
                local_profiles = context.profiles({"tables": tables}, config.get("source_sha256"))
                image_rows, image_tables = context.resolve(image_rows, image_tables,
                    {**config, "context_profiles": (config.get("context_profiles", []) + local_profiles)[:8]})
                if image_tables:
                    strategies.append(("IMAGE_CELL_OCR", image_rows, image_tables))
                    ocr_used = True
            except (ValueError, RuntimeError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
                code = str(exc)
                warnings.append(code if code in {"OCR_CELL_LIMIT", "OCR_PIXEL_LIMIT", "OCR_TIME_BUDGET"}
                                else "CELL_OCR_UNAVAILABLE")
            rows, tables, coverage, summaries = quality.choose(strategies)
            if (not rows or coverage["state"] != "COMPLETE_CANDIDATES") and deadline - time.monotonic() > 3:
                try:
                    region_rows, region_tables, region_words = region_ocr.extract(page, config, deadline=deadline)
                    if region_tables:
                        strategies.append(("OCR_REGION_LAYOUT", region_rows, region_tables))
                        words, ocr_used = region_words, True
                        rows, tables, coverage, summaries = quality.choose(strategies)
                except (ValueError, RuntimeError, OSError, TimeoutError, subprocess.SubprocessError):
                    warnings.append("REGION_OCR_UNAVAILABLE")
            # Borderless/broken-grid pages retain the bounded existing OCR.
            if (not rows or coverage["state"] != "COMPLETE_CANDIDATES") and deadline - time.monotonic() > 3:
                if page.rect.width * page.rect.height * (config["ocr_dpi"] / 72) ** 2 > config["ocr_max_pixels"]:
                    warnings.append("OCR_PIXEL_LIMIT")
                else:
                    try:
                        textpage = ocr.textpage(page, {**config, "ocr_full": len(words) < 3})
                        ocr_words = words_for(page, textpage, config["max_words"])
                        ocr_rows, ocr_tables = layout_rows(ocr_words, page.cropbox.width, continuation=layout_continuation)
                        for row in ocr_rows:
                            row["method"] = "OCR_WORD_LAYOUT"
                            row["warnings"].append("OCR_REQUIRES_REVIEW")
                            row["confidence"] = min(row["confidence"], .7)
                        strategies.append(("OCR_LAYOUT", ocr_rows, ocr_tables))
                        words = ocr_words
                        raw_text = page.get_text("text", textpage=textpage)
                        if len(raw_text) > 500000:
                            raise ValueError("PAGE_TEXT_LIMIT")
                        ocr_used = True
                    except Exception:
                        warnings.append("OCR_UNAVAILABLE")
            rows, tables, coverage, summaries = quality.choose(strategies)
    for table in tables:
        warnings.extend(table.get("geometry", {}).get("warnings", []))
        warnings.extend(table["schema"].get("warnings", []))
        warnings.extend(table["quality"]["warnings"])
    warnings.extend(coverage.get("warnings", []))
    if ocr_used:
        warnings.append("OCR_REQUIRES_REVIEW")
    if uncovered_image and not any(t["method"] == "IMAGE_CELL_OCR" or t.get("ocr_profile", {}).get("engine") == "TESSERACT_CLI" for t in tables):
        # A good native island cannot conceal an unread raster list elsewhere.
        coverage.update({"state": "NEEDS_REVIEW", "unresolved_regions": 1})
        warnings.append("RASTER_COVERAGE_UNRESOLVED")
    return {"raw_text": raw_text, "words": words, "width": page.rect.width, "height": page.rect.height,
        "unrotated_width": page.cropbox.width, "unrotated_height": page.cropbox.height,
        "rotation": page.rotation, "rotation_matrix": list(page.rotation_matrix),
        "tables": tables, "rows": rows, "method": "OCR" if ocr_used else "NATIVE", "ocr_used": ocr_used,
        "warnings": sorted(set(warnings)), "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION, "quality": coverage, "strategies": summaries,
        "metrics": {"wall_seconds": round(time.monotonic() - started, 4), "ocr_used": ocr_used}}
