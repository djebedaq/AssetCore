from __future__ import annotations

import hashlib
from datetime import datetime

from app.models import (
    AuditLog,
    DocumentParticipant,
    DocumentSignature,
    DocumentType,
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    Repair,
    TransferBatch,
    TransferProtocol,
    User,
)
from sqlalchemy import func, select


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _add_official_document(
    session,
    *,
    number: str,
    document_type: str,
    actor_id: int,
    created_at: datetime,
    machine_id: int | None = None,
    transfer_id: int | None = None,
    snapshot: dict | None = None,
    status: str = "DRAFT",
    signed_slots: tuple[str, ...] = (),
) -> OfficialDocument:
    document = OfficialDocument(
        document_number=number,
        document_type=document_type,
        machine_id=machine_id,
        transfer_id=transfer_id,
        created_by_id=actor_id,
        created_at=created_at,
    )
    session.add(document)
    session.flush()
    docx = f"docx:{number}".encode()
    pdf = f"pdf:{number}".encode()
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status=status,
        language="bg",
        snapshot=snapshot or {},
        snapshot_sha256=_sha(repr(snapshot or {}).encode()),
        signing_sha256=_sha(f"signing:{number}".encode()),
        docx_content=docx,
        docx_sha256=_sha(docx),
        pdf_content=pdf,
        pdf_sha256=_sha(pdf),
        prepared_by_id=actor_id,
        created_at=created_at,
        finalized_at=created_at if status in {"SIGNED", "FINALIZED"} else None,
    )
    session.add(version)
    session.flush()
    document.current_version_id = version.id
    for index, slot_code in enumerate(signed_slots, start=1):
        participant = DocumentParticipant(
            document_version_id=version.id,
            slot_code=slot_code,
            participant_kind="INTERNAL",
            user_id=actor_id,
            external_signer_id=None,
            operation_role=slot_code,
            identity_snapshot={"user_id": actor_id, "slot": slot_code},
            identity_snapshot_sha256=_sha(f"participant:{number}:{slot_code}".encode()),
        )
        session.add(participant)
        session.flush()
        session.add(
            DocumentSignature(
                participant_id=participant.id,
                document_version_id=version.id,
                consent_text="Тестово потвърждение",
                strokes_encrypted=b"encrypted-strokes",
                image_encrypted=b"encrypted-image",
                canvas_width=320,
                canvas_height=120,
                stroke_count=1,
                point_count=8,
                document_sha256=version.signing_sha256,
                image_sha256=_sha(f"image:{number}:{index}".encode()),
                signature_sha256=_sha(f"signature:{number}:{index}".encode()),
                signed_at=created_at,
                confirmed_at=created_at,
            )
        )
    return document


def _add_legacy_generated_pair(
    session,
    *,
    number: str,
    document_type: str,
    actor_id: int,
    created_at: datetime,
    machine_id: int | None = None,
    repair_id: int | None = None,
    part_request_id: int | None = None,
    transfer_id: int | None = None,
) -> None:
    for file_format in ("docx", "pdf"):
        content = f"legacy:{number}:{file_format}".encode()
        session.add(
            GeneratedDocument(
                document_number=number,
                document_type=document_type,
                format=file_format,
                language="bg",
                filename=f"{number}.{file_format}",
                media_type=(
                    "application/pdf"
                    if file_format == "pdf"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content=content,
                sha256=_sha(content),
                machine_id=machine_id,
                repair_id=repair_id,
                part_request_id=part_request_id,
                transfer_id=transfer_id,
                snapshot={"historical": True},
                created_by_id=actor_id,
                created_at=created_at,
            )
        )


def _seed_registry_scenario(session_factory, machine_ids) -> dict[str, int]:
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        batch = TransferBatch(
            batch_reference="BATCH-REGISTRY-TEST",
            status="PARTIALLY_RETURNED",
            created_by_id=actor.id,
            created_at=datetime(2026, 8, 20, 8, 0),
        )
        session.add(batch)
        session.flush()
        incomplete_transfer = TransferProtocol(
            machine_id=machine_ids["9"],
            batch_id=batch.id,
            protocol_number="TR-REG-009",
            protocol_type="Предаване",
            is_active=True,
            issue_status="COMPLETED",
            issued_by_id=actor.id,
            issued_at=datetime(2026, 8, 20, 9, 0),
            created_at=datetime(2026, 8, 20, 8, 30),
        )
        completed_transfer = TransferProtocol(
            machine_id=machine_ids["10"],
            batch_id=batch.id,
            protocol_number="TR-REG-010",
            protocol_type="Предаване",
            is_active=False,
            issue_status="COMPLETED",
            return_status="COMPLETED",
            issued_by_id=actor.id,
            returned_by_id=actor.id,
            issued_at=datetime(2026, 8, 21, 9, 0),
            returned_at=datetime(2026, 8, 22, 11, 0),
            created_at=datetime(2026, 8, 21, 8, 30),
        )
        session.add_all([incomplete_transfer, completed_transfer])
        session.flush()

        issue_9 = _add_official_document(
            session,
            number="TR-REG-009",
            document_type=DocumentType.TRANSFER_ISSUE.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 20, 9, 0),
            machine_id=machine_ids["9"],
            transfer_id=incomplete_transfer.id,
            status="SIGNED",
            signed_slots=("ACCEPTANCE", "HANDOVER"),
        )
        _add_official_document(
            session,
            number="TR-REG-010",
            document_type=DocumentType.TRANSFER_ISSUE.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 21, 9, 0),
            machine_id=machine_ids["10"],
            transfer_id=completed_transfer.id,
            status="SIGNED",
            signed_slots=("ACCEPTANCE", "HANDOVER"),
        )
        return_10 = _add_official_document(
            session,
            number="TR-REG-010-R",
            document_type=DocumentType.TRANSFER_RETURN.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 22, 11, 0),
            machine_id=machine_ids["10"],
            transfer_id=completed_transfer.id,
            status="PARTIALLY_SIGNED",
            signed_slots=("RETURNED_BY",),
        )

        repair = Repair(
            machine_id=machine_ids["11"],
            repair_reference="REP-REG-011",
            reported_problem="Тестов регистров сценарий",
            status="COMPLETED",
            opened_at=datetime(2026, 8, 18, 8, 0),
            closed_at=datetime(2026, 8, 19, 16, 0),
        )
        legacy_repair = Repair(
            machine_id=machine_ids["12"],
            repair_reference="REP-LEGACY-012",
            reported_problem="Исторически тестов сценарий",
            status="COMPLETED",
            opened_at=datetime(2026, 7, 1, 8, 0),
            closed_at=datetime(2026, 7, 2, 16, 0),
        )
        session.add_all([repair, legacy_repair])
        session.flush()
        repair_document = _add_official_document(
            session,
            number="REP-REG-011",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 19, 16, 0),
            machine_id=machine_ids["11"],
            snapshot={"repair_id": repair.id},
            status="FINALIZED",
        )
        _add_legacy_generated_pair(
            session,
            number="REP-REG-011",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 19, 16, 0),
            machine_id=machine_ids["11"],
            repair_id=repair.id,
        )
        _add_legacy_generated_pair(
            session,
            number="REP-LEGACY-012",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            created_at=datetime(2026, 7, 2, 16, 0),
            machine_id=machine_ids["12"],
            repair_id=legacy_repair.id,
        )

        request = PartRequest(
            machine_id=machine_ids["13"],
            part_name="Тестов ред за регистъра",
            quantity=1,
            status="APPROVED",
            request_reference="PR-REG-013",
            requested_by_id=actor.id,
            created_at=datetime(2026, 8, 23, 9, 0),
        )
        legacy_request = PartRequest(
            machine_id=machine_ids["14"],
            part_name="Исторически тестов ред",
            quantity=1,
            status="DELIVERED",
            request_reference="PR-LEGACY-014",
            requested_by_id=actor.id,
            created_at=datetime(2026, 6, 1, 9, 0),
        )
        session.add_all([request, legacy_request])
        session.flush()
        part_document = _add_official_document(
            session,
            number="PR-REG-013",
            document_type=DocumentType.PART_REQUEST.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 23, 10, 0),
            machine_id=machine_ids["13"],
            snapshot={"request_id": request.id},
            status="DRAFT",
        )
        _add_legacy_generated_pair(
            session,
            number="PR-REG-013",
            document_type=DocumentType.PART_REQUEST.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 23, 10, 0),
            machine_id=machine_ids["13"],
            part_request_id=request.id,
        )
        _add_legacy_generated_pair(
            session,
            number="PR-LEGACY-014",
            document_type=DocumentType.PART_REQUEST.value,
            actor_id=actor.id,
            created_at=datetime(2026, 6, 1, 10, 0),
            machine_id=machine_ids["14"],
            part_request_id=legacy_request.id,
        )

        orphan = OfficialDocument(
            document_number="ORPHAN-REGISTRY-ROW",
            document_type=DocumentType.PART_REQUEST.value,
            machine_id=machine_ids["15"],
            created_by_id=actor.id,
            created_at=datetime(2026, 5, 1, 10, 0),
        )
        session.add(orphan)
        session.commit()
        return {
            "issue_9": issue_9.id,
            "return_10": return_10.id,
            "repair_document": repair_document.id,
            "part_document": part_document.id,
        }


def test_registry_groups_canonical_and_historical_documents_without_duplicates(
    client, auth_headers, session_factory, machine_ids
):
    _seed_registry_scenario(session_factory, machine_ids)

    response = client.get("/api/official-documents/registry", headers=auth_headers)
    assert response.status_code == 200, response.text
    registry = response.json()
    assert registry["transfers"]["count"] == 2
    assert registry["repairs"]["count"] == 2
    assert registry["parts"]["count"] == 2

    transfers = {
        item["machine_number"]: item for item in registry["transfers"]["items"]
    }
    incomplete = transfers["9"]
    assert incomplete["status"] == "INCOMPLETE"
    assert incomplete["created_at"] is None
    assert incomplete["signature_status"] == "SIGNED"
    assert [doc["document_type"] for doc in incomplete["documents"]] == [
        "TRANSFER_ISSUE"
    ]
    assert incomplete["documents"][0]["document_number"] == "TR-REG-009"

    completed = transfers["10"]
    assert completed["status"] == "COMPLETE"
    assert completed["created_at"].startswith("2026-08-22")
    assert completed["signature_status"] == "PARTIALLY_SIGNED"
    assert [doc["document_number"] for doc in completed["documents"]] == [
        "TR-REG-010",
        "TR-REG-010-R",
    ]

    repairs = registry["repairs"]["items"]
    assert [item["created_at"] for item in repairs] == sorted(
        [item["created_at"] for item in repairs], reverse=True
    )
    current_repair = next(item for item in repairs if item["machine_number"] == "11")
    assert current_repair["status"] == "COMPLETE"
    assert current_repair["signature_status"] == "NOT_REQUIRED"
    assert len(current_repair["documents"]) == 1
    assert current_repair["documents"][0]["official_document_id"] is not None
    historical_repair = next(
        item for item in repairs if item["machine_number"] == "12"
    )
    assert historical_repair["documents"][0]["official_document_id"] is None
    assert {
        file["format"] for file in historical_repair["documents"][0]["files"]
    } == {"docx", "pdf"}

    parts = registry["parts"]["items"]
    current_part = next(item for item in parts if item["machine_number"] == "13")
    assert current_part["status"] == "COMPLETE"
    assert current_part["signature_status"] == "UNSIGNED"
    assert len(current_part["documents"]) == 1
    assert current_part["documents"][0]["document_number"] == "PR-REG-013"
    assert sum(
        document["document_number"] == "PR-REG-013"
        for item in parts
        for document in item["documents"]
    ) == 1


def test_registry_and_preview_are_read_only_and_legacy_orphan_does_not_break_list(
    client, auth_headers, session_factory, machine_ids
):
    ids = _seed_registry_scenario(session_factory, machine_ids)
    with session_factory() as session:
        before = {
            "official_count": session.scalar(select(func.count(OfficialDocument.id))),
            "version_count": session.scalar(
                select(func.count(OfficialDocumentVersion.id))
            ),
            "audit_count": session.scalar(select(func.count(AuditLog.id))),
            "hash": session.get(
                OfficialDocumentVersion,
                session.get(OfficialDocument, ids["repair_document"]).current_version_id,
            ).pdf_sha256,
        }

    registry = client.get("/api/official-documents/registry", headers=auth_headers)
    assert registry.status_code == 200, registry.text
    legacy_list = client.get("/api/official-documents", headers=auth_headers)
    assert legacy_list.status_code == 200, legacy_list.text
    assert "ORPHAN-REGISTRY-ROW" not in {
        item["document_number"] for item in legacy_list.json()
    }
    preview = client.get(
        f"/api/official-documents/{ids['repair_document']}/preview/pdf",
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text

    with session_factory() as session:
        after = {
            "official_count": session.scalar(select(func.count(OfficialDocument.id))),
            "version_count": session.scalar(
                select(func.count(OfficialDocumentVersion.id))
            ),
            "audit_count": session.scalar(select(func.count(AuditLog.id))),
            "hash": session.get(
                OfficialDocumentVersion,
                session.get(OfficialDocument, ids["repair_document"]).current_version_id,
            ).pdf_sha256,
        }
    assert after == before


def test_registry_requires_document_view_permission(
    client, viewer_headers, session_factory, machine_ids
):
    _seed_registry_scenario(session_factory, machine_ids)
    response = client.get("/api/official-documents/registry", headers=viewer_headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"
