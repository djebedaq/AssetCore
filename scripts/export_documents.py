"""Export immutable generated documents to a ZIP with a SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.models import GeneratedDocument, OfficialDocument, OfficialDocumentVersion  # noqa: E402
from sqlalchemy import select  # noqa: E402


def _safe(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:160] or "document"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.suffix.casefold() != ".zip":
        raise SystemExit("The export target must use a .zip extension.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "format": "assetcore-document-export-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "files": [],
    }
    with SessionLocal() as db, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for item in db.scalars(select(GeneratedDocument).order_by(GeneratedDocument.id)):
            name = f"generated/{item.id}-{_safe(item.filename)}"
            archive.writestr(name, item.content)
            manifest["files"].append(
                {"path": name, "sha256": hashlib.sha256(item.content).hexdigest(), "record": "generated_document", "id": item.id}
            )
        documents = {item.id: item for item in db.scalars(select(OfficialDocument))}
        for version in db.scalars(select(OfficialDocumentVersion).order_by(OfficialDocumentVersion.document_id, OfficialDocumentVersion.version)):
            document = documents.get(version.document_id)
            if document is None:
                continue
            stem = f"official/{_safe(document.document_number)}-v{version.version}"
            for suffix, content in (("docx", version.docx_content), ("pdf", version.pdf_content)):
                if content is None:
                    continue
                name = f"{stem}.{suffix}"
                archive.writestr(name, content)
                manifest["files"].append(
                    {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "record": "official_document_version", "id": version.id}
                )
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2),
        )
    print(f"Exported {len(manifest['files'])} immutable document files to {output.name}.")


if __name__ == "__main__":
    main()
