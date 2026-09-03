"""Real-PostgreSQL parity coverage for the DOCS-01A registry query path."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest
from app.models import (
    AuditLog,
    DocumentType,
    GeneratedDocument,
    Machine,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    Repair,
    TransferBatch,
    TransferProtocol,
    User,
)
from app.official_documents.registry import (
    count_official_document_registry_items,
    query_official_document_registry_items,
)
from app.official_documents.schemas import OfficialRegistryCategory
from sqlalchemy import func, select

# Reuse the existing disposable, migrated PostgreSQL schema fixture.
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _add_canonical_document(
    db,
    *,
    number: str,
    document_type: str,
    actor_id: int,
    machine_id: int,
    created_at: datetime,
    transfer_id: int | None = None,
    snapshot: dict | None = None,
) -> OfficialDocument:
    document = OfficialDocument(
        document_number=number,
        document_type=document_type,
        machine_id=machine_id,
        transfer_id=transfer_id,
        created_by_id=actor_id,
        created_at=created_at,
    )
    db.add(document)
    db.flush()
    docx = f"docx:{number}".encode()
    pdf = f"pdf:{number}".encode()
    snapshot = snapshot or {}
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status="FINALIZED",
        language="bg",
        snapshot=snapshot,
        snapshot_sha256=_sha(repr(snapshot).encode()),
        signing_sha256=_sha(f"signing:{number}".encode()),
        docx_content=docx,
        docx_sha256=_sha(docx),
        pdf_content=pdf,
        pdf_sha256=_sha(pdf),
        prepared_by_id=actor_id,
        created_at=created_at,
        finalized_at=created_at,
    )
    db.add(version)
    db.flush()
    document.current_version_id = version.id
    return document


def _add_matching_legacy_pair(
    db,
    *,
    number: str,
    document_type: str,
    actor_id: int,
    machine_id: int,
    created_at: datetime,
    transfer_id: int | None = None,
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
                filename=f"{number}.{file_format}",
                media_type=(
                    "application/pdf"
                    if file_format == "pdf"
                    else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content=content,
                sha256=_sha(content),
                machine_id=machine_id,
                transfer_id=transfer_id,
                repair_id=repair_id,
                part_request_id=part_request_id,
                snapshot={"historical": True},
                created_by_id=actor_id,
                created_at=created_at,
            )
        )


def _integrity_snapshot(db) -> dict:
    return {
        "official": list(
            db.execute(
                select(
                    OfficialDocument.id,
                    OfficialDocument.current_version_id,
                ).order_by(OfficialDocument.id)
            )
        ),
        "versions": list(
            db.execute(
                select(
                    OfficialDocumentVersion.id,
                    OfficialDocumentVersion.document_id,
                    OfficialDocumentVersion.snapshot_sha256,
                    OfficialDocumentVersion.signing_sha256,
                    OfficialDocumentVersion.docx_sha256,
                    OfficialDocumentVersion.pdf_sha256,
                ).order_by(OfficialDocumentVersion.id)
            )
        ),
        "generated_count": db.scalar(select(func.count(GeneratedDocument.id))),
        "transfer_count": db.scalar(select(func.count(TransferProtocol.id))),
        "batch_count": db.scalar(select(func.count(TransferBatch.id))),
        "repair_count": db.scalar(select(func.count(Repair.id))),
        "request_count": db.scalar(select(func.count(PartRequest.id))),
        "audit_count": db.scalar(select(func.count(AuditLog.id))),
    }


def test_docs01a_registry_query_parity_on_real_postgres(pg_factory):  # noqa: F811
    """Prove grouping, search, pagination and read-only semantics on PostgreSQL."""
    assert pg_factory.kw["bind"].dialect.name == "postgresql"

    with pg_factory() as db:
        baseline_counts = count_official_document_registry_items(db)
        actor = db.scalar(select(User).where(User.email == "admin@assetcore.local"))
        machines = {
            machine.inventory_number: machine
            for machine in db.scalars(
                select(Machine).where(Machine.inventory_number.in_(("9", "11", "13", "14", "15")))
            )
        }
        assert actor is not None
        assert set(machines) == {"9", "11", "13", "14", "15"}

        batch = TransferBatch(
            batch_reference="PG-DOCS01A-BATCH",
            status="ACTIVE",
            created_by_id=actor.id,
            created_at=datetime(2026, 9, 1, 8, 0),
        )
        db.add(batch)
        db.flush()
        transfer = TransferProtocol(
            machine_id=machines["9"].id,
            batch_id=batch.id,
            protocol_number="PG-DOCS01A-TRANSFER-REFERENCE",
            protocol_type="Предаване",
            is_active=True,
            issue_status="COMPLETED",
            issued_by_id=actor.id,
            issued_at=datetime(2026, 9, 1, 9, 0),
            created_at=datetime(2026, 9, 1, 8, 30),
        )
        db.add(transfer)
        db.flush()
        issue_document = _add_canonical_document(
            db,
            number="PG-DOCS01A-ISSUE-009",
            document_type=DocumentType.TRANSFER_ISSUE.value,
            actor_id=actor.id,
            machine_id=machines["9"].id,
            transfer_id=transfer.id,
            created_at=datetime(2026, 9, 1, 9, 0),
        )
        _add_matching_legacy_pair(
            db,
            number=issue_document.document_number,
            document_type=DocumentType.TRANSFER_ISSUE.value,
            actor_id=actor.id,
            machine_id=machines["9"].id,
            transfer_id=transfer.id,
            created_at=datetime(2026, 9, 1, 9, 0),
        )

        repair = Repair(
            machine_id=machines["11"].id,
            repair_reference="PG-DOCS01A-REPAIR-REFERENCE",
            reported_problem="PostgreSQL DOCS-01A parity fixture",
            status="COMPLETED",
            opened_at=datetime(2026, 9, 1, 10, 0),
            closed_at=datetime(2026, 9, 1, 12, 0),
        )
        db.add(repair)
        db.flush()
        repair_document = _add_canonical_document(
            db,
            number="PG-DOCS01A-REPAIR-011",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            machine_id=machines["11"].id,
            snapshot={"repair_id": repair.id},
            created_at=datetime(2026, 9, 1, 12, 0),
        )
        _add_matching_legacy_pair(
            db,
            number=repair_document.document_number,
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            machine_id=machines["11"].id,
            repair_id=repair.id,
            created_at=datetime(2026, 9, 1, 12, 0),
        )

        part_keys: list[tuple[datetime, str]] = []
        for index, machine_number in enumerate(("13", "14", "15"), start=1):
            created_at = datetime(2026, 9, 1, 13, 0) + timedelta(hours=index)
            request = PartRequest(
                machine_id=machines[machine_number].id,
                part_name=f"PostgreSQL registry parity fixture {index}",
                quantity=1,
                status="APPROVED",
                request_reference=f"PG-DOCS01A-PART-REFERENCE-{index:03d}",
                requested_by_id=actor.id,
                created_at=created_at,
            )
            db.add(request)
            db.flush()
            part_document = _add_canonical_document(
                db,
                number=f"PG-DOCS01A-PART-DOCUMENT-{index:03d}",
                document_type=DocumentType.PART_REQUEST.value,
                actor_id=actor.id,
                machine_id=machines[machine_number].id,
                snapshot={"request_id": request.id},
                created_at=created_at,
            )
            _add_matching_legacy_pair(
                db,
                number=part_document.document_number,
                document_type=DocumentType.PART_REQUEST.value,
                actor_id=actor.id,
                machine_id=machines[machine_number].id,
                part_request_id=request.id,
                created_at=created_at,
            )
            part_keys.append((created_at, f"part-request:{request.id}"))
        db.commit()

        before = _integrity_snapshot(db)
        expected_counts = {
            **baseline_counts,
            "transfers": baseline_counts["transfers"] + 1,
            "repairs": baseline_counts["repairs"] + 1,
            "parts": baseline_counts["parts"] + 3,
        }
        assert count_official_document_registry_items(db) == expected_counts

        transfer_page = query_official_document_registry_items(
            db,
            category=OfficialRegistryCategory.TRANSFERS,
            query="pg-docs01a-transfer-reference",
        )
        assert transfer_page["total"] == transfer_page["count"] == 1
        transfer_item = transfer_page["items"][0]
        assert transfer_item["status"] == "INCOMPLETE"
        assert transfer_item["created_at"] is None
        assert [document["document_type"] for document in transfer_item["documents"]] == [
            DocumentType.TRANSFER_ISSUE.value
        ]
        assert transfer_item["documents"][0]["official_document_id"] == (issue_document.id)

        repair_page = query_official_document_registry_items(
            db,
            category=OfficialRegistryCategory.REPAIRS,
            query="pg-docs01a-repair-reference",
        )
        assert repair_page["total"] == repair_page["count"] == 1
        assert len(repair_page["items"][0]["documents"]) == 1
        assert repair_page["items"][0]["documents"][0]["official_document_id"] == repair_document.id

        expected_order = [
            key for _, key in sorted(part_keys, key=lambda value: value[0], reverse=True)
        ]
        first_page = query_official_document_registry_items(
            db,
            category=OfficialRegistryCategory.PARTS,
            query="pg-docs01a-part-reference",
            page=1,
            page_size=2,
        )
        second_page = query_official_document_registry_items(
            db,
            category=OfficialRegistryCategory.PARTS,
            query="pg-docs01a-part-reference",
            page=2,
            page_size=2,
        )
        assert (first_page["total"], first_page["count"]) == (3, 2)
        assert (second_page["total"], second_page["count"]) == (3, 1)
        assert first_page["total_pages"] == second_page["total_pages"] == 2
        keys = [
            item["registry_key"] for page in (first_page, second_page) for item in page["items"]
        ]
        assert keys == expected_order
        assert len(keys) == len(set(keys)) == 3
        assert all(
            len(item["documents"]) == 1 and item["documents"][0]["official_document_id"] is not None
            for page in (first_page, second_page)
            for item in page["items"]
        )
        repeated = query_official_document_registry_items(
            db,
            category=OfficialRegistryCategory.PARTS,
            query="pg-docs01a-part-reference",
            page=1,
            page_size=2,
        )
        assert [item["registry_key"] for item in repeated["items"]] == (expected_order[:2])

        authoritative_search = query_official_document_registry_items(
            db,
            category=OfficialRegistryCategory.PARTS,
            query="pg-docs01a-part-reference-002",
        )
        assert authoritative_search["total"] == 1
        assert authoritative_search["items"][0]["machine_number"] == "14"

        db.expire_all()
        assert _integrity_snapshot(db) == before
        assert not db.new
        assert not db.dirty
        assert not db.deleted
