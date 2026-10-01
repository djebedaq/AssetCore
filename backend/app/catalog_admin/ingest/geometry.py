"""PDF rotation-aware coordinates and vocabulary-constrained label matching."""

import fitz

from .labels import label_members


def normalized_geometry(bbox: list[float], page: dict) -> dict:
    rect = fitz.Rect(bbox) * fitz.Matrix(*page["rotation_matrix"])
    width, height = page["width"], page["height"]
    padding = 2
    x = min(.998, max(0, (rect.x0 - padding) / width))
    y = min(.998, max(0, (rect.y0 - padding) / height))
    w = min(1 - x, max(.002, (rect.width + 2 * padding) / width))
    h = min(1 - y, max(.002, (rect.height + 2 * padding) / height))
    return {"x": round(x, 8), "y": round(y, 8), "width": round(w, 8), "height": round(h, 8)}


def match_position(position: str, layouts: list[tuple[int, dict]], vocabulary: set[str] | None = None) -> dict:
    locations = []
    ocr = False
    combined = False
    for number, page in layouts:
        for label in page["labels"]:
            members = label_members(label["text"])
            is_combined = bool(members and len(members) > 1)
            if members and position in members and (not is_combined or vocabulary is not None and set(members) <= vocabulary):
                locations.append({"page_number": number, "bbox": label["bbox"],
                    "raw_text": label["text"], "method": page["method"], "combined": is_combined,
                    **normalized_geometry(label["bbox"], page)})
                ocr |= page["ocr_used"]
                combined |= is_combined
    match = "NOT_FOUND" if not locations else "MULTIPLE_CANDIDATES" if len(locations) > 1 else "LOW_CONFIDENCE" if ocr or combined else "EXACT"
    return {"match": match, "locations": locations, "ocr_used": ocr, "combined": combined}
