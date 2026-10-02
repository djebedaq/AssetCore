"""Disposable process boundary for native PDF parsing and local OCR.

Only generated paths and fixed arguments are used. Never prints native error text.
"""

import base64
import json
import sys
from pathlib import Path

import fitz

from .extraction import extract_page


def main() -> None:
    source, output, operation, page_number, config_text = sys.argv[1:]
    config = json.loads(config_text)
    try:
        # Unix deployments enforce address-space and CPU bounds in addition to
        # the parent wall-clock timeout. Windows uses the same killable boundary.
        if sys.platform != "win32":
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
            resource.setrlimit(resource.RLIMIT_CPU, (config["timeout"], config["timeout"] + 1))
            resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
        with fitz.open(source) as pdf:
            if operation == "validate":
                if pdf.needs_pass or pdf.is_encrypted:
                    result = {"error": "catalog_source_encrypted"}
                elif pdf.page_count > config["max_pages"]:
                    result = {"error": "catalog_source_page_limit"}
                elif pdf.is_repaired or pdf.page_count < 1:
                    result = {"error": "catalog_source_invalid_pdf"}
                else:
                    result = {"page_count": pdf.page_count}
            elif operation in {"preview", "thumbnail"}:
                if not 1 <= int(page_number) <= pdf.page_count:
                    raise ValueError("invalid page")
                page = pdf[int(page_number) - 1]
                if not 0 < page.rect.width <= 14400 or not 0 < page.rect.height <= 14400:
                    raise ValueError("invalid page")
                pixels = 160_000 if operation == "thumbnail" else 4_000_000
                scale = min(1.0, (pixels / max(1, page.rect.width * page.rect.height)) ** .5)
                png = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False,
                                     colorspace=fitz.csRGB).tobytes("png")
                result = {"image": base64.b64encode(png).decode("ascii")}
            else:
                if operation != "page" or not 1 <= int(page_number) <= pdf.page_count:
                    raise ValueError("invalid page")
                page = pdf[int(page_number) - 1]
                if not 0 < page.rect.width <= 14400 or not 0 < page.rect.height <= 14400:
                    raise ValueError("invalid page")
                result = extract_page(page, config)
    except Exception:
        result = {"error": "catalog_extraction_page_failed" if operation == "page" else "catalog_source_invalid_pdf"}
    Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
