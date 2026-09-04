from __future__ import annotations

import hashlib
from datetime import datetime

from app.models import (
    AuditLog,
    DocumentType,
    GeneratedDocument,
    Machine,
    MachineEvent,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    PartRequestStatus,
    Repair,
    RepairStatus,
    TransferProtocol,
    User,
)
from sqlalchemy import func, select


def _passport(client, headers, machine_id: int) -> dict:
    response = client.get(f"/api/machines/{machine_id}/passport", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _admin(db) -> User:
    actor = db.scalar(select(User).where(User.email == "admin@assetcore.local"))
    assert actor is not None
    return actor


def _add_official_document(
    db,
    *,
    machine_id: int | None,
    actor_id: int,
    number: str,
    document_type: str,
    snapshot: dict,
) -> OfficialDocument:
    content = f"passport-v2:{number}".encode()
    digest = hashlib.sha256(content).hexdigest()
    document = OfficialDocument(
        document_number=number,
        document_type=document_type,
        machine_id=machine_id,
        created_by_id=actor_id,
    )
    db.add(document)
    db.flush()
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status="FINALIZED",
        language="bg",
        snapshot=snapshot,
        snapshot_sha256=digest,
        signing_sha256=digest,
        docx_content=content,
        docx_sha256=digest,
        pdf_content=content,
        pdf_sha256=digest,
        prepared_by_id=actor_id,
        finalized_at=datetime(2026, 9, 3, 12, 0),
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    return document


def _add_matching_legacy_documents(
    db,
    *,
    machine_id: int,
    actor_id: int,
    number: str,
    document_type: str,
    repair_id: int | None = None,
    part_request_id: int | None = None,
) -> None:
    for file_format in ("docx", "pdf"):
        content = f"legacy:{number}:{file_format}".encode()
        db.add(
            GeneratedDocument(
                document_number=number,
                document_type=document_type,
                format=file_format,
                language="bg",
                filename=f"legacy.{file_format}",
                media_type="application/octet-stream",
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                machine_id=machine_id,
                repair_id=repair_id,
                part_request_id=part_request_id,
                snapshot={},
                created_by_id=actor_id,
            )
        )


def _document_integrity_snapshot(db) -> dict:
    return {
        "official_documents": [
            tuple(row)
            for row in db.execute(
                select(
                    OfficialDocument.id,
                    OfficialDocument.machine_id,
                    OfficialDocument.current_version_id,
                ).order_by(OfficialDocument.id)
            )
        ],
        "official_versions": [
            tuple(row)
            for row in db.execute(
                select(
                    OfficialDocumentVersion.id,
                    OfficialDocumentVersion.snapshot,
                    OfficialDocumentVersion.snapshot_sha256,
                    OfficialDocumentVersion.signing_sha256,
                    OfficialDocumentVersion.docx_sha256,
                    OfficialDocumentVersion.pdf_sha256,
                ).order_by(OfficialDocumentVersion.id)
            )
        ],
        "repairs": [
            tuple(row)
            for row in db.execute(
                select(
                    Repair.id,
                    Repair.machine_id,
                    Repair.status,
                    Repair.closed_at,
                ).order_by(Repair.id)
            )
        ],
        "part_requests": [
            tuple(row)
            for row in db.execute(
                select(
                    PartRequest.id,
                    PartRequest.machine_id,
                    PartRequest.status,
                    PartRequest.request_reference,
                ).order_by(PartRequest.id)
            )
        ],
        "generated_documents": [
            tuple(row)
            for row in db.execute(
                select(
                    GeneratedDocument.id,
                    GeneratedDocument.machine_id,
                    GeneratedDocument.repair_id,
                    GeneratedDocument.part_request_id,
                    GeneratedDocument.sha256,
                ).order_by(GeneratedDocument.id)
            )
        ],
        "audit_count": db.scalar(select(func.count(AuditLog.id))),
    }


def test_free_ready_machine_has_truthful_empty_operational_summary(
    client, auth_headers, machine_ids
):
    passport = _passport(client, auth_headers, machine_ids["4"])

    assert passport["current_state"]["available"] is True
    assert passport["current_state"]["active_transfer"] is None
    assert passport["current_state"]["active_repair"] is None
    assert passport["current_state"]["last_completed_repair"] is None
    assert passport["current_state"]["last_transfer"] is None
    assert passport["current_state"]["pending_part_requests"] == {
        "count": 0,
        "latest_request_reference": None,
    }
    assert passport["official_documents"] == []


def test_latest_completed_repair_is_deterministic_and_not_replaced_by_active_repair(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["9"]
    tied_close = datetime(2026, 9, 2, 14, 0)
    with session_factory() as db:
        older = Repair(
            machine_id=machine_id,
            repair_reference="ASSET02-REPAIR-OLDER",
            reported_problem="Test-only older completed repair",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 8, 30, 8, 0),
            closed_at=tied_close,
            test_passed=True,
        )
        newest_tie = Repair(
            machine_id=machine_id,
            repair_reference="ASSET02-REPAIR-TIE-WINNER",
            reported_problem="Test-only deterministic tie winner",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 8, 31, 8, 0),
            closed_at=tied_close,
            test_passed=True,
        )
        active = Repair(
            machine_id=machine_id,
            repair_reference="ASSET02-REPAIR-ACTIVE",
            reported_problem="Test-only active repair",
            status=RepairStatus.DIAGNOSIS.value,
            opened_at=datetime(2026, 9, 3, 8, 0),
        )
        db.add_all([older, newest_tie, active])
        db.commit()
        winner_id = newest_tie.id
        active_id = active.id

    passport = _passport(client, auth_headers, machine_id)

    assert passport["current_state"]["active_repair"]["id"] == active_id
    assert passport["current_state"]["last_completed_repair"] == {
        "id": winner_id,
        "repair_reference": "ASSET02-REPAIR-TIE-WINNER",
        "status": RepairStatus.COMPLETED.value,
        "opened_at": "2026-08-31T08:00:00",
        "closed_at": "2026-09-02T14:00:00",
        "test_passed": True,
    }


def test_last_transfer_uses_effective_chronology_and_stable_id_tie_breaker(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["10"]
    effective_at = datetime(2026, 9, 2, 16, 0)
    with session_factory() as db:
        actor = _admin(db)
        first = TransferProtocol(
            machine_id=machine_id,
            protocol_number="ASSET02-TRANSFER-FIRST",
            is_active=False,
            issued_by_id=actor.id,
            issued_at=datetime(2026, 9, 1, 8, 0),
            returned_at=effective_at,
            created_at=datetime(2026, 9, 1, 7, 0),
        )
        tied_winner = TransferProtocol(
            machine_id=machine_id,
            protocol_number="ASSET02-TRANSFER-TIE-WINNER",
            is_active=False,
            issued_by_id=actor.id,
            issued_at=effective_at,
            created_at=datetime(2026, 8, 30, 7, 0),
        )
        db.add_all([first, tied_winner])
        db.commit()
        winner_id = tied_winner.id

    passport = _passport(client, auth_headers, machine_id)

    assert passport["current_state"]["last_transfer"]["id"] == winner_id
    assert passport["current_state"]["last_transfer"]["protocol_number"] == (
        "ASSET02-TRANSFER-TIE-WINNER"
    )
    assert [item["protocol_number"] for item in passport["transfers"]] == [
        "ASSET02-TRANSFER-TIE-WINNER",
        "ASSET02-TRANSFER-FIRST",
    ]


def test_pending_part_request_summary_uses_all_non_terminal_canonical_statuses(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["11"]
    statuses = list(PartRequestStatus)
    created_at = datetime(2026, 9, 2, 10, 0)
    with session_factory() as db:
        actor = _admin(db)
        for status in statuses:
            db.add(
                PartRequest(
                    machine_id=machine_id,
                    part_name=f"Test-only {status.value}",
                    quantity=1,
                    status=status.value,
                    request_reference=f"ASSET02-REQUEST-{status.value}",
                    requested_by_id=actor.id,
                    created_at=created_at,
                )
            )
        db.commit()

    passport = _passport(client, auth_headers, machine_id)

    assert passport["current_state"]["pending_part_requests"] == {
        "count": 6,
        "latest_request_reference": "ASSET02-REQUEST-PARTIALLY_DELIVERED",
    }
    assert {item["status"] for item in passport["part_requests"]} == {
        status.value for status in statuses
    }


def test_machine_scoped_official_documents_are_exact_and_canonical_wins(
    client, auth_headers, machine_ids, session_factory
):
    target_id = machine_ids["4"]
    other_id = machine_ids["14"]
    with session_factory() as db:
        actor = _admin(db)
        target_repair = Repair(
            machine_id=target_id,
            repair_reference="ASSET02-OFFICIAL-REPAIR-4",
            reported_problem="Test-only exact machine linkage",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 2, 8, 0),
            closed_at=datetime(2026, 9, 3, 12, 0),
        )
        other_repair = Repair(
            machine_id=other_id,
            repair_reference="ASSET02-OFFICIAL-REPAIR-14",
            reported_problem="Test-only fuzzy-number guard",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 2, 8, 0),
            closed_at=datetime(2026, 9, 3, 12, 0),
        )
        db.add_all([target_repair, other_repair])
        db.flush()
        canonical = _add_official_document(
            db,
            machine_id=target_id,
            actor_id=actor.id,
            number="ASSET02-CANONICAL-MACHINE-4",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            snapshot={"repair_id": target_repair.id},
        )
        _add_official_document(
            db,
            machine_id=other_id,
            actor_id=actor.id,
            number="ASSET02-CANONICAL-MACHINE-14",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            snapshot={"repair_id": other_repair.id},
        )
        _add_matching_legacy_documents(
            db,
            machine_id=target_id,
            actor_id=actor.id,
            number=canonical.document_number,
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            repair_id=target_repair.id,
        )
        db.commit()
        canonical_id = canonical.id

    passport = _passport(client, auth_headers, target_id)

    assert len(passport["official_documents"]) == 1
    item = passport["official_documents"][0]
    assert item["machine_id"] == target_id
    assert item["machine_number"] == "4"
    assert len(item["documents"]) == 1
    assert item["documents"][0]["official_document_id"] == canonical_id
    assert item["documents"][0]["document_number"] == (
        "ASSET02-CANONICAL-MACHINE-4"
    )
    assert all(
        document["document_number"] != "ASSET02-CANONICAL-MACHINE-14"
        for registry_item in passport["official_documents"]
        for document in registry_item["documents"]
    )
    assert all(
        document["display_separately"] is False
        for document in passport["generated_documents"]
    )


def test_snapshot_linked_null_machine_canonical_documents_are_exact_and_read_only(
    client, auth_headers, machine_ids, session_factory
):
    target_id = machine_ids["4"]
    other_id = machine_ids["14"]
    with session_factory() as db:
        actor = _admin(db)
        target_repair = Repair(
            machine_id=target_id,
            repair_reference="ASSET02-NULL-REPAIR-4",
            reported_problem="Test-only NULL machine canonical repair linkage",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 2, 8, 0),
            closed_at=datetime(2026, 9, 3, 12, 0),
        )
        other_repair = Repair(
            machine_id=other_id,
            repair_reference="ASSET02-NULL-REPAIR-14",
            reported_problem="Test-only cross-machine canonical repair guard",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 2, 8, 0),
            closed_at=datetime(2026, 9, 3, 12, 0),
        )
        target_request = PartRequest(
            machine_id=target_id,
            part_name="Test-only NULL machine canonical part request",
            quantity=1,
            status=PartRequestStatus.APPROVED.value,
            request_reference="ASSET02-NULL-PART-4",
            requested_by_id=actor.id,
        )
        other_request = PartRequest(
            machine_id=other_id,
            part_name="Test-only cross-machine canonical part request guard",
            quantity=1,
            status=PartRequestStatus.APPROVED.value,
            request_reference="ASSET02-NULL-PART-14",
            requested_by_id=actor.id,
        )
        db.add_all([target_repair, other_repair, target_request, other_request])
        db.flush()

        target_repair_document = _add_official_document(
            db,
            machine_id=None,
            actor_id=actor.id,
            number="ASSET02-NULL-CANONICAL-REPAIR-4",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            snapshot={"repair_id": target_repair.id},
        )
        _add_official_document(
            db,
            machine_id=None,
            actor_id=actor.id,
            number="ASSET02-NULL-CANONICAL-REPAIR-14",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            snapshot={"repair_id": other_repair.id},
        )
        target_part_document = _add_official_document(
            db,
            machine_id=None,
            actor_id=actor.id,
            number="ASSET02-NULL-CANONICAL-PART-4",
            document_type=DocumentType.PART_REQUEST.value,
            snapshot={"request_id": target_request.id},
        )
        _add_official_document(
            db,
            machine_id=None,
            actor_id=actor.id,
            number="ASSET02-NULL-CANONICAL-PART-14",
            document_type=DocumentType.PART_REQUEST.value,
            snapshot={"request_id": other_request.id},
        )
        _add_matching_legacy_documents(
            db,
            machine_id=target_id,
            actor_id=actor.id,
            number=target_repair_document.document_number,
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            repair_id=target_repair.id,
        )
        _add_matching_legacy_documents(
            db,
            machine_id=target_id,
            actor_id=actor.id,
            number=target_part_document.document_number,
            document_type=DocumentType.PART_REQUEST.value,
            part_request_id=target_request.id,
        )
        db.commit()
        target_document_ids = {target_repair_document.id, target_part_document.id}
        before = _document_integrity_snapshot(db)

    passport = _passport(client, auth_headers, target_id)

    documents = [
        document
        for item in passport["official_documents"]
        for document in item["documents"]
    ]
    assert {document["official_document_id"] for document in documents} == (
        target_document_ids
    )
    assert {document["document_number"] for document in documents} == {
        "ASSET02-NULL-CANONICAL-REPAIR-4",
        "ASSET02-NULL-CANONICAL-PART-4",
    }
    assert "ASSET02-NULL-CANONICAL-REPAIR-14" not in str(
        passport["official_documents"]
    )
    assert "ASSET02-NULL-CANONICAL-PART-14" not in str(
        passport["official_documents"]
    )
    assert len(passport["official_documents"]) == 2
    assert len(passport["generated_documents"]) == 4
    assert all(
        document["display_separately"] is False
        for document in passport["generated_documents"]
    )

    with session_factory() as db:
        assert _document_integrity_snapshot(db) == before
        assert not db.new
        assert not db.dirty
        assert not db.deleted


def test_observer_summary_does_not_leak_new_sensitive_aggregates(
    client, auth_headers, viewer_headers, machine_ids, session_factory
):
    machine_id = machine_ids["13"]
    with session_factory() as db:
        actor = _admin(db)
        repair = Repair(
            machine_id=machine_id,
            repair_reference="ASSET02-OBSERVER-SECRET-REPAIR",
            reported_problem="Test-only restricted repair problem",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 1, 8, 0),
            closed_at=datetime(2026, 9, 2, 8, 0),
        )
        request = PartRequest(
            machine_id=machine_id,
            part_name="Test-only restricted request",
            quantity=1,
            status=PartRequestStatus.APPROVED.value,
            request_reference="ASSET02-OBSERVER-SECRET-REQUEST",
            requested_by_id=actor.id,
        )
        db.add_all([repair, request])
        db.commit()

    full = _passport(client, auth_headers, machine_id)
    limited = _passport(client, viewer_headers, machine_id)

    assert full["current_state"]["last_completed_repair"] is not None
    assert full["current_state"]["pending_part_requests"]["count"] == 1
    assert limited["limited_view"] is True
    assert limited["current_state"]["last_completed_repair"] is None
    assert limited["current_state"]["last_transfer"] is None
    assert limited["current_state"]["pending_part_requests"] == {
        "count": 0,
        "latest_request_reference": None,
    }
    assert limited["official_documents"] == []
    assert limited["repairs"] == []
    assert limited["part_requests"] == []
    assert limited["audit_visible"] is False
    assert "ASSET02-OBSERVER-SECRET" not in str(limited)


def test_passport_v2_get_is_read_only_and_audit_remains_permission_controlled(
    client, auth_headers, viewer_headers, machine_ids, session_factory
):
    machine_id = machine_ids["15"]
    with session_factory() as db:
        machine = db.get(Machine, machine_id)
        assert machine is not None
        db.add(
            MachineEvent(
                machine_id=machine_id,
                event_type="IMPORTED",
                reference="ASSET02-READ-ONLY",
                created_at=datetime(2026, 9, 1, 8, 0),
            )
        )
        db.add(
            AuditLog(
                entity_type="machine",
                entity_id=machine_id,
                action="ASSET02_READ_ONLY_BASELINE",
                details="{}",
                created_at=datetime(2026, 9, 1, 8, 0),
            )
        )
        db.commit()
        before = {
            model.__tablename__: db.scalar(select(func.count(model.id)))
            for model in (
                Machine,
                MachineEvent,
                Repair,
                TransferProtocol,
                PartRequest,
                GeneratedDocument,
                OfficialDocument,
                OfficialDocumentVersion,
                AuditLog,
            )
        }
        updated_at = machine.updated_at

    full = _passport(client, auth_headers, machine_id)
    limited = _passport(client, viewer_headers, machine_id)

    assert full["audit_visible"] is True
    assert any(item["action"] == "ASSET02_READ_ONLY_BASELINE" for item in full["audit"])
    assert limited["audit_visible"] is False
    assert limited["audit"] == []
    with session_factory() as db:
        after = {
            model.__tablename__: db.scalar(select(func.count(model.id)))
            for model in (
                Machine,
                MachineEvent,
                Repair,
                TransferProtocol,
                PartRequest,
                GeneratedDocument,
                OfficialDocument,
                OfficialDocumentVersion,
                AuditLog,
            )
        }
        assert after == before
        assert db.get(Machine, machine_id).updated_at == updated_at
        assert not db.new
        assert not db.dirty
        assert not db.deleted


def test_same_timestamp_history_order_is_stable_by_descending_id(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["16"]
    created_at = datetime(2026, 9, 2, 11, 0)
    with session_factory() as db:
        first = MachineEvent(
            machine_id=machine_id,
            event_type="IMPORTED",
            reference="ASSET02-HISTORY-FIRST",
            created_at=created_at,
        )
        second = MachineEvent(
            machine_id=machine_id,
            event_type="IMPORTED",
            reference="ASSET02-HISTORY-SECOND",
            created_at=created_at,
        )
        db.add_all([first, second])
        db.commit()

    passport = _passport(client, auth_headers, machine_id)

    assert [item["reference"] for item in passport["history"][:2]] == [
        "ASSET02-HISTORY-SECOND",
        "ASSET02-HISTORY-FIRST",
    ]
