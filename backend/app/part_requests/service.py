from __future__ import annotations

from contextlib import contextmanager
from math import isfinite
from threading import RLock
from typing import Iterator

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..audit import add_audit_log
from ..models import (
    ApprovalDecision,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    PartRequestStatus,
    User,
    utcnow,
)
from ..permissions import Permission, has_permission
from ..workflow import business_conflict

OFFICIAL_DOCUMENT_STATUSES = frozenset(
    {
        PartRequestStatus.APPROVED.value,
        PartRequestStatus.ORDERED.value,
        PartRequestStatus.PARTIALLY_DELIVERED.value,
        PartRequestStatus.DELIVERED.value,
    }
)

_sqlite_document_generation_lock = RLock()


def _is_whole_quantity(value: float) -> bool:
    numeric = float(value)
    return isfinite(numeric) and numeric.is_integer()


def part_request_quantity_compatibility(request: PartRequest) -> dict:
    affected_lines = [
        {
            "line_id": line.id,
            "quantity": line.quantity,
            "delivered_quantity": line.delivered_quantity,
        }
        for line in request.lines
        if not _is_whole_quantity(line.quantity)
        or not _is_whole_quantity(line.delivered_quantity)
    ]
    if not affected_lines:
        return {
            "status": "COMPATIBLE",
            "affected_line_ids": [],
            "recovery_action": "NONE",
        }
    if request.status == PartRequestStatus.DRAFT.value:
        recovery_action = "CREATE_REPLACEMENT"
    elif request.status in {
        PartRequestStatus.SUBMITTED.value,
        PartRequestStatus.WAITING_APPROVAL.value,
    }:
        recovery_action = "REJECT_AND_RECREATE"
    elif request.status in {
        PartRequestStatus.APPROVED.value,
        PartRequestStatus.ORDERED.value,
        PartRequestStatus.PARTIALLY_DELIVERED.value,
    }:
        recovery_action = "CANCEL_AND_RECREATE"
    else:
        recovery_action = "HISTORICAL_ONLY"
    return {
        "status": "LEGACY_FRACTIONAL",
        "affected_line_ids": [line["line_id"] for line in affected_lines],
        "recovery_action": recovery_action,
        "affected_lines": affected_lines,
    }


def legacy_quantity_conflict(request: PartRequest) -> HTTPException:
    compatibility = part_request_quantity_compatibility(request)
    recovery_action = compatibility["recovery_action"]
    messages = {
        "CREATE_REPLACEMENT": (
            "Историческата чернова съдържа дробни количества и не може да бъде "
            "подадена по целочисления процес. Създайте нова заявка с цели количества; "
            "черновата ще остане в историята без промяна."
        ),
        "REJECT_AND_RECREATE": (
            "Историческата заявка съдържа дробни количества и не може да бъде "
            "одобрена по целочисления процес. Отхвърлете я и създайте нова заявка "
            "с цели количества."
        ),
        "CANCEL_AND_RECREATE": (
            "Историческата заявка съдържа дробни количества и не може да бъде "
            "изпълнена по целочисления процес. Отменете я без промяна на количествата "
            "и създайте нова заявка с цели количества."
        ),
        "HISTORICAL_ONLY": (
            "Заявката съдържа исторически дробни количества и е достъпна само като "
            "непроменена история."
        ),
    }
    return business_conflict(
        "legacy_fractional_part_request_requires_recovery",
        messages[recovery_action],
        request_reference=request.request_reference,
        current_status=request.status,
        recovery_action=recovery_action,
        affected_line_ids=compatibility["affected_line_ids"],
        affected_lines=compatibility.get("affected_lines", []),
    )


def _request_statement(request_id: int):
    return (
        select(PartRequest)
        .options(
            joinedload(PartRequest.machine),
            joinedload(PartRequest.repair),
            joinedload(PartRequest.requested_by),
            joinedload(PartRequest.decided_by),
            selectinload(PartRequest.lines).selectinload(
                PartRequestLine.linked_catalog_part
            ),
            selectinload(PartRequest.approvals).joinedload(
                PartRequestApproval.decided_by
            ),
            selectinload(PartRequest.attachments),
        )
        .where(PartRequest.id == request_id)
    )


def load_request(
    db: Session, request_id: int, *, lock: bool = False
) -> PartRequest | None:
    statement = _request_statement(request_id)
    if lock and db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update(of=PartRequest)
    return db.scalar(statement)


@contextmanager
def part_request_document_generation_guard(db: Session) -> Iterator[None]:
    """Serialize local SQLite generation while PostgreSQL uses the request row lock."""
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        with _sqlite_document_generation_lock:
            yield
        return
    yield


def submit_for_approval(
    db: Session,
    request: PartRequest,
    user: User,
    *,
    line_count: int | None = None,
) -> None:
    if request.status != PartRequestStatus.DRAFT.value:
        raise business_conflict(
            "part_request_not_draft",
            "Само чернова може да бъде изпратена за одобрение.",
            request_reference=request.request_reference,
            current_status=request.status,
        )
    resolved_line_count = len(request.lines) if line_count is None else line_count
    if resolved_line_count < 1:
        raise business_conflict(
            "part_request_has_no_lines", "Заявката няма редове с части."
        )
    if part_request_quantity_compatibility(request)["status"] == "LEGACY_FRACTIONAL":
        raise legacy_quantity_conflict(request)
    previous_status = request.status
    request.status = PartRequestStatus.WAITING_APPROVAL.value
    request.submitted_at = utcnow()
    request.decided_at = None
    request.decided_by_id = None
    request.decision_note = None
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "Заявката е изпратена за одобрение",
        {
            "request_reference": request.request_reference,
            "previous_status": previous_status,
            "new_status": request.status,
            "line_count": resolved_line_count,
        },
        request.request_reference,
    )


def decide_request(
    db: Session,
    request: PartRequest,
    user: User,
    decision: ApprovalDecision,
    note: str | None,
) -> None:
    if request.status != PartRequestStatus.WAITING_APPROVAL.value:
        raise business_conflict(
            "part_request_not_waiting_approval",
            "Заявката не очаква одобрение.",
            request_reference=request.request_reference,
            current_status=request.status,
        )
    if (
        decision == ApprovalDecision.APPROVED
        and part_request_quantity_compatibility(request)["status"]
        == "LEGACY_FRACTIONAL"
    ):
        raise legacy_quantity_conflict(request)
    previous_status = request.status
    if decision == ApprovalDecision.APPROVED:
        request.status = PartRequestStatus.APPROVED.value
    elif decision == ApprovalDecision.REJECTED:
        request.status = PartRequestStatus.REJECTED.value
    else:
        request.status = PartRequestStatus.DRAFT.value
    request.decided_at = utcnow()
    request.decided_by_id = user.id
    request.decision_note = note
    db.add(
        PartRequestApproval(
            request_id=request.id,
            decision=decision.value,
            note=note,
            decided_by_id=user.id,
        )
    )
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "Решение по заявка за части",
        {
            "request_reference": request.request_reference,
            "decision": decision.value,
            "previous_status": previous_status,
            "new_status": request.status,
        },
        request.request_reference,
    )


def pending_action_count(db: Session, user: User) -> int:
    if not has_permission(user, Permission.REQUESTS_APPROVE):
        return 0
    return int(
        db.scalar(
            select(func.count(PartRequest.id)).where(
                PartRequest.status == PartRequestStatus.WAITING_APPROVAL.value
            )
        )
        or 0
    )
