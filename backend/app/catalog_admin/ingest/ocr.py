"""Offline OCR with explicit runtime/language-pack detection."""

import os
import re
import shutil
import subprocess
from pathlib import Path


def language_folder() -> Path:
    configured = os.environ.get("TESSDATA_PREFIX")
    if configured:
        return Path(configured)
    executable = shutil.which("tesseract")
    if not executable:
        raise RuntimeError("OCR unavailable")
    local = Path(executable).parent / "tessdata"
    if local.is_dir():
        return local
    result = subprocess.run([executable, "--list-langs"], capture_output=True, text=True,
                            timeout=5, check=True)
    match = re.search(r'List of available languages in "(.+)"', result.stdout)
    if not match:
        raise RuntimeError("OCR unavailable")
    return Path(match.group(1))


def textpage(page, config):
    languages = config["ocr_languages"].split("+")
    if not languages or any(not re.fullmatch(r"[a-z0-9_]{2,20}", language) for language in languages):
        raise RuntimeError("OCR languages unavailable")
    folder = language_folder()
    if any(not (folder / f"{language}.traineddata").is_file() for language in languages):
        raise RuntimeError("OCR languages unavailable")
    return page.get_textpage_ocr(language=config["ocr_languages"], dpi=config["ocr_dpi"],
                               full=config["ocr_full"], tessdata=str(folder))
