"""A page's bounded native layout, selective offline OCR and structural evidence."""

import re

import fitz

from . import ocr
from .tables import POSITION, field_name, layout_rows, ruled_rows, word_lines

ROLE_WORDS = re.compile(
    r"exploded\s+(view|scheme)|spare\s+parts?(\s+list)?|parts?\s+list|"
    r"ersatzteilliste|explosionszeichnung|разглобена\s+схема|списък\s+части|"
    r"взрыв.?схема|перечень\s+деталей", re.I)


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
    blocks = page.get_text("dict", textpage=textpage, flags=3)["blocks"]
    heading_candidates = []
    for block in blocks:
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span["text"] for span in spans).strip()
            if (3 <= len(text) <= 255 and line["bbox"][1] < page.cropbox.height * .3
                    and not field_name(text) and not POSITION.fullmatch(text)):
                heading_candidates.append({"text": text, "bbox": list(line["bbox"]),
                    "size": max((span["size"] for span in spans), default=0)})
    heading_candidates.sort(key=lambda item: (-item["size"], item["bbox"][1]))
    heading = None
    for candidate in heading_candidates:
        cleaned = ROLE_WORDS.sub("", candidate["text"]).strip(" -—:·")
        if len(cleaned) >= 3 and not re.fullmatch(r"[\d\W]+", cleaned):
            heading = cleaned
            break
    # Prefer actual cell borders; coordinate columns work for borderless and OCR tables.
    rows, tables = [], []
    if method == "NATIVE":
        try:
            rows, tables = ruled_rows(page)
        except Exception:
            warnings.append("TABLE_DETECTION_FAILED")
    if not rows:
        rows, tables = layout_rows(words, page.cropbox.width)
    if method == "OCR":
        for row in rows:
            row["method"] = "OCR_WORD_LAYOUT"
            row["warnings"].append("OCR_REQUIRES_REVIEW")
            row["confidence"] = min(row["confidence"], .7)
    regions = [row["bbox"] for row in rows] + [table["bbox"] for table in tables]

    def in_table(bbox):
        center = fitz.Point((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        return any(center in fitz.Rect(region) for region in regions)

    labels = []
    for line in word_lines(words):
        if any(word["text"].casefold() in {"mm", "cm", "kg", "bar", "ø", "°"} for word in line):
            continue
        for index, word in enumerate(line):
            isolated = ((index == 0 or word["bbox"][0] - line[index - 1]["bbox"][2] > 20)
                        and (index == len(line) - 1 or line[index + 1]["bbox"][0] - word["bbox"][2] > 20))
            if (isolated and POSITION.fullmatch(word["text"]) and not in_table(word["bbox"])
                    and 0.05 * page.cropbox.height < word["bbox"][1] < .94 * page.cropbox.height):
                labels.append(word)
    drawing_count = len(page.get_drawings())
    scheme_title = bool(re.search(r"exploded|explosions|разглобена|взрыв", raw_text, re.I))
    scheme = scheme_title or len(labels) >= 2 and drawing_count >= 1 or len(labels) >= 5
    list_page = bool(rows)
    role = "BOTH" if scheme and list_page else "SPARE_PARTS_LIST" if list_page else "EXPLODED_SCHEME" if scheme else "AMBIGUOUS" if tables or needs_ocr else "OTHER"
    confidence = .94 if list_page and not warnings else .9 if scheme_title and heading else .7 if scheme else .4
    if role == "OTHER" and not warnings and words:
        confidence = .9
    if not heading and role != "OTHER":
        warnings.append("HEADING_NOT_FOUND")
    return {"raw_text": raw_text, "words": words, "width": page.rect.width, "height": page.rect.height,
        "unrotated_width": page.cropbox.width, "unrotated_height": page.cropbox.height,
        "rotation": page.rotation, "rotation_matrix": list(page.rotation_matrix),
        "headings": heading_candidates[:40], "heading": heading, "tables": tables,
        "rows": rows, "labels": labels, "method": method, "ocr_used": method == "OCR",
        "warnings": warnings, "role": role, "confidence": confidence,
        "role_evidence": {"table_rows": len(rows), "isolated_labels": len(labels),
                          "drawing_count": drawing_count, "scheme_title": scheme_title}}
