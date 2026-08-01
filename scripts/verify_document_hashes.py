"""Verify stored hashes for generated and official document versions."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models import GeneratedDocument, OfficialDocumentVersion  # noqa: E402
from sqlalchemy import select  # noqa: E402


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def main() -> None:
    failures: list[str] = []
    checked = 0
    with SessionLocal() as db:
        for item in db.scalars(select(GeneratedDocument).order_by(GeneratedDocument.id)):
            checked += 1
            if hashlib.sha256(item.content).hexdigest() != item.sha256:
                failures.append(f"generated_document:{item.id}")
        for item in db.scalars(select(OfficialDocumentVersion).order_by(OfficialDocumentVersion.id)):
            checked += 1
            if hashlib.sha256(_canonical(item.snapshot)).hexdigest() != item.snapshot_sha256:
                failures.append(f"official_snapshot:{item.id}")
            if item.docx_content is not None and hashlib.sha256(item.docx_content).hexdigest() != item.docx_sha256:
                failures.append(f"official_docx:{item.id}")
            if item.pdf_content is not None and hashlib.sha256(item.pdf_content).hexdigest() != item.pdf_sha256:
                failures.append(f"official_pdf:{item.id}")
    if failures:
        print("Hash verification failed for: " + ", ".join(failures))
        raise SystemExit(1)
    print(f"Verified hashes for {checked} document records.")


if __name__ == "__main__":
    main()
