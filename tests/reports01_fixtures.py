"""Explicitly synthetic records, only for disposable test/loopback QA databases."""

from datetime import UTC, datetime, timedelta

from app.models import (
    AssetCategory,
    Machine,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    Repair,
    RepairEvent,
    RepairPart,
    RequestApprovalSnapshot,
    RequestDeliveryEvent,
    TransferBatch,
    TransferProtocol,
    User,
)
from sqlalchemy import select


def reports_fixture(db, now=None):
    now = now or datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
    category = AssetCategory(
        code="REPORTS01_QA",
        name_bg="REPORTS-01 QA",
        name_en="REPORTS-01 QA",
        name_ru="REPORTS-01 QA",
        capabilities=["HAS_TRANSFER_WORKFLOW", "HAS_REPAIR_WORKFLOW", "HAS_PARTS_CATALOG"],
    )
    db.add(category)
    db.flush()
    machines = [
        Machine(
            inventory_number=f"REPORTS-QA-{i}",
            name=f"Synthetic reports QA {i}",
            category="REPORTS01_QA",
            category_id=category.id,
            brand="QA",
            model="Synthetic",
            status="REPAIR" if i == 1 else "READY",
        )
        for i in range(1, 4)
    ]
    db.add_all(machines)
    db.flush()
    batch = TransferBatch(
        batch_reference="REPORTS-QA-B1", created_by_id=owner.id, status="PARTIALLY_RETURNED"
    )
    second = TransferBatch(
        batch_reference="REPORTS-QA-B2", created_by_id=owner.id, status="PARTIALLY_RETURNED"
    )
    db.add_all([batch, second])
    db.flush()
    transfers = []
    for index, (machine, group, start, end) in enumerate(
        [
            (machines[0], batch, 20, 18),
            (machines[1], batch, 20, None),
            (machines[2], batch, 20, 17),
            (machines[0], second, 15, 13),
            (machines[2], second, 15, None),
        ],
        1,
    ):
        transfer = TransferProtocol(
            machine_id=machine.id,
            batch_id=group.id,
            protocol_number=f"REPORTS-QA-T{index}",
            issue_status="COMPLETED",
            issued_at=now - timedelta(days=start),
            is_active=end is None,
            return_status="COMPLETED" if end else None,
            returned_at=now - timedelta(days=end) if end else None,
            return_next_status="REPAIR" if index == 1 else "READY" if end else None,
            return_damage="Synthetic QA damage" if index == 1 else None,
        )
        db.add(transfer)
        transfers.append(transfer)
    db.flush()
    for index, days in enumerate([70, 50, 20, 10, 8]):
        opened = now - timedelta(days=days)
        repair = Repair(
            machine_id=machines[0].id,
            reported_problem=f"Synthetic QA problem {index + 1}",
            repair_reference=f"REPORTS-QA-R{index + 1}",
            opened_at=opened,
            started_at=opened + timedelta(hours=1) if index < 3 else None,
            closed_at=opened + timedelta(days=1) if index < 4 else None,
            status="COMPLETED" if index < 4 else "REPAIRING",
            source_return_transfer_id=transfers[0].id if index == 4 else None,
            diagnosis_minutes=10 if index == 0 else None,
            repair_minutes=30 if index == 0 else None,
            testing_minutes=5 if index == 0 else None,
        )
        db.add(repair)
        db.flush()
        for _ in range(2):
            db.add(
                RepairEvent(
                    repair_id=repair.id,
                    user_id=owner.id,
                    event_type="NOTE",
                    description="Synthetic QA evidence",
                )
            )
        if index == 0:
            db.add(
                RepairPart(
                    repair_id=repair.id,
                    description="Synthetic QA used part",
                    quantity=1,
                    unit="pcs",
                    created_by_id=owner.id,
                    created_at=now - timedelta(days=20),
                )
            )
    request = PartRequest(
        machine_id=machines[0].id,
        part_name="Synthetic QA request",
        quantity=5,
        request_kind="FREE_FORM",
        request_reference="REPORTS-QA-REQUEST",
        status="PARTIALLY_DELIVERED",
        created_at=now - timedelta(days=20),
        ordered_at=now - timedelta(days=20),
        requested_by_id=owner.id,
        submitted_at=now - timedelta(days=20),
    )
    db.add(request)
    db.flush()
    db.add(
        RequestApprovalSnapshot(
            request_id=request.id,
            number=9000,
            official_number="KK9000",
            approved_at=now - timedelta(days=20),
            approved_by_id=owner.id,
            data={"qa_only": True},
            sha256="d" * 64,
        )
    )
    line = PartRequestLine(
        request_id=request.id,
        description="Synthetic QA item",
        quantity=5,
        exact_quantity="5",
        unit="pcs",
        delivered_quantity=0,
    )
    liquid = PartRequestLine(
        request_id=request.id,
        description="Synthetic QA liquid",
        quantity=5.5,
        exact_quantity="5.5",
        unit="l",
        delivered_quantity=0,
    )
    db.add_all([line, liquid])
    db.flush()
    receipt = RequestDeliveryEvent(
        request_id=request.id,
        actor_id=owner.id,
        actor_name="Synthetic QA",
        occurred_at=now.replace(tzinfo=UTC) - timedelta(days=18),
        kind="RECEIPT",
        quantities={str(line.id): "2"},
        idempotency_key="reports-qa-receipt",
        payload_sha256="a" * 64,
    )
    db.add(receipt)
    db.flush()
    db.add_all(
        [
            RequestDeliveryEvent(
                request_id=request.id,
                actor_id=owner.id,
                actor_name="Synthetic QA",
                occurred_at=now.replace(tzinfo=UTC) - timedelta(days=17),
                kind="CORRECTION",
                correction_of_id=receipt.id,
                quantities={str(line.id): "-2"},
                idempotency_key="reports-qa-correction",
                payload_sha256="b" * 64,
            ),
            RequestDeliveryEvent(
                request_id=request.id,
                actor_id=owner.id,
                actor_name="Synthetic QA",
                occurred_at=now.replace(tzinfo=UTC) - timedelta(days=16),
                kind="RECEIPT",
                quantities={str(line.id): "1"},
                idempotency_key="reports-qa-receipt2",
                payload_sha256="c" * 64,
            ),
            PartRequestApproval(
                request_id=request.id,
                decided_by_id=owner.id,
                decision="APPROVED",
                decided_at=now - timedelta(days=20),
            ),
            PartRequest(
                machine_id=None,
                part_name="Synthetic QA general request",
                quantity=1,
                status="APPROVED",
                created_at=now - timedelta(days=2),
            ),
        ]
    )
    db.commit()
    return {
        "now": now,
        "category_id": category.id,
        "machine_ids": [m.id for m in machines],
        "request_id": request.id,
        "owner_id": owner.id,
        "transfer_ids": [t.id for t in transfers],
    }
