"""Real, overlapping PostgreSQL domain transactions against migrated QA schemas.

No HTTP/SQLite simulation: a third connection holds the canonical row while
both independent worker connections demonstrably wait on PostgreSQL locks.
Only random schemas in the explicitly named concurrency test DB are removed.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.hardening_api import start_emergency_access
from app.hardening_schemas import EmergencyAccessStart
from app.industrial_api import (
    create_multi_part_request,
    create_repair_case,
    decide_part_request,
    generate_part_request_documents,
)
from app.industrial_schemas import (
    MultiPartRequestCreate,
    PartRequestDecision,
    PartRequestLineCreate,
    RepairCaseCreate,
)
from app.models import (
    ApprovalDecision,
    AuditLog,
    DocumentParticipant,
    EmergencyAccessSession,
    ExternalSigner,
    GeneratedDocument,
    InstallationOwnership,
    Location,
    Machine,
    MachineEvent,
    OfficialDocument,
    OfficialDocumentVersion,
    PartCatalog,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    ProtocolDocument,
    Repair,
    RepairEvent,
    TransferBatch,
    TransferProtocol,
    User,
)
from app.schemas import BulkIssueRequest
from app.security import hash_password
from app.seed import seed_database
from app.transfer_service import TransferServiceError, bulk_issue
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def pg_factory():
    value = os.environ.get("ASSETCORE_POSTGRES_CONCURRENCY_URL")
    if not value:
        if os.environ.get("ASSETCORE_REQUIRE_POSTGRES_TESTS") == "true":
            pytest.fail("PostgreSQL concurrency URL is required in this CI job.")
        pytest.skip("Dedicated PostgreSQL concurrency database is not configured.")
    url = make_url(value)
    if url.get_backend_name() != "postgresql" or url.database != "assetcore_test_concurrency":
        pytest.fail("Concurrency tests require the dedicated assetcore_test_concurrency DB.")
    schema = f"pr31_{uuid4().hex}"
    admin = create_engine(url, connect_args={"connect_timeout": 10})
    engine = create_engine(
        url,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c search_path={schema} -c lock_timeout=15000 -c statement_timeout=45000",
        },
    )
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        config = Config(str(ROOT / "backend/alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "backend/alembic"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        factory = sessionmaker(engine, autoflush=False)
        with factory() as db:
            seed_database(db)
            owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            assert owner is not None
            # QA identity only in this disposable schema, never business seed data.
            owner.first_name, owner.middle_name, owner.last_name = "QA", "Concurrent", "Owner"
            owner.full_name = "QA Concurrent Owner"
            owner.job_title = "QA operator"
            owner.profile_status = "PROFILE_COMPLETE"
            db.commit()
        yield factory
    finally:
        engine.dispose()
        with admin.begin() as connection:
            # schema is generated above, not user/config input; never drop a DB.
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


@dataclass(frozen=True)
class Outcome:
    status: int
    code: str | None = None


def race(factory, model, identifier, operations, success_status=201):
    barrier = Barrier(3, timeout=12)
    pids = [None, None]
    engine = factory.kw["bind"]

    def worker(index):
        with factory() as db:
            pids[index] = db.scalar(text("SELECT pg_backend_pid()"))
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                operations[index](db, actor)
                return Outcome(success_status)
            except (HTTPException, TransferServiceError) as exc:
                db.rollback()
                code = (
                    exc.code
                    if isinstance(exc, TransferServiceError)
                    else (exc.detail.get("code") if isinstance(exc.detail, dict) else None)
                )
                return Outcome(exc.status_code, code)

    with engine.connect() as coordinator, ThreadPoolExecutor(max_workers=2) as pool:
        coordinator.execute(select(model.id).where(model.id == identifier).with_for_update())
        futures = [pool.submit(worker, index) for index in range(2)]
        try:
            barrier.wait()
            assert len(set(pids)) == 2
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                # Clear PostgreSQL's statistics snapshot on each poll. Both
                # connections must be waiting before the coordinator releases.
                coordinator.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = coordinator.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids) "
                        "AND wait_event_type = 'Lock' AND cardinality(pg_blocking_pids(pid)) > 0"
                    ),
                    {"pids": pids},
                )
                if waiting == 2:
                    break
                if any(future.done() for future in futures):
                    pytest.fail("A worker finished before both canonical row locks overlapped.")
                time.sleep(0.025)
            else:
                pytest.fail("Both transactions did not overlap on PostgreSQL locks in time.")
        finally:
            coordinator.rollback()
        outcomes = [future.result(timeout=50) for future in futures]
    assert sorted(item.status for item in outcomes) == [success_status, 409]
    return outcomes


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def audit(db, action):
    return db.scalars(select(AuditLog).where(AuditLog.action == action)).all()


def assert_document_ownership(db):
    for version in db.scalars(select(OfficialDocumentVersion)):
        assert db.get(OfficialDocument, version.document_id) is not None
    for document in db.scalars(select(OfficialDocument)):
        version = db.get(OfficialDocumentVersion, document.current_version_id)
        assert version is not None and version.document_id == document.id
    for participant in db.scalars(select(DocumentParticipant)):
        assert db.get(OfficialDocumentVersion, participant.document_version_id) is not None


def test_two_issue_transactions_create_one_active_transfer(pg_factory, issue_payload):
    with pg_factory() as db:
        machine = db.scalar(select(Machine).where(Machine.inventory_number == "4"))
        machine_id, before_status, before_location = machine.id, machine.status, machine.location_id
        payload = issue_payload(machine_id)
        payload["location_id"] = db.scalar(select(Location.id).where(Location.is_active.is_(True)))
    data = BulkIssueRequest.model_validate(payload)
    outcomes = race(
        pg_factory, Machine, machine_id, [lambda db, actor: bulk_issue(db, actor, data)] * 2
    )
    assert next(item for item in outcomes if item.status == 409).code == "issue_conflict"
    with pg_factory() as db:
        assert count(db, TransferProtocol) == count(db, TransferBatch) == 1
        transfer = db.scalar(select(TransferProtocol))
        assert transfer.is_active and transfer.machine_id == machine_id
        assert transfer.issue_status == "AWAITING_SIGNATURE"
        machine = db.get(Machine, machine_id)
        assert (machine.status, machine.location_id) == (before_status, before_location)
        documents = db.scalars(select(ProtocolDocument)).all()
        assert len(documents) == 2 and {item.format for item in documents} == {"docx", "pdf"}
        assert all(
            item.transfer_id == transfer.id and item.batch_id == transfer.batch_id
            for item in documents
        )
        # Individual protocol + the existing batch signing document, not two issues.
        assert count(db, OfficialDocument) == count(db, OfficialDocumentVersion) == 2
        assert count(db, ExternalSigner) == 1
        assert len(audit(db, "Издаването очаква подписи")) == 1
        assert len(audit(db, "Групово издаване – очаква подписи")) == 1
        assert len(audit(db, "Отказано групово издаване")) == 1
        assert count(db, MachineEvent) == 1
        assert_document_ownership(db)


def test_two_open_repair_transactions_create_one_repair(pg_factory):
    with pg_factory() as db:
        machine_id = db.scalar(select(Machine.id).where(Machine.inventory_number == "4"))
    payload = RepairCaseCreate(machine_id=machine_id, reported_problem="QA concurrent repair")
    outcomes = race(
        pg_factory,
        Machine,
        machine_id,
        [
            lambda db, actor: create_repair_case(payload, user=actor, db=db),
        ]
        * 2,
    )
    assert next(item for item in outcomes if item.status == 409).code == "open_repair_exists"
    with pg_factory() as db:
        assert count(db, Repair) == count(db, RepairEvent) == count(db, MachineEvent) == 1
        repair = db.scalar(select(Repair))
        assert repair.machine_id == machine_id and repair.status == "ACCEPTED"
        assert db.scalar(select(RepairEvent)).repair_id == repair.id
        assert db.get(Machine, machine_id).status == "REPAIR"
        assert len(audit(db, "Създаден вътрешен ремонт")) == 1
        assert count(db, OfficialDocument) == count(db, GeneratedDocument) == 0


def create_request(factory, *, approve=False):
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        part = db.scalar(
            select(PartCatalog).where(
                PartCatalog.is_verified.is_(True), PartCatalog.is_active.is_(True)
            )
        )
        assert part is not None
        machine_id = db.scalar(
            select(Machine.id).where(
                Machine.inventory_number.in_(
                    [str(number) for number in part.compatible_machine_numbers]
                )
            )
        )
        assert machine_id is not None
        payload = MultiPartRequestCreate(
            machine_id=machine_id,
            submit_for_approval=True,
            reason="QA concurrent request",
            lines=[
                PartRequestLineCreate(
                    catalog_part_id=part.id,
                    part_number=part.part_number,
                    description=part.description,
                    quantity=1,
                    position=part.position,
                    unit=part.unit,
                    source_document=part.source_document,
                    source_page=part.source_page,
                )
            ],
        )
        result = create_multi_part_request(payload, user=actor, db=db)
        if approve:
            decide_part_request(
                result["id"],
                PartRequestDecision(decision=ApprovalDecision.APPROVED),
                user=actor,
                db=db,
            )
        return result["id"]


def test_conflicting_part_request_decisions_have_one_canonical_outcome(pg_factory):
    identifier = create_request(pg_factory)
    outcomes = race(
        pg_factory,
        PartRequest,
        identifier,
        [
            lambda db, actor: decide_part_request(
                identifier,
                PartRequestDecision(decision=ApprovalDecision.APPROVED),
                user=actor,
                db=db,
            ),
            lambda db, actor: decide_part_request(
                identifier,
                PartRequestDecision(decision=ApprovalDecision.REJECTED),
                user=actor,
                db=db,
            ),
        ],
        success_status=200,
    )
    assert (
        next(item for item in outcomes if item.status == 409).code
        == "part_request_not_waiting_approval"
    )
    with pg_factory() as db:
        assert (
            count(db, PartRequest)
            == count(db, PartRequestLine)
            == count(db, PartRequestApproval)
            == 1
        )
        item = db.get(PartRequest, identifier)
        approval = db.scalar(select(PartRequestApproval))
        assert approval.request_id == identifier and approval.decision == item.status
        assert item.status == ("APPROVED" if outcomes[0].status == 200 else "REJECTED")
        logs = audit(db, "Решение по заявка за части")
        assert len(logs) == 1 and json.loads(logs[0].details)["new_status"] == item.status
        assert item.decided_at and item.decided_by_id == approval.decided_by_id
        assert count(db, OfficialDocument) == count(db, GeneratedDocument) == 0


def test_two_parts_protocol_generations_create_one_canonical_document(pg_factory):
    identifier = create_request(pg_factory, approve=True)

    def operation(db, actor):
        return generate_part_request_documents(identifier, language="bg", user=actor, db=db)

    outcomes = race(pg_factory, PartRequest, identifier, [operation] * 2)
    assert (
        next(item for item in outcomes if item.status == 409).code
        == "part_request_protocol_already_generated"
    )
    with pg_factory() as db:
        assert count(db, OfficialDocument) == count(db, OfficialDocumentVersion) == 1
        assert (
            count(db, PartRequest)
            == count(db, PartRequestLine)
            == count(db, PartRequestApproval)
            == 1
        )
        canonical = db.scalar(select(OfficialDocument))
        assert canonical.document_number == db.get(PartRequest, identifier).request_reference
        documents = db.scalars(select(GeneratedDocument)).all()
        assert len(documents) == 2 and {item.format for item in documents} == {"docx", "pdf"}
        assert all(
            item.part_request_id == identifier and item.document_number == canonical.document_number
            for item in documents
        )
        assert all(hashlib.sha256(item.content).hexdigest() == item.sha256 for item in documents)
        version = db.scalar(select(OfficialDocumentVersion))
        before = (
            version.snapshot,
            version.snapshot_sha256,
            version.docx_sha256,
            version.pdf_sha256,
        )
        assert version.docx_content.startswith(b"PK") and version.pdf_content.startswith(b"%PDF")
        assert_document_ownership(db)
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        with pytest.raises(HTTPException) as rejected:
            operation(db, actor)
        assert rejected.value.status_code == 409
        db.rollback()
        db.refresh(version)
        assert (
            version.snapshot,
            version.snapshot_sha256,
            version.docx_sha256,
            version.pdf_sha256,
        ) == before
        assert count(db, OfficialDocument) == count(db, OfficialDocumentVersion) == 1
        assert len(audit(db, "Генериран документ за заявка за части")) == 1


def test_two_emergency_starts_keep_one_owner_and_one_active_session(pg_factory):
    password = secrets.token_urlsafe(32)
    with pg_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        identifier, owner_id = ownership.id, ownership.owner_user_id
        actor = db.get(User, owner_id)
        actor.password_hash = hash_password(password)
        db.commit()
    data = EmergencyAccessStart(current_password=password, reason="QA concurrent emergency start")

    def operation(db, actor):
        request = Request(
            {
                "type": "http",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "method": "POST",
                "path": "/api/emergency-access/start",
            }
        )
        return start_emergency_access(data, request, actor=actor, db=db)

    outcomes = race(pg_factory, InstallationOwnership, identifier, [operation] * 2)
    assert (
        next(item for item in outcomes if item.status == 409).code
        == "emergency_access_already_active"
    )
    with pg_factory() as db:
        assert count(db, EmergencyAccessSession) == count(db, InstallationOwnership) == 1
        item = db.scalar(select(EmergencyAccessSession))
        assert item.owner_user_id == owner_id and item.ended_at is None
        assert db.get(InstallationOwnership, identifier).owner_user_id == owner_id
        assert db.get(User, owner_id).role == "administrator"
        assert len(audit(db, "Започната контролирана аварийна административна процедура")) == 1
        assert len(audit(db, "Отказано повторно начало на аварийна административна процедура")) == 1
        assert all(password not in (entry.details or "") for entry in db.scalars(select(AuditLog)))
