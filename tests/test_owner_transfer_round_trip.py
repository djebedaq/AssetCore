"""Owner handoff regression coverage using only isolated test databases."""

from __future__ import annotations

import json

import pytest
from app.governance import owner_service
from app.main import app
from app.models import AuditLog, AuthSession, InstallationOwnership, User, UserRole
from app.security import hash_password
from app.seed import seed_database
from app.settings import settings
from fastapi.testclient import TestClient
from sqlalchemy import func, select

FIRST_REASON = "F03 isolated transfer from owner A to administrator B."
REVERSE_REASON = "F03 isolated reverse transfer from owner B to administrator A."
EMERGENCY_REASON = "F03 isolated verification of the owner-only emergency procedure."
END_REASON = "F03 isolated completion of the owner-only emergency procedure."


def _login(client, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        headers={"X-AssetCore-Auth-Mode": "bearer"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _browser_login(client, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        headers={"X-AssetCore-Auth-Mode": "session"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies.get(settings.csrf_cookie_name)}


def _create_target(
    session_factory,
    *,
    email: str = "f03-owner-b@example.invalid",
    role: str = UserRole.ADMINISTRATOR.value,
    active: bool = True,
    complete: bool = True,
) -> tuple[int, str]:
    password = "StrongPass123!"
    with session_factory() as db:
        target = User(
            email=email,
            full_name="QA F03 Owner B",
            first_name="QA" if complete else None,
            middle_name="F03" if complete else None,
            last_name="Owner B" if complete else None,
            job_title="Test administrator" if complete else None,
            profile_status="PROFILE_COMPLETE" if complete else "PROFILE_INCOMPLETE",
            password_hash=hash_password(password),
            role=role,
            is_active=active,
        )
        db.add(target)
        db.commit()
        return target.id, password


def _successful_owner_audits(db):
    return db.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_type == "installation_owner",
            AuditLog.action == "Прехвърлена собственост на инсталацията",
        )
        .order_by(AuditLog.id)
    ).all()


def _assert_one_owner(db, expected_owner_id: int) -> InstallationOwnership:
    ownership = db.scalar(select(InstallationOwnership))
    owners = db.scalars(select(User).where(User.is_system_owner.is_(True))).all()
    assert len(owners) == 1
    assert ownership.owner_user_id == owners[0].id == expected_owner_id
    assert owners[0].is_active is True
    assert owners[0].role == UserRole.ADMINISTRATOR.value
    return ownership


def test_owner_transfer_round_trip_a_to_b_to_a(client, auth_headers, session_factory):
    target_id, target_password = _create_target(session_factory)
    with session_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        original_owner_id = ownership.owner_user_id
        original_version = ownership.version
        original_token_versions = {
            original_owner_id: db.get(User, original_owner_id).token_version,
            target_id: db.get(User, target_id).token_version,
        }

    target_bearer_before_first = _login(
        client, "f03-owner-b@example.invalid", target_password
    )
    first_owner_browser = TestClient(app, raise_server_exceptions=False)
    first_target_browser = TestClient(app, raise_server_exceptions=False)
    reverse_owner_browser = TestClient(app, raise_server_exceptions=False)
    reverse_target_browser = TestClient(app, raise_server_exceptions=False)
    try:
        first_owner_csrf = _browser_login(
            first_owner_browser, "admin@assetcore.local", "AssetCore123!"
        )
        _browser_login(
            first_target_browser, "f03-owner-b@example.invalid", target_password
        )
        first = first_owner_browser.post(
            "/api/owner/transfer",
            headers={**first_owner_csrf, "X-Request-ID": "f03-a-to-b"},
            json={
                "target_user_id": target_id,
                "current_password": "AssetCore123!",
                "reason": FIRST_REASON,
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["owner_user_id"] == target_id
        assert first.json()["designation_version"] == original_version + 1
        assert first_owner_browser.get("/api/auth/me").status_code == 401
        assert first_target_browser.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers=auth_headers).status_code == 401
        assert (
            client.get("/api/auth/me", headers=target_bearer_before_first).status_code
            == 401
        )

        former_owner_headers = _login(
            client, "admin@assetcore.local", "AssetCore123!"
        )
        current_owner_headers = _login(
            client, "f03-owner-b@example.invalid", target_password
        )
        assert client.get("/api/owner/audit", headers=former_owner_headers).status_code == 403
        assert client.get("/api/owner/audit", headers=current_owner_headers).status_code == 200
        with session_factory() as db:
            item = _assert_one_owner(db, target_id)
            assert item.version == original_version + 1
            assert item.designated_by_id == original_owner_id
            assert item.transfer_reason == FIRST_REASON

        reverse_owner_csrf = _browser_login(
            reverse_owner_browser, "f03-owner-b@example.invalid", target_password
        )
        _browser_login(
            reverse_target_browser, "admin@assetcore.local", "AssetCore123!"
        )
        reverse = reverse_owner_browser.post(
            "/api/owner/transfer",
            headers={**reverse_owner_csrf, "X-Request-ID": "f03-b-to-a"},
            json={
                "target_user_id": original_owner_id,
                "current_password": target_password,
                "reason": REVERSE_REASON,
            },
        )
        assert reverse.status_code == 200, reverse.text
        assert reverse.json()["owner_user_id"] == original_owner_id
        assert reverse.json()["designation_version"] == original_version + 2
        assert reverse_owner_browser.get("/api/auth/me").status_code == 401
        assert reverse_target_browser.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me", headers=former_owner_headers).status_code == 401
        assert client.get("/api/auth/me", headers=current_owner_headers).status_code == 401
    finally:
        first_owner_browser.close()
        first_target_browser.close()
        reverse_owner_browser.close()
        reverse_target_browser.close()

    restored_owner_headers = _login(
        client, "admin@assetcore.local", "AssetCore123!"
    )
    former_target_headers = _login(
        client, "f03-owner-b@example.invalid", target_password
    )
    assert client.get("/api/owner/audit", headers=restored_owner_headers).status_code == 200
    denied = client.get("/api/owner/audit", headers=former_target_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "owner_only"

    with session_factory() as db:
        ownership = _assert_one_owner(db, original_owner_id)
        assert ownership.version == original_version + 2
        assert ownership.designated_by_id == target_id
        assert ownership.transfer_reason == REVERSE_REASON
        assert {db.get(User, value).role for value in (original_owner_id, target_id)} == {
            UserRole.ADMINISTRATOR.value
        }
        assert {role.value for role in UserRole} == {
            "administrator",
            "director",
            "mechanic",
            "observer",
        }
        assert (
            db.get(User, original_owner_id).token_version
            == original_token_versions[original_owner_id] + 2
        )
        assert (
            db.get(User, target_id).token_version
            == original_token_versions[target_id] + 2
        )
        audits = _successful_owner_audits(db)
        assert len(audits) == 2
        assert [entry.user_id for entry in audits] == [original_owner_id, target_id]
        assert [entry.operation_reference for entry in audits] == [
            "f03-a-to-b",
            "f03-b-to-a",
        ]
        assert [json.loads(entry.details) for entry in audits] == [
            {
                "previous_owner_user_id": original_owner_id,
                "new_owner_user_id": target_id,
                "reason": FIRST_REASON,
                "designation_version": original_version + 1,
            },
            {
                "previous_owner_user_id": target_id,
                "new_owner_user_id": original_owner_id,
                "reason": REVERSE_REASON,
                "designation_version": original_version + 2,
            },
        ]
        sessions = db.scalars(select(AuthSession).order_by(AuthSession.id)).all()
        assert len(sessions) == 4
        assert all(session.revoked_at is not None for session in sessions)
        assert [session.revoked_reason for session in sessions] == [
            "owner_transferred",
            "owner_designated",
            "owner_transferred",
            "owner_designated",
        ]

        before_seed = (
            ownership.owner_user_id,
            ownership.version,
            ownership.designated_by_id,
            ownership.transfer_reason,
        )
        seed_database(db)
        ownership = _assert_one_owner(db, original_owner_id)
        assert (
            ownership.owner_user_id,
            ownership.version,
            ownership.designated_by_id,
            ownership.transfer_reason,
        ) == before_seed


def test_owner_transfer_failure_after_demotion_flush_rolls_back_everything(
    client, session_factory, monkeypatch
):
    target_id, _ = _create_target(session_factory)
    owner_browser = TestClient(app, raise_server_exceptions=False)
    target_browser = TestClient(app, raise_server_exceptions=False)
    try:
        owner_csrf = _browser_login(
            owner_browser, "admin@assetcore.local", "AssetCore123!"
        )
        _browser_login(target_browser, "f03-owner-b@example.invalid", "StrongPass123!")
        with session_factory() as db:
            ownership = db.scalar(select(InstallationOwnership))
            owner_id = ownership.owner_user_id
            before = {
                "owner_user_id": ownership.owner_user_id,
                "version": ownership.version,
                "designated_by_id": ownership.designated_by_id,
                "reason": ownership.transfer_reason,
                "owner_token_version": db.get(User, owner_id).token_version,
                "target_token_version": db.get(User, target_id).token_version,
                "audit_count": db.scalar(select(func.count(AuditLog.id))),
            }

        def fail_before_audit(*_args, **_kwargs):
            raise RuntimeError("controlled F03 rollback injection")

        monkeypatch.setattr(owner_service, "add_audit_log", fail_before_audit)
        response = owner_browser.post(
            "/api/owner/transfer",
            headers=owner_csrf,
            json={
                "target_user_id": target_id,
                "current_password": "AssetCore123!",
                "reason": FIRST_REASON,
            },
        )
        assert response.status_code == 500

        with session_factory() as db:
            ownership = _assert_one_owner(db, owner_id)
            assert (
                ownership.owner_user_id,
                ownership.version,
                ownership.designated_by_id,
                ownership.transfer_reason,
            ) == (
                before["owner_user_id"],
                before["version"],
                before["designated_by_id"],
                before["reason"],
            )
            assert db.get(User, owner_id).token_version == before["owner_token_version"]
            assert db.get(User, target_id).token_version == before["target_token_version"]
            assert db.scalar(select(func.count(AuditLog.id))) == before["audit_count"]
            sessions = db.scalars(select(AuthSession).order_by(AuthSession.id)).all()
            assert len(sessions) == 2
            assert all(session.revoked_at is None for session in sessions)
            assert all(session.revoked_reason is None for session in sessions)
        assert owner_browser.get("/api/auth/me").status_code == 200
        assert target_browser.get("/api/auth/me").status_code == 200
    finally:
        owner_browser.close()
        target_browser.close()


def test_owner_transfer_wrong_password_changes_no_owner_state(
    client, auth_headers, session_factory
):
    target_id, _ = _create_target(session_factory)
    with session_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        owner_id = ownership.owner_user_id
        before = (
            ownership.owner_user_id,
            ownership.version,
            db.get(User, owner_id).token_version,
            db.get(User, target_id).token_version,
        )
    response = client.post(
        "/api/owner/transfer",
        headers=auth_headers,
        json={
            "target_user_id": target_id,
            "current_password": "wrong-password",
            "reason": FIRST_REASON,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "reauthentication_failed"
    with session_factory() as db:
        ownership = _assert_one_owner(db, owner_id)
        assert (
            ownership.owner_user_id,
            ownership.version,
            db.get(User, owner_id).token_version,
            db.get(User, target_id).token_version,
        ) == before
        assert len(_successful_owner_audits(db)) == 0


@pytest.mark.parametrize(
    ("case", "expected_status", "expected_code"),
    [
        ("same", 409, "owner_unchanged"),
        ("missing", 404, "user_not_found"),
        ("inactive", 409, "invalid_owner_target"),
        ("non_admin", 409, "invalid_owner_target"),
        ("incomplete", 409, "profile_incomplete"),
    ],
)
def test_owner_transfer_invalid_targets_keep_existing_errors_and_state(
    client, auth_headers, session_factory, case, expected_status, expected_code
):
    with session_factory() as db:
        ownership = db.scalar(select(InstallationOwnership))
        owner_id = ownership.owner_user_id
        original_version = ownership.version
        owner_token_version = db.get(User, owner_id).token_version

    if case == "same":
        target_id = owner_id
    elif case == "missing":
        target_id = 999999
    else:
        target_id, _ = _create_target(
            session_factory,
            active=case != "inactive",
            role=(
                UserRole.DIRECTOR.value
                if case == "non_admin"
                else UserRole.ADMINISTRATOR.value
            ),
            complete=case != "incomplete",
        )

    response = client.post(
        "/api/owner/transfer",
        headers=auth_headers,
        json={
            "target_user_id": target_id,
            "current_password": "AssetCore123!",
            "reason": FIRST_REASON,
        },
    )
    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    with session_factory() as db:
        ownership = _assert_one_owner(db, owner_id)
        assert ownership.version == original_version
        assert db.get(User, owner_id).token_version == owner_token_version
        assert len(_successful_owner_audits(db)) == 0


def test_owner_round_trip_preserves_emergency_owner_only_rule(
    client, auth_headers, session_factory
):
    target_id, target_password = _create_target(session_factory)
    with session_factory() as db:
        original_owner_id = db.scalar(select(InstallationOwnership)).owner_user_id

    first = client.post(
        "/api/owner/transfer",
        headers=auth_headers,
        json={
            "target_user_id": target_id,
            "current_password": "AssetCore123!",
            "reason": FIRST_REASON,
        },
    )
    assert first.status_code == 200
    former_headers = _login(client, "admin@assetcore.local", "AssetCore123!")
    current_headers = _login(client, "f03-owner-b@example.invalid", target_password)
    payload = {
        "current_password": "AssetCore123!",
        "reason": EMERGENCY_REASON,
        "duration_minutes": 5,
    }
    denied = client.post("/api/emergency-access/start", headers=former_headers, json=payload)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "owner_only"
    started = client.post(
        "/api/emergency-access/start",
        headers=current_headers,
        json={**payload, "current_password": target_password},
    )
    assert started.status_code == 201
    ended = client.post(
        f"/api/emergency-access/{started.json()['session_id']}/end",
        headers=current_headers,
        json={"current_password": target_password, "reason": END_REASON},
    )
    assert ended.status_code == 200

    reverse = client.post(
        "/api/owner/transfer",
        headers=current_headers,
        json={
            "target_user_id": original_owner_id,
            "current_password": target_password,
            "reason": REVERSE_REASON,
        },
    )
    assert reverse.status_code == 200
    former_target_headers = _login(
        client, "f03-owner-b@example.invalid", target_password
    )
    restored_headers = _login(client, "admin@assetcore.local", "AssetCore123!")
    denied = client.post(
        "/api/emergency-access/start",
        headers=former_target_headers,
        json={**payload, "current_password": target_password},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "owner_only"
    restored = client.post(
        "/api/emergency-access/start", headers=restored_headers, json=payload
    )
    assert restored.status_code == 201

    with session_factory() as db:
        _assert_one_owner(db, original_owner_id)
        entries = db.scalars(
            select(AuditLog).where(AuditLog.entity_type == "emergency_access")
        ).all()
        details = [json.loads(entry.details) for entry in entries]
        assert all(item.get("permissions_elevated") is False for item in details)
