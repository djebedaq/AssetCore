"""Free-form editing and event-based execution inside the canonical requests workflow."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..database import get_db
from ..models import AuditLog, PartRequest, PartRequestLine, RequestDeliveryEvent, User, utcnow
from ..permissions import Permission, ensure_request_draft_editor, require_permission
from ..persistence import _commit
from ..workflow import business_conflict
from .official import canonical_hash, ensure_editable, quantity, received, record_receipt, utc_iso
from .request_schemas import (
    DeliveryCorrection,
    DeliveryCreate,
    FreeFormRequest,
    RequestCancel,
    decimal_text,
)
from .service import load_request, submit_for_approval

router = APIRouter()
creator = require_permission(Permission.REQUESTS_CREATE)
approver = require_permission(Permission.REQUESTS_APPROVE)
viewer = require_permission(Permission.REQUESTS_VIEW)


def output(request, db):
    from ..industrial_api import _part_request_dict
    from ..models import GeneratedDocument

    docs = list(
        db.scalars(select(GeneratedDocument).where(GeneratedDocument.part_request_id == request.id))
    )
    return _part_request_dict(request, docs)


@router.get("/part-requests/{request_id}/history")
def history(
    request_id: int,
    offset: int = Query(0, ge=0),
    _: User = Depends(viewer),
    db: Session = Depends(get_db),
):
    if db.get(PartRequest, request_id) is None:
        raise HTTPException(404, detail={"code": "request_not_found"})
    rows = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "part_request", AuditLog.entity_id == request_id)
            .order_by(AuditLog.id.desc())
            .offset(offset)
            .limit(101)
        )
    )
    aliases = {
        "Създадена многоредова заявка за части": "CREATED",
        "Заявката е изпратена за одобрение": "SUBMITTED",
        "Решение по заявка за части": "DECISION",
        "Обновено изпълнение на заявка за части": "EXECUTION",
        "Генериран документ за заявка за части": "REQUEST_DOCUMENTS_ARCHIVED",
    }
    codes = {
        "FREE_FORM_CREATED",
        "FREE_FORM_EDITED",
        "REQUEST_ORDERED",
        "REQUEST_CANCELLED",
        "REQUEST_DELIVERY_RECORDED",
        "REQUEST_DELIVERY_REVERSED",
        "REQUEST_DOCUMENTS_ARCHIVED",
        "REQUEST_DOCUMENT_GENERATION_FAILED",
    }
    return {
        "has_next": len(rows) > 100,
        "items": [
            {
                "id": row.id,
                "action_code": aliases.get(
                    row.action, row.action if row.action in codes else "OTHER"
                ),
                "actor_name": row.user_name,
                "occurred_at": utc_iso(row.created_at),
            }
            for row in rows[:100]
        ],
    }


def required(db, identifier):
    request = load_request(db, identifier, lock=True)
    if request is None:
        raise HTTPException(404, detail={"code": "request_not_found"})
    return request


def write_lines(db, request, payload):
    request.department, request.reason, request.language = (
        payload.department,
        payload.reason,
        payload.language,
    )
    request.part_name = payload.lines[0].description
    request.lines.clear()
    db.flush()
    for index, row in enumerate(payload.lines, 1):
        request.lines.append(
            PartRequestLine(
                position=str(index),
                description=row.description,
                quantity=float(row.quantity),
                exact_quantity=decimal_text(row.quantity),
                unit=row.unit,
            )
        )
    db.flush()


@router.post("/part-requests/free-form", status_code=201)
def create_free_form(
    payload: FreeFormRequest, user: User = Depends(creator), db: Session = Depends(get_db)
):
    request = PartRequest(
        request_kind="FREE_FORM",
        part_name=payload.lines[0].description,
        requested_by_id=user.id,
        status="DRAFT",
        language=payload.language,
    )
    db.add(request)
    db.flush()
    request.request_reference = f"PR-{request.created_at:%Y}-{request.id:06d}"
    write_lines(db, request, payload)
    if payload.submit_for_approval:
        submit_for_approval(db, request, user)
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "FREE_FORM_CREATED",
        {"line_count": len(payload.lines)},
    )
    _commit(db)
    return output(request, db)


@router.put("/part-requests/{request_id}/free-form")
def edit_free_form(
    request_id: int,
    payload: FreeFormRequest,
    user: User = Depends(creator),
    db: Session = Depends(get_db),
):
    request = required(db, request_id)
    ensure_editable(request)
    ensure_request_draft_editor(user, request.requested_by_id)
    if request.request_kind != "FREE_FORM" or request.status != "DRAFT":
        raise business_conflict(
            "request_not_editable_draft", "Редакция е допустима само за чернова на свободна заявка."
        )
    write_lines(db, request, payload)
    if payload.submit_for_approval:
        submit_for_approval(db, request, user)
    add_audit_log(
        db, user, "part_request", request.id, "FREE_FORM_EDITED", {"line_count": len(payload.lines)}
    )
    _commit(db)
    return output(request, db)


@router.get("/part-requests/{request_id}/preview")
def preview(request_id: int, _: User = Depends(viewer), db: Session = Depends(get_db)):
    from ..documents.request_issue_documents import preview_pdf

    request = load_request(db, request_id)
    if request is None:
        raise HTTPException(404, detail={"code": "request_not_found"})
    ensure_editable(request)
    if request.status not in {"DRAFT", "SUBMITTED", "WAITING_APPROVAL", "REJECTED"}:
        raise business_conflict("request_already_approved", "Заявката вече е одобрена.")
    return Response(
        preview_pdf(db, request),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="request-preview.pdf"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _existing(request, key, digest):
    existing = next((e for e in request.delivery_events if e.idempotency_key == key), None)
    if existing and existing.payload_sha256 != digest:
        raise business_conflict(
            "delivery_idempotency_conflict", "Ключът за доставка вече е използван."
        )
    return existing


def _status(request):
    if request.status == "CANCELLED":
        return
    totals = received(request)
    request.status = (
        "DELIVERED"
        if all(totals[line.id] == quantity(line) for line in request.lines)
        else "PARTIALLY_DELIVERED"
        if any(totals.values())
        else "ORDERED"
        if request.ordered_at
        else "APPROVED"
    )
    request.delivered_at = utcnow() if request.status == "DELIVERED" else None


@router.post("/part-requests/{request_id}/deliveries", status_code=201)
def add_delivery(
    request_id: int,
    payload: DeliveryCreate,
    user: User = Depends(creator),
    db: Session = Depends(get_db),
):
    request = required(db, request_id)
    digest = canonical_hash(payload.model_dump(mode="json"))
    if _existing(request, payload.idempotency_key, digest):
        return output(request, db)
    event = record_receipt(
        db,
        request,
        user,
        {row.line_id: row.quantity for row in payload.lines},
        supplier=payload.supplier,
        note=payload.note,
        key=payload.idempotency_key,
        digest=digest,
    )
    _status(request)
    add_audit_log(
        db, user, "part_request", request.id, "REQUEST_DELIVERY_RECORDED", {"event_id": event.id}
    )
    _commit(db)
    return output(request, db)


@router.post("/part-requests/{request_id}/deliveries/{event_id}/reverse", status_code=201)
def reverse_delivery(
    request_id: int,
    event_id: int,
    payload: DeliveryCorrection,
    user: User = Depends(creator),
    db: Session = Depends(get_db),
):
    request = required(db, request_id)
    digest = canonical_hash({**payload.model_dump(), "event_id": event_id})
    if request.status == "CANCELLED":
        raise business_conflict(
            "cancelled_request_delivery_locked", "Доставките на отменена заявка са заключени."
        )
    if _existing(request, payload.idempotency_key, digest):
        return output(request, db)
    original = next((e for e in request.delivery_events if e.id == event_id), None)
    if (
        not original
        or original.kind != "RECEIPT"
        or any(e.correction_of_id == event_id for e in request.delivery_events)
    ):
        raise business_conflict(
            "delivery_not_reversible", "Доставката не може да бъде сторнирана повторно."
        )
    event = RequestDeliveryEvent(
        request_id=request.id,
        actor_id=user.id,
        actor_name=user.full_name,
        occurred_at=datetime.now(UTC),
        kind="CORRECTION",
        correction_of_id=event_id,
        quantities={k: decimal_text(-Decimal(v)) for k, v in original.quantities.items()},
        note=payload.reason,
        idempotency_key=payload.idempotency_key,
        payload_sha256=digest,
    )
    request.delivery_events.append(event)
    db.flush()
    _status(request)
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "REQUEST_DELIVERY_REVERSED",
        {"event_id": event.id, "correction_of_id": event_id, "reason": payload.reason},
    )
    _commit(db)
    return output(request, db)


def cancel(db, request, user, payload):
    if request.status == "CANCELLED":
        raise business_conflict("request_already_cancelled", "Заявката вече е отменена.")
    if request.status not in {"APPROVED", "ORDERED", "PARTIALLY_DELIVERED"}:
        raise business_conflict("request_not_cancellable", "Заявката не допуска отмяна.")
    if payload.replacement_request_id:
        replacement = db.get(PartRequest, payload.replacement_request_id)
        if replacement is None or replacement.id == request.id:
            raise business_conflict("invalid_replacement_request", "Невалидна заместваща заявка.")
    request.status = "CANCELLED"
    request.cancelled_at, request.cancelled_by_id = datetime.now(UTC), user.id
    request.cancellation_reason, request.replacement_request_id = (
        payload.reason,
        payload.replacement_request_id,
    )
    add_audit_log(
        db,
        user,
        "part_request",
        request.id,
        "REQUEST_CANCELLED",
        {"reason": payload.reason, "replacement_request_id": payload.replacement_request_id},
        request.approval_snapshot.official_number
        if request.approval_snapshot
        else request.request_reference,
    )


@router.post("/part-requests/{request_id}/cancel")
def cancel_request(
    request_id: int,
    payload: RequestCancel,
    user: User = Depends(approver),
    db: Session = Depends(get_db),
):
    request = required(db, request_id)
    cancel(db, request, user, payload)
    _commit(db)
    return output(request, db)
