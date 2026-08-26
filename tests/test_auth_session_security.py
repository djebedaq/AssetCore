from __future__ import annotations

from datetime import timedelta

from app.auth_sessions import secret_hash
from app.auth_throttle import remote_source
from app.main import app
from app.models import AuthenticationThrottle, AuthSession, User, utcnow
from app.security import hash_password
from app.settings import Settings, settings
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from starlette.requests import Request


def _session_login(
    client: TestClient,
    *,
    email: str = "admin@assetcore.local",
    password: str = "AssetCore123!",
):
    response = client.post(
        "/api/auth/login",
        headers={"X-AssetCore-Auth-Mode": "session"},
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    assert "access_token" not in response.json()
    session_token = client.cookies.get(settings.session_cookie_name)
    csrf_token = client.cookies.get(settings.csrf_cookie_name)
    assert session_token
    assert csrf_token
    return response, session_token, csrf_token


def _add_login_user(session_factory, email: str, role: str = "mechanic") -> int:
    with session_factory() as db:
        user = User(
            email=email,
            full_name="Тестов Потребител Сесия",
            first_name="Тестов",
            middle_name="Потребител",
            last_name="Сесия",
            job_title="QA",
            profile_status="PROFILE_COMPLETE",
            password_hash=hash_password("StrongPass123!"),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return user.id


def test_browser_login_uses_hashed_durable_session_and_explicit_cookie_policy(
    client, session_factory
):
    response, raw_session, raw_csrf = _session_login(client)
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(
        value for value in cookies if value.startswith(f"{settings.session_cookie_name}=")
    )
    csrf_cookie = next(
        value for value in cookies if value.startswith(f"{settings.csrf_cookie_name}=")
    )

    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie
    assert "Max-Age=" in session_cookie
    assert "Secure" not in session_cookie

    with session_factory() as db:
        stored = db.scalar(select(AuthSession))
        assert stored is not None
        assert stored.token_hash == secret_hash(raw_session)
        assert stored.csrf_token_hash == secret_hash(raw_csrf)
        assert stored.token_hash != raw_session
        assert stored.csrf_token_hash != raw_csrf


def test_production_cookie_marks_session_secure(client, monkeypatch):
    monkeypatch.setattr(settings, "deployment_environment", "production")
    secure_client = TestClient(app, base_url="https://testserver")
    try:
        response, _, _ = _session_login(secure_client)
    finally:
        secure_client.close()
    session_cookie = next(
        value
        for value in response.headers.get_list("set-cookie")
        if value.startswith(f"{settings.session_cookie_name}=")
    )
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie


def test_session_reload_get_and_csrf_protected_mutation(client):
    _, _, csrf_token = _session_login(client)
    assert client.get("/api/auth/me").status_code == 200

    missing = client.patch(
        "/api/users/me/preferences",
        json={"preferred_language": "en"},
    )
    assert missing.status_code == 403
    assert missing.json()["detail"]["code"] == "csrf_failed"

    invalid = client.patch(
        "/api/users/me/preferences",
        headers={"X-CSRF-Token": "invalid-test-csrf"},
        json={"preferred_language": "en"},
    )
    assert invalid.status_code == 403
    assert invalid.json()["detail"]["code"] == "csrf_failed"

    valid = client.patch(
        "/api/users/me/preferences",
        headers={"X-CSRF-Token": csrf_token},
        json={"preferred_language": "en"},
    )
    assert valid.status_code == 200, valid.text
    assert valid.json()["preferred_language"] == "en"


def test_logout_revokes_session_and_old_cookie_cannot_be_replayed(client):
    _, raw_session, csrf_token = _session_login(client)
    response = client.post(
        "/api/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 204
    assert client.cookies.get(settings.session_cookie_name) is None

    replay_client = TestClient(app)
    try:
        replay_client.cookies.set(settings.session_cookie_name, raw_session)
        replay = replay_client.get("/api/auth/me")
    finally:
        replay_client.close()
    assert replay.status_code == 401
    assert replay.json()["detail"]["code"] == "invalid_session"


def test_expired_and_revoked_sessions_are_rejected(client, session_factory):
    _, raw_session, _ = _session_login(client)
    with session_factory() as db:
        stored = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == secret_hash(raw_session))
        )
        stored.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/auth/me").status_code == 401

    client.cookies.clear()
    _, raw_session, _ = _session_login(client)
    with session_factory() as db:
        stored = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == secret_hash(raw_session))
        )
        stored.revoked_at = utcnow()
        stored.revoked_reason = "test_revocation"
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_deactivation_and_role_change_invalidate_existing_sessions(
    client, session_factory
):
    user_id = _add_login_user(session_factory, "session-state@example.invalid")
    _session_login(
        client,
        email="session-state@example.invalid",
        password="StrongPass123!",
    )
    with session_factory() as db:
        user = db.get(User, user_id)
        user.role = "observer"
        user.token_version += 1
        db.commit()
    assert client.get("/api/auth/me").status_code == 401

    client.cookies.clear()
    _session_login(
        client,
        email="session-state@example.invalid",
        password="StrongPass123!",
    )
    with session_factory() as db:
        user = db.get(User, user_id)
        user.is_active = False
        user.token_version += 1
        db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_password_change_rotates_current_session_and_revokes_other_sessions(
    client, session_factory
):
    _, _, first_csrf = _session_login(client)
    second_client = TestClient(app)
    try:
        _session_login(second_client)
        changed = client.post(
            "/api/auth/change-password",
            headers={"X-CSRF-Token": first_csrf},
            json={
                "current_password": "AssetCore123!",
                "new_password": "ChangedOwner123!",
                "confirm_password": "ChangedOwner123!",
            },
        )
        assert changed.status_code == 200, changed.text
        assert "access_token" not in changed.json()
        assert second_client.get("/api/auth/me").status_code == 401
    finally:
        second_client.close()
    assert client.get("/api/auth/me").status_code == 200


def test_login_throttle_is_temporary_and_does_not_lock_unrelated_account(
    client, session_factory, monkeypatch
):
    _add_login_user(session_factory, "unrelated@example.invalid", role="observer")
    monkeypatch.setattr(settings, "login_rate_limit_attempts", 3)
    monkeypatch.setattr(settings, "login_source_rate_limit_attempts", 100)
    monkeypatch.setattr(settings, "login_rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "login_rate_limit_base_block_seconds", 5)
    monkeypatch.setattr(settings, "login_rate_limit_max_block_seconds", 5)

    statuses = [
        client.post(
            "/api/auth/login",
            headers={"X-AssetCore-Auth-Mode": "session"},
            json={"email": "admin@assetcore.local", "password": "wrong-password"},
        ).status_code
        for _ in range(3)
    ]
    assert statuses == [401, 401, 429]
    blocked = client.post(
        "/api/auth/login",
        headers={"X-AssetCore-Auth-Mode": "session"},
        json={"email": "admin@assetcore.local", "password": "AssetCore123!"},
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "authentication_throttled"
    assert int(blocked.headers["Retry-After"]) >= 1

    unrelated = client.post(
        "/api/auth/login",
        headers={"X-AssetCore-Auth-Mode": "session"},
        json={"email": "unrelated@example.invalid", "password": "StrongPass123!"},
    )
    assert unrelated.status_code == 200, unrelated.text

    with session_factory() as db:
        for row in db.scalars(select(AuthenticationThrottle)):
            row.blocked_until = utcnow() - timedelta(seconds=1)
            row.window_started_at = utcnow() - timedelta(seconds=61)
        db.commit()
    recovered = client.post(
        "/api/auth/login",
        headers={"X-AssetCore-Auth-Mode": "session"},
        json={"email": "admin@assetcore.local", "password": "AssetCore123!"},
    )
    assert recovered.status_code == 200, recovered.text


def test_login_rejects_cross_site_browser_origin(client):
    response = client.post(
        "/api/auth/login",
        headers={
            "Origin": "https://untrusted.example.invalid",
            "Sec-Fetch-Site": "cross-site",
            "X-AssetCore-Auth-Mode": "session",
        },
        json={"email": "admin@assetcore.local", "password": "AssetCore123!"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"


def test_forwarded_source_is_used_only_for_a_configured_trusted_proxy(monkeypatch):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": [(b"x-forwarded-for", b"203.0.113.8")],
            "client": ("127.0.0.1", 41000),
            "server": ("testserver", 80),
            "scheme": "http",
            "http_version": "1.1",
        }
    )
    monkeypatch.setattr(settings, "trusted_proxy_ips", None)
    assert remote_source(request) == "127.0.0.1"
    monkeypatch.setattr(settings, "trusted_proxy_ips", "127.0.0.1/32")
    assert remote_source(request) == "203.0.113.8"


def test_bearer_compatibility_is_rejected_in_production_configuration():
    try:
        Settings(
            _env_file=None,
            deployment_environment="production",
            frontend_origin="https://assetcore.example.invalid",
            bearer_compatibility_enabled=True,
        )
    except ValidationError as exc:
        assert "restricted to development/test" in str(exc)
    else:
        raise AssertionError("Production settings accepted bearer compatibility")


def test_owner_emergency_reauthentication_remains_required_for_cookie_session(client):
    _, _, csrf_token = _session_login(client)
    response = client.post(
        "/api/emergency-access/start",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "reason": "Проверка на защитеното повторно удостоверяване за аварийна процедура.",
            "current_password": "wrong-password",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "reauthentication_failed"
