from __future__ import annotations

import hashlib

import pytest
from app.models import (
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    User,
)
from app.official_documents.integrity import (
    OfficialDocumentIntegrityError,
    require_current_version,
    set_current_version,
    validate_official_document_integrity,
)
from sqlalchemy import select


def _document_with_version(session, *, actor_id: int, number: str):
    document = OfficialDocument(
        document_number=number,
        document_type="PART_REQUEST",
        created_by_id=actor_id,
    )
    session.add(document)
    session.flush()
    content = f"canonical:{number}".encode()
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status=OfficialDocumentStatus.FINALIZED.value,
        language="bg",
        snapshot={"test_scope": "official-document-integrity"},
        snapshot_sha256=hashlib.sha256(number.encode()).hexdigest(),
        signing_sha256=hashlib.sha256(content).hexdigest(),
        docx_content=content,
        docx_sha256=hashlib.sha256(content).hexdigest(),
        prepared_by_id=actor_id,
    )
    session.add(version)
    session.flush()
    return document, version


def test_valid_current_version_passes_application_and_schema_integrity(
    session_factory,
):
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        document, version = _document_with_version(
            session,
            actor_id=actor.id,
            number="TEST-INTEGRITY-VALID",
        )
        set_current_version(session, document, version)
        session.commit()

    with session_factory() as session:
        document = session.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == "TEST-INTEGRITY-VALID"
            )
        )
        assert require_current_version(session, document).document_id == document.id
        report = validate_official_document_integrity(session)
        assert report["valid"] is True
        assert report["blocking_count"] == 0
        assert report["tolerated_history_count"] == 0
        assert report["schema"]["composite_foreign_key"] is True


def test_current_version_from_another_document_is_rejected(session_factory):
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        first, first_version = _document_with_version(
            session,
            actor_id=actor.id,
            number="TEST-INTEGRITY-OWNER-A",
        )
        second, second_version = _document_with_version(
            session,
            actor_id=actor.id,
            number="TEST-INTEGRITY-OWNER-B",
        )
        set_current_version(session, first, first_version)
        set_current_version(session, second, second_version)
        with pytest.raises(
            OfficialDocumentIntegrityError,
            match="принадлежи на друг официален документ",
        ) as caught:
            set_current_version(session, second, first_version)
        assert caught.value.code == "official_document_version_wrong_owner"


def test_missing_current_version_is_rejected_by_application_guard(session_factory):
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        document, _ = _document_with_version(
            session,
            actor_id=actor.id,
            number="TEST-INTEGRITY-MISSING",
        )
        with pytest.raises(OfficialDocumentIntegrityError) as caught:
            set_current_version(session, document, 999_999_999)
        assert caught.value.code == "official_document_version_missing"
