"""Real-PostgreSQL parity coverage for the ASSET-02 passport assembly."""

from __future__ import annotations

from datetime import datetime

import pytest
from app.assets.passport import machine_passport
from app.models import (
    DocumentType,
    Machine,
    PartRequest,
    PartRequestStatus,
    Repair,
    RepairStatus,
    TransferProtocol,
    User,
)
from sqlalchemy import func, select
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_official_document_registry_postgres import (
    _add_canonical_document,
    _add_matching_legacy_pair,
)

pytestmark = pytest.mark.postgres


def _read_only_snapshot(db) -> dict[str, int]:
    return {
        model.__tablename__: db.scalar(select(func.count(model.id))) or 0
        for model in (Machine, Repair, TransferProtocol, PartRequest)
    }


def test_asset02_passport_summary_and_exact_documents_on_real_postgres(
    pg_factory,
):  # noqa: F811
    """Prove deterministic summaries, exact linkage and read-only behavior on PostgreSQL."""
    assert pg_factory.kw["bind"].dialect.name == "postgresql"

    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.email == "admin@assetcore.local"))
        machines = {
            machine.inventory_number: machine
            for machine in db.scalars(
                select(Machine).where(Machine.inventory_number.in_(("4", "14")))
            )
        }
        assert actor is not None
        assert set(machines) == {"4", "14"}
        target = machines["4"]
        other = machines["14"]
        tie_at = datetime(2026, 9, 3, 12, 0)

        older_repair = Repair(
            machine_id=target.id,
            repair_reference="PG-ASSET02-REPAIR-OLDER",
            reported_problem="PostgreSQL ASSET-02 deterministic repair fixture",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 1, 8, 0),
            closed_at=tie_at,
            test_passed=True,
        )
        latest_repair = Repair(
            machine_id=target.id,
            repair_reference="PG-ASSET02-REPAIR-LATEST",
            reported_problem="PostgreSQL ASSET-02 tie-break fixture",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 2, 8, 0),
            closed_at=tie_at,
            test_passed=True,
        )
        other_repair = Repair(
            machine_id=other.id,
            repair_reference="PG-ASSET02-REPAIR-MACHINE-14",
            reported_problem="PostgreSQL ASSET-02 exact-link guard fixture",
            status=RepairStatus.COMPLETED.value,
            opened_at=datetime(2026, 9, 2, 8, 0),
            closed_at=tie_at,
        )
        db.add_all([older_repair, latest_repair, other_repair])
        db.flush()

        first_transfer = TransferProtocol(
            machine_id=target.id,
            protocol_number="PG-ASSET02-TRANSFER-FIRST",
            protocol_type="Предаване",
            is_active=False,
            issued_by_id=actor.id,
            issued_at=datetime(2026, 9, 1, 9, 0),
            returned_at=tie_at,
            created_at=datetime(2026, 9, 1, 8, 30),
        )
        latest_transfer = TransferProtocol(
            machine_id=target.id,
            protocol_number="PG-ASSET02-TRANSFER-LATEST",
            protocol_type="Предаване",
            is_active=False,
            issued_by_id=actor.id,
            issued_at=tie_at,
            created_at=datetime(2026, 9, 1, 8, 0),
        )
        db.add_all([first_transfer, latest_transfer])

        first_pending = PartRequest(
            machine_id=target.id,
            part_name="PostgreSQL ASSET-02 pending fixture one",
            quantity=1,
            status=PartRequestStatus.APPROVED.value,
            request_reference="PG-ASSET02-REQUEST-FIRST",
            requested_by_id=actor.id,
            created_at=tie_at,
        )
        latest_pending = PartRequest(
            machine_id=target.id,
            part_name="PostgreSQL ASSET-02 pending fixture two",
            quantity=1,
            status=PartRequestStatus.ORDERED.value,
            request_reference="PG-ASSET02-REQUEST-LATEST",
            requested_by_id=actor.id,
            created_at=tie_at,
        )
        delivered = PartRequest(
            machine_id=target.id,
            part_name="PostgreSQL ASSET-02 terminal fixture",
            quantity=1,
            status=PartRequestStatus.DELIVERED.value,
            request_reference="PG-ASSET02-REQUEST-TERMINAL",
            requested_by_id=actor.id,
            created_at=tie_at,
        )
        db.add_all([first_pending, latest_pending, delivered])
        db.flush()

        canonical = _add_canonical_document(
            db,
            number="PG-ASSET02-CANONICAL-MACHINE-4",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            machine_id=target.id,
            snapshot={"repair_id": latest_repair.id},
            created_at=tie_at,
        )
        _add_matching_legacy_pair(
            db,
            number=canonical.document_number,
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            machine_id=target.id,
            repair_id=latest_repair.id,
            created_at=tie_at,
        )
        _add_canonical_document(
            db,
            number="PG-ASSET02-CANONICAL-MACHINE-14",
            document_type=DocumentType.REPAIR_PROTOCOL.value,
            actor_id=actor.id,
            machine_id=other.id,
            snapshot={"repair_id": other_repair.id},
            created_at=tie_at,
        )
        db.commit()

        before = _read_only_snapshot(db)
        canonical_id = canonical.id
        latest_repair_id = latest_repair.id
        latest_transfer_id = latest_transfer.id
        passport = machine_passport(target.id, actor, db)

        assert passport["current_state"]["last_completed_repair"]["id"] == (
            latest_repair_id
        )
        assert passport["current_state"]["last_transfer"]["id"] == latest_transfer_id
        assert passport["current_state"]["pending_part_requests"] == {
            "count": 2,
            "latest_request_reference": "PG-ASSET02-REQUEST-LATEST",
        }
        assert [item["protocol_number"] for item in passport["transfers"]] == [
            "PG-ASSET02-TRANSFER-LATEST",
            "PG-ASSET02-TRANSFER-FIRST",
        ]

        documents = [
            document
            for item in passport["official_documents"]
            for document in item["documents"]
        ]
        assert len(documents) == 1
        assert documents[0]["official_document_id"] == canonical_id
        assert documents[0]["document_number"] == "PG-ASSET02-CANONICAL-MACHINE-4"
        assert all(
            item["machine_id"] == target.id
            for item in passport["official_documents"]
        )
        assert all(
            document["display_separately"] is False
            for document in passport["generated_documents"]
        )
        assert "PG-ASSET02-CANONICAL-MACHINE-14" not in str(
            passport["official_documents"]
        )

        db.expire_all()
        assert _read_only_snapshot(db) == before
        assert not db.new
        assert not db.dirty
        assert not db.deleted
