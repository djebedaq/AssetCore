"""Real PostgreSQL 16 rollback, row-lock and historical migration evidence."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from app.models import (
    ApprovalDecision,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    RequestApprovalSnapshot,
    RequestNumberCounter,
    User,
)
from app.part_requests.request_routes import add_delivery
from app.part_requests.request_schemas import DeliveryCreate
from app.part_requests.service import decide_request, load_request
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def test_pg_upgrade_existing_schema_preserves_history(pg_factory):
    from test_requests01_migrations import verify_upgrade

    verify_upgrade(pg_factory.kw["bind"])


def make_requests(factory, count=1):
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        items = []
        for index in range(count):
            request = PartRequest(
                part_name="QA request",
                request_kind="FREE_FORM" if index % 2 == 0 else "CATALOG",
                department="QA",
                status="WAITING_APPROVAL",
                requested_by_id=actor.id,
            )
            request.lines.append(
                PartRequestLine(
                    description="QA exact quantity",
                    quantity=2.5 if index % 2 == 0 else 1,
                    exact_quantity="2.5" if index % 2 == 0 else None,
                    unit="l" if index % 2 == 0 else "pcs",
                )
            )
            db.add(request)
            db.flush()
            request.request_reference = f"PR-QA-{request.id}"
            items.append(request.id)
        actor_id = actor.id
        db.commit()
        return actor_id, items


def test_pg_concurrent_shared_sequence_and_duplicate_approval(pg_factory):
    actor_id, identifiers = make_requests(pg_factory, 8)
    barrier = Barrier(8)

    def approve(identifier):
        with pg_factory() as db:
            barrier.wait(timeout=20)
            request = load_request(db, identifier, lock=True)
            decide_request(db, request, db.get(User, actor_id), ApprovalDecision.APPROVED, None)
            db.commit()
            return request.approval_snapshot.number

    with ThreadPoolExecutor(max_workers=8) as executor:
        numbers = sorted(executor.map(approve, identifiers))
    assert numbers == list(range(1000, 1008))
    barrier = Barrier(8)
    with ThreadPoolExecutor(max_workers=8) as executor:
        repeated = list(executor.map(approve, [identifiers[0]] * 8))
    assert len(set(repeated)) == 1
    with pg_factory() as db:
        assert db.get(RequestNumberCounter, 1).next_value == 1008
        assert db.scalar(select(func.count()).select_from(PartRequestApproval)) == 8
        assert db.scalar(select(func.count()).select_from(RequestApprovalSnapshot)) == 8


def test_pg_rollback_reuses_only_uncommitted_number(pg_factory):
    actor_id, identifiers = make_requests(pg_factory, 2)
    with pg_factory() as db:
        request = load_request(db, identifiers[0], lock=True)
        decide_request(db, request, db.get(User, actor_id), ApprovalDecision.APPROVED, None)
        assert request.approval_snapshot.number == 1000
        db.rollback()
    with pg_factory() as db:
        request = load_request(db, identifiers[1], lock=True)
        decide_request(db, request, db.get(User, actor_id), ApprovalDecision.APPROVED, None)
        db.commit()
        assert request.approval_snapshot.official_number == "KK1000"
        assert db.get(PartRequest, identifiers[0]).status == "WAITING_APPROVAL"


def test_pg_receipt_race_does_not_overdeliver(pg_factory):
    actor_id, identifiers = make_requests(pg_factory)
    with pg_factory() as db:
        request = load_request(db, identifiers[0], lock=True)
        decide_request(db, request, db.get(User, actor_id), ApprovalDecision.APPROVED, None)
        line_id = request.lines[0].id
        db.commit()
    barrier = Barrier(2)

    def receive(index):
        with pg_factory() as db:
            actor = db.get(User, actor_id)
            barrier.wait(timeout=20)
            try:
                result = add_delivery(
                    identifiers[0],
                    DeliveryCreate.model_validate(
                        {
                            "idempotency_key": f"qa-{index}",
                            "lines": [{"line_id": line_id, "quantity": "2"}],
                        }
                    ),
                    actor,
                    db,
                )
                return Decimal(result["lines"][0]["received_quantity"])
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(receive, range(2)))
    assert sorted(results) == [Decimal("2"), 409]


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE part_requests SET reason = 'QA mutation' WHERE id = :id",
        "UPDATE part_request_lines SET exact_quantity = '999' WHERE request_id = :id",
        "DELETE FROM request_approval_snapshots WHERE request_id = :id",
        "UPDATE request_number_counter SET next_value = 1000 WHERE id = 1",
    ],
)
def test_pg_immutable_evidence_database_guards(pg_factory, statement):
    actor_id, identifiers = make_requests(pg_factory)
    with pg_factory() as db:
        request = load_request(db, identifiers[0], lock=True)
        decide_request(db, request, db.get(User, actor_id), ApprovalDecision.APPROVED, None)
        db.commit()
    with pg_factory() as db, pytest.raises(DBAPIError):
        db.execute(text(statement), {"id": identifiers[0]})
        db.commit()
