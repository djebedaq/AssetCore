"""Independent CLI word/layout OCR for unruled or broken-grid regions."""

import fitz
from PIL import Image

from . import cell_ocr
from .tables import layout_rows


def extract(page, config, *, deadline=None):
    scale = min(300 / 72, (config["ocr_max_pixels"] / max(1, page.rect.get_area())) ** .5)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    transform = fitz.Matrix(1 / scale, 0, 0, 1 / scale, 0, 0) * page.derotation_matrix
    reading = cell_ocr.recognize([image], psm=6, deadline=deadline)[0]
    if len(reading["words"]) > config["max_words"]:
        raise ValueError("PAGE_WORD_LIMIT")
    words = []
    for word in reading["words"]:
        left, top, width, height = word["bbox"]
        words.append({"text": word["text"], "bbox": list(fitz.Rect(left, top, left + width, top + height) * transform),
            "ocr_confidence": word["confidence"]})
    rows, tables = layout_rows(words, page.cropbox.width)
    for table in tables:
        table["ocr_profile"] = {"engine": "TESSERACT_CLI", "language": "eng", "psm": 6}
        table["raster"] = {"kind": "PAGE_RENDER", "pixel_to_pdf": list(transform), "original_pixels": list(image.size)}
    for row in rows:
        row["method"] = "OCR_REGION_LAYOUT"
        row["warnings"].append("OCR_REQUIRES_REVIEW")
        row["confidence"] = min(row["confidence"], .7)
    return rows, tables, words
