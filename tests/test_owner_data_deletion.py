"""Physical deletion/security tests: only temporary SQLite files, with FK enforcement."""

from __future__ import annotations

import json
from datetime import timedelta
from http.cookies import SimpleCookie

import pytest
from app.auth_sessions import issue_browser_session
from app.database import Base, _configure_sqlite, get_db
from app.governance import owner_data_deletion as service
from app.main import app
from app.models import (
    AssetCategory,
    AuditLog,
    AuthSession,
    CategoryFieldDefinition,
    Department,
    DocumentParticipant,
    ExternalSigner,
    GeneratedDocument,
    InstallationOwnership,
    Location,
    Machine,
    MachineAttachment,
    MachineEvent,
    MachineFieldValue,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    Repair,
    SignatureSlot,
    TransferProtocol,
    User,
    utcnow,
)
from app.security import create_access_token, hash_password
from app.seed import MACHINES, seed_database
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

QA_PASSWORD = "Deletion-QA-only123!"


@pytest.fixture()
def deletion_factory(tmp_path):
    # This fixture never uses the application engine or any configured DB URL.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'owner-deletion.db'}", connect_args={"check_same_thread": False}
    )
    event.listen(engine, "connect", _configure_sqlite)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False)
    with factory() as db:
        owner = User(
            email="owner@qa.invalid",
            full_name="QA Owner",
            role="administrator",
            is_system_owner=True,
            password_hash=hash_password(QA_PASSWORD),
        )
        db.add(owner)
        db.flush()
        db.add(InstallationOwnership(owner_user_id=owner.id, designated_by_id=owner.id))
        db.commit()
    yield factory
    engine.dispose()


@pytest.fixture()
def deletion_client(deletion_factory):
    def override_db():
        with deletion_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with deletion_factory() as db:
        headers = {"Authorization": f"Bearer {create_access_token(db.get(User, 1))}"}
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield client, headers
    finally:
        client.close()
        app.dependency_overrides.clear()


def target(factory, model, **values):
    with factory() as db:
        item = model(**values)
        db.add(item)
        db.commit()
        return item.id


def user(factory, role="observer", **values):
    return target(
        factory,
        User,
        email=f"{role}@qa.invalid",
        full_name="QA Disposable User",
        password_hash=hash_password(QA_PASSWORD),
        role=role,
        **values,
    )


def machine(factory, **values):
    return target(
        factory,
        Machine,
        inventory_number="QA-DELETE",
        name="QA Disposable Asset",
        category="QA",
        brand="QA",
        **values,
    )


def preview(pair, kind, identifier, **params):
    client, headers = pair
    return client.get(
        f"/api/owner/data-deletion/{kind}/{identifier}/preview", headers=headers, params=params
    )


def execute(pair, kind, identifier, phrase, **values):
    client, headers = pair
    return client.post(
        f"/api/owner/data-deletion/{kind}/{identifier}/execute",
        headers=headers,
        json={"current_password": QA_PASSWORD, "confirmation_text": phrase, **values},
    )


@pytest.mark.parametrize("role", ["administrator", "director", "mechanic", "observer"])
def test_ordinary_roles_cannot_preview_or_execute(deletion_client, deletion_factory, role):
    identifier = user(deletion_factory, role)
    with deletion_factory() as db:
        headers = {"Authorization": f"Bearer {create_access_token(db.get(User, identifier))}"}
    pair = deletion_client[0], headers
    for response in (
        preview(pair, "user", identifier),
        execute(pair, "user", identifier, "DELETE"),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "owner_only"
    with deletion_factory() as db:
        assert db.get(User, identifier) is not None


@pytest.mark.parametrize("tampering", ["flag", "designation", "active", "role"])
def test_owner_guard_rechecks_all_invariants(deletion_client, deletion_factory, tampering):
    if tampering in {"active", "role"}:
        # DB invariant prevents even a malformed owner flag on these users.
        with deletion_factory() as db:
            owner = db.get(User, 1)
            if tampering == "active":
                owner.is_active = False
            else:
                owner.role = "director"
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
            assert db.get(User, 1).is_active and db.get(User, 1).role == "administrator"
        return
    with deletion_factory() as db:
        if tampering == "flag":
            db.get(User, 1).is_system_owner = False
        else:
            other = User(
                email="designation@qa.invalid",
                full_name="QA",
                role="administrator",
                password_hash=hash_password(QA_PASSWORD),
            )
            db.add(other)
            db.flush()
            db.scalar(select(InstallationOwnership)).owner_user_id = other.id
        db.commit()
    assert preview(deletion_client, "location", 1).status_code == 403
    assert execute(deletion_client, "location", 1, "DELETE").status_code == 403


def test_owner_is_protected_and_preview_does_not_mutate(deletion_client, deletion_factory):
    with deletion_factory() as db:
        before = [(log.id, log.details) for log in db.scalars(select(AuditLog))]
    response = preview(deletion_client, "user", 1)
    assert response.status_code == 200
    assert not response.json()["can_delete"]
    assert response.json()["blockers"][0]["code"] == "system_owner_protected"
    with deletion_factory() as db:
        assert before == [(log.id, log.details) for log in db.scalars(select(AuditLog))]
    rejected = execute(deletion_client, "user", 1, response.json()["confirmation_text"])
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "system_owner_protected"
    with deletion_factory() as db:
        assert db.get(User, 1).is_system_owner


def test_unused_nonowner_administrator_physically_deleted_sessions_and_audit(
    deletion_client, deletion_factory
):
    identifier = user(deletion_factory, "administrator")
    with deletion_factory() as db:
        bearer = create_access_token(db.get(User, identifier))
        db.add(
            AuthSession(
                user_id=identifier,
                token_hash="a" * 64,
                csrf_token_hash="b" * 64,
                user_token_version=0,
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        # entity_id is a historical snapshot, not an FK to the described user.
        db.add(AuditLog(entity_type="user", entity_id=identifier, user_id=1, action="QA_CREATE"))
        db.commit()
    before = preview(deletion_client, "user", identifier).json()
    assert before["can_delete"]
    assert before["owned_records_to_delete"][0]["code"] == "auth_sessions"
    response = execute(deletion_client, "user", identifier, before["confirmation_text"])
    assert response.status_code == 200
    with deletion_factory() as db:
        assert db.get(User, identifier) is None
        assert db.scalar(select(func.count()).select_from(AuthSession)) == 0
        entries = db.scalars(select(AuditLog).where(AuditLog.entity_id == identifier)).all()
        assert len(entries) == 2
        snapshot = json.loads(
            next(log for log in entries if log.action == "OWNER_PERMANENT_DELETE").details
        )
        assert snapshot["identity"] == "administrator@qa.invalid"
        assert QA_PASSWORD not in str(snapshot)
    assert (
        deletion_client[0]
        .get("/api/auth/me", headers={"Authorization": f"Bearer {bearer}"})
        .status_code
        == 401
    )


@pytest.mark.parametrize(
    "change,code,status",
    [
        ({"current_password": "wrong"}, "reauthentication_failed", 403),
        ({"confirmation_text": "DELETE wrong"}, "deletion_confirmation_mismatch", 409),
    ],
)
def test_reauthentication_and_exact_confirmation_required(
    deletion_client, deletion_factory, change, code, status
):
    identifier = user(deletion_factory)
    data = preview(deletion_client, "user", identifier).json()
    phrase = change.get("confirmation_text", data["confirmation_text"])
    values = {key: value for key, value in change.items() if key != "confirmation_text"}
    response = execute(deletion_client, "user", identifier, phrase, **values)
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    with deletion_factory() as db:
        assert db.get(User, identifier) is not None
        log = db.scalar(select(AuditLog))
        assert log.action == "OWNER_PERMANENT_DELETE_REJECTED"
        assert log.operation_reference
        assert "current_password" not in log.details and QA_PASSWORD not in log.details


def test_sensitive_password_throttling_is_persistent(deletion_client, deletion_factory):
    from app.settings import settings

    identifier = user(deletion_factory)
    for _ in range(settings.sensitive_rate_limit_attempts):
        response = execute(deletion_client, "user", identifier, "DELETE", current_password="wrong")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert (
        execute(deletion_client, "user", identifier, "DELETE observer@qa.invalid").status_code
        == 429
    )
    with deletion_factory() as db:
        assert db.get(User, identifier)


@pytest.mark.parametrize(
    "model,values,kind",
    [
        (Department, {"code": "QA", "name_bg": "QA отдел"}, "department"),
        (Location, {"name": "QA disposable location"}, "location"),
        (AssetCategory, {"code": "QA", "name_bg": "QA категория"}, "asset_category"),
        (
            ExternalSigner,
            {
                "first_name": "QA",
                "last_name": "Signer",
                "participant_role": "QA",
                "created_by_id": 1,
            },
            "external_signer",
        ),
        (
            SignatureSlot,
            {"document_type": "OTHER", "code": "QA", "label_bg": "QA"},
            "signature_slot",
        ),
    ],
)
def test_unused_master_records_physically_deleted(
    deletion_client, deletion_factory, model, values, kind
):
    identifier = target(deletion_factory, model, **values)
    data = preview(deletion_client, kind, identifier).json()
    assert data["can_delete"]
    assert execute(deletion_client, kind, identifier, data["confirmation_text"]).status_code == 200
    with deletion_factory() as db:
        assert db.get(model, identifier) is None


@pytest.mark.parametrize("reference", ["users", "machines", "audit_logs", "machine_events"])
def test_current_and_protected_references_block(deletion_client, deletion_factory, reference):
    if reference == "users":
        identifier = target(deletion_factory, Department, code="QA", name_bg="QA")
        user(deletion_factory, department_id=identifier)
        kind, model = "department", Department
    elif reference == "machines":
        identifier = target(deletion_factory, Location, name="QA")
        machine(deletion_factory, location_id=identifier)
        kind, model = "location", Location
    else:
        identifier = user(deletion_factory)
        if reference == "audit_logs":
            target(
                deletion_factory,
                AuditLog,
                entity_type="authentication_session",
                action="QA",
                user_id=identifier,
            )
        else:
            machine_id = machine(deletion_factory)
            target(
                deletion_factory,
                MachineEvent,
                machine_id=machine_id,
                event_type="MACHINE_CREATED",
                user_id=identifier,
            )
        kind, model = "user", User
    data = preview(deletion_client, kind, identifier).json()
    assert not data["can_delete"]
    assert {row["code"]: row["count"] for row in data["blockers"]}[reference] == 1
    response = execute(deletion_client, kind, identifier, data["confirmation_text"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "deletion_blocked"
    with deletion_factory() as db:
        assert db.get(model, identifier)


def test_department_string_alias_and_location_event_history_block(
    deletion_client, deletion_factory
):
    department_id = target(deletion_factory, Department, code="QA", name_bg="QA отдел")
    location_id = target(deletion_factory, Location, name="QA historical location")
    machine_id = machine(deletion_factory, department="  QA ОТДЕЛ  ")
    target(
        deletion_factory,
        MachineEvent,
        machine_id=machine_id,
        event_type="LOCATION_CHANGED",
        previous_location_id=location_id,
    )
    for kind, identifier, code in (
        ("department", department_id, "machines"),
        ("location", location_id, "machine_events"),
    ):
        data = preview(deletion_client, kind, identifier).json()
        assert not data["can_delete"]
        assert any(row["code"] == code for row in data["blockers"])
        assert (
            execute(deletion_client, kind, identifier, data["confirmation_text"]).status_code == 409
        )


def test_category_and_field_safe_cleanup_and_scope(deletion_client, deletion_factory):
    category_id = target(deletion_factory, AssetCategory, code="QA", name_bg="QA")
    field_id = target(
        deletion_factory, CategoryFieldDefinition, category_id=category_id, code="QA", label_bg="QA"
    )
    assert preview(deletion_client, "category_field", field_id).status_code == 422
    assert (
        preview(
            deletion_client, "category_field", field_id, category_id=category_id + 1
        ).status_code
        == 404
    )
    assert (
        execute(
            deletion_client, "category_field", field_id, "DELETE", category_id=category_id + 1
        ).status_code
        == 404
    )
    data = preview(deletion_client, "asset_category", category_id).json()
    assert data["can_delete"] and data["owned_records_to_delete"][0]["count"] == 1
    assert (
        execute(
            deletion_client, "asset_category", category_id, data["confirmation_text"]
        ).status_code
        == 200
    )
    with deletion_factory() as db:
        assert db.get(AssetCategory, category_id) is None
        assert db.get(CategoryFieldDefinition, field_id) is None
    # Removed code is available again.
    target(deletion_factory, AssetCategory, code="QA", name_bg="QA")


def test_unused_field_physically_deleted(deletion_client, deletion_factory):
    category_id = target(deletion_factory, AssetCategory, code="QA", name_bg="QA")
    field_id = target(
        deletion_factory, CategoryFieldDefinition, category_id=category_id, code="QA", label_bg="QA"
    )
    data = preview(deletion_client, "category_field", field_id, category_id=category_id).json()
    assert data["can_delete"]
    assert (
        execute(
            deletion_client,
            "category_field",
            field_id,
            data["confirmation_text"],
            category_id=category_id,
        ).status_code
        == 200
    )
    with deletion_factory() as db:
        assert db.get(CategoryFieldDefinition, field_id) is None
        assert db.get(AssetCategory, category_id)


def test_category_assignment_and_field_values_block(deletion_client, deletion_factory):
    category_id = target(deletion_factory, AssetCategory, code="QA", name_bg="QA")
    field_id = target(
        deletion_factory, CategoryFieldDefinition, category_id=category_id, code="QA", label_bg="QA"
    )
    machine_id = machine(deletion_factory, category_id=category_id)
    target(
        deletion_factory,
        MachineFieldValue,
        machine_id=machine_id,
        field_id=field_id,
        value="retained QA technical value",
    )
    for kind, identifier, params in (
        ("asset_category", category_id, {}),
        ("category_field", field_id, {"category_id": category_id}),
    ):
        data = preview(deletion_client, kind, identifier, **params).json()
        assert not data["can_delete"]
        assert (
            execute(
                deletion_client, kind, identifier, data["confirmation_text"], **params
            ).status_code
            == 409
        )
    with deletion_factory() as db:
        assert db.scalar(select(MachineFieldValue)).value == "retained QA technical value"


def test_machine_baseline_owned_cleanup_and_audit(deletion_client, deletion_factory):
    machine_id = machine(deletion_factory)
    category_id = target(deletion_factory, AssetCategory, code="QA", name_bg="QA")
    field_id = target(
        deletion_factory, CategoryFieldDefinition, category_id=category_id, code="QA", label_bg="QA"
    )
    target(
        deletion_factory, MachineFieldValue, machine_id=machine_id, field_id=field_id, value="QA"
    )
    target(
        deletion_factory,
        MachineEvent,
        machine_id=machine_id,
        event_type="MACHINE_CREATED",
        user_id=1,
    )
    target(
        deletion_factory,
        MachineAttachment,
        machine_id=machine_id,
        filename="QA.txt",
        media_type="text/plain",
        content=b"QA",
        sha256="a" * 64,
        created_by_id=1,
    )
    data = preview(deletion_client, "machine", machine_id).json()
    assert data["can_delete"]
    assert {row["code"] for row in data["owned_records_to_delete"]} == {
        "machine_field_values",
        "machine_events",
        "machine_attachments",
    }
    assert (
        execute(deletion_client, "machine", machine_id, data["confirmation_text"]).status_code
        == 200
    )
    with deletion_factory() as db:
        assert db.get(Machine, machine_id) is None
        for model in (MachineEvent, MachineAttachment, MachineFieldValue):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        log = db.scalar(select(AuditLog))
        assert log.action == "OWNER_PERMANENT_DELETE"
        assert len(json.loads(log.details)["owned_records_to_delete"]) == 3


@pytest.mark.parametrize(
    "reference", ["repair", "transfer", "parts", "generated", "official", "event", "attachment"]
)
def test_machine_protected_history_blocks_without_cascade(
    deletion_client, deletion_factory, reference
):
    machine_id = machine(deletion_factory)
    if reference == "repair":
        target(deletion_factory, Repair, machine_id=machine_id, reported_problem="QA")
    elif reference == "transfer":
        target(
            deletion_factory,
            TransferProtocol,
            machine_id=machine_id,
            protocol_number="QA-TRANSFER",
            condition_text="QA",
        )
    elif reference == "parts":
        target(deletion_factory, PartRequest, machine_id=machine_id, part_name="QA")
    elif reference == "generated":
        target(
            deletion_factory,
            GeneratedDocument,
            machine_id=machine_id,
            document_number="QA",
            document_type="OTHER",
            format="pdf",
            filename="QA.pdf",
            media_type="application/pdf",
            content=b"QA",
            sha256="a" * 64,
            created_by_id=1,
        )
    elif reference == "official":
        target(
            deletion_factory,
            OfficialDocument,
            machine_id=machine_id,
            document_type="OTHER",
            document_number="QA",
            created_by_id=1,
        )
    elif reference == "event":
        target(deletion_factory, MachineEvent, machine_id=machine_id, event_type="TRANSFER_ISSUED")
    else:
        target(
            deletion_factory,
            MachineAttachment,
            machine_id=machine_id,
            kind="OFFICIAL",
            filename="QA.pdf",
            media_type="application/pdf",
            content=b"QA",
            sha256="a" * 64,
            created_by_id=1,
        )
    data = preview(deletion_client, "machine", machine_id).json()
    assert not data["can_delete"]
    assert data["blockers"][0]["count"] == 1
    assert (
        execute(deletion_client, "machine", machine_id, data["confirmation_text"]).status_code
        == 409
    )
    with deletion_factory() as db:
        assert db.get(Machine, machine_id)


def test_stale_preview_is_recomputed(deletion_client, deletion_factory):
    machine_id = machine(deletion_factory)
    data = preview(deletion_client, "machine", machine_id).json()
    assert data["can_delete"]
    target(
        deletion_factory, Repair, machine_id=machine_id, reported_problem="QA concurrent reference"
    )
    response = execute(deletion_client, "machine", machine_id, data["confirmation_text"])
    assert response.status_code == 409
    assert response.json()["detail"]["blockers"][0]["count"] == 1


def test_conflict_rolls_back_child_cleanup_and_success_audit(
    deletion_client, deletion_factory, monkeypatch
):
    machine_id = machine(deletion_factory)
    target(deletion_factory, MachineEvent, machine_id=machine_id, event_type="MACHINE_CREATED")
    data = preview(deletion_client, "machine", machine_id).json()
    original = service.Session.execute

    def fail_target_delete(db, statement, *args, **kwargs):
        if getattr(statement, "is_delete", False) and statement.table.name == "machines":
            raise IntegrityError("private SQL", {}, Exception("private details"))
        return original(db, statement, *args, **kwargs)

    monkeypatch.setattr(service.Session, "execute", fail_target_delete)
    response = execute(deletion_client, "machine", machine_id, data["confirmation_text"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "deletion_conflict"
    assert "private" not in response.text
    with deletion_factory() as db:
        assert db.get(Machine, machine_id)
        assert db.scalar(select(MachineEvent))
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize(
    "kind",
    [
        "table_name",
        "software_license",
        "transfer",
        "technical_document",
        "document_template",
        "repair_kit",
    ],
)
def test_unknown_or_excluded_resource_rejected(deletion_client, kind):
    assert (
        preview(deletion_client, kind, 1).json()["detail"]["code"] == "unsupported_delete_resource"
    )
    response = execute(deletion_client, kind, 1, "DELETE")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_delete_resource"


def test_all_incoming_user_fks_have_reviewed_labels():
    assert all(
        table.name in service.REFERENCE_LABELS for table, _ in service.incoming_references(User)
    )
    assert "audit_logs" in {table.name for table, _ in service.incoming_references(User)}


def test_deleted_user_browser_session_is_invalid(deletion_client, deletion_factory):
    identifier = user(deletion_factory)
    response = Response()
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    with deletion_factory() as db:
        issue_browser_session(db, db.get(User, identifier), request, response)
        db.commit()
    browser = TestClient(app, raise_server_exceptions=False)
    try:
        for header in response.headers.getlist("set-cookie"):
            cookies = SimpleCookie()
            cookies.load(header)
            for name, morsel in cookies.items():
                browser.cookies.set(name, morsel.value)
        assert browser.get("/api/auth/me").status_code == 200
        data = preview(deletion_client, "user", identifier).json()
        assert data["can_delete"]
        assert (
            execute(deletion_client, "user", identifier, data["confirmation_text"]).status_code
            == 200
        )
        assert browser.get("/api/auth/me").status_code == 401
    finally:
        browser.close()


def test_authentication_and_payload_validation_do_not_expose_password(deletion_client):
    client, _ = deletion_client
    assert client.get("/api/owner/data-deletion/user/1/preview").status_code == 401
    response = execute(deletion_client, "user", 1, "DELETE", table_name="users")
    assert response.status_code == 422
    assert QA_PASSWORD not in response.text and "password_hash" not in response.text


def test_owner_is_checked_again_after_writer_lock(deletion_client, deletion_factory, monkeypatch):
    from sqlalchemy import update

    identifier = user(deletion_factory)
    original = service._lock_dependencies

    def lose_ownership(db, kind):
        original(db, kind)
        db.execute(update(User).where(User.id == 1).values(is_system_owner=False))

    monkeypatch.setattr(service, "_lock_dependencies", lose_ownership)
    response = execute(deletion_client, "user", identifier, "DELETE observer@qa.invalid")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_only"
    with deletion_factory() as db:
        assert db.get(User, identifier)
        assert db.get(User, 1).is_system_owner  # All changes rolled back.


def test_signer_and_slot_keep_document_version_identity(deletion_client, deletion_factory):
    signer_id = target(
        deletion_factory,
        ExternalSigner,
        first_name="QA",
        last_name="Signer",
        participant_role="QA",
        created_by_id=1,
    )
    slot_id = target(
        deletion_factory, SignatureSlot, document_type="OTHER", code="QA", label_bg="QA"
    )
    document_id = target(
        deletion_factory,
        OfficialDocument,
        document_number="QA-SIGNED",
        document_type="OTHER",
        created_by_id=1,
    )
    version_id = target(
        deletion_factory,
        OfficialDocumentVersion,
        document_id=document_id,
        version=1,
        snapshot={"identity": "QA frozen"},
        snapshot_sha256="a" * 64,
        prepared_by_id=1,
        docx_content=b"QA retained reference",
    )
    participant_id = target(
        deletion_factory,
        DocumentParticipant,
        document_version_id=version_id,
        slot_code="QA",
        participant_kind="EXTERNAL",
        external_signer_id=signer_id,
        operation_role="QA",
        identity_snapshot={"name": "QA frozen signer"},
        identity_snapshot_sha256="b" * 64,
    )
    for kind, identifier in (("external_signer", signer_id), ("signature_slot", slot_id)):
        data = preview(deletion_client, kind, identifier).json()
        assert not data["can_delete"]
        assert any(
            row["code"] == "document_participants" and row["count"] == 1 for row in data["blockers"]
        )
        assert (
            execute(deletion_client, kind, identifier, data["confirmation_text"]).status_code == 409
        )
    other_slot = target(
        deletion_factory, SignatureSlot, document_type="REPAIR_PROTOCOL", code="QA", label_bg="QA"
    )
    data = preview(deletion_client, "signature_slot", other_slot).json()
    assert data["can_delete"]  # The slot code is scoped by document type.
    assert (
        execute(
            deletion_client, "signature_slot", other_slot, data["confirmation_text"]
        ).status_code
        == 200
    )
    with deletion_factory() as db:
        assert db.get(DocumentParticipant, participant_id).identity_snapshot == {
            "name": "QA frozen signer"
        }
        assert db.get(OfficialDocumentVersion, version_id).docx_content == b"QA retained reference"


def test_parts_doc_snapshot_chain_is_retained(client, auth_headers, session_factory):
    from app.models import PartVisualArtifact, PartVisualOccurrence, PartVisualSnapshot
    from visual_snapshot_cases import future_catalog, request_payload

    data = future_catalog(session_factory)
    response = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=request_payload(data)
    )
    assert response.status_code == 201

    def snapshot():
        with session_factory() as db:
            return (
                [
                    (row.id, row.sha256, row.catalog)
                    for row in db.scalars(select(PartVisualSnapshot))
                ],
                [
                    (row.id, row.artifact_sha256, row.source_metadata)
                    for row in db.scalars(select(PartVisualOccurrence))
                ],
                [(row.sha256, row.content) for row in db.scalars(select(PartVisualArtifact))],
            )

    before = snapshot()
    assert all(before)
    pair = client, auth_headers
    deletion = preview(pair, "machine", data["machine_id"]).json()
    assert not deletion["can_delete"]
    assert (
        execute(
            pair,
            "machine",
            data["machine_id"],
            deletion["confirmation_text"],
            current_password="AssetCore123!",
        ).status_code
        == 409
    )
    assert snapshot() == before


def test_empty_hpwj_category_does_not_resurrect(client, auth_headers, session_factory):
    with session_factory() as db:
        assert db.get_bind().url.database.endswith("assetcore-test.db")
        ids = list(db.scalars(select(Machine.id)))
        assert len(ids) == 19
        category_id = db.scalar(select(AssetCategory.id).where(AssetCategory.code == "HPWJ"))
    pair = client, auth_headers
    for identifier in ids:
        data = preview(pair, "machine", identifier).json()
        assert data["can_delete"]
        assert (
            execute(
                pair,
                "machine",
                identifier,
                data["confirmation_text"],
                current_password="AssetCore123!",
            ).status_code
            == 200
        )
    data = preview(pair, "asset_category", category_id).json()
    assert data["can_delete"]
    assert (
        execute(
            pair,
            "asset_category",
            category_id,
            data["confirmation_text"],
            current_password="AssetCore123!",
        ).status_code
        == 200
    )
    with session_factory() as db:
        seed_database(db)
        assert db.scalar(select(func.count()).select_from(Machine)) == 0
        assert db.scalar(select(AssetCategory).where(AssetCategory.code == "HPWJ")) is None


def test_failed_fresh_bootstrap_rolls_back_marker_and_can_retry(tmp_path, monkeypatch):
    from app import seed

    engine = create_engine(f"sqlite:///{tmp_path / 'failed-bootstrap.db'}")
    event.listen(engine, "connect", _configure_sqlite)
    Base.metadata.create_all(engine)
    original = seed._seed_document_templates

    def fail_templates(_db):
        raise RuntimeError("QA interrupted bootstrap")

    try:
        with sessionmaker(engine, autoflush=False)() as db:
            monkeypatch.setattr(seed, "_seed_document_templates", fail_templates)
            with pytest.raises(RuntimeError, match="QA interrupted bootstrap"):
                seed_database(db)
            for model in (User, InstallationOwnership, Machine, Location, AssetCategory):
                assert db.scalar(select(func.count()).select_from(model)) == 0
            monkeypatch.setattr(seed, "_seed_document_templates", original)
            seed_database(db)
            assert db.scalar(select(func.count()).select_from(Machine)) == 19
            seed_database(db)
            assert db.scalar(select(func.count()).select_from(Machine)) == 19
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "kind,model", [("machine", Machine), ("location", Location), ("signature_slot", SignatureSlot)]
)
def test_seeded_deletion_stays_absent_on_normal_seed(
    client, auth_headers, session_factory, kind, model
):
    # conftest creates a fresh DB under pytest's temporary directory; no application DB is used.
    with session_factory() as db:
        assert db.get_bind().url.database.endswith("assetcore-test.db")
        assert db.scalar(select(func.count()).select_from(Machine)) == len(MACHINES) == 19
        item = db.scalar(select(model).order_by(model.id.desc()))
        identifier = item.id
    pair = client, auth_headers
    data = preview(pair, kind, identifier).json()
    assert data["can_delete"]
    response = execute(
        pair, kind, identifier, data["confirmation_text"], current_password="AssetCore123!"
    )
    assert response.status_code == 200
    with session_factory() as db:
        seed_database(db)
        seed_database(db)
        assert db.get(model, identifier) is None
        expected_machines = 18 if kind == "machine" else 19
        assert db.scalar(select(func.count()).select_from(Machine)) == expected_machines
        assert (
            len({item.inventory_number for item in db.scalars(select(Machine))})
            == expected_machines
        )
