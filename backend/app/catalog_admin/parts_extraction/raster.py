"""Bounded image composition, physical ruled bands and exact PDF transforms.

Pillow is already a runtime dependency. Long-run detection uses its native
pixel conversion plus bounded byte scans; no OpenCV/NumPy runtime is needed.
"""

import re
import subprocess
from collections import defaultdict

import fitz
from PIL import Image, ImageFilter, ImageOps

from . import cell_ocr
from .schema import header_candidates, normalize_header
from .tables import parse_region
from .values import POSITION


def clusters(values, tolerance=3):
    groups = []
    for value in values:
        if not groups or value - groups[-1][-1] > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [round(sum(group) / len(group)) for group in groups]


def runs(image, minimum):
    width, height = image.size
    data = image.tobytes()
    pattern = re.compile(b"\xff{" + str(max(12, minimum)).encode() + b",}")
    found = []
    for y in range(height):
        for match in pattern.finditer(data[y * width:(y + 1) * width]):
            found.append((y, match.start(), match.end() - 1))
    return found


def grids(image):
    # A three-pixel closing tolerates small compression gaps in straight rules.
    ink = image.convert("L").point(lambda x: 255 if x < 180 else 0).filter(ImageFilter.MaxFilter(3))
    width, height = image.size
    horizontal = runs(ink, max(40, width // 5))
    groups = defaultdict(list)
    tolerance = max(4, width // 200)
    for y, left, right in horizontal:
        groups[(round(left / tolerance), round(right / tolerance))].append((y, left, right))
    results = []
    for group in sorted(groups.values(), key=len, reverse=True)[:80]:
        ys = clusters(sorted({line[0] for line in group}))
        if len(ys) < 3:
            continue
        left = round(sum(line[1] for line in group) / len(group))
        right = round(sum(line[2] for line in group) / len(group))
        vertical = runs(ink.crop((max(0, left - tolerance), ys[0], min(width, right + tolerance), ys[-1] + 1))
            .transpose(Image.Transpose.TRANSPOSE), max(40, int((ys[-1] - ys[0]) * .75)))
        xs = clusters(sorted({x for x, _, _ in vertical}))
        xs = [x + max(0, left - tolerance) for x in xs]
        xs = [x for x in xs if left - tolerance <= x <= right + tolerance]
        if not 4 <= len(xs) <= 13 or len(ys) > 2001:
            continue
        if any(b - a < 8 for a, b in zip(xs, xs[1:])) or any(b - a < 8 for a, b in zip(ys, ys[1:])):
            continue
        box = [xs[0], ys[0], xs[-1], ys[-1]]
        if any(abs(box[0] - old["bbox"][0]) < tolerance * 2 and abs(box[1] - old["bbox"][1]) < tolerance * 2
               for old in results):
            continue
        results.append({"xs": xs, "ys": ys, "bbox": box})
    return results


def images(page, config):
    remaining = config["ocr_max_pixels"]
    regions = page.get_image_info(xrefs=True)
    result = []
    for info in sorted(regions, key=lambda i: fitz.Rect(i["bbox"]).get_area(), reverse=True)[:8]:
        width, height, xref = info["width"], info["height"], info.get("xref")
        if not xref or width * height > remaining or width < 100 or height < 80:
            continue
        # Check dimensions BEFORE decoding a potentially compressed image bomb.
        base = fitz.Pixmap(page.parent, xref)
        if base.width * base.height > remaining:
            raise ValueError("OCR_PIXEL_LIMIT")
        mask = page.parent.extract_image(xref).get("smask")
        if mask:
            dimensions = [page.parent.xref_get_key(mask, key)[1] for key in ("Width", "Height")]
            if not all(v.isdigit() for v in dimensions) or int(dimensions[0]) * int(dimensions[1]) > config["ocr_max_pixels"]:
                raise ValueError("OCR_PIXEL_LIMIT")
            alpha = fitz.Pixmap(page.parent, mask)
            if alpha.width != base.width or alpha.height != base.height:
                continue
            base = fitz.Pixmap(base, alpha)
        if base.colorspace and base.colorspace.n != 3:
            base = fitz.Pixmap(fitz.csRGB, base)
        mode = "RGBA" if base.alpha else "RGB"
        image = Image.frombytes(mode, (base.width, base.height), base.samples)
        if base.alpha:
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(image)
            image = background.convert("RGB")
        transform = fitz.Matrix(1 / width, 0, 0, 1 / height, 0, 0) * fitz.Matrix(info["transform"])
        remaining -= width * height
        result.append((image, transform, {"kind": "EMBEDDED_IMAGE", "xref": xref, "mask": bool(mask),
            "original_pixels": [width, height], "pixel_to_pdf": list(transform),
            "placement_bbox": list(info["bbox"])}))
    if not result:
        area = page.rect.width * page.rect.height
        scale = min(300 / 72, (config["ocr_max_pixels"] / max(1, area)) ** .5)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        transform = fitz.Matrix(1 / scale, 0, 0, 1 / scale, 0, 0) * page.derotation_matrix
        result.append((image, transform, {"kind": "PAGE_RENDER", "original_pixels": list(image.size),
            "pixel_to_pdf": list(transform), "mask": "RENDERER_COMPOSITION"}))
    return result


def crop_cells(image, xs, top, bottom):
    crops, boxes = [], []
    for left, right in zip(xs, xs[1:]):
        inset = max(3, min(6, (bottom - top) // 12))
        box = [left + inset, top + inset, right - inset, bottom - inset]
        crops.append(ImageOps.expand(image.crop(box), border=20, fill="white"))
        boxes.append(box)
    return crops, boxes


def orientation(image, transform, deadline):
    from .raster_geometry import locate
    choices = locate(image, transform, grids)
    if not choices:
        return None
    header_images, keys = [], []
    for option, (oriented, _, _, found) in enumerate(choices):
        for index, grid in enumerate(found[:8]):
            crops, _ = crop_cells(oriented, grid["xs"], *grid["ys"][:2])
            header_images.extend(crops)
            keys.extend([(option, index)] * len(crops))
    if not header_images or len(header_images) > cell_ocr.MAX_CELLS:
        raise ValueError("OCR_CELL_LIMIT")
    best = None
    # Technical identifiers are always English. A different header/description
    # model is tried only when English does not establish local BOM semantics.
    for language in ("eng", "deu", "bul", "rus"):
        try:
            readings = cell_ocr.recognize(header_images, language=language, deadline=deadline)
        except RuntimeError:
            continue
        grouped = defaultdict(list)
        for key, reading in zip(keys, readings, strict=True):
            grouped[key].append(reading)
        for option, choice in enumerate(choices):
            score = sum(bool(header_candidates(cell["text"])) for (which, _), cells in grouped.items()
                        if which == option for cell in cells)
            if best is None or score > best[0]:
                best = (score, choice, {index: cells for (which, index), cells in grouped.items() if which == option}, language)
        if best and best[0] >= 3:
            break
    return best[1:] if best else None


def description_model(headers, read_model):
    # An English model can read German headings well; that does not make the
    # original descriptions English. Identifier recognition stays English.
    tokens = {normalize_header(cell["text"]) for cell in headers}
    hints = {
        "deu": {"benennung", "beschreibung", "bezeichnung", "menge", "anzahl", "teile nr", "teil nr"},
        "bul": {"номер част", "кат номер", "бр", "забележка", "забележки", "номенклатурен номер"},
        "rus": {"номер детали", "название", "обозначение", "кол во", "примечание", "примечания"},
    }
    matched = [language for language, values in hints.items() if tokens & values]
    return matched[0] if len(matched) == 1 else read_model


def extract(page, config, *, deadline=None):
    all_rows, tables = [], []
    try:
        for rows, table in regions(page, config, deadline=deadline):
            all_rows.extend(rows)
            tables.append(table)
    except (ValueError, RuntimeError, OSError, TimeoutError, subprocess.SubprocessError) as exc:
        if not tables:
            raise
        code = str(exc)
        warning = code if code in {"OCR_CELL_LIMIT", "OCR_PIXEL_LIMIT", "OCR_TIME_BUDGET", "PAGE_WORD_LIMIT"} else "CELL_OCR_UNAVAILABLE"
        for table in tables:
            table["incomplete_regions"] = True
            table.setdefault("strategy_warnings", []).append(warning)
    return all_rows, tables


def regions(page, config, *, deadline=None):
    used, words_used = 0, 0
    for original, original_transform, evidence in images(page, config):
        selected = orientation(original, original_transform, deadline)
        if not selected:
            continue
        (image, transform, angle, found), headers, header_language = selected
        for index, grid in enumerate(found[:8]):
            xs, ys = grid["xs"], grid["ys"]
            columns = len(xs) - 1
            count = columns * (len(ys) - 1)
            if used + count > cell_ocr.MAX_CELLS:
                raise ValueError("OCR_CELL_LIMIT")
            used += count
            crops, cell_boxes = [], []
            for top, bottom in zip(ys[1:], ys[2:]):
                images_, boxes_ = crop_cells(image, xs, top, bottom)
                crops.extend(images_)
                cell_boxes.extend(boxes_)
            recognized = cell_ocr.adaptive(crops, deadline=deadline)
            description_language = description_model(headers[index], header_language)
            if description_language != "eng":
                description_cols = [col for col, cell in enumerate(headers[index])
                                    if "description" in header_candidates(cell["text"])]
                desc_indices = [i for i in range(len(crops)) if i % columns in description_cols]
                if desc_indices:
                    descriptions = cell_ocr.adaptive([crops[i] for i in desc_indices],
                        deadline=deadline, language=description_language)
                    for i, reading in zip(desc_indices, descriptions, strict=True):
                        recognized[i] = reading
            _, header_boxes = crop_cells(image, xs, *ys[:2])
            recognized = [{**cell, "language": header_language, "psm": 7, "alternatives": []}
                          for cell in headers[index]] + recognized
            words_used += sum(len(reading["words"]) for cell in recognized for reading in [cell, *cell.get("alternatives", [])])
            if words_used > config["max_words"]:
                raise ValueError("PAGE_WORD_LIMIT")
            cell_boxes = header_boxes + cell_boxes
            cells = [[cell["text"] for cell in recognized[i:i + columns]] for i in range(0, len(recognized), columns)]
            boxes = [list(fitz.Rect(xs[0], top, xs[-1], bottom) * transform) for top, bottom in zip(ys, ys[1:])]
            headerless = (any(POSITION.fullmatch(v) for v in cells[0])
                and sum(bool(header_candidates(v)) for v in cells[0]) < 2)
            rows, table = parse_region([""] * columns if headerless else cells[0], cells if headerless else cells[1:],
                boxes if headerless else boxes[1:], list(fitz.Rect(grid["bbox"]) * transform), "IMAGE_CELL_OCR")
            if headerless:
                rows = []
                table["schema"].update({"state": "NEEDS_REVIEW", "mapping": {}, "warnings": ["CONTINUATION_UNRESOLVED"]})
            for cell, pixel_box in zip(recognized, cell_boxes, strict=True):
                cell["bbox"] = list(fitz.Rect(pixel_box) * transform)
                cell["crop_bbox_pixels"], cell["crop_padding"] = pixel_box, 20
                for word in cell["words"]:
                    x, y, w, h = word["bbox"]
                    word["pdf_bbox"] = list(fitz.Rect(pixel_box[0] + x - 20, pixel_box[1] + y - 20,
                        pixel_box[0] + x + w - 20, pixel_box[1] + y + h - 20) * transform)
            table.update({"raster": {**evidence, "pixel_to_pdf": list(transform), "orientation_degrees": angle},
                "grid": grid, "page_width": page.cropbox.width,
                "geometry": {"state": "RESOLVED", "warnings": [],
                    "normalized_boundaries": [x / image.width for x in xs]},
                "cell_evidence": recognized,
                "ocr_profile": {"engine": "TESSERACT_CLI", "identifier_language": "eng",
                    "description_language": description_language, "psm": "ADAPTIVE_LINE_OR_BLOCK", "oem": 1}})
            for row in rows:
                row["warnings"].append("OCR_REQUIRES_REVIEW")
                offset = row["source_row_index"] + (0 if headerless else 1)
                evidence_cells = recognized[offset * columns:(offset + 1) * columns]
                row["cell_evidence"] = evidence_cells
                if any(cell["alternatives"] and any(alt["text"] != cell["text"] for alt in cell["alternatives"])
                       for cell in evidence_cells):
                    row["warnings"].append("OCR_READ_DISAGREEMENT")
                row["confidence"] = min(row["confidence"], .7)
            yield rows, table
