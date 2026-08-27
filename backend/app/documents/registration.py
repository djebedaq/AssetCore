"""Existing canonical numbering and version registration; callers own transactions."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DocumentTemplateVersion,
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    User,
    utcnow,
)
from ..official_documents.integrity import (
    set_current_version,
)
from ..template_engine import TemplateValidationError
from .common import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    _language,
    safe_filename,
)
from .templates import (
    _preparer_values,
)


def _next_generated_number(db: Session, base: str) -> str:
    existing = db.scalars(
        select(GeneratedDocument.document_number)
        .where(GeneratedDocument.document_number.like(f"{base}%"))
        .distinct()
    ).all()
    if base not in existing:
        return base
    version = 2
    while f"{base}-V{version}" in existing:
        version += 1
    return f"{base}-V{version}"


def _generated_documents(
    *,
    number: str,
    document_type: str,
    language: str,
    template_version: DocumentTemplateVersion | None,
    docx: bytes,
    pdf: bytes,
    snapshot: dict,
    created_by_id: int,
    machine_id: int | None = None,
    repair_id: int | None = None,
    part_request_id: int | None = None,
    transfer_id: int | None = None,
    batch_id: int | None = None,
) -> list[GeneratedDocument]:
    documents = []
    stem = safe_filename(number)
    for format_name, media_type, content in (
        ("docx", DOCX_MEDIA_TYPE, docx),
        ("pdf", PDF_MEDIA_TYPE, pdf),
    ):
        documents.append(
            GeneratedDocument(
                document_number=number,
                document_type=document_type,
                format=format_name,
                language=_language(language),
                filename=f"{stem}.{format_name}",
                media_type=media_type,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                template_version_id=template_version.id if template_version else None,
                machine_id=machine_id,
                repair_id=repair_id,
                part_request_id=part_request_id,
                transfer_id=transfer_id,
                batch_id=batch_id,
                snapshot=snapshot,
                created_by_id=created_by_id,
            )
        )
    return documents


def _register_official_version(
    db: Session,
    *,
    number: str,
    document_type: str,
    language: str,
    docx: bytes,
    pdf: bytes,
    snapshot: dict,
    created_by_id: int,
    machine_id: int | None = None,
    transfer_id: int | None = None,
    batch_id: int | None = None,
    template_version_id: int | None = None,
    initial_status: str = OfficialDocumentStatus.DRAFT.value,
) -> OfficialDocument:
    existing = db.scalar(
        select(OfficialDocument).where(OfficialDocument.document_number == number)
    )
    if existing is not None:
        raise TemplateValidationError(
            f"Официален документ с номер {number} вече съществува и няма да бъде презаписан."
        )
    preparer = db.get(User, created_by_id)
    preparer_values = _preparer_values(db, created_by_id)
    official_snapshot = dict(snapshot)
    official_snapshot["prepared_by"] = {
        "user_id": preparer.id,
        "first_name": preparer.first_name,
        "middle_name": preparer.middle_name,
        "last_name": preparer.last_name,
        "display_name": preparer_values["PREPARER_NAME"],
        "job_title": preparer_values["PREPARER_JOB_TITLE"],
        "department_id": preparer.department_id,
        "department": preparer.profile_department.name_bg if preparer.profile_department else None,
        "operation_role": "PREPARER",
        "captured_at": utcnow().isoformat(timespec="seconds") + "Z",
    }
    document = OfficialDocument(
        document_number=number,
        document_type=document_type,
        machine_id=machine_id,
        transfer_id=transfer_id,
        batch_id=batch_id,
        created_by_id=created_by_id,
    )
    db.add(document)
    db.flush()
    snapshot_sha256 = hashlib.sha256(
        json.dumps(
            official_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    docx_sha256 = hashlib.sha256(docx).hexdigest()
    pdf_sha256 = hashlib.sha256(pdf).hexdigest()
    signing_sha256 = hashlib.sha256(
        json.dumps(
            {
                "document_number": number,
                "document_type": document_type,
                "snapshot_sha256": snapshot_sha256,
                "docx_sha256": docx_sha256,
                "pdf_sha256": pdf_sha256,
                "version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status=initial_status,
        language=_language(language),
        template_version_id=template_version_id,
        snapshot=official_snapshot,
        snapshot_sha256=snapshot_sha256,
        signing_sha256=signing_sha256,
        docx_content=docx,
        docx_sha256=docx_sha256,
        pdf_content=pdf,
        pdf_sha256=pdf_sha256,
        prepared_by_id=created_by_id,
        finalized_at=(
            utcnow()
            if initial_status == OfficialDocumentStatus.FINALIZED.value
            else None
        ),
    )
    db.add(version)
    db.flush()
    set_current_version(db, document, version)
    return document
