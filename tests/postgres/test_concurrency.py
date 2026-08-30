"""Real, overlapping PostgreSQL domain transactions against migrated QA schemas.

No HTTP/SQLite simulation: a third connection holds the canonical row while
both independent worker connections demonstrably wait on PostgreSQL locks.
Only random schemas in the explicitly named concurrency test DB are removed.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.governance.owner_service import transfer_owner
from app.hardening_api import (
    confirm_signature,
    create_official_document,
    create_signature_session,
    signing_summary,
    start_emergency_access,
    submit_signature,
    supersede_document,
)
from app.hardening_schemas import (
    EmergencyAccessStart,
    OfficialDocumentCreate,
    OwnerTransferRequest,
    SignatureSessionCreate,
    SignatureSubmit,
    SupersedeDocumentRequest,
)
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
    AuthSession,
    DocumentParticipant,
    DocumentSignature,
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
    SignatureSession,
    TransferBatch,
    TransferProtocol,
    User,
    UserRole,
    utcnow,
)
from app.schemas import BulkIssueRequest
from app.security import hash_password
from app.seed import seed_database
from app.transfer_service import TransferServiceError, bulk_issue
from fastapi import HTTPException
from PIL import Image, ImageDraw
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


def _request(method: str, path: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "method": method,
            "path": path,
        }
    )


def _postgres_signature_payload(consent_text: str) -> SignatureSubmit:
    output = io.BytesIO()
    image = Image.new("RGBA", (320, 120), "white")
    ImageDraw.Draw(image).line(
        [(15, 80), (70, 30), (135, 88), (205, 25), (300, 75)],
        fill="black",
        width=5,
    )
    image.save(output, format="PNG")
    return SignatureSubmit.model_validate(
        {
            "consent_accepted": True,
            "consent_text": consent_text,
            "strokes": [
                [
                    {"x": 20 + index * 20, "y": 30 + index, "t": index * 10}
                    for index in range(8)
                ]
            ],
            "image_base64": base64.b64encode(output.getvalue()).decode(),
            "canvas_width": 320,
            "canvas_height": 120,
        }
    )


def _prepare_postgres_stale_signature(factory, suffix: str) -> dict:
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        participants = [
            {
                "slot_code": "REQUESTED_BY",
                "operation_role": "QA requester",
                "user_id": actor.id,
            },
            {
                "slot_code": "APPROVED_BY",
                "operation_role": "QA approver",
                "user_id": actor.id,
            },
        ]
        created = create_official_document(
            OfficialDocumentCreate(
                document_number=f"QA-F02-{suffix}",
                document_type="PART_REQUEST",
                snapshot={"test_scope": "postgres-superseded-signing"},
                participants=participants,
            ),
            _request("POST", "/api/official-documents"),
            actor=actor,
            db=db,
        )
        participant_id = created["participants"][0]["id"]
        signing_session = create_signature_session(
            SignatureSessionCreate(participant_id=participant_id),
            _request("POST", "/api/signatures/sessions"),
            actor=actor,
            db=db,
        )
        token = signing_session["signing_token"]
        summary = signing_summary(token, db)
        submit_signature(
            token,
            _postgres_signature_payload(summary["consent_notice"]),
            db,
        )
        document = db.get(OfficialDocument, created["id"])
        version = db.get(OfficialDocumentVersion, document.current_version_id)
        signature = db.scalar(
            select(DocumentSignature).where(
                DocumentSignature.participant_id == participant_id
            )
        )
        session = db.scalar(
            select(SignatureSession).where(
                SignatureSession.participant_id == participant_id
            )
        )
        return {
            "document_id": document.id,
            "version_id": version.id,
            "signature_id": signature.id,
            "session_id": session.id,
            "token": token,
            "participants": participants,
            "snapshot_sha256": version.snapshot_sha256,
            "signing_sha256": version.signing_sha256,
        }


def _postgres_correction_payload(fixture: dict) -> SupersedeDocumentRequest:
    return SupersedeDocumentRequest(
        reason="QA PostgreSQL superseded-signing lifecycle correction.",
        snapshot={"test_scope": "postgres-superseded-signing-correction"},
        participants=fixture["participants"],
    )


def test_postgres_stale_confirm_cannot_reactivate_superseded_version(pg_factory):
    fixture = _prepare_postgres_stale_signature(pg_factory, uuid4().hex)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        supersede_document(
            fixture["document_id"],
            _postgres_correction_payload(fixture),
            _request(
                "POST",
                f"/api/official-documents/{fixture['document_id']}/supersede",
            ),
            actor=actor,
            db=db,
        )
        document = db.get(OfficialDocument, fixture["document_id"])
        first_version = db.get(OfficialDocumentVersion, fixture["version_id"])
        second_version = db.get(OfficialDocumentVersion, document.current_version_id)
        evidence = (
            document.current_version_id,
            first_version.status,
            first_version.finalized_at,
            first_version.snapshot_sha256,
            first_version.signing_sha256,
            second_version.status,
            second_version.snapshot_sha256,
            second_version.signing_sha256,
        )
        with pytest.raises(HTTPException) as rejected:
            confirm_signature(fixture["token"], db)
        assert rejected.value.status_code == 410
        assert rejected.value.detail["code"] == "signing_session_closed"
        db.rollback()

    with pg_factory() as db:
        document = db.get(OfficialDocument, fixture["document_id"])
        first_version = db.get(OfficialDocumentVersion, fixture["version_id"])
        second_version = db.get(OfficialDocumentVersion, document.current_version_id)
        assert (
            document.current_version_id,
            first_version.status,
            first_version.finalized_at,
            first_version.snapshot_sha256,
            first_version.signing_sha256,
            second_version.status,
            second_version.snapshot_sha256,
            second_version.signing_sha256,
        ) == evidence
        assert first_version.status == "SUPERSEDED"
        assert db.get(DocumentSignature, fixture["signature_id"]).confirmed_at is None
        stale_session = db.get(SignatureSession, fixture["session_id"])
        assert stale_session.consumed_at is None and stale_session.rejected_at is None
        assert len(audit(db, "Потвърден ръчен графичен подпис")) == 0


def test_postgres_supersede_and_confirm_race_preserves_canonical_lifecycle(pg_factory):
    fixture = _prepare_postgres_stale_signature(pg_factory, uuid4().hex)
    barrier = Barrier(3, timeout=12)
    pids = [None, None]
    engine = pg_factory.kw["bind"]

    def confirm_worker():
        with pg_factory() as db:
            pids[0] = db.scalar(text("SELECT pg_backend_pid()"))
            barrier.wait()
            try:
                confirm_signature(fixture["token"], db)
                return Outcome(200)
            except HTTPException as exc:
                db.rollback()
                return Outcome(exc.status_code, exc.detail.get("code"))

    def supersede_worker():
        with pg_factory() as db:
            pids[1] = db.scalar(text("SELECT pg_backend_pid()"))
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                supersede_document(
                    fixture["document_id"],
                    _postgres_correction_payload(fixture),
                    _request(
                        "POST",
                        f"/api/official-documents/{fixture['document_id']}/supersede",
                    ),
                    actor=actor,
                    db=db,
                )
                return Outcome(201)
            except HTTPException as exc:
                db.rollback()
                return Outcome(exc.status_code, exc.detail.get("code"))

    with engine.connect() as coordinator, ThreadPoolExecutor(max_workers=2) as pool:
        coordinator.execute(
            select(OfficialDocument.id)
            .where(OfficialDocument.id == fixture["document_id"])
            .with_for_update()
        )
        futures = [pool.submit(confirm_worker), pool.submit(supersede_worker)]
        try:
            barrier.wait()
            assert len(set(pids)) == 2
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                coordinator.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = coordinator.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids) "
                        "AND wait_event_type = 'Lock' "
                        "AND cardinality(pg_blocking_pids(pid)) > 0"
                    ),
                    {"pids": pids},
                )
                if waiting == 2:
                    break
                if any(future.done() for future in futures):
                    pytest.fail("A worker finished before both document locks overlapped.")
                time.sleep(0.025)
            else:
                pytest.fail("Both lifecycle transactions did not overlap in time.")
        finally:
            coordinator.rollback()
        confirm_outcome, supersede_outcome = [
            future.result(timeout=50) for future in futures
        ]

    assert supersede_outcome.status == 201
    assert (confirm_outcome.status, confirm_outcome.code) in {
        (200, None),
        (410, "signing_session_closed"),
    }
    with pg_factory() as db:
        document = db.get(OfficialDocument, fixture["document_id"])
        first_version = db.get(OfficialDocumentVersion, fixture["version_id"])
        second_version = db.get(OfficialDocumentVersion, document.current_version_id)
        assert document.current_version_id == second_version.id
        assert first_version.status == "SUPERSEDED"
        assert first_version.snapshot_sha256 == fixture["snapshot_sha256"]
        assert first_version.signing_sha256 == fixture["signing_sha256"]
        assert second_version.version == 2
        assert second_version.status == "READY_FOR_SIGNATURE"
        assert count(db, OfficialDocumentVersion) == 2
        signature = db.get(DocumentSignature, fixture["signature_id"])
        session = db.get(SignatureSession, fixture["session_id"])
        if confirm_outcome.status == 200:
            assert signature.confirmed_at is not None and session.consumed_at is not None
            assert len(audit(db, "Потвърден ръчен графичен подпис")) == 1
        else:
            assert signature.confirmed_at is None and session.consumed_at is None
            assert len(audit(db, "Потвърден ръчен графичен подпис")) == 0


def _postgres_owner_target(db, nonce: str, suffix: str, password: str) -> User:
    target = User(
        email=f"f03-{suffix}-{nonce}@example.invalid",
        full_name=f"QA F03 Owner {suffix}",
        first_name="QA",
        middle_name="F03",
        last_name=f"Owner {suffix}",
        job_title="Test administrator",
        profile_status="PROFILE_COMPLETE",
        password_hash=hash_password(password),
        role=UserRole.ADMINISTRATOR.value,
        is_active=True,
    )
    db.add(target)
    db.flush()
    return target


def _postgres_auth_session(db, user: User, marker: str) -> AuthSession:
    now = utcnow()
    item = AuthSession(
        user_id=user.id,
        token_hash=hashlib.sha256(f"session-{marker}-{uuid4().hex}".encode()).hexdigest(),
        csrf_token_hash=hashlib.sha256(f"csrf-{marker}-{uuid4().hex}".encode()).hexdigest(),
        user_token_version=user.token_version,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=1),
    )
    db.add(item)
    db.flush()
    return item


def _postgres_owner_success_audits(db):
    return db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "installation_owner",
            AuditLog.action == "Прехвърлена собственост на инсталацията",
        )
        .order_by(AuditLog.id)
    ).all()


def test_postgres_owner_transfer_round_trip_a_to_b_to_a_to_b(pg_factory):
    nonce = uuid4().hex
    passwords = {
        "a": secrets.token_urlsafe(32),
        "b": secrets.token_urlsafe(32),
    }
    with pg_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        owner_a = db.get(User, ownership.owner_user_id)
        owner_a.password_hash = hash_password(passwords["a"])
        owner_b = _postgres_owner_target(db, nonce, "b", passwords["b"])
        db.commit()
        owner_ids = {"a": owner_a.id, "b": owner_b.id}
        initial_version = ownership.version
        initial_tokens = {
            key: db.get(User, identifier).token_version
            for key, identifier in owner_ids.items()
        }

    steps = [
        ("a", "b", "F03 PostgreSQL owner A to owner B."),
        ("b", "a", "F03 PostgreSQL reverse owner B to owner A."),
        ("a", "b", "F03 PostgreSQL owner A to owner B again."),
    ]
    session_ids: list[tuple[int, int]] = []
    for sequence, (actor_key, target_key, reason) in enumerate(steps, start=1):
        with pg_factory() as db:
            actor = db.get(User, owner_ids[actor_key])
            target = db.get(User, owner_ids[target_key])
            actor_session = _postgres_auth_session(db, actor, f"{sequence}-actor")
            target_session = _postgres_auth_session(db, target, f"{sequence}-target")
            db.commit()
            session_ids.append((actor_session.id, target_session.id))

            result = transfer_owner(
                OwnerTransferRequest(
                    target_user_id=target.id,
                    current_password=passwords[actor_key],
                    reason=reason,
                ),
                _request("POST", "/api/owner/transfer"),
                actor=actor,
                db=db,
            )
            assert result["owner_user_id"] == target.id
            assert result["designation_version"] == initial_version + sequence

        with pg_factory() as db:
            ownership = db.scalar(select(InstallationOwnership))
            owners = db.scalars(
                select(User).where(User.is_system_owner.is_(True))
            ).all()
            assert len(owners) == 1
            assert ownership.owner_user_id == owners[0].id == owner_ids[target_key]
            assert ownership.version == initial_version + sequence
            assert ownership.designated_by_id == owner_ids[actor_key]
            assert ownership.transfer_reason == reason
            assert owners[0].is_active is True
            assert owners[0].role == UserRole.ADMINISTRATOR.value
            assert (
                db.get(User, owner_ids["a"]).token_version
                == initial_tokens["a"] + sequence
            )
            assert (
                db.get(User, owner_ids["b"]).token_version
                == initial_tokens["b"] + sequence
            )
            actor_session = db.get(AuthSession, session_ids[-1][0])
            target_session = db.get(AuthSession, session_ids[-1][1])
            assert actor_session.revoked_at is not None
            assert actor_session.revoked_reason == "owner_transferred"
            assert target_session.revoked_at is not None
            assert target_session.revoked_reason == "owner_designated"
            entries = _postgres_owner_success_audits(db)
            assert len(entries) == sequence
            details = json.loads(entries[-1].details)
            assert details == {
                "previous_owner_user_id": owner_ids[actor_key],
                "new_owner_user_id": owner_ids[target_key],
                "reason": reason,
                "designation_version": initial_version + sequence,
            }

    with pg_factory() as db:
        assert {
            db.get(User, owner_ids[key]).role for key in ("a", "b")
        } == {UserRole.ADMINISTRATOR.value}
        assert {role.value for role in UserRole} == {
            "administrator",
            "director",
            "mechanic",
            "observer",
        }
        sessions = db.scalars(
            select(AuthSession).where(
                AuthSession.id.in_([identifier for pair in session_ids for identifier in pair])
            )
        ).all()
        assert len(sessions) == 6
        assert all(item.revoked_at is not None for item in sessions)


def test_postgres_overlapping_owner_transfers_are_serialized(pg_factory):
    nonce = uuid4().hex
    owner_password = secrets.token_urlsafe(32)
    target_password = secrets.token_urlsafe(32)
    with pg_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        owner_a = db.get(User, ownership.owner_user_id)
        owner_a.password_hash = hash_password(owner_password)
        owner_b = _postgres_owner_target(db, nonce, "b", target_password)
        owner_c = _postgres_owner_target(db, nonce, "c", target_password)
        _postgres_auth_session(db, owner_a, "race-a")
        _postgres_auth_session(db, owner_b, "race-b")
        _postgres_auth_session(db, owner_c, "race-c")
        db.commit()
        ownership_id = ownership.id
        initial_version = ownership.version
        owner_a_id = owner_a.id
        target_ids = [owner_b.id, owner_c.id]
        initial_tokens = {
            item.id: item.token_version for item in (owner_a, owner_b, owner_c)
        }

    reasons = [
        "F03 overlapping transfer from owner A to administrator B.",
        "F03 overlapping transfer from owner A to administrator C.",
    ]
    barrier = Barrier(3, timeout=12)
    pids = [None, None]
    engine = pg_factory.kw["bind"]

    def worker(index):
        with pg_factory() as db:
            pids[index] = db.scalar(text("SELECT pg_backend_pid()"))
            actor = db.get(User, owner_a_id)
            barrier.wait()
            try:
                transfer_owner(
                    OwnerTransferRequest(
                        target_user_id=target_ids[index],
                        current_password=owner_password,
                        reason=reasons[index],
                    ),
                    _request("POST", "/api/owner/transfer"),
                    actor=actor,
                    db=db,
                )
                return Outcome(200)
            except HTTPException as exc:
                db.rollback()
                return Outcome(
                    exc.status_code,
                    exc.detail.get("code") if isinstance(exc.detail, dict) else None,
                )

    with engine.connect() as coordinator, ThreadPoolExecutor(max_workers=2) as pool:
        coordinator.execute(
            select(InstallationOwnership.id)
            .where(InstallationOwnership.id == ownership_id)
            .with_for_update()
        )
        futures = [pool.submit(worker, index) for index in range(2)]
        try:
            barrier.wait()
            assert len(set(pids)) == 2
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                coordinator.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = coordinator.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(:pids) "
                        "AND wait_event_type = 'Lock' "
                        "AND cardinality(pg_blocking_pids(pid)) > 0"
                    ),
                    {"pids": pids},
                )
                if waiting == 2:
                    break
                if any(future.done() for future in futures):
                    pytest.fail(
                        "An owner transfer finished before both canonical locks overlapped."
                    )
                time.sleep(0.025)
            else:
                pytest.fail("Both owner transfers did not overlap on PostgreSQL locks.")
        finally:
            coordinator.rollback()
        outcomes = [future.result(timeout=50) for future in futures]

    assert sorted(item.status for item in outcomes) == [200, 403]
    loser = next(item for item in outcomes if item.status == 403)
    assert loser.code == "owner_only"
    winner_index = next(index for index, item in enumerate(outcomes) if item.status == 200)
    winner_id = target_ids[winner_index]
    loser_id = target_ids[1 - winner_index]

    with pg_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        owners = db.scalars(select(User).where(User.is_system_owner.is_(True))).all()
        assert len(owners) == 1
        assert ownership.owner_user_id == owners[0].id == winner_id
        assert ownership.version == initial_version + 1
        assert ownership.designated_by_id == owner_a_id
        assert ownership.transfer_reason == reasons[winner_index]
        assert db.get(User, owner_a_id).token_version == initial_tokens[owner_a_id] + 1
        assert db.get(User, winner_id).token_version == initial_tokens[winner_id] + 1
        assert db.get(User, loser_id).token_version == initial_tokens[loser_id]
        sessions = {
            item.user_id: item
            for item in db.scalars(
                select(AuthSession).where(
                    AuthSession.user_id.in_([owner_a_id, *target_ids])
                )
            )
        }
        assert sessions[owner_a_id].revoked_reason == "owner_transferred"
        assert sessions[winner_id].revoked_reason == "owner_designated"
        assert sessions[loser_id].revoked_at is None
        assert sessions[loser_id].revoked_reason is None
        entries = _postgres_owner_success_audits(db)
        assert len(entries) == 1
        assert json.loads(entries[0].details) == {
            "previous_owner_user_id": owner_a_id,
            "new_owner_user_id": winner_id,
            "reason": reasons[winner_index],
            "designation_version": initial_version + 1,
        }
