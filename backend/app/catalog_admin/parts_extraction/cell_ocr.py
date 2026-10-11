"""One bounded, offline Tesseract CLI process for a batch of private cells.

The parent worker owns the process group / Windows job. No shell, network,
application configuration, arbitrary CLI arguments or user-supplied paths.
"""

import csv
import os
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import ImageOps

from .ocr import language_folder

MAX_CELLS = 512
MAX_OUTPUT = 4 * 1024 * 1024


def recognize(images, *, psm=7, language="eng", deadline=None):
    if not images or len(images) > MAX_CELLS or psm not in {6, 7, 11}:
        raise ValueError("OCR_CELL_LIMIT")
    if language not in {"eng", "deu", "bul", "rus"}:
        raise ValueError("OCR_PROFILE_INVALID")
    executable = shutil.which("tesseract")
    folder = language_folder()
    if not executable or not (folder / f"{language}.traineddata").is_file():
        raise RuntimeError("OCR_UNAVAILABLE")
    remaining = min(35, (deadline - time.monotonic()) if deadline else 35)
    if remaining <= 0:
        raise TimeoutError("OCR_TIME_BUDGET")
    with TemporaryDirectory(prefix="assetcore-cells-") as temporary:
        root = Path(temporary)
        names = []
        for index, image in enumerate(images):
            name = root / f"cell-{index:04d}.png"
            image.save(name)
            names.append(str(name))
        listing, output = root / "images.txt", root / "result"
        listing.write_text("\n".join(names) + "\n", encoding="utf-8")
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}}
        env["OMP_THREAD_LIMIT"] = "1"
        subprocess.run([executable, str(listing), str(output), "--tessdata-dir", str(folder),
            "-l", language, "--oem", "1", "--psm", str(psm), "-c", "tessedit_create_tsv=1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env, timeout=remaining, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        target = output.with_suffix(".tsv")
        if not target.is_file() or target.stat().st_size > MAX_OUTPUT:
            raise ValueError("OCR_OUTPUT_LIMIT")
        result = [{"text": "", "words": [], "confidence": None} for _ in images]
        with target.open(encoding="utf-8") as stream:
            for word in csv.DictReader(stream, delimiter="\t"):
                if word.get("level") != "5" or not word.get("text", "").strip():
                    continue
                index = int(word["page_num"]) - 1
                if not 0 <= index < len(result):
                    raise ValueError("OCR_PAGE_ALIGNMENT")
                record = {"text": word["text"], "confidence": float(word["conf"]),
                    "bbox": [int(word[k]) for k in ("left", "top", "width", "height")]}
                result[index]["words"].append(record)
        for item in result:
            item["text"] = " ".join(word["text"] for word in item["words"])
            if item["words"]:
                item["confidence"] = min(word["confidence"] for word in item["words"])
        return result


def line_mode(image):
    ink = image.convert("L").point(lambda p: 255 if p < 160 else 0)
    width, height = ink.size
    data = ink.tobytes()
    bands = []
    for y in range(height):
        if data[y * width:(y + 1) * width].count(255) < max(2, width // 150):
            continue
        if not bands or y - bands[-1][-1] > 4:
            bands.append([y])
        else:
            bands[-1].append(y)
    substantial = [band for band in bands if len(band) > 5]
    return 6 if len(substantial) > 1 else 7


def adaptive(images, *, deadline=None, language="eng"):
    if len(images) > MAX_CELLS:
        raise ValueError("OCR_CELL_LIMIT")
    groups = defaultdict(list)
    result = [None] * len(images)
    for index, image in enumerate(images):
        groups[line_mode(image)].append(index)
    for psm, indices in groups.items():
        batch = recognize([images[i] for i in indices], psm=psm, language=language, deadline=deadline)
        for i, item in zip(indices, batch, strict=True):
            result[i] = {**item, "psm": psm, "language": language, "alternatives": []}
    suspicious = [i for i, item in enumerate(result) if not item["text"] or (item["confidence"] or 0) < 45][:24]
    if suspicious and (deadline is None or deadline - time.monotonic() > 3):
        # One selective second reading, never character substitution or a PN
        # whitelist. Conflicting readings stay evidence requiring human review.
        retry = recognize([ImageOps.autocontrast(images[i].convert("L")) for i in suspicious],
            psm=6, language=language, deadline=deadline)
        for i, alternative in zip(suspicious, retry, strict=True):
            result[i]["alternatives"].append({**alternative, "psm": 6, "preprocess": "AUTOCONTRAST"})
            if not result[i]["text"] and alternative["text"]:
                result[i]["text"] = alternative["text"]
    return result
