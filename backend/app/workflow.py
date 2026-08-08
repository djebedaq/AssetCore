from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .models import Machine, MachineEvent, MachineStatus, Repair, RepairStatus, User

MACHINE_STATUS_TRANSITIONS: dict[str, set[str]] = {
    MachineStatus.READY.value: {
        MachineStatus.ISSUED.value,
        MachineStatus.REPAIR.value,
    },
    MachineStatus.ISSUED.value: {
        MachineStatus.READY.value,
        MachineStatus.REPAIR.value,
    },
    MachineStatus.REPAIR.value: {MachineStatus.READY.value},
}

REPAIR_STATUS_TRANSITIONS: dict[str, set[str]] = {
    RepairStatus.ACCEPTED.value: {RepairStatus.DIAGNOSIS.value},
    RepairStatus.DIAGNOSIS.value: {
        RepairStatus.WAITING_APPROVAL.value,
        RepairStatus.WAITING_PARTS.value,
        RepairStatus.REPAIRING.value,
    },
    RepairStatus.WAITING_APPROVAL.value: {
        RepairStatus.WAITING_PARTS.value,
        RepairStatus.REPAIRING.value,
    },
    RepairStatus.WAITING_PARTS.value: {RepairStatus.REPAIRING.value},
    RepairStatus.REPAIRING.value: {
        RepairStatus.WAITING_PARTS.value,
        RepairStatus.TESTING.value,
    },
    RepairStatus.TESTING.value: {
        RepairStatus.REPAIRING.value,
        RepairStatus.COMPLETED.value,
    },
    RepairStatus.COMPLETED.value: set(),
}

REPAIR_TO_MACHINE_STATUS = {
    RepairStatus.ACCEPTED.value: MachineStatus.REPAIR.value,
    RepairStatus.DIAGNOSIS.value: MachineStatus.REPAIR.value,
    RepairStatus.WAITING_APPROVAL.value: MachineStatus.REPAIR.value,
    RepairStatus.WAITING_PARTS.value: MachineStatus.REPAIR.value,
    RepairStatus.REPAIRING.value: MachineStatus.REPAIR.value,
    RepairStatus.TESTING.value: MachineStatus.REPAIR.value,
    RepairStatus.COMPLETED.value: MachineStatus.READY.value,
}


def business_conflict(code: str, message: str, **details: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **details},
    )


def ensure_machine_transition(current: str, new: str) -> None:
    if current == new:
        return
    if new not in MACHINE_STATUS_TRANSITIONS.get(current, set()):
        raise business_conflict(
            "invalid_machine_status_transition",
            f"Преходът на машината от „{current}“ към „{new}“ не е разрешен.",
            current_status=current,
            requested_status=new,
        )


def ensure_repair_transition(current: str, new: str) -> None:
    if current == new:
        return
    if new not in REPAIR_STATUS_TRANSITIONS.get(current, set()):
        raise business_conflict(
            "invalid_repair_status_transition",
            f"Преходът на ремонта от „{current}“ към „{new}“ не е разрешен.",
            current_status=current,
            requested_status=new,
        )


def ensure_repair_can_complete(repair: Repair) -> None:
    missing: list[str] = []
    if repair.inspection_completed_at is None:
        missing.append("преглед")
    if repair.cleaning_required and repair.cleaning_completed_at is None:
        missing.append("почистване")
    if repair.test_required and repair.test_passed is not True:
        missing.append("успешен тест")
    if not (repair.work_performed or "").strip():
        missing.append("описание на извършената работа")
    if not (repair.result or "").strip():
        missing.append("резултат")
    if missing:
        raise business_conflict(
            "repair_completion_requirements_missing",
            "Ремонтът не може да бъде завършен преди всички задължителни стъпки.",
            missing_requirements=missing,
        )


def add_machine_event(
    db: Session,
    machine: Machine,
    user: User | None,
    event_type: str,
    *,
    reference: str | None = None,
    previous_status: str | None = None,
    new_status: str | None = None,
    previous_location_id: int | None = None,
    new_location_id: int | None = None,
    details: dict | None = None,
) -> MachineEvent:
    event = MachineEvent(
        machine_id=machine.id,
        event_type=event_type,
        reference=reference,
        previous_status=previous_status,
        new_status=new_status,
        previous_location_id=previous_location_id,
        new_location_id=new_location_id,
        details=details,
        user_id=user.id if user else None,
    )
    db.add(event)
    return event
