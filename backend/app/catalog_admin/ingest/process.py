"""Fixed, timeout-bound process execution with cleaned, private temporary files."""

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore

from ...settings import settings
from ..service import fail

SLOTS = BoundedSemaphore(settings.catalog_ingest_max_processes)

def extract(content: bytes, operation: str, number: int, config: dict) -> dict:
    if not SLOTS.acquire(blocking=False):
        raise fail("catalog_ingest_busy")
    try:
        return _extract(content, operation, number, config)
    finally:
        SLOTS.release()


def _extract(content: bytes, operation: str, number: int, config: dict) -> dict:
    with TemporaryDirectory(prefix="assetcore-ingest-") as folder:
        source = Path(folder) / "source.pdf"
        output = Path(folder) / "evidence.json"
        source.write_bytes(content)
        # The parser does not need application/database/licence credentials.
        public_runtime = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
                          "LANG", "LC_ALL", "TESSDATA_PREFIX", "LD_LIBRARY_PATH", "PYTHONUTF8"}
        env = {key: value for key, value in os.environ.items() if key.upper() in public_runtime}
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
        try:
            completed = subprocess.Popen([sys.executable, "-m", "app.catalog_admin.ingest.worker",
                str(source), str(output), operation, str(number), json.dumps(config)],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            lease = None
            try:
                if sys.platform == "win32":
                    from .windows_limits import attach
                    lease = attach(completed)
                completed.wait(timeout=config["timeout"])
            except BaseException:
                completed.kill()
                completed.wait()
                raise
            finally:
                if lease:
                    lease.close()
            if completed.returncode != 0 or not output.is_file() or output.stat().st_size > 16 * 1024 * 1024:
                raise fail("catalog_ingest_resource_limit", 422)
            return json.loads(output.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired:
            raise fail("catalog_ingest_timeout", 422) from None
        except (OSError, RuntimeError):
            raise fail("catalog_ingest_resource_limit", 422) from None


def configuration(settings) -> dict:
    return {"timeout": settings.catalog_ingest_page_timeout_seconds,
        "max_pages": settings.catalog_pdf_max_pages, "max_words": settings.catalog_ingest_max_words,
        "ocr_enabled": settings.catalog_ocr_enabled, "ocr_languages": settings.catalog_ocr_languages,
        "ocr_dpi": settings.catalog_ocr_dpi, "ocr_max_pixels": settings.catalog_ocr_max_pixels}
