"""Shared attachment byte validation and metadata, without domain workflow logic."""

from __future__ import annotations

import base64
import binascii
import io
import zipfile
from pathlib import Path

from fastapi import HTTPException

from .industrial_schemas import AttachmentCreate, TechnicalDocumentUpload, TemplateVersionCreate
from .models import MachineAttachment, PartRequestAttachment, RepairAttachment

MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _decode_file(
    payload: AttachmentCreate | TechnicalDocumentUpload | TemplateVersionCreate,
) -> tuple[str, bytes]:
    filename = Path(payload.filename).name
    if filename != payload.filename or filename in {"", ".", ".."}:
        raise HTTPException(
            status_code=422,
            detail={"code": "unsafe_filename", "message": "Името на файла не е допустимо."},
        )
    if payload.media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_media_type",
                "message": "Файловият формат не се поддържа.",
            },
        )
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_file_content", "message": "Файлът не е валидно кодиран."},
        ) from exc
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_file_size",
                "message": "Файлът трябва да бъде с размер до 12 MB.",
            },
        )
    suffix = Path(filename).suffix.lower()
    signatures_valid = {
        "application/pdf": suffix == ".pdf" and content.startswith(b"%PDF-"),
        "image/png": suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": suffix in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"),
        "image/webp": suffix == ".webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
    }
    office_roots = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
            ".docx",
            "word/document.xml",
        ),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (
            ".xlsx",
            "xl/workbook.xml",
        ),
    }
    if payload.media_type in office_roots:
        expected_suffix, required_member = office_roots[payload.media_type]
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                names = set(package.namelist())
            valid_signature = suffix == expected_suffix and {
                "[Content_Types].xml",
                required_member,
            }.issubset(names)
        except zipfile.BadZipFile:
            valid_signature = False
    else:
        valid_signature = signatures_valid.get(payload.media_type, False)
    if not valid_signature:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "file_signature_mismatch",
                "message": "Съдържанието на файла не съответства на заявения формат.",
            },
        )
    return filename, content


def _attachment_dict(
    item: MachineAttachment | RepairAttachment | PartRequestAttachment, kind: str
) -> dict:
    return {
        "id": item.id,
        "filename": item.filename,
        "media_type": item.media_type,
        "sha256": item.sha256,
        "created_at": item.created_at,
        "description": getattr(item, "description", None),
        "kind": getattr(item, "kind", None),
        "caption": getattr(item, "caption", None),
        "stage": getattr(item, "stage", None),
        "request_line_id": getattr(item, "request_line_id", None),
        "download_endpoint": f"/{kind}-attachments/{item.id}/download",
    }
