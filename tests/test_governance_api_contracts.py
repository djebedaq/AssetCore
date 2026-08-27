"""Pre-extraction governance contracts, using only isolated test databases."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
from datetime import timedelta
from pathlib import Path

import pytest
from app import hardening_api, licensing
from app.main import app
from app.models import AuditLog, AuthSession, EmergencyAccessSession, SoftwareLicense, User
from app.security import hash_password
from app.settings import settings
from app.web_security import CONTENT_SECURITY_POLICY
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import func, select

GOLDEN = Path(__file__).parent / "fixtures" / "governance_api_baseline.json"
PATHS = (
    "/api/owner",
    "/api/owner/audit",
    "/api/owner/transfer",
    "/api/emergency-access/status",
    "/api/emergency-access/start",
    "/api/emergency-access/{session_id}/end",
    "/api/license/status",
    "/api/license/validate",
    "/api/license/install",
)
REASON = "Isolated governance regression; no production operation."


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _dependency_contract(dependant):
    call = dependant.call
    name = getattr(call, "__qualname__", type(call).__qualname__)
    module = getattr(call, "__module__", type(call).__module__)
    return {
        "call": f"{module}.{name}",
        "parameter": dependant.name,
        "permission": getattr(call, "__assetcore_permission__", None),
        "use_cache": dependant.use_cache,
        "dependencies": [_dependency_contract(item) for item in dependant.dependencies],
    }


def governance_contracts():
    """Freeze actual OpenAPI operations and complete nested auth dependencies."""
    schema = app.openapi()
    routes = [route for route in app.routes if isinstance(route, APIRoute) and route.path in PATHS]
    operations = {path: schema["paths"][path] for path in PATHS}
    referenced = set()

    def include_references(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                name = reference.rsplit("/", 1)[-1]
                if name not in referenced:
                    referenced.add(name)
                    include_references(schema["components"]["schemas"][name])
            for child in value.values():
                include_references(child)
        elif isinstance(value, list):
            for child in value:
                include_references(child)

    include_references(operations)
    return {
        "routes": {
            f"{method} {route.path}": {
                "name": route.name,
                "status_code": route.status_code,
                "tags": route.tags,
                "dependencies": [_dependency_contract(item) for item in route.dependant.dependencies],
                "openapi_sha256": _sha(operations[route.path][method.lower()]),
            }
            for route in routes
            for method in sorted(route.methods)
        },
        "schemas": {
            name: _sha(schema["components"]["schemas"][name]) for name in sorted(referenced)
        },
    }


def _payloads():
    return {
        "/api/owner/transfer": {
            "target_user_id": 1, "current_password": "AssetCore123!", "reason": REASON,
        },
        "/api/emergency-access/start": {
            "current_password": "AssetCore123!", "reason": REASON, "duration_minutes": 5,
        },
        "/api/emergency-access/999999/end": {
            "current_password": "AssetCore123!", "reason": REASON,
        },
        "/api/license/install": {"payload": {}, "signature": "x" * 88},
    }


def _new_user(factory, role="administrator"):
    with factory() as db:
        user = User(
            email=f"governance-{role}@example.invalid", full_name="QA Governance User",
            first_name="QA", middle_name="Governance", last_name="User", job_title="QA",
            profile_status="PROFILE_COMPLETE", role=role,
            password_hash=hash_password("StrongPass123!"), is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id, user.email


def _login(client, email="admin@assetcore.local", password="AssetCore123!", *, browser=False):
    response = client.post(
        "/api/auth/login", headers={"X-AssetCore-Auth-Mode": "session" if browser else "bearer"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    if browser:
        return {"X-CSRF-Token": client.cookies.get(settings.csrf_cookie_name)}
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _security_headers(response):
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_governance_openapi_and_auth_dependencies_match_pre_extraction_baseline():
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert governance_contracts() == expected["contracts"]
    assert len(expected["contracts"]["routes"]) == 9


def test_all_governance_routes_require_authentication(client):
    for path in PATHS:
        url = path.replace("{session_id}", "999999")
        payload = _payloads().get(url)
        response = client.get(url) if payload is None else client.post(url, json=payload)
        assert response.status_code == 401, url
        _security_headers(response)


def test_all_governance_mutations_require_session_bound_csrf(client, session_factory):
    csrf = _login(client, browser=True)
    with session_factory() as db:
        before = db.scalar(select(func.count(AuditLog.id)))
    for path, payload in _payloads().items():
        for headers in ({}, {"X-CSRF-Token": "not-the-session-token"}):
            response = client.post(path, headers=headers, json=payload)
            assert response.status_code == 403, path
            assert response.json()["detail"]["code"] == "csrf_failed"
            _security_headers(response)
    with session_factory() as db:
        assert db.scalar(select(func.count(AuditLog.id))) == before
        assert db.scalar(select(func.count(EmergencyAccessSession.id))) == 0
    assert client.get("/api/owner", headers=csrf).status_code == 200


@pytest.mark.parametrize("role", ["administrator", "director", "mechanic", "observer"])
def test_role_never_substitutes_for_owner_designation(client, session_factory, role):
    identifier, email = _new_user(session_factory, role)
    headers = _login(client, email, "StrongPass123!")
    for path, payload in _payloads().items():
        response = client.post(path, headers=headers, json=payload)
        assert response.status_code == 403, path
        assert response.json()["detail"]["code"] == "owner_only"
    response = client.get("/api/owner/audit", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_only"
    for path in ("/api/owner", "/api/license/status", "/api/license/validate", "/api/emergency-access/status"):
        assert client.get(path, headers=headers).status_code == 200
    with session_factory() as db:
        user = db.get(User, identifier)
        assert user.role == role and not user.is_system_owner
        assert db.scalar(select(func.count(SoftwareLicense.id))) == 0
        assert db.scalar(select(func.count(EmergencyAccessSession.id))) == 0


def test_protected_owner_profile_is_unchanged_by_another_administrator(client, auth_headers, session_factory):
    _, email = _new_user(session_factory)
    headers = _login(client, email, "StrongPass123!")
    owner_id = client.get("/api/owner", headers=auth_headers).json()["owner_user_id"]
    with session_factory() as db:
        owner = db.get(User, owner_id)
        original = (owner.full_name, owner.job_title, owner.token_version)
    response = client.put(
        f"/api/users/{owner_id}/profile", headers=headers,
        json={"first_name": "QA", "middle_name": "Blocked", "last_name": "Change", "job_title": "QA"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "owner_profile_protected"
    with session_factory() as db:
        owner = db.get(User, owner_id)
        assert (owner.full_name, owner.job_title, owner.token_version) == original


def test_owner_transfer_preserves_audit_and_revokes_both_owners_sessions(client, auth_headers, session_factory):
    target_id, email = _new_user(session_factory)
    target_bearer = _login(client, email, "StrongPass123!")
    owner_id = client.get("/api/owner", headers=auth_headers).json()["owner_user_id"]
    owner_browser, target_browser = TestClient(app), TestClient(app)
    try:
        owner_csrf = _login(owner_browser, browser=True)
        _login(target_browser, email, "StrongPass123!", browser=True)
        data = {"target_user_id": target_id, "current_password": "AssetCore123!", "reason": REASON}
        rejected = owner_browser.post(
            "/api/owner/transfer", headers={**owner_csrf, "X-Request-ID": "qa-owner-rejected"},
            json={**data, "current_password": "wrong-qa-password"},
        )
        assert rejected.status_code == 403
        assert rejected.json()["detail"] == {
            "code": "reauthentication_failed", "message": "Текущата парола е неправилна.",
        }
        transferred = owner_browser.post(
            "/api/owner/transfer", headers={**owner_csrf, "X-Request-ID": "qa-owner-success"}, json=data,
        )
        assert transferred.status_code == 200
        assert transferred.json()["owner_user_id"] == target_id
        assert transferred.json()["designation_version"] == 2
        assert owner_browser.get("/api/auth/me").status_code == 401
        assert target_browser.get("/api/auth/me").status_code == 401
    finally:
        owner_browser.close()
        target_browser.close()
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 401
    assert client.get("/api/auth/me", headers=target_bearer).status_code == 401
    with session_factory() as db:
        assert not db.get(User, owner_id).is_system_owner
        assert db.get(User, target_id).is_system_owner
        assert {db.get(User, value).role for value in (owner_id, target_id)} == {"administrator"}
        sessions = db.scalars(select(AuthSession)).all()
        assert len(sessions) == 2
        assert all(row.revoked_at for row in sessions)
        assert {row.revoked_reason for row in sessions} == {"owner_transferred", "owner_designated"}
        entries = db.scalars(select(AuditLog).where(AuditLog.entity_type == "installation_owner").order_by(AuditLog.id)).all()
        assert [row.action for row in entries] == ["Отказано прехвърляне на собственост", "Прехвърлена собственост на инсталацията"]
        assert [row.operation_reference for row in entries] == ["qa-owner-rejected", "qa-owner-success"]
        assert json.loads(entries[0].details) == {"result": "rejected", "target_user_id": target_id, "reason": "invalid_reauthentication"}
        assert json.loads(entries[1].details) == {"previous_owner_user_id": owner_id, "new_owner_user_id": target_id, "reason": REASON, "designation_version": 2}
        assert all(row.user_id == owner_id for row in entries)
    fresh = _login(client, email, "StrongPass123!")
    history = client.get("/api/owner/audit", headers=fresh)
    assert history.status_code == 200
    assert [row["correlation_id"] for row in history.json()] == ["qa-owner-success", "qa-owner-rejected"]


@pytest.mark.parametrize("path", ["/api/owner/transfer", "/api/emergency-access/start", "/api/emergency-access/999999/end"])
def test_sensitive_reauthentication_keeps_bounded_throttle(client, auth_headers, session_factory, monkeypatch, path):
    monkeypatch.setattr(settings, "sensitive_rate_limit_attempts", 2)
    payload = {**_payloads()[path], "current_password": "wrong-qa-password"}
    first = client.post(path, headers=auth_headers, json=payload)
    second = client.post(path, headers=auth_headers, json=payload)
    third = client.post(path, headers=auth_headers, json=_payloads()[path])
    assert [first.status_code, second.status_code, third.status_code] == [403, 429, 429]
    assert first.json()["detail"]["code"] == "reauthentication_failed"
    assert second.json()["detail"]["code"] == third.json()["detail"]["code"] == "authentication_throttled"
    assert int(third.headers["retry-after"]) > 0
    with session_factory() as db:
        assert all("wrong-qa-password" not in (row.details or "") for row in db.scalars(select(AuditLog)))


def test_emergency_end_and_expiry_keep_exact_conflicts(client, auth_headers, session_factory):
    data = _payloads()["/api/emergency-access/start"]
    first = client.post("/api/emergency-access/start", headers=auth_headers, json=data)
    assert first.status_code == 201
    identifier = first.json()["session_id"]
    end = {"current_password": "AssetCore123!", "reason": REASON}
    missing = client.post("/api/emergency-access/999999/end", headers=auth_headers, json=end)
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "emergency_access_not_found"
    with session_factory() as db:
        item = db.get(EmergencyAccessSession, identifier)
        item.expires_at = licensing.utcnow() - timedelta(seconds=1)
        db.commit()
    expired = client.post(f"/api/emergency-access/{identifier}/end", headers=auth_headers, json=end)
    assert expired.status_code == 409
    assert expired.json()["detail"]["code"] == "emergency_access_not_active"
    assert client.get("/api/emergency-access/status", headers=auth_headers).json()["active"] is False
    second = client.post("/api/emergency-access/start", headers=auth_headers, json=data)
    assert second.status_code == 201
    with session_factory() as db:
        old = db.get(EmergencyAccessSession, identifier)
        assert old.ended_at == old.expires_at
        assert old.end_reason == "Автоматично приключване след изтичане на определения срок."
    end_path = f"/api/emergency-access/{second.json()['session_id']}/end"
    assert client.post(end_path, headers=auth_headers, json=end).status_code == 200
    duplicate = client.post(end_path, headers=auth_headers, json=end)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "emergency_access_not_active"


def test_license_read_only_install_history_and_emergency_do_not_bypass_rbac(client, auth_headers, session_factory, monkeypatch):
    # The private key exists only in this isolated test's memory, never in the app.
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    monkeypatch.setattr(settings, "license_public_key", base64.b64encode(public).decode())
    monkeypatch.setattr(settings, "installation_id", "governance-qa")
    monkeypatch.setattr(settings, "deployment_environment", "development")
    now = licensing.utcnow()

    def envelope(identifier, end):
        payload = {
            "license_id": identifier, "rightsholder": licensing.RIGHTSHOLDER,
            "client_name": "Isolated QA", "installation_id": "governance-qa",
            "modules": ["assets"], "max_users": 100, "max_assets": 100,
            "valid_from": (now - timedelta(days=1)).isoformat(), "valid_until": end.isoformat(),
            "license_type": "ANNUAL", "environment": "development", "allowed_domains": [],
            "max_installations": 1, "grace_days": 0, "version": 1,
        }
        return {"payload": payload, "signature": base64.b64encode(key.sign(licensing.canonical_payload(payload))).decode()}

    first = envelope("QA-GOV-1", now + timedelta(days=1))
    installed = client.post("/api/license/install", headers=auth_headers, json=first)
    assert installed.status_code == 200 and installed.json()["state"] == "ACTIVE"
    duplicate = client.post("/api/license/install", headers=auth_headers, json=first)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "license_already_installed"
    invalid = client.post("/api/license/install", headers=auth_headers, json={**first, "signature": base64.b64encode(b"x" * 64).decode()})
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "invalid_license_signature"
    monkeypatch.setattr(licensing, "utcnow", lambda: now + timedelta(days=2))
    monkeypatch.setattr(settings, "license_enforcement_enabled", True)
    monkeypatch.setattr(importlib.import_module("app.main"), "SessionLocal", session_factory)
    state = client.get("/api/license/status", headers=auth_headers)
    validate = client.get("/api/license/validate", headers=auth_headers)
    assert state.json() == validate.json()
    assert state.json()["read_only"] and state.json()["state"] == "READ_ONLY"
    assert client.get("/api/machines", headers=auth_headers).status_code == 200
    started = client.post("/api/emergency-access/start", headers=auth_headers, json=_payloads()["/api/emergency-access/start"])
    assert started.status_code == 201
    # Starting emergency context does not make the canonical licence writable.
    # The pre-existing HTTP serialization defect is reproduced separately below.
    with session_factory() as db:
        assert licensing.evaluate_license(db).read_only is True
    second = envelope("QA-GOV-2", now + timedelta(days=10))
    replaced = client.post("/api/license/install", headers=auth_headers, json=second)
    assert replaced.status_code == 200 and replaced.json()["state"] == "ACTIVE"
    with session_factory() as db:
        records = db.scalars(select(SoftwareLicense).order_by(SoftwareLicense.id)).all()
        assert len(records) == 2
        assert not records[0].is_active and records[0].superseded_at
        assert records[0].payload == first["payload"]
        assert records[0].signature == first["signature"]
        assert records[0].payload_sha256 == licensing.payload_hash(first["payload"])
        assert records[1].is_active
        entries = db.scalars(select(AuditLog).where(AuditLog.entity_type == "software_license").order_by(AuditLog.id)).all()
        assert [entry.action for entry in entries] == ["Инсталиран и проверен лиценз", "Отказано инсталиране на лиценз", "Инсталиран и проверен лиценз"]
        assert json.loads(entries[-1].details)["previous_license_id"] == "QA-GOV-1"
        emergency = db.scalar(select(AuditLog).where(AuditLog.entity_type == "emergency_access"))
        assert json.loads(emergency.details)["permissions_elevated"] is False


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="Pre-existing main.py licence middleware passes datetime to plain JSONResponse; outside zero-behavior-change extraction.",
)
def test_known_license_read_only_http_serialization_regression(client, auth_headers, session_factory, monkeypatch):
    # Reproduced on base 37b9c0f before extraction. A fix must remove this marker;
    # strict XPASS makes that lifecycle explicit, without changing the middleware here.
    monkeypatch.setattr(settings, "license_enforcement_enabled", True)
    monkeypatch.setattr(importlib.import_module("app.main"), "SessionLocal", session_factory)
    diagnostic_client = TestClient(app, raise_server_exceptions=True)
    try:
        blocked = diagnostic_client.patch("/api/machines/999999", headers=auth_headers, json={})
    finally:
        diagnostic_client.close()
    assert blocked.status_code == 423
    assert blocked.json()["detail"]["code"] == "license_read_only"
    _security_headers(blocked)


def test_legacy_governance_imports_are_route_callables():
    for route in hardening_api.router.routes:
        if isinstance(route, APIRoute) and route.path in PATHS:
            assert getattr(hardening_api, route.name) is route.endpoint
