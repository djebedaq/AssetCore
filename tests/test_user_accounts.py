from __future__ import annotations

import json
from datetime import datetime

import pytest
from app.models import AuditLog, User, UserRole
from app.permissions import ROLE_PERMISSIONS, Permission
from app.security import hash_password, verify_password
from app.seed import _seed_verified_registry
from app.settings import settings
from sqlalchemy import func, select


def _add_user(
    session_factory,
    *,
    email: str,
    role: str,
    password: str = "StrongPass123!",
    active: bool = True,
    must_change_password: bool = False,
) -> int:
    with session_factory() as session:
        user = User(
            email=email,
            full_name=f"Test {role}",
            first_name="Test",
            middle_name="Automation",
            last_name=role.title(),
            job_title=f"Test {role}",
            profile_status="PROFILE_COMPLETE",
            password_hash=hash_password(password),
            role=role,
            preferred_language="bg",
            is_active=active,
            must_change_password=must_change_password,
        )
        session.add(user)
        session.commit()
        return user.id


def _login(client, email: str, password: str = "StrongPass123!") -> tuple[dict, dict]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def _create_payload(email: str, role: str) -> dict:
    return {
        "email": email,
        "first_name": "Test",
        "middle_name": "Automation",
        "last_name": role.title(),
        "job_title": f"Test {role}",
        "role": role,
        "preferred_language": "bg",
        "temporary_password": "Temporary123!",
        "confirm_password": "Temporary123!",
        "is_active": True,
    }


@pytest.mark.parametrize("configured_email", [None, "not-an-email"])
def test_runtime_seed_requires_explicit_valid_owner_email(
    monkeypatch, configured_email
):
    monkeypatch.setattr(settings, "assetcore_owner_email", configured_email)

    with pytest.raises(RuntimeError, match="ASSETCORE_OWNER_EMAIL"):
        _seed_verified_registry(None)


def test_bootstrap_has_exactly_one_protected_administrator_and_safe_profile(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        owners = session.scalars(select(User).where(User.is_system_owner.is_(True))).all()
        assert len(owners) == 1
        assert owners[0].role == UserRole.ADMINISTRATOR.value
        assert owners[0].is_active is True

    response = client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    profile = response.json()
    assert profile["role"] == "administrator"
    assert profile["is_system_owner"] is True
    assert profile["is_active"] is True
    assert profile["must_change_password"] is False
    assert "password_hash" not in profile
    assert set(profile["permissions"]) == {
        permission.value for permission in Permission
    }


@pytest.mark.parametrize("role", ["director", "mechanic", "observer"])
def test_administrator_can_create_each_standard_role(
    client, auth_headers, session_factory, role
):
    response = client.post(
        "/api/users",
        headers=auth_headers,
        json=_create_payload(f"{role}@example.invalid", role),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == role
    assert body["must_change_password"] is True
    assert "password_hash" not in body
    with session_factory() as session:
        stored = session.get(User, body["id"])
        assert stored.password_hash != "Temporary123!"
        assert verify_password("Temporary123!", stored.password_hash)


def test_new_user_requires_structured_identity(client, auth_headers):
    payload = _create_payload("missing-middle@example.invalid", "observer")
    payload.pop("middle_name")
    response = client.post("/api/users", headers=auth_headers, json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("role", ["mechanic", "observer"])
def test_director_can_create_only_operational_roles(
    client, session_factory, role
):
    _add_user(session_factory, email="director@example.invalid", role="director")
    headers, _ = _login(client, "director@example.invalid")
    response = client.post(
        "/api/users",
        headers=headers,
        json=_create_payload(f"new-{role}@example.invalid", role),
    )
    assert response.status_code == 201, response.text
    assert response.json()["role"] == role


@pytest.mark.parametrize("role", ["director", "administrator"])
def test_director_role_escalation_is_rejected_and_audited(
    client, session_factory, role
):
    _add_user(session_factory, email="director@example.invalid", role="director")
    headers, _ = _login(client, "director@example.invalid")
    response = client.post(
        "/api/users",
        headers=headers,
        json=_create_payload(f"forbidden-{role}@example.invalid", role),
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "role_escalation_denied"
    with session_factory() as session:
        entry = session.scalar(
            select(AuditLog)
            .where(AuditLog.action == "Отказан опит за повишаване на роля")
            .order_by(AuditLog.id.desc())
        )
        assert json.loads(entry.details)["reason"] == "role_escalation_denied"


@pytest.mark.parametrize("role", ["mechanic", "observer"])
def test_non_managers_cannot_access_user_administration(
    client, session_factory, role
):
    _add_user(session_factory, email=f"{role}@example.invalid", role=role)
    headers, _ = _login(client, f"{role}@example.invalid")
    assert client.get("/api/users", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/users",
            headers=headers,
            json=_create_payload("blocked@example.invalid", "observer"),
        ).status_code
        == 403
    )


def test_user_filters_and_director_scope(client, auth_headers, session_factory):
    mechanic_id = _add_user(
        session_factory, email="mechanic-filter@example.invalid", role="mechanic"
    )
    observer_id = _add_user(
        session_factory,
        email="observer-filter@example.invalid",
        role="observer",
        active=False,
    )
    _add_user(session_factory, email="director-filter@example.invalid", role="director")
    owner_list = client.get(
        "/api/users?search=filter&role=observer&is_active=false", headers=auth_headers
    )
    assert owner_list.status_code == 200
    assert [item["id"] for item in owner_list.json()] == [observer_id]

    director_headers, _ = _login(client, "director-filter@example.invalid")
    visible = client.get("/api/users", headers=director_headers)
    assert visible.status_code == 200
    assert {item["role"] for item in visible.json()} <= {"mechanic", "observer"}
    assert mechanic_id in {item["id"] for item in visible.json()}
    assert all("password_hash" not in item for item in visible.json())


def test_director_can_edit_and_switch_mechanic_observer_roles(
    client, session_factory
):
    _add_user(session_factory, email="director@example.invalid", role="director")
    target_id = _add_user(
        session_factory, email="target@example.invalid", role="mechanic"
    )
    headers, _ = _login(client, "director@example.invalid")
    changed = client.patch(
        f"/api/users/{target_id}",
        headers=headers,
        json={"full_name": "Updated test user", "role": "observer", "preferred_language": "ru"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["role"] == "observer"
    assert changed.json()["preferred_language"] == "ru"
    restored = client.patch(
        f"/api/users/{target_id}", headers=headers, json={"role": "mechanic"}
    )
    assert restored.status_code == 200
    assert restored.json()["role"] == "mechanic"


def test_director_cannot_manage_director_or_system_owner(
    client, session_factory
):
    actor_id = _add_user(
        session_factory, email="director-actor@example.invalid", role="director"
    )
    other_id = _add_user(
        session_factory, email="director-other@example.invalid", role="director"
    )
    headers, _ = _login(client, "director-actor@example.invalid")
    with session_factory() as session:
        owner_id = session.scalar(select(User.id).where(User.is_system_owner.is_(True)))
    assert client.get(f"/api/users/{owner_id}", headers=headers).status_code == 403
    assert client.patch(
        f"/api/users/{other_id}", headers=headers, json={"full_name": "Blocked"}
    ).status_code == 403
    assert client.patch(
        f"/api/users/{actor_id}", headers=headers, json={"role": "administrator"}
    ).status_code == 403


def test_system_owner_cannot_be_changed_deactivated_or_reset(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        owner_id = session.scalar(select(User.id).where(User.is_system_owner.is_(True)))
    assert client.patch(
        f"/api/users/{owner_id}", headers=auth_headers, json={"role": "director"}
    ).status_code == 403
    assert client.post(
        f"/api/users/{owner_id}/deactivate", headers=auth_headers
    ).status_code == 403
    assert client.post(
        f"/api/users/{owner_id}/reset-password",
        headers=auth_headers,
        json={
            "temporary_password": "Replacement123!",
            "confirm_password": "Replacement123!",
        },
    ).status_code == 403
    with session_factory() as session:
        owner = session.get(User, owner_id)
        assert owner.is_active is True
        assert owner.role == "administrator"
        assert session.scalar(
            select(func.count(User.id)).where(User.is_system_owner.is_(True))
        ) == 1


def test_activation_deactivation_and_old_token_invalidation(
    client, auth_headers, session_factory
):
    target_id = _add_user(
        session_factory, email="session-user@example.invalid", role="mechanic"
    )
    target_headers, _ = _login(client, "session-user@example.invalid")
    deactivated = client.post(
        f"/api/users/{target_id}/deactivate", headers=auth_headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["user"]["is_active"] is False
    assert client.get("/api/auth/me", headers=target_headers).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "session-user@example.invalid", "password": "StrongPass123!"},
    ).status_code == 403
    activated = client.post(f"/api/users/{target_id}/activate", headers=auth_headers)
    assert activated.status_code == 200
    assert activated.json()["user"]["is_active"] is True


def test_duplicate_email_invalid_role_and_language_are_rejected(
    client, auth_headers
):
    created = client.post(
        "/api/users",
        headers=auth_headers,
        json=_create_payload("MixedCase@Example.Invalid", "observer"),
    )
    assert created.status_code == 201
    assert created.json()["email"] == "mixedcase@example.invalid"
    duplicate = client.post(
        "/api/users",
        headers=auth_headers,
        json=_create_payload("MIXEDCASE@example.invalid", "mechanic"),
    )
    assert duplicate.status_code == 409
    invalid_role = _create_payload("invalid-role@example.invalid", "obsolete")
    assert client.post("/api/users", headers=auth_headers, json=invalid_role).status_code == 422
    invalid_language = _create_payload("invalid-language@example.invalid", "observer")
    invalid_language["preferred_language"] = "de"
    assert client.post(
        "/api/users", headers=auth_headers, json=invalid_language
    ).status_code == 422


@pytest.mark.parametrize(
    "password",
    ["short1!A", "alllowercase1!", "ALLUPPERCASE1!", "NoDigits!!!", "NoSpecial123"],
)
def test_password_policy_rejects_weak_temporary_passwords(
    client, auth_headers, password
):
    payload = _create_payload("policy@example.invalid", "observer")
    payload["temporary_password"] = password
    payload["confirm_password"] = password
    assert client.post("/api/users", headers=auth_headers, json=payload).status_code == 422


def test_reset_forces_password_change_and_never_audits_secrets(
    client, auth_headers, session_factory
):
    target_id = _add_user(
        session_factory, email="reset-user@example.invalid", role="mechanic"
    )
    reset = client.post(
        f"/api/users/{target_id}/reset-password",
        headers=auth_headers,
        json={
            "temporary_password": "Temporary456!",
            "confirm_password": "Temporary456!",
        },
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["user"]["must_change_password"] is True
    assert "temporary_password" not in reset.text
    headers, login = _login(client, "reset-user@example.invalid", "Temporary456!")
    assert login["user"]["must_change_password"] is True
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    blocked = client.get("/api/repairs", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "password_change_required"
    wrong = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={
            "current_password": "Wrong123!",
            "new_password": "Permanent789!",
            "confirm_password": "Permanent789!",
        },
    )
    assert wrong.status_code == 400
    changed = client.post(
        "/api/auth/change-password",
        headers=headers,
        json={
            "current_password": "Temporary456!",
            "new_password": "Permanent789!",
            "confirm_password": "Permanent789!",
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["user"]["must_change_password"] is False
    new_headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert client.get("/api/repairs", headers=new_headers).status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    with session_factory() as session:
        audit_text = "\n".join(
            filter(None, session.scalars(select(AuditLog.details)).all())
        )
        assert "Temporary456!" not in audit_text
        assert "Permanent789!" not in audit_text
        user = session.get(User, target_id)
        assert user.password_changed_at is not None
        assert verify_password("Permanent789!", user.password_hash)


def test_login_updates_last_login_and_role_reset_invalidates_old_token(
    client, auth_headers, session_factory
):
    target_id = _add_user(
        session_factory, email="token-user@example.invalid", role="mechanic"
    )
    headers, body = _login(client, "token-user@example.invalid")
    assert datetime.fromisoformat(body["user"]["last_login_at"])
    changed = client.patch(
        f"/api/users/{target_id}", headers=auth_headers, json={"role": "observer"}
    )
    assert changed.status_code == 200
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_observer_receives_only_machine_status_location_and_limited_search(
    client, session_factory, machine_ids
):
    _add_user(session_factory, email="observer@example.invalid", role="observer")
    headers, _ = _login(client, "observer@example.invalid")
    listing = client.get("/api/machines", headers=headers)
    assert listing.status_code == 200
    machine = listing.json()[0]
    assert {"id", "inventory_number", "name", "brand", "model", "status", "location"} <= set(machine)
    assert "serial_number" not in machine
    assert "pressure_bar" not in machine
    passport = client.get(
        f"/api/machines/{machine_ids['7']}/passport", headers=headers
    )
    assert passport.status_code == 200
    assert passport.json()["limited_view"] is True
    for key in (
        "repairs",
        "transfers",
        "part_requests",
        "generated_documents",
        "technical_documents",
        "audit",
    ):
        assert passport.json()[key] == []
    search = client.get("/api/search?q=Falch", headers=headers)
    assert search.status_code == 200
    assert search.json()["machines"]
    assert search.json()["parts"] == []
    assert "serial_number" not in search.json()["machines"][0]
    for protected_path in (
        "/api/locations",
        "/api/categories",
        "/api/departments",
        "/api/technical-library",
        "/api/admin/reference-data",
        "/api/audit",
        f"/api/machines/{machine_ids['7']}/qr",
    ):
        assert client.get(protected_path, headers=headers).status_code == 403


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/transfers/bulk-issue", {"machine_ids": [1]}),
        ("post", "/api/transfers/bulk-return", {"items": []}),
        ("post", "/api/repair-cases", {"machine_id": 1, "reported_problem": "x"}),
        ("post", "/api/part-requests/multi", {"lines": []}),
    ],
)
def test_observer_cannot_mutate_operational_workflows(
    client, session_factory, method, path, payload
):
    _add_user(session_factory, email="observer@example.invalid", role="observer")
    headers, _ = _login(client, "observer@example.invalid")
    assert getattr(client, method)(path, headers=headers, json=payload).status_code == 403


def test_permission_matrix_matches_final_role_contract():
    assert set(ROLE_PERMISSIONS) == {
        "administrator",
        "director",
        "mechanic",
        "observer",
    }
    assert ROLE_PERMISSIONS["administrator"] == frozenset(Permission)
    assert Permission.USERS_CREATE in ROLE_PERMISSIONS["director"]
    assert Permission.REQUESTS_APPROVE in ROLE_PERMISSIONS["director"]
    assert Permission.SETTINGS_MANAGE not in ROLE_PERMISSIONS["director"]
    assert Permission.USERS_VIEW not in ROLE_PERMISSIONS["mechanic"]
    assert ROLE_PERMISSIONS["observer"] == frozenset({Permission.ASSETS_VIEW})


def test_director_cannot_manage_settings_but_owner_can(
    client, auth_headers, session_factory
):
    _add_user(session_factory, email="director@example.invalid", role="director")
    director_headers, _ = _login(client, "director@example.invalid")
    assert client.get(
        "/api/admin/reference-data", headers=director_headers
    ).status_code == 403
    assert client.get("/api/admin/reference-data", headers=auth_headers).status_code == 200


def test_no_physical_user_delete_endpoint(client, auth_headers, session_factory):
    target_id = _add_user(
        session_factory, email="preserved@example.invalid", role="observer"
    )
    assert client.delete(f"/api/users/{target_id}", headers=auth_headers).status_code == 405
    with session_factory() as session:
        assert session.get(User, target_id) is not None


def test_mechanic_operational_workflows_and_director_request_approval(
    client, session_factory, machine_ids, issue_payload, finalize_signatures
):
    """Integration coverage for the final mechanic/director operational boundary."""
    _add_user(session_factory, email="mechanic-workflow@example.invalid", role="mechanic")
    mechanic_headers, _ = _login(client, "mechanic-workflow@example.invalid")
    _add_user(session_factory, email="director-approval@example.invalid", role="director")
    director_headers, _ = _login(client, "director-approval@example.invalid")

    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=mechanic_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert issued.status_code == 201, issued.text
    finalize_signatures(client, issued)
    transfer = issued.json()["transfers"][0]
    assert len(transfer["documents"]) == 2

    returned = client.post(
        "/api/transfers/bulk-return",
        headers=mechanic_headers,
        json={
            "items": [
                {
                    "transfer_id": transfer["transfer_id"],
                    "machine_id": transfer["machine_id"],
                    "condition_text": "test-only returned condition",
                    "result_text": "test-only inspection routing",
                    "notes": "",
                    "returned_by": "",
                    "accepted_by": "",
                    "next_status": "READY",
                    "returned_person": {
                        "first_name": "Тестов",
                        "middle_name": "Външен",
                        "last_name": "Връщащ",
                        "job_title": "Тестова длъжност",
                        "company_or_department": "Тестово звено",
                    },
                }
            ]
        },
    )
    assert returned.status_code == 200, returned.text
    finalize_signatures(client, returned)

    repair = client.post(
        "/api/repair-cases",
        headers=mechanic_headers,
        json={
            "machine_id": machine_ids["5"],
            "reported_problem": "test-only mechanic report",
            "condition_before": "test-only initial condition",
            "cleaning_required": False,
            "test_required": True,
        },
    )
    assert repair.status_code == 201, repair.text
    repair_id = repair.json()["id"]
    for payload in (
        {
            "status": "DIAGNOSIS",
            "inspection_complete": True,
            "diagnosis": "test-only mechanic diagnosis",
            "required_work": "test-only mechanic required work",
            "diagnosis_minutes": 20,
        },
        {"status": "REPAIRING", "work_performed": "test-only mechanic work", "repair_minutes": 35},
        {"status": "TESTING"},
        {
            "status": "COMPLETED",
            "test_passed": True,
            "test_details": "test-only successful mechanic test",
            "testing_minutes": 10,
            "condition_after": "test-only final condition",
            "result": "test-only completed repair",
        },
    ):
        transition = client.patch(
            f"/api/repair-cases/{repair_id}", headers=mechanic_headers, json=payload
        )
        assert transition.status_code == 200, transition.text
    assert transition.json()["status"] == "COMPLETED"

    request = client.post(
        "/api/part-requests/multi",
        headers=mechanic_headers,
        json={
            "machine_id": machine_ids["4"],
            "priority": "NORMAL",
            "language": "bg",
            "reason": "test-only mechanic request",
            "lines": [
                {
                    "description": "test-only manually identified requirement",
                    "quantity": 1,
                    "unit": "pcs",
                }
            ],
        },
    )
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    submitted = client.post(
        f"/api/part-requests/{request_id}/submit", headers=mechanic_headers
    )
    assert submitted.status_code == 200, submitted.text
    own_approval = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=mechanic_headers,
        json={"decision": "APPROVED", "note": "must be rejected"},
    )
    assert own_approval.status_code == 403
    approved = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=director_headers,
        json={"decision": "APPROVED", "note": "test-only director approval"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
