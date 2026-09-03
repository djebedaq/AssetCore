from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import app.official_documents.registry as registry_service
from app.models import (
    AuditLog,
    DocumentParticipant,
    DocumentSignature,
    DocumentType,
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    ProtocolDocument,
    Repair,
    TransferBatch,
    TransferProtocol,
    User,
)
from app.official_documents.schemas import OfficialRegistryCategory
from sqlalchemy import event, func, select


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
            protocol_number="TP-REFERENCE-009",
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
            repair_reference="REPAIR-REFERENCE-011",
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
            request_reference="REQUEST-REFERENCE-013",
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


def _seed_paged_part_registry(
    session_factory, machine_ids, *, count: int = 8
) -> list[str]:
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        identities: list[tuple[datetime, str]] = []
        for index in range(count):
            created_at = datetime(2026, 7, 15, 12, 0) - timedelta(
                days=max(index - 1, 0)
            )
            request = PartRequest(
                machine_id=machine_ids["15"],
                part_name=f"Registry pagination fixture {index}",
                quantity=1,
                status="APPROVED",
                request_reference=f"REQUEST-PAGE-{index:03d}",
                requested_by_id=actor.id,
                created_at=created_at,
            )
            session.add(request)
            session.flush()
            _add_official_document(
                session,
                number=f"PART-DOCUMENT-{index:03d}",
                document_type=DocumentType.PART_REQUEST.value,
                actor_id=actor.id,
                created_at=created_at,
                machine_id=machine_ids["15"],
                snapshot={"request_id": request.id},
            )
            identities.append((created_at, f"part-request:{request.id}"))
        session.commit()
    return [
        registry_key
        for _, registry_key in sorted(identities, reverse=True)
    ]


def _add_machine_search_transfer(session_factory, machine_ids) -> None:
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        batch = TransferBatch(
            batch_reference="BATCH-ALPHA",
            status="ACTIVE",
            created_by_id=actor.id,
            created_at=datetime(2026, 8, 25, 8, 0),
        )
        session.add(batch)
        session.flush()
        transfer = TransferProtocol(
            machine_id=machine_ids["17"],
            batch_id=batch.id,
            protocol_number="TRANSFER-ALPHA",
            protocol_type="Предаване",
            is_active=True,
            issue_status="COMPLETED",
            issued_by_id=actor.id,
            issued_at=datetime(2026, 8, 25, 9, 0),
            created_at=datetime(2026, 8, 25, 8, 30),
        )
        session.add(transfer)
        session.flush()
        _add_official_document(
            session,
            number="ISSUE-ALPHA",
            document_type=DocumentType.TRANSFER_ISSUE.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 25, 9, 0),
            machine_id=machine_ids["17"],
            transfer_id=transfer.id,
            status="FINALIZED",
        )
        session.commit()


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


def test_registry_does_not_complete_return_only_transfer_lifecycle(
    client, auth_headers, session_factory, machine_ids
):
    with session_factory() as session:
        actor = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        transfer = TransferProtocol(
            machine_id=machine_ids["16"],
            protocol_number="TR-REG-RETURN-ONLY-016",
            protocol_type="Предаване",
            is_active=False,
            issue_status="COMPLETED",
            return_status="COMPLETED",
            returned_by_id=actor.id,
            returned_at=datetime(2026, 8, 24, 11, 0),
            created_at=datetime(2026, 8, 23, 8, 30),
        )
        session.add(transfer)
        session.flush()
        _add_official_document(
            session,
            number="TR-REG-RETURN-ONLY-016-R",
            document_type=DocumentType.TRANSFER_RETURN.value,
            actor_id=actor.id,
            created_at=datetime(2026, 8, 24, 11, 0),
            machine_id=machine_ids["16"],
            transfer_id=transfer.id,
            status="FINALIZED",
        )
        session.commit()

    response = client.get("/api/official-documents/registry", headers=auth_headers)
    assert response.status_code == 200, response.text
    transfers = response.json()["transfers"]
    assert transfers["count"] == 1
    lifecycle = transfers["items"][0]
    assert lifecycle["machine_number"] == "16"
    assert lifecycle["status"] == "INCOMPLETE"
    assert lifecycle["created_at"] is None
    assert [document["document_type"] for document in lifecycle["documents"]] == [
        "TRANSFER_RETURN"
    ]
    assert lifecycle["documents"][0]["document_number"] == (
        "TR-REG-RETURN-ONLY-016-R"
    )

    paged = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "transfers"},
    )
    assert paged.status_code == 200, paged.text
    assert paged.json()["total"] == 1
    assert paged.json()["items"] == transfers["items"]


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


def test_paged_registry_matches_legacy_sections_and_counts_without_category_leaks(
    client, auth_headers, session_factory, machine_ids
):
    _seed_registry_scenario(session_factory, machine_ids)
    _add_machine_search_transfer(session_factory, machine_ids)

    legacy = client.get(
        "/api/official-documents/registry", headers=auth_headers
    ).json()
    counts_response = client.get(
        "/api/official-documents/registry/counts", headers=auth_headers
    )
    assert counts_response.status_code == 200, counts_response.text
    counts = counts_response.json()
    allowed_types = {
        "transfers": {"TRANSFER_ISSUE", "TRANSFER_RETURN"},
        "repairs": {"REPAIR_PROTOCOL"},
        "parts": {"PART_REQUEST"},
    }

    for category in ("transfers", "repairs", "parts"):
        response = client.get(
            "/api/official-documents/registry/items",
            headers=auth_headers,
            params={"category": category, "page_size": 100},
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page["category"] == category
        assert page["total"] == counts[category] == legacy[category]["count"]
        assert page["count"] == page["total"]
        assert page["items"] == legacy[category]["items"]
        assert {
            document["document_type"]
            for item in page["items"]
            for document in item["documents"]
        }.issubset(allowed_types[category])

    assert counts == {"transfers": 3, "repairs": 2, "parts": 2}


def test_category_search_uses_only_authoritative_identifiers_with_literal_matching(
    client, auth_headers, session_factory, machine_ids
):
    _seed_registry_scenario(session_factory, machine_ids)
    _add_machine_search_transfer(session_factory, machine_ids)

    cases = (
        ("transfers", "  17  ", {"17"}),
        ("transfers", "issue-alpha", {"17"}),
        ("transfers", "TRANSFER-alpha", {"17"}),
        ("transfers", "batch-alpha", {"17"}),
        ("transfers", "tr-reg-010-r", {"10"}),
        ("repairs", "rep-reg-011", {"11"}),
        ("repairs", "repair-reference-011", {"11"}),
        ("parts", "pr-reg-013", {"13"}),
        ("parts", "request-reference-013", {"13"}),
        ("repairs", "rep-legacy-012", {"12"}),
        ("parts", "pr-legacy-014", {"14"}),
    )
    for category, query, expected_machines in cases:
        response = client.get(
            "/api/official-documents/registry/items",
            headers=auth_headers,
            params={"category": category, "q": query, "page_size": 100},
        )
        assert response.status_code == 200, response.text
        assert {item["machine_number"] for item in response.json()["items"]} == (
            expected_machines
        )

    for literal in ("%", "_", "\\"):
        response = client.get(
            "/api/official-documents/registry/items",
            headers=auth_headers,
            params={"category": "transfers", "q": literal},
        )
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0

    unfiltered = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "repairs"},
    ).json()
    whitespace = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "repairs", "q": "   "},
    ).json()
    assert whitespace == unfiltered

    historical = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "repairs", "q": "rep-legacy-012"},
    ).json()["items"][0]
    assert historical["documents"][0]["official_document_id"] is None
    assert {
        file["download_endpoint"]
        for file in historical["documents"][0]["files"]
    } == {
        "/generated-documents/3/download",
        "/generated-documents/4/download",
    }


def test_registry_pagination_is_stable_complete_and_handles_empty_or_high_pages(
    client, auth_headers, session_factory, machine_ids
):
    expected_order = _seed_paged_part_registry(session_factory, machine_ids, count=8)
    collected: list[str] = []
    first_page_keys: list[str] | None = None
    for page_number in range(1, 4):
        response = client.get(
            "/api/official-documents/registry/items",
            headers=auth_headers,
            params={"category": "parts", "page": page_number, "page_size": 3},
        )
        assert response.status_code == 200, response.text
        page = response.json()
        assert page == {
            **page,
            "category": "parts",
            "total": 8,
            "count": 3 if page_number < 3 else 2,
            "page": page_number,
            "page_size": 3,
            "total_pages": 3,
            "has_previous": page_number > 1,
            "has_next": page_number < 3,
        }
        keys = [item["registry_key"] for item in page["items"]]
        if page_number == 1:
            first_page_keys = keys
        collected.extend(keys)

    assert collected == expected_order
    assert len(collected) == len(set(collected)) == 8
    repeated = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "parts", "page": 1, "page_size": 3},
    ).json()
    assert [item["registry_key"] for item in repeated["items"]] == first_page_keys

    high = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "parts", "page": 99, "page_size": 3},
    ).json()
    assert high["total"] == 8
    assert high["count"] == 0
    assert high["items"] == []
    assert high["total_pages"] == 3
    assert high["has_previous"] is True
    assert high["has_next"] is False

    empty_search = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "parts", "q": "NO-SUCH-IDENTIFIER"},
    ).json()
    assert empty_search["total"] == 0
    assert empty_search["count"] == 0
    assert empty_search["items"] == []
    assert empty_search["total_pages"] == 0
    assert empty_search["has_previous"] is False
    assert empty_search["has_next"] is False

    empty_category = client.get(
        "/api/official-documents/registry/items",
        headers=auth_headers,
        params={"category": "transfers"},
    ).json()
    assert empty_category["total"] == empty_category["count"] == 0
    assert empty_category["items"] == []
    assert empty_category["total_pages"] == 0


def test_registry_query_parameter_validation_and_permission_boundaries(
    client, auth_headers, viewer_headers
):
    invalid_params = (
        {"category": "unknown"},
        {"category": "transfers", "page": 0},
        {"category": "transfers", "page_size": 0},
        {"category": "transfers", "page_size": 101},
        {"category": "transfers", "q": "x" * 201},
    )
    for params in invalid_params:
        response = client.get(
            "/api/official-documents/registry/items",
            headers=auth_headers,
            params=params,
        )
        assert response.status_code == 422, response.text

    for path in (
        "/api/official-documents/registry/items?category=transfers",
        "/api/official-documents/registry/counts",
    ):
        forbidden = client.get(path, headers=viewer_headers)
        assert forbidden.status_code == 403
        assert forbidden.json()["detail"] == {
            "code": "permission_denied",
            "message": "Нямате права за това действие.",
            "permission": "documents.view",
        }
        no_session = client.get(path)
        assert no_session.status_code == 401


def test_paged_and_count_registry_reads_preserve_rows_versions_hashes_and_audit(
    client, auth_headers, session_factory, machine_ids
):
    _seed_registry_scenario(session_factory, machine_ids)

    def integrity_snapshot():
        with session_factory() as session:
            versions = list(
                session.execute(
                    select(
                        OfficialDocumentVersion.id,
                        OfficialDocumentVersion.document_id,
                        OfficialDocumentVersion.snapshot_sha256,
                        OfficialDocumentVersion.signing_sha256,
                        OfficialDocumentVersion.docx_sha256,
                        OfficialDocumentVersion.pdf_sha256,
                    ).order_by(OfficialDocumentVersion.id)
                )
            )
            return {
                "official": list(
                    session.execute(
                        select(
                            OfficialDocument.id,
                            OfficialDocument.current_version_id,
                        ).order_by(OfficialDocument.id)
                    )
                ),
                "versions": versions,
                "generated_count": session.scalar(
                    select(func.count(GeneratedDocument.id))
                ),
                "protocol_count": session.scalar(
                    select(func.count(ProtocolDocument.id))
                ),
                "transfer_count": session.scalar(
                    select(func.count(TransferProtocol.id))
                ),
                "batch_count": session.scalar(select(func.count(TransferBatch.id))),
                "repair_count": session.scalar(select(func.count(Repair.id))),
                "request_count": session.scalar(select(func.count(PartRequest.id))),
                "participant_count": session.scalar(
                    select(func.count(DocumentParticipant.id))
                ),
                "signature_count": session.scalar(
                    select(func.count(DocumentSignature.id))
                ),
                "audit_count": session.scalar(select(func.count(AuditLog.id))),
            }

    before = integrity_snapshot()
    counts = client.get(
        "/api/official-documents/registry/counts", headers=auth_headers
    )
    assert counts.status_code == 200, counts.text
    for category in ("transfers", "repairs", "parts"):
        response = client.get(
            "/api/official-documents/registry/items",
            headers=auth_headers,
            params={"category": category, "q": "REG"},
        )
        assert response.status_code == 200, response.text
    assert integrity_snapshot() == before


def test_counts_skip_expensive_hydration_and_page_queries_do_not_scale_per_item(
    session_factory, machine_ids, monkeypatch
):
    _seed_paged_part_registry(session_factory, machine_ids, count=24)
    with session_factory() as session:
        engine = session.get_bind()
        statements: list[str] = []

        def capture_statement(_conn, _cursor, statement, *_args):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement.lower())

        event.listen(engine, "before_cursor_execute", capture_statement)
        try:
            monkeypatch.setattr(
                registry_service,
                "_signature_states",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("counts must not hydrate signature state")
                ),
            )
            counts = registry_service.count_official_document_registry_items(session)
        finally:
            event.remove(engine, "before_cursor_execute", capture_statement)
        assert counts == {"transfers": 0, "repairs": 0, "parts": 24}
        assert not any("document_signatures" in statement for statement in statements)
        assert not any("document_participants" in statement for statement in statements)
        assert not any("docx_content" in statement for statement in statements)
        assert not any("pdf_content" in statement for statement in statements)

    monkeypatch.undo()

    def select_count(page_size: int) -> tuple[int, dict]:
        with session_factory() as measured_session:
            engine = measured_session.get_bind()
            count = 0

            def count_selects(_conn, _cursor, statement, *_args):
                nonlocal count
                if statement.lstrip().upper().startswith("SELECT"):
                    count += 1

            event.listen(engine, "before_cursor_execute", count_selects)
            try:
                result = registry_service.query_official_document_registry_items(
                    measured_session,
                    category=OfficialRegistryCategory.PARTS,
                    page_size=page_size,
                )
            finally:
                event.remove(engine, "before_cursor_execute", count_selects)
        return count, result

    small_selects, small = select_count(1)
    large_selects, large = select_count(20)
    assert small["count"] == 1
    assert large["count"] == 20
    assert small["total"] == large["total"] == 24
    assert large_selects <= small_selects + 1
