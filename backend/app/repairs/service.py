from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..application_errors import unexpected_workflow_error
from ..document_generation import (
    ConfirmedTemplateUnavailableError,
    TemplateValidationError,
    make_repair_documents,
)
from ..models import (
    GeneratedDocument,
    Location,
    Repair,
    RepairEventType,
    RepairStatus,
    User,
    utcnow,
)
from ..workflow import (
    REPAIR_TO_MACHINE_STATUS,
    business_conflict,
    ensure_machine_transition,
    ensure_repair_can_complete,
    ensure_repair_stage_requirements,
    ensure_repair_transition,
)

logger = logging.getLogger("uvicorn.error")

REPAIR_TRANSITION_EVENTS = {
    RepairStatus.DIAGNOSIS.value: RepairEventType.DIAGNOSIS.value,
    RepairStatus.REPAIRING.value: RepairEventType.REPAIR_ACTION.value,
    RepairStatus.COMPLETED.value: RepairEventType.COMPLETED.value,
}


def _active_workshop_location(db: Session) -> Location:
    statement = select(Location).where(
        Location.name == "Цех",
        Location.is_active.is_(True),
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update()
    workshop = db.scalar(statement)
    if workshop is None:
        raise business_conflict(
            "active_workshop_location_missing",
            "Ремонтът не може да бъде завършен, защото няма активно местоположение „Цех“.",
        )
    return workshop


def apply_repair_transition(
    db: Session,
    repair: Repair,
    next_status: str,
    user: User,
) -> tuple[str, int | None]:
    """Apply the canonical repair and machine transition without committing."""
    ensure_repair_transition(repair.status, next_status)
    ensure_repair_stage_requirements(repair, next_status)
    previous_location_id = repair.machine.location_id
    if next_status == RepairStatus.COMPLETED.value:
        ensure_repair_can_complete(repair)
        workshop = _active_workshop_location(db)
        now = utcnow()
        repair.closed_at = now
        repair.approved_by_id = user.id
        repair.approved_by = user
        repair.approved_at = now
        repair.machine.location_id = workshop.id
    if next_status == RepairStatus.REPAIRING.value and repair.started_at is None:
        repair.started_at = utcnow()
    repair.status = next_status
    machine_status = REPAIR_TO_MACHINE_STATUS[next_status]
    try:
        ensure_machine_transition(repair.machine.status, machine_status)
    except HTTPException as exc:
        repair_controlled = set(REPAIR_TO_MACHINE_STATUS.values())
        if (
            repair.machine.status not in repair_controlled
            or machine_status not in repair_controlled
        ):
            raise exc
    repair.machine.status = machine_status
    return REPAIR_TRANSITION_EVENTS[next_status], previous_location_id


def generate_completion_documents_or_rollback(
    db: Session,
    repair: Repair,
    user: User,
) -> list[GeneratedDocument]:
    """Persist required repair files, rolling back the whole owner transaction on failure."""
    db.flush()
    db.expire(repair, ["events", "parts_used", "participants", "attachments"])
    try:
        documents = make_repair_documents(db, repair, user.id, "bg")
        db.add_all(documents)
        db.flush()
        return documents
    except ConfirmedTemplateUnavailableError as exc:
        db.rollback()
        raise business_conflict(
            "repair_protocol_template_unavailable",
            exc.message,
            document_type=exc.document_type,
            language="bg",
        ) from exc
    except TemplateValidationError as exc:
        db.rollback()
        raise business_conflict(
            "repair_protocol_generation_failed",
            "Ремонтът не е приключен, защото задължителният протокол не може да бъде генериран.",
            document_type="REPAIR_PROTOCOL",
            language="bg",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise unexpected_workflow_error(
            logger,
            exc,
            code="repair_protocol_generation_failed",
            message=(
                "Ремонтът не е приключен поради грешка при генериране "
                "на задължителния протокол."
            ),
            operation="repair_completion",
            stage="document_generation",
            diagnostic_prefix="REPERR",
            context={
                "repair_id": repair.id,
                "machine_id": repair.machine_id,
                "user_id": user.id,
            },
        ) from exc
