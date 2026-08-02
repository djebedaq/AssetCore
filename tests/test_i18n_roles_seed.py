from __future__ import annotations

import json
import re
from pathlib import Path

from app.localization import MESSAGES, STATUS_LABELS, SUPPORTED_LANGUAGES
from app.models import AuditLog, Machine, MachineStatus, User
from app.security import hash_password
from app.seed import seed_database
from sqlalchemy import select


def _create_user(session_factory, *, email: str, role: str, language: str = "bg"):
    with session_factory() as session:
        session.add(
            User(
                email=email,
                full_name=f"Test {role}",
                first_name="Test",
                middle_name="Automation",
                last_name=role.title(),
                job_title=f"Test {role}",
                profile_status="PROFILE_COMPLETE",
                password_hash=hash_password("test-only-password"),
                role=role,
                preferred_language=language,
            )
        )
        session.commit()


def _login(client, email: str, language: str = "bg") -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        headers={"Accept-Language": language},
        json={"email": email, "password": "test-only-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}", "Accept-Language": language}


def test_language_preference_is_returned_persisted_and_audited(
    client, auth_headers, session_factory
):
    current = client.get("/api/auth/me", headers=auth_headers)
    assert current.status_code == 200
    assert current.json()["preferred_language"] == "bg"

    changed = client.patch(
        "/api/users/me/preferences",
        headers=auth_headers,
        json={"preferred_language": "en"},
    )
    assert changed.status_code == 200
    assert changed.json()["preferred_language"] == "en"

    with session_factory() as session:
        user = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        assert user.preferred_language == "en"
        entry = session.scalar(
            select(AuditLog).where(AuditLog.action == "Променен предпочитан език")
        )
        assert json.loads(entry.details) == {
            "previous_language": "bg",
            "new_language": "en",
        }


def test_director_can_issue_mechanic_can_repair_and_observer_cannot_mutate(
    client, session_factory, machine_ids, issue_payload, viewer_headers
):
    _create_user(session_factory, email="director@example.invalid", role="director")
    director_headers = _login(client, "director@example.invalid")
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=director_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert issued.status_code == 201, issued.text

    _create_user(session_factory, email="mechanic@example.invalid", role="mechanic")
    mechanic_headers = _login(client, "mechanic@example.invalid")
    repair = client.post(
        "/api/repairs",
        headers=mechanic_headers,
        json={
            "machine_id": machine_ids["5"],
            "reported_problem": "test-only reported condition",
            "status": "ACCEPTED",
        },
    )
    assert repair.status_code == 201, repair.text

    forbidden = client.post(
        "/api/machines",
        headers=viewer_headers,
        json={
            "inventory_number": "test-only",
            "name": "test-only",
            "category": "test-only",
            "brand": "test-only",
            "pressure_bar": 0,
            "status": "READY",
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["code"] == "permission_denied"


def test_russian_profile_localizes_duplicate_issue_conflict(
    client, session_factory, machine_ids, issue_payload
):
    _create_user(
        session_factory,
        email="director-ru@example.invalid",
        role="director",
        language="ru",
    )
    headers = _login(client, "director-ru@example.invalid", "ru")
    first = client.post(
        "/api/transfers/bulk-issue",
        headers=headers,
        json=issue_payload(machine_ids["7"]),
    )
    second = client.post(
        "/api/transfers/bulk-issue",
        headers=headers,
        json=issue_payload(machine_ids["7"]),
    )
    assert first.status_code == 201
    assert second.status_code == 409
    detail = second.json()["detail"]
    assert "Оборудование №7" in detail["message"]
    assert detail["conflicts"][0]["status"] == "READY"
    assert detail["conflicts"][0]["issue_status"] == "AWAITING_SIGNATURE"


def test_seed_never_deletes_user_managed_future_category(session_factory):
    with session_factory() as session:
        record = Machine(
            inventory_number="test-user-managed-record",
            name="test-only asset record",
            category="test-future-category",
            brand="test-only",
            pressure_bar=0,
            status=MachineStatus.READY.value,
        )
        session.add(record)
        session.commit()
        record_id = record.id
        seed_database(session)
        preserved = session.get(Machine, record_id)
        assert preserved is not None
        assert preserved.category == "test-future-category"


def test_unknown_historical_status_remains_readable(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        session.add(
            Machine(
                inventory_number="test-historical-status",
                name="test-only historical record",
                category="test-future-category",
                brand="test-only",
                pressure_bar=0,
                status="LEGACY_UNMAPPED_STATUS",
            )
        )
        session.commit()

    machines = client.get("/api/machines", headers=auth_headers)
    availability = client.get("/api/transfers/availability", headers=auth_headers)
    assert machines.status_code == 200
    assert availability.status_code == 200
    assert any(
        item["status"] == "LEGACY_UNMAPPED_STATUS" for item in machines.json()
    )
    historical = next(
        item
        for item in availability.json()
        if item["machine_number"] == "test-historical-status"
    )
    assert historical["available"] is False
    assert historical["status_label"] == "LEGACY_UNMAPPED_STATUS"


def test_backend_catalogs_have_exact_language_parity_and_stable_status_codes():
    expected_languages = set(SUPPORTED_LANGUAGES)
    assert all(set(translations) == expected_languages for translations in MESSAGES.values())
    assert all(
        set(translations) == expected_languages for translations in STATUS_LABELS.values()
    )
    assert {status.value for status in MachineStatus} == {
        "READY",
        "ISSUED",
        "IN_USE",
        "RETURNED",
        "INSPECTION",
        "CLEANING",
        "REPAIR",
        "WAITING_APPROVAL",
        "WAITING_PARTS",
        "TESTING",
    }


def test_react_components_contain_no_hardcoded_cyrillic_user_text():
    root = Path(__file__).resolve().parents[1]
    for relative_path in [
        "frontend/src/App.tsx",
        "frontend/src/BulkTransfers.tsx",
        "frontend/src/IndustrialPlatform.tsx",
        "frontend/src/api.ts",
    ]:
        source = (root / relative_path).read_text(encoding="utf-8")
        assert re.search(r"[А-Яа-яЁё]", source) is None, relative_path
