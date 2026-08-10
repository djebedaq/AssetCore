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
    RepairStatus.DIAGNOSIS.value: {RepairStatus.REPAIRING.value},
    RepairStatus.REPAIRING.value: {RepairStatus.COMPLETED.value},
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


def ensure_repair_stage_requirements(repair: Repair, new: str) -> None:
    """Validate data at the moment it becomes operationally required."""
    missing: list[str] = []
    message = ""
    if new == RepairStatus.DIAGNOSIS.value:
        if not (repair.reported_problem or "").strip():
            missing.append("reported_problem")
        if not (repair.condition_before or "").strip():
            missing.append("condition_before")
        message = (
            "За преминаване към Диагностика попълнете описанието на проблема "
            "и състоянието при приемане."
        )
    elif new == RepairStatus.REPAIRING.value:
        if not (repair.diagnosis or "").strip():
            missing.append("diagnosis")
        if not (repair.required_work or "").strip():
            missing.append("required_work")
        if not repair.diagnosis_minutes:
            missing.append("diagnosis_minutes")
        message = (
            "За преминаване към ремонт попълнете диагнозата, необходимата работа "
            "и реалното време за диагностика."
        )
    if missing:
        raise business_conflict(
            (
                "repair_completion_requirements_missing"
                if new == RepairStatus.COMPLETED.value
                else "repair_stage_requirements_missing"
            ),
            message,
            current_status=repair.status,
            requested_status=new,
            missing_fields=missing,
        )


def ensure_repair_can_start_finalization(repair: Repair) -> None:
    missing_fields: list[str] = []
    if not (repair.work_performed or "").strip():
        missing_fields.append("work_performed")
    if not repair.repair_minutes:
        missing_fields.append("repair_minutes")
    if missing_fields:
        raise business_conflict(
            "repair_stage_requirements_missing",
            "За преминаване към финалната проверка попълнете извършената работа и реалното време за ремонт.",
            current_status=repair.status,
            requested_status=RepairStatus.REPAIRING.value,
            missing_fields=missing_fields,
        )


def ensure_repair_can_complete(repair: Repair) -> None:
    missing_fields: list[str] = []
    missing_requirements: list[str] = []

    def require_text(field: str, label: str) -> None:
        if not (getattr(repair, field) or "").strip():
            missing_fields.append(field)
            missing_requirements.append(label)

    require_text("reported_problem", "описание на проблема")
    require_text("condition_before", "състояние при приемане")
    require_text("diagnosis", "диагноза")
    require_text("required_work", "необходима работа")
    require_text("work_performed", "описание на извършената работа")
    require_text("result", "краен резултат")
    require_text("condition_after", "състояние след ремонта")
    if repair.test_required and repair.test_passed is not True:
        missing_fields.append("test_passed")
        missing_requirements.append("успешен тест")
    if repair.test_required and not (repair.test_method or "").strip():
        missing_fields.append("test_method")
        missing_requirements.append("метод на тестване")
    if repair.test_required and not (repair.test_details or "").strip():
        missing_fields.append("test_details")
        missing_requirements.append("описание на теста")
    if not repair.diagnosis_minutes:
        missing_fields.append("diagnosis_minutes")
        missing_requirements.append("реално време за диагностика")
    if not repair.repair_minutes:
        missing_fields.append("repair_minutes")
        missing_requirements.append("реално време за ремонт")
    if repair.test_required and not repair.testing_minutes:
        missing_fields.append("testing_minutes")
        missing_requirements.append("реално време за тестване")
    if missing_fields:
        raise business_conflict(
            "repair_completion_requirements_missing",
            "Ремонтът не може да бъде завършен преди да са попълнени и проверени всички задължителни данни.",
            missing_fields=missing_fields,
            missing_requirements=missing_requirements,
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
