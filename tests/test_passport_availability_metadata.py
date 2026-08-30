from __future__ import annotations

import app.assets.passport as passport_module
from app.models import (
    AuditLog,
    Machine,
    MachineStatus,
    Repair,
    RepairStatus,
    TransferProtocol,
    utcnow,
)
from app.permissions import Permission
from sqlalchemy import func, select


def _create_active_repair(client, auth_headers, machine_id: int) -> dict:
    response = client.post(
        "/api/repair-cases",
        headers=auth_headers,
        json={
            "machine_id": machine_id,
            "reported_problem": "Изолиран тест за паспортно състояние",
            "condition_before": "Приета за проверка на метаданните",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _passport(client, headers, machine_id: int) -> dict:
    response = client.get(f"/api/machines/{machine_id}/passport", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_ready_machine_passport_is_available_and_issuable(
    client, auth_headers, machine_ids
):
    passport = _passport(client, auth_headers, machine_ids["4"])

    assert passport["machine"]["status"] == MachineStatus.READY.value
    assert passport["current_state"]["active_transfer"] is None
    assert passport["current_state"]["active_repair"] is None
    assert passport["current_state"]["available"] is True
    assert passport["current_state"]["allowed_actions"] == {
        "issue": True,
        "return": False,
        "repair": True,
        "edit": True,
    }


def test_active_repair_disables_passport_availability_and_issue_action(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["4"]
    repair = _create_active_repair(client, auth_headers, machine_id)
    with session_factory() as db:
        audit_count_before = db.scalar(select(func.count(AuditLog.id)))

    passport = _passport(client, auth_headers, machine_id)

    assert passport["machine"]["status"] == MachineStatus.REPAIR.value
    assert passport["current_state"]["active_transfer"] is None
    assert passport["current_state"]["active_repair"]["id"] == repair["id"]
    assert passport["current_state"]["allowed_actions"]["issue"] is False
    assert passport["current_state"]["available"] is False
    assert passport["current_state"]["allowed_actions"]["repair"] is False
    with session_factory() as db:
        stored_repair = db.get(Repair, repair["id"])
        stored_machine = db.get(Machine, machine_id)
        assert stored_repair.status == RepairStatus.ACCEPTED.value
        assert stored_machine.status == MachineStatus.REPAIR.value
        assert db.scalar(select(func.count(AuditLog.id))) == audit_count_before


def test_active_repair_issue_guard_remains_authoritative(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    machine_id = machine_ids["5"]
    repair = _create_active_repair(client, auth_headers, machine_id)

    response = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_id),
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "issue_conflict",
        "message": "Машина №5 е в ремонт.",
        "conflicts": [
            {
                "machine_id": machine_id,
                "machine_number": "5",
                "status": MachineStatus.REPAIR.value,
                "status_label": "В ремонт",
                "issue_status": None,
                "return_status": None,
                "active_transfer_id": None,
                "protocol_number": None,
                "batch_reference": None,
                "issued_at": None,
                "current_recipient_or_location": "Цех",
                "active_repair_id": repair["id"],
                "repair_reference": repair["repair_reference"],
                "message": "Машина №5 е в ремонт.",
            }
        ],
    }
    with session_factory() as db:
        assert db.scalar(select(func.count(TransferProtocol.id))) == 0
        assert db.get(Repair, repair["id"]).status == RepairStatus.ACCEPTED.value
        assert db.get(Machine, machine_id).status == MachineStatus.REPAIR.value


def test_active_transfer_passport_preserves_return_action(
    client, auth_headers, machine_ids, issue_payload, finalize_signatures
):
    machine_id = machine_ids["7"]
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_id),
    )
    assert issued.status_code == 201, issued.text
    finalize_signatures(client, issued)

    passport = _passport(client, auth_headers, machine_id)

    assert passport["machine"]["status"] == MachineStatus.ISSUED.value
    assert passport["current_state"]["active_transfer"] is not None
    assert passport["current_state"]["active_repair"] is None
    assert passport["current_state"]["available"] is False
    assert passport["current_state"]["allowed_actions"]["issue"] is False
    assert passport["current_state"]["allowed_actions"]["return"] is True


def test_inactive_machine_passport_is_not_available_or_issuable(
    client, auth_headers, machine_ids
):
    machine_id = machine_ids["9"]
    updated = client.patch(
        f"/api/machines/{machine_id}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert updated.status_code == 200, updated.text

    passport = _passport(client, auth_headers, machine_id)

    assert passport["machine"]["is_active"] is False
    assert passport["current_state"]["available"] is False
    assert passport["current_state"]["allowed_actions"]["issue"] is False


def test_completed_repair_is_historical_for_passport_availability(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["12"]
    repair = _create_active_repair(client, auth_headers, machine_id)
    with session_factory() as db:
        stored_repair = db.get(Repair, repair["id"])
        stored_repair.status = RepairStatus.COMPLETED.value
        stored_repair.closed_at = utcnow()
        stored_machine = db.get(Machine, machine_id)
        stored_machine.status = MachineStatus.READY.value
        db.commit()

    passport = _passport(client, auth_headers, machine_id)

    assert passport["current_state"]["active_repair"] is None
    assert passport["current_state"]["available"] is True
    assert passport["current_state"]["allowed_actions"]["issue"] is True
    assert passport["current_state"]["allowed_actions"]["repair"] is True
    assert passport["repairs"][0]["status"] == RepairStatus.COMPLETED.value


def test_observer_active_repair_passport_stays_limited_and_has_no_actions(
    client, auth_headers, viewer_headers, machine_ids
):
    machine_id = machine_ids["13"]
    _create_active_repair(client, auth_headers, machine_id)

    passport = _passport(client, viewer_headers, machine_id)

    assert passport["limited_view"] is True
    assert passport["machine"]["status"] == MachineStatus.REPAIR.value
    assert passport["current_state"]["active_repair"] == {
        "status": RepairStatus.ACCEPTED.value
    }
    assert passport["current_state"]["available"] is False
    assert passport["current_state"]["allowed_actions"] == {
        "issue": False,
        "return": False,
        "repair": False,
        "edit": False,
    }
    assert passport["qr_endpoint"] is None
    assert passport["audit_visible"] is False


def test_issue_action_requires_transfer_create_permission_even_when_available(
    client, auth_headers, machine_ids, monkeypatch
):
    original_has_permission = passport_module.has_permission

    def restricted_permission(user, permission):
        if permission == Permission.TRANSFERS_CREATE:
            return False
        return original_has_permission(user, permission)

    monkeypatch.setattr(passport_module, "has_permission", restricted_permission)

    passport = _passport(client, auth_headers, machine_ids["14"])

    assert passport["current_state"]["available"] is True
    assert passport["current_state"]["allowed_actions"]["issue"] is False
    assert passport["current_state"]["allowed_actions"]["repair"] is True
