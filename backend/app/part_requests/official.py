"""Transactional KK issue and immutable approval evidence. Caller owns commit."""

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..models import (
    DocumentType,
    GeneratedDocument,
    OfficialDocument,
    PartRequest,
    RequestApprovalSnapshot,
    RequestNumberCounter,
)
from ..template_engine import source_bytes
from ..workflow import business_conflict
from .request_schemas import decimal_text


def canonical_hash(data):
    return hashlib.sha256(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def utc_iso(value):
    return (
        value.replace(tzinfo=UTC).isoformat()
        if value and value.tzinfo is None
        else (value.isoformat() if value else None)
    )


def kind(request):
    if request.request_kind == "FREE_FORM":
        return "FREE_FORM"
    if request.repair_kit_id:
        return "REPAIR_KIT"
    return "UNKNOWN_PART" if any(line.is_unknown_part for line in request.lines) else "CATALOG"


def quantity(line):
    return (
        Decimal(line.exact_quantity)
        if line.exact_quantity is not None
        else Decimal(str(line.quantity))
    )


def capture_data(request):
    from ..documents.part_request_documents import _request_snapshot

    data = _request_snapshot(request)
    data["submitted_at"], data["decided_at"] = utc_iso(request.submitted_at), utc_iso(request.decided_at)
    data.update(
        {
            "schema_version": 1,
            "request_kind": kind(request),
            "requested_by_name": request.requested_by.full_name if request.requested_by else None,
            "requested_by_job_title": request.requested_by.job_title
            if request.requested_by
            else None,
            "approved_by_name": request.decided_by.full_name if request.decided_by else None,
            "approved_by_job_title": request.decided_by.job_title if request.decided_by else None,
            "machine": (
                {
                    key: getattr(request.machine, key)
                    for key in (
                        "name",
                        "inventory_number",
                        "brand",
                        "model",
                        "serial_number",
                        "pressure_bar",
                    )
                }
                if request.machine
                else None
            ),
            "attachments": [
                {
                    "id": a.id,
                    "line_id": a.request_line_id,
                    "filename": a.filename,
                    "media_type": a.media_type,
                    "sha256": hashlib.sha256(a.content).hexdigest(),
                }
                for a in request.attachments
            ],
        }
    )
    if request.decided_by:
        actor = request.decided_by
        data["prepared_by"] = {
            "user_id": actor.id,
            "first_name": actor.first_name,
            "middle_name": actor.middle_name,
            "last_name": actor.last_name,
            "display_name": actor.full_name,
            "job_title": actor.job_title,
            "department_id": actor.department_id,
            "department": actor.profile_department.name_bg if actor.profile_department else None,
            "legal_name_exception_confirmed": bool(
                actor.legal_name_exception
                and actor.legal_name_exception_reason
                and actor.legal_name_exception_approved_by_id
                and actor.legal_name_exception_approved_at
            ),
            "operation_role": "PREPARER",
            "captured_at": utc_iso(request.decided_at),
        }
    for saved, line in zip(data["lines"], sorted(request.lines, key=lambda x: x.id), strict=True):
        saved.update(
            {
                "id": line.id,
                "quantity": decimal_text(quantity(line)),
                "visual_sha256": line.visual_snapshot.sha256 if line.visual_snapshot else None,
            }
        )
        # Execution fields are intentionally absent from approval evidence.
        saved.pop("delivered_quantity", None)
    for key in ("supplier", "delivery_note", "ordered_at", "delivered_at"):
        data.pop(key, None)
    return data


def issue_number(db, request):
    from ..documents.common import ConfirmedTemplateUnavailableError
    from ..documents.templates import _template_version

    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(RequestNumberCounter).values(id=1, next_value=1000).on_conflict_do_nothing())
    number = db.scalar(
        update(RequestNumberCounter)
        .where(RequestNumberCounter.id == 1)
        .values(next_value=RequestNumberCounter.next_value + 1)
        .returning(RequestNumberCounter.next_value - 1)
    )
    official_number = f"KK{number}"
    if (
        db.scalar(
            select(OfficialDocument.id).where(OfficialDocument.document_number == official_number)
        )
        or db.scalar(
            select(GeneratedDocument.id).where(GeneratedDocument.document_number == official_number)
        )
        or db.scalar(select(PartRequest.id).where(PartRequest.request_reference == official_number))
    ):
        raise business_conflict(
            "kk_historical_number_conflict", "Номерът е зает от исторически документ."
        )
    data = capture_data(request)
    approved_at = datetime.now(UTC)
    data.update(
        {
            "official_number": official_number,
            "approved_at": approved_at.isoformat(),
            "approved_by_id": request.decided_by_id,
        }
    )
    try:
        template = _template_version(db, DocumentType.PART_REQUEST.value, request.language)
        content = source_bytes(template)
    except (ConfirmedTemplateUnavailableError, ValueError, OSError):
        template, content = None, None
    data["template_sha256"] = hashlib.sha256(content).hexdigest() if content else None
    snapshot = RequestApprovalSnapshot(
        request_id=request.id,
        number=number,
        official_number=official_number,
        approved_at=approved_at,
        approved_by_id=request.decided_by_id,
        data=data,
        sha256=canonical_hash(data),
        template_version_id=template.id if template else None,
        template_content=content,
    )
    db.add(snapshot)
    request.approval_snapshot = snapshot
    request.generation_status = "PENDING"
    db.flush()


def ensure_editable(request):
    if request.approval_snapshot is not None:
        raise business_conflict("approved_request_is_immutable", "Одобрените данни са заключени.")


def received(request):
    totals = {line.id: Decimal(str(line.delivered_quantity)) for line in request.lines}
    for event in request.delivery_events:
        for line_id, delta in event.quantities.items():
            totals[int(line_id)] += Decimal(delta)
    return totals


def presentation(request):
    snapshot = request.approval_snapshot
    result = {
        "request_kind": kind(request),
        "official_number": snapshot.official_number if snapshot else None,
        "approved_at": utc_iso(snapshot.approved_at) if snapshot else None,
        "generation_status": request.generation_status,
        "generation_error": request.generation_error,
        "cancelled_at": utc_iso(request.cancelled_at),
        "cancelled_by_id": request.cancelled_by_id,
        "cancellation_reason": request.cancellation_reason,
        "replacement_request_id": request.replacement_request_id,
        "delivery_events": [
            {
                "id": e.id,
                "kind": e.kind,
                "quantities": e.quantities,
                "actor_id": e.actor_id,
                "actor_name": e.actor_name,
                "occurred_at": utc_iso(e.occurred_at),
                "supplier": e.supplier,
                "note": e.note,
                "correction_of_id": e.correction_of_id,
            }
            for e in sorted(request.delivery_events, key=lambda e: e.id)
        ],
    }
    return result
