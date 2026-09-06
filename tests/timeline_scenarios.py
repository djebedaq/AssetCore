"""Synthetic lifecycle evidence only in disposable SQLite/PostgreSQL test databases."""

import hashlib
import json
from datetime import datetime, timedelta

from app.models import (
    AuditLog,
    DocumentSignature,
    GeneratedDocument,
    Machine,
    MachineEvent,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    ProtocolDocument,
    Repair,
    RepairEvent,
    RepairPart,
    TransferProtocol,
    User,
)
from sqlalchemy import select

AT = datetime(2026, 9, 1, 12)


def persist(db, model, **values):
    row = model(**values)
    db.add(row)
    db.flush()
    return row


def actor_and_machines(db):
    actor = db.scalar(select(User).where(User.email == "admin@assetcore.local"))
    machines = {m.inventory_number: m.id for m in db.scalars(select(Machine))}
    return actor, machines


def transfer(db, machine_id, **overrides):
    values = dict(
        machine_id=machine_id,
        protocol_number=f"QA-ISSUE-{machine_id}",
        issue_status="COMPLETED",
        issued_at=AT,
        created_at=AT,
        is_active=True,
    )
    values.update(overrides)
    return persist(db, TransferProtocol, **values)


def repair(db, machine_id, **overrides):
    values = dict(
        machine_id=machine_id,
        repair_reference=f"QA-REPAIR-{machine_id}",
        reported_problem="Test-only operational fault",
        status="ACCEPTED",
        opened_at=AT,
    )
    values.update(overrides)
    return persist(db, Repair, **values)


def request(db, machine_id, **overrides):
    values = dict(
        machine_id=machine_id,
        request_reference=f"QA-REQUEST-{machine_id}",
        part_name="Test-only request",
        status="DRAFT",
        quantity=1,
        created_at=AT,
    )
    values.update(overrides)
    return persist(db, PartRequest, **values)


def repair_event(db, repair_id, actor_id, code, **overrides):
    values = dict(repair_id=repair_id, user_id=actor_id, event_type=code, created_at=AT)
    values.update(overrides)
    return persist(db, RepairEvent, **values)


def machine_event(db, machine_id, code, **overrides):
    values = dict(machine_id=machine_id, event_type=code, created_at=AT)
    values.update(overrides)
    return persist(db, MachineEvent, **values)


def approval(db, request_id, actor_id, decision, **overrides):
    values = dict(request_id=request_id, decided_by_id=actor_id, decision=decision, decided_at=AT)
    values.update(overrides)
    return persist(db, PartRequestApproval, **values)


def transition(db, request_id, previous, new, **overrides):
    values = dict(
        entity_type="part_request",
        entity_id=request_id,
        action="Обновено изпълнение на заявка за части",
        created_at=AT,
        details=json.dumps({"previous_status": previous, "new_status": new}),
    )
    values.update(overrides)
    return persist(db, AuditLog, **values)


def official(
    db,
    actor_id,
    machine_id,
    number,
    document_type,
    *,
    snapshot=None,
    transfer_id=None,
    finalized_at=AT,
    version_number=1,
    created_at=AT,
):
    doc = persist(
        db,
        OfficialDocument,
        document_number=number,
        document_type=document_type,
        machine_id=machine_id,
        transfer_id=transfer_id,
        created_by_id=actor_id,
        created_at=created_at,
    )
    content = f"TEST-ONLY:{number}".encode()
    digest = hashlib.sha256(content).hexdigest()
    version = persist(
        db,
        OfficialDocumentVersion,
        document_id=doc.id,
        version=version_number,
        status="FINALIZED" if finalized_at else "DRAFT",
        snapshot=snapshot or {},
        snapshot_sha256=digest,
        signing_sha256=digest,
        docx_content=content,
        docx_sha256=digest,
        pdf_content=content,
        pdf_sha256=digest,
        prepared_by_id=actor_id,
        created_at=created_at,
        finalized_at=finalized_at,
    )
    doc.current_version_id = version.id
    db.flush()
    return doc


def legacy(db, actor_id, machine_id, number, document_type, **links):
    result = []
    for file_format in ("pdf", "docx"):
        content = f"TEST-ONLY:{number}:{file_format}".encode()
        result.append(
            persist(
                db,
                GeneratedDocument,
                document_number=number,
                document_type=document_type,
                format=file_format,
                filename=f"test.{file_format}",
                media_type="application/octet-stream",
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                snapshot={"test_only": True},
                machine_id=machine_id,
                created_by_id=actor_id,
                created_at=AT,
                **links,
            )
        )
    return result


def fingerprint(db):
    """All columns/bytes, not just counts: reads cannot change history or hashes."""
    models = (
        Machine,
        MachineEvent,
        TransferProtocol,
        Repair,
        RepairEvent,
        RepairPart,
        PartRequest,
        PartRequestApproval,
        PartRequestLine,
        GeneratedDocument,
        ProtocolDocument,
        OfficialDocument,
        OfficialDocumentVersion,
        AuditLog,
        DocumentSignature,
    )
    result = {}
    for model in models:
        rows = list(db.execute(select(model.__table__).order_by(model.id)))
        result[model.__tablename__] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest())
    return result


def parity_scenario(db):
    """Identical committed representative facts exercised by both database suites."""
    actor, machines = actor_and_machines(db)
    references = {}
    for number in ("4", "14"):
        machine_id = machines[number]
        asset = machine_event(
            db, machine_id, "MACHINE_UPDATED", reference=f"ASSET-MACHINE-{number}"
        )
        movement = transfer(
            db,
            machine_id,
            protocol_number=f"ISSUE-MACHINE-{number}",
            issued_at=AT - timedelta(days=1),
        )
        machine_event(db, machine_id, "TRANSFER_ISSUED", details={"transfer_id": movement.id})
        case = repair(db, machine_id, repair_reference=f"REPAIR-MACHINE-{number}")
        accepted = repair_event(db, case.id, actor.id, "ACCEPTED", status_after="ACCEPTED")
        machine_event(db, machine_id, "REPAIR_ACCEPTED", details={"repair_id": case.id})
        used = persist(
            db,
            RepairPart,
            repair_id=case.id,
            created_by_id=actor.id,
            description=f"Test-only used part machine {number}",
            quantity=2,
            created_at=AT,
        )
        req = request(
            db,
            machine_id,
            request_reference=f"REQUEST-MACHINE-{number}",
            created_at=AT,
            submitted_at=AT,
            ordered_at=AT,
            status="PARTIALLY_DELIVERED",
        )
        approved = approval(db, req.id, actor.id, "APPROVED")
        partial = transition(db, req.id, "ORDERED", "PARTIALLY_DELIVERED")
        docs = [
            official(
                db,
                actor.id,
                None,
                f"DOC-ISSUE-MACHINE-{number}",
                "TRANSFER_ISSUE",
                transfer_id=movement.id,
            ),
            official(
                db,
                actor.id,
                None,
                f"DOC-REPAIR-MACHINE-{number}",
                "REPAIR_PROTOCOL",
                snapshot={"repair_id": case.id},
            ),
            official(
                db,
                actor.id,
                None,
                f"DOC-REQUEST-MACHINE-{number}",
                "PART_REQUEST",
                snapshot={"request_id": req.id},
            ),
        ]
        legacy(
            db,
            actor.id,
            machine_id,
            docs[0].document_number,
            "TRANSFER_ISSUE",
            transfer_id=movement.id,
        )
        legacy(
            db,
            actor.id,
            machine_id,
            f"LEGACY-REPAIR-{number}",
            "REPAIR_PROTOCOL",
            repair_id=case.id,
        )
        legacy(
            db,
            actor.id,
            machine_id,
            f"LEGACY-REQUEST-{number}",
            "PART_REQUEST",
            part_request_id=req.id,
        )
        # Latest-first: every source shares AT except the real earlier issue.
        references[number] = {
            "machine_id": machine_id,
            "transfer_id": movement.id,
            "keys": [
                *[f"official_document:{doc.id}:v1" for doc in reversed(docs)],
                f"part_request_transition:{partial.id}",
                f"part_request_approval:{approved.id}",
                f"part_request:{req.id}:ordered",
                f"part_request:{req.id}:submitted",
                f"part_request:{req.id}:created",
                f"repair_part:{used.id}:used",
                f"repair_event:{accepted.id}",
                f"machine_event:{asset.id}",
                f"transfer:{movement.id}:issued",
            ],
            "official_ids": [d.id for d in docs],
        }
    db.commit()
    return actor, references
