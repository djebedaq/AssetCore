"""Owner-only administrator assignment through public APIs in isolated fixtures."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from app.main import app
from app.models import AuditLog, AuthSession, User
from app.permissions import ROLE_PERMISSIONS, Permission
from app.settings import settings
from app.user_api import _assignable_roles
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_owner_transfer_round_trip import _browser_login
from test_user_accounts import _add_user, _create_payload, _login


@pytest.mark.parametrize("actor_role", ["administrator", "director"])
@pytest.mark.parametrize("assigned_role", ["administrator", "director"])
def test_nonowner_cannot_create_or_assign_privileged_roles(
    client, session_factory, actor_role, assigned_role
):
    _add_user(session_factory, email="actor@qa.invalid", role=actor_role)
    target_id = _add_user(session_factory, email="target@qa.invalid", role="mechanic")
    headers, _ = _login(client, "actor@qa.invalid")
    for response in (
        client.post("/api/users", headers=headers,
                    json=_create_payload("blocked@qa.invalid", assigned_role)),
        client.patch(f"/api/users/{target_id}", headers=headers, json={"role": assigned_role}),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "role_escalation_denied"
    with session_factory() as db:
        assert db.get(User, target_id).role == "mechanic"
        assert db.scalar(select(User).where(User.email == "blocked@qa.invalid")) is None


@pytest.mark.parametrize("initial_role", ["director", "mechanic", "observer"])
def test_owner_promotion_revokes_bearer_and_browser_sessions_and_audits_roles(
    client, auth_headers, session_factory, initial_role
):
    target_id = _add_user(session_factory, email="promotion@qa.invalid", role=initial_role)
    bearer, _ = _login(client, "promotion@qa.invalid")
    with TestClient(app, raise_server_exceptions=False) as browser:
        _browser_login(browser, "promotion@qa.invalid", "StrongPass123!")
        with session_factory() as db:
            previous_version = db.get(User, target_id).token_version
        promoted = client.patch(
            f"/api/users/{target_id}", headers=auth_headers, json={"role": "administrator"}
        )
        assert promoted.status_code == 200
        assert promoted.json()["is_system_owner"] is False
        assert client.get("/api/auth/me", headers=bearer).status_code == 401
        assert browser.get("/api/auth/me").status_code == 401
    with session_factory() as db:
        assert db.get(User, target_id).token_version == previous_version + 1
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == target_id)).revoked_at
        entry = db.scalar(select(AuditLog).where(
            AuditLog.entity_id == target_id, AuditLog.action == "Променен потребител"
        ))
        details = json.loads(entry.details)
        assert details["old_role"] == initial_role
        assert details["new_role"] == "administrator"


@pytest.mark.parametrize("lower_role", ["director", "mechanic", "observer"])
def test_owner_can_manage_and_demote_nonowner_administrator(
    client, auth_headers, session_factory, lower_role
):
    identifier = _add_user(session_factory, email="managed-admin@qa.invalid", role="administrator")
    bearer, _ = _login(client, "managed-admin@qa.invalid")
    assert client.patch(f"/api/users/{identifier}", headers=auth_headers,
                        json={"job_title": "QA managed administrator"}).status_code == 200
    for operation in ("deactivate", "activate"):
        assert client.post(f"/api/users/{identifier}/{operation}", headers=auth_headers).status_code == 200
    assert client.post(f"/api/users/{identifier}/reset-password", headers=auth_headers, json={
        "temporary_password": "Temporary123!", "confirm_password": "Temporary123!",
    }).status_code == 200
    demoted = client.patch(f"/api/users/{identifier}", headers=auth_headers,
                          json={"role": lower_role})
    assert demoted.status_code == 200
    assert demoted.json()["role"] == lower_role
    assert client.get("/api/auth/me", headers=bearer).status_code == 401
    assert client.post(f"/api/users/{identifier}/deactivate", headers=auth_headers).status_code == 200
    assert client.post(f"/api/users/{identifier}/activate", headers=auth_headers).status_code == 200
    assert client.post(f"/api/users/{identifier}/reset-password", headers=auth_headers, json={
        "temporary_password": "Temporary123!", "confirm_password": "Temporary123!",
    }).status_code == 200


@pytest.mark.parametrize("target_role", ["administrator", "director", "mechanic", "observer"])
def test_nonowner_administrator_management_scope(client, session_factory, target_role):
    _add_user(session_factory, email="actor@qa.invalid", role="administrator")
    identifier = _add_user(session_factory, email="target@qa.invalid", role=target_role)
    headers, _ = _login(client, "actor@qa.invalid")
    expected = 200 if target_role in {"mechanic", "observer"} else 403
    for response in (
        client.patch(f"/api/users/{identifier}", headers=headers, json={"job_title": "QA update"}),
        client.post(f"/api/users/{identifier}/deactivate", headers=headers),
        client.post(f"/api/users/{identifier}/activate", headers=headers),
        client.post(f"/api/users/{identifier}/reset-password", headers=headers, json={
            "temporary_password": "Temporary123!", "confirm_password": "Temporary123!",
        }),
    ):
        assert response.status_code == expected


@pytest.mark.parametrize("actor_role", ["administrator", "director"])
def test_owner_and_self_protection(client, session_factory, actor_role):
    identifier = _add_user(session_factory, email="actor@qa.invalid", role=actor_role)
    headers, _ = _login(client, "actor@qa.invalid")
    owner = client.get("/api/owner", headers=headers).json()["owner_user_id"]
    for target in (owner, identifier):
        assert client.patch(f"/api/users/{target}", headers=headers,
                            json={"role": "observer"}).status_code == 403
        assert client.patch(f"/api/users/{target}", headers=headers,
                            json={"job_title": "QA forbidden update"}).status_code == 403
        assert client.post(f"/api/users/{target}/deactivate", headers=headers).status_code == 403
        assert client.post(f"/api/users/{target}/reset-password", headers=headers, json={
            "temporary_password": "Temporary123!", "confirm_password": "Temporary123!",
        }).status_code == 403


def test_owner_assignment_requires_existing_permission(client, auth_headers, session_factory, monkeypatch):
    identifier = _add_user(session_factory, email="permission-target@qa.invalid", role="mechanic")
    monkeypatch.setitem(ROLE_PERMISSIONS, "administrator",
                        ROLE_PERMISSIONS["administrator"] - {Permission.USERS_ASSIGN_ADMINISTRATOR})
    denied = client.post("/api/users", headers=auth_headers,
                         json=_create_payload("blocked@qa.invalid", "administrator"))
    assert denied.status_code == 403
    assert client.patch(f"/api/users/{identifier}", headers=auth_headers,
                        json={"role": "administrator"}).status_code == 403


def test_client_cannot_mutate_owner_flag(client, auth_headers):
    payload = _create_payload("flag@qa.invalid", "administrator")
    payload["is_system_owner"] = True
    assert client.post("/api/users", headers=auth_headers, json=payload).status_code == 422
    created = client.post("/api/users", headers=auth_headers,
                          json=_create_payload("valid@qa.invalid", "administrator"))
    assert created.status_code == 201
    assert client.patch(f"/api/users/{created.json()['id']}", headers=auth_headers,
                        json={"is_system_owner": True}).status_code == 422


def test_administrator_creation_keeps_license_user_limit(client, auth_headers, monkeypatch):
    # Exercise the existing capacity check after passing administrator assignment.
    from app import user_api

    monkeypatch.setattr(settings, "license_enforcement_enabled", True)
    monkeypatch.setattr(user_api, "active_license", lambda db: SimpleNamespace(payload={"max_users": 1}))
    response = client.post("/api/users", headers=auth_headers,
                           json=_create_payload("capacity@qa.invalid", "administrator"))
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "license_user_limit_reached"


def test_owner_flag_without_administrator_role_cannot_assign_administrator():
    # Database constraints also forbid this state; the assignment guard must
    # nevertheless check the role explicitly, independently of permission grants.
    actor = User(id=123, role="director", is_system_owner=True)
    assert {role.value for role in _assignable_roles(actor)} == {"mechanic", "observer"}


def test_nonowner_administrator_cannot_self_approve_legal_name_exception(client, session_factory):
    identifier = _add_user(session_factory, email="self-profile@qa.invalid", role="administrator")
    headers, _ = _login(client, "self-profile@qa.invalid")
    denied = client.put(f"/api/users/{identifier}/profile", headers=headers, json={
        "first_name": "QA", "middle_name": None, "last_name": "Administrator",
        "job_title": "QA administrator", "legal_name_exception": True,
        "legal_name_exception_reason": "QA administrator must not approve their own exception.",
    })
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "legal_name_exception_requires_admin"


@pytest.mark.parametrize("actor_role,owner", [("administrator", True), ("administrator", False), ("director", False)])
@pytest.mark.parametrize("target_role", ["administrator", "director", "mechanic", "observer"])
def test_structured_profile_management_uses_same_scope(
    client, auth_headers, session_factory, actor_role, owner, target_role
):
    if owner:
        headers = auth_headers
    else:
        _add_user(session_factory, email="profile-actor@qa.invalid", role=actor_role)
        headers, _ = _login(client, "profile-actor@qa.invalid")
    identifier = _add_user(session_factory, email="profile-target@qa.invalid", role=target_role)
    response = client.put(f"/api/users/{identifier}/profile", headers=headers, json={
        "first_name": "QA", "middle_name": "Profile", "last_name": "Scope", "job_title": "QA scope",
    })
    assert response.status_code == (200 if owner or target_role in {"mechanic", "observer"} else 403)
