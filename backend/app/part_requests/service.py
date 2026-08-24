from __future__ import annotations

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
        PartRequestStatus.CANCELLED.value,
    }
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
