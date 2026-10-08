"""Bounded operational reads. No workflow writes or historical snapshot changes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, defer, joinedload, selectinload

from .assets.serializers import _limited_machine
from .assets.service import _machine_with_capabilities, category_navigation
from .assets.timeline_details import operational_text
from .database import get_db
from .industrial_api import _part_request_dict
from .models import (
    AssetCategory,
    GeneratedDocument,
    Machine,
    PartRequest,
    PartRequestApproval,
    PartRequestAttachment,
    PartRequestLine,
    Repair,
    RepairEvent,
    TransferBatch,
    TransferProtocol,
    User,
)
from .permissions import (
    Permission,
    ensure_permission,
    has_permission,
    is_observer,
    require_permission,
)

router = APIRouter(prefix="/api/workspace")
Module = Literal["machines", "transfers", "repairs", "requests", "catalog"]
CAPABILITIES = {
    "transfers": "HAS_TRANSFER_WORKFLOW",
    "repairs": "HAS_REPAIR_WORKFLOW",
    "catalog": "HAS_PARTS_CATALOG",
}
PERMISSIONS = {
    "machines": Permission.ASSETS_VIEW,
    "transfers": Permission.TRANSFERS_VIEW,
    "repairs": Permission.REPAIRS_VIEW,
    "requests": Permission.REQUESTS_VIEW,
    "catalog": Permission.PARTS_VIEW,
}


@dataclass
class Filters:
    category_id: int | None
    scope: str
    q: str
    status: str | None
    date_from: date | None
    date_to: date | None
    sort: str
    page: int
    page_size: int
    machine_id: int | None
    record_id: int | None


def filters(
    category_id: int | None = Query(None, ge=1),
    scope: Literal["all", "legacy", "mixed"] = "all",
    q: str = Query("", max_length=200),
    status: str | None = Query(None, max_length=80),
    date_from: date | None = None,
    date_to: date | None = None,
    sort: Literal["newest", "oldest"] = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    machine_id: int | None = Query(None, ge=1),
    record_id: int | None = Query(None, ge=1),
) -> Filters:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, detail={"code": "invalid_date_range"})
    return Filters(
        category_id,
        scope,
        q.strip(),
        status,
        date_from,
        date_to,
        sort,
        page,
        page_size,
        machine_id,
        record_id,
    )


def eligible_ids(db: Session, module: str) -> list[int]:
    capability = CAPABILITIES.get(module)
    return [
        category.id
        for category in db.scalars(select(AssetCategory))
        if not capability or capability in (category.capabilities or [])
    ]


def category_scope(db: Session, module: str, f: Filters):
    ids = eligible_ids(db, module)
    if f.category_id is not None:
        if f.category_id not in ids:
            raise HTTPException(422, detail={"code": "category_not_eligible"})
        return Machine.category_id == f.category_id
    if f.scope == "legacy":
        return or_(Machine.category_id.is_(None), Machine.category_id.not_in(ids))
    return literal(True)


def search(f: Filters, *columns):
    # Treat user input as a literal substring, including SQL wildcard characters.
    value = f.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return or_(*(column.ilike(f"%{value}%", escape="\\") for column in columns))


def dated(statement, column, f: Filters):
    if f.date_from:
        statement = statement.where(column >= datetime.combine(f.date_from, time.min))
    if f.date_to:
        statement = statement.where(
            column < datetime.combine(f.date_to + timedelta(days=1), time.min)
        )
    return statement


def page_rows(db: Session, statement, timestamp, identifier, f: Filters):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    order = (
        (timestamp.asc(), identifier.asc())
        if f.sort == "oldest"
        else (timestamp.desc(), identifier.desc())
    )
    rows = (
        db.execute(statement.order_by(*order).offset((f.page - 1) * f.page_size).limit(f.page_size))
        .unique()
        .all()
    )
    return rows, {
        "total": total,
        "page": f.page,
        "page_size": f.page_size,
        "total_pages": (total + f.page_size - 1) // f.page_size,
        "has_previous": f.page > 1,
        "has_next": f.page * f.page_size < total,
    }


@router.get("/categories")
def categories(
    module: Module = "machines",
    user: User = Depends(require_permission(Permission.ASSETS_VIEW)),
    db: Session = Depends(get_db),
):
    ensure_permission(user, PERMISSIONS[module])
    ids = set(eligible_ids(db, module))
    return [item for item in category_navigation(user, db) if item["id"] in ids]


@router.get("/machines")
def machines(
    module: Module = "machines",
    active_only: bool = False,
    f: Filters = Depends(filters),
    user: User = Depends(require_permission(Permission.ASSETS_VIEW)),
    db: Session = Depends(get_db),
):
    ensure_permission(user, PERMISSIONS[module])
    statement = (
        select(Machine)
        .where(category_scope(db, module, f))
        .options(joinedload(Machine.location), joinedload(Machine.category_definition))
    )
    if module in CAPABILITIES and (module == "catalog" or f.scope != "legacy"):
        statement = statement.where(Machine.category_id.in_(eligible_ids(db, module)))
    if f.q:
        columns = (
            (Machine.inventory_number, Machine.name)
            if is_observer(user)
            else (
                Machine.inventory_number,
                Machine.name,
                Machine.serial_number,
                Machine.brand,
                Machine.model,
            )
        )
        statement = statement.where(search(f, *columns))
    if f.status:
        statement = statement.where(Machine.status == f.status)
    if f.machine_id:
        statement = statement.where(Machine.id == f.machine_id)
    if active_only:
        statement = statement.where(Machine.is_active.is_(True))
    rows, meta = page_rows(db, statement, Machine.created_at, Machine.id, f)
    serializer = _limited_machine if is_observer(user) else _machine_with_capabilities
    return meta | {"items": [serializer(row[0]) for row in rows]}


@router.get("/repairs")
def repairs(
    f: Filters = Depends(filters),
    user: User = Depends(require_permission(Permission.REPAIRS_VIEW)),
    db: Session = Depends(get_db),
):
    statement = (
        select(Repair, Machine)
        .join(Machine, Repair.machine_id == Machine.id)
        .where(category_scope(db, "repairs", f))
    )
    if f.q:
        statement = statement.where(
            search(
                f,
                Machine.inventory_number,
                Machine.name,
                Machine.serial_number,
                Repair.repair_reference,
                Repair.reported_problem,
            )
        )
    if f.status:
        statement = statement.where(Repair.status == f.status)
    if f.machine_id:
        statement = statement.where(Repair.machine_id == f.machine_id)
    if f.record_id:
        statement = statement.where(Repair.id == f.record_id)
    statement = dated(statement, Repair.opened_at, f)
    rows, meta = page_rows(db, statement, Repair.opened_at, Repair.id, f)
    return meta | {
        "items": [
            {
                "id": r.id,
                "machine_id": m.id,
                "category_id": m.category_id,
                "machine_name": m.name,
                "machine_number": m.inventory_number,
                "repair_reference": r.repair_reference,
                "reported_problem": r.reported_problem,
                "status": r.status,
                "opened_at": r.opened_at,
                "closed_at": r.closed_at,
            }
            for r, m in rows
        ]
    }


@router.get("/requests")
def requests(
    f: Filters = Depends(filters),
    user: User = Depends(require_permission(Permission.REQUESTS_VIEW)),
    db: Session = Depends(get_db),
):
    # Preserve requests linked via a repair and general requests without a machine.
    statement = (
        select(PartRequest)
        .outerjoin(Repair, PartRequest.repair_id == Repair.id)
        .outerjoin(Machine, Machine.id == func.coalesce(PartRequest.machine_id, Repair.machine_id))
        .where(category_scope(db, "requests", f))
    )
    if f.q:
        statement = statement.where(
            or_(
                search(
                    f,
                    Machine.inventory_number,
                    Machine.serial_number,
                    PartRequest.request_reference,
                    PartRequest.part_name,
                    PartRequest.reason,
                ),
                PartRequest.lines.any(
                    search(f, PartRequestLine.part_number, PartRequestLine.description)
                ),
            )
        )
    if f.status:
        statement = statement.where(PartRequest.status == f.status)
    if f.record_id:
        statement = statement.where(PartRequest.id == f.record_id)
    if f.machine_id:
        statement = statement.where(Machine.id == f.machine_id)
    statement = dated(statement, PartRequest.created_at, f).options(
        joinedload(PartRequest.machine),
        joinedload(PartRequest.repair),
        joinedload(PartRequest.requested_by),
        joinedload(PartRequest.decided_by),
        selectinload(PartRequest.lines).joinedload(PartRequestLine.linked_catalog_part),
        selectinload(PartRequest.approvals).joinedload(PartRequestApproval.decided_by),
        selectinload(PartRequest.attachments).defer(PartRequestAttachment.content),
    )
    rows, meta = page_rows(db, statement, PartRequest.created_at, PartRequest.id, f)
    items = [row[0] for row in rows]
    documents = {}
    for document in db.scalars(
        select(GeneratedDocument)
        .options(defer(GeneratedDocument.content))
        .where(GeneratedDocument.part_request_id.in_([item.id for item in items]))
    ):
        documents.setdefault(document.part_request_id, []).append(document)
    return meta | {
        "items": [_part_request_dict(item, documents.get(item.id, [])) for item in items]
    }


@router.get("/batches")
def batches(
    context: Literal["active", "completed", "pending", "all"] = "active",
    f: Filters = Depends(filters),
    user: User = Depends(require_permission(Permission.TRANSFERS_VIEW)),
    db: Session = Depends(get_db),
):
    t = TransferProtocol
    issued = func.sum(case((t.issue_status == "COMPLETED", 1), else_=0))
    active = func.sum(
        case((and_(t.issue_status == "COMPLETED", t.is_active.is_(True)), 1), else_=0)
    )
    returned = func.sum(
        case(
            (
                and_(
                    t.issue_status == "COMPLETED",
                    t.return_status == "COMPLETED",
                    t.is_active.is_(False),
                ),
                1,
            ),
            else_=0,
        )
    )
    pending = func.sum(
        case(
            (
                or_(
                    t.issue_status == "AWAITING_SIGNATURE", t.return_status == "AWAITING_SIGNATURE"
                ),
                1,
            ),
            else_=0,
        )
    )
    summary = (
        select(
            t.batch_id.label("batch_id"),
            func.count(t.id).label("total"),
            issued.label("issued"),
            active.label("active"),
            returned.label("returned"),
            pending.label("pending"),
            func.count(func.distinct(func.coalesce(Machine.category_id, -1))).label(
                "category_count"
            ),
        )
        .join(Machine, t.machine_id == Machine.id)
        .where(t.batch_id.is_not(None))
        .group_by(t.batch_id)
        .subquery()
    )
    statement = select(TransferBatch, summary).join(summary, summary.c.batch_id == TransferBatch.id)
    if context == "active":
        statement = statement.where(summary.c.active > 0)
    elif context == "completed":
        statement = statement.where(
            summary.c.issued > 0,
            summary.c.active == 0,
            summary.c.returned == summary.c.issued,
            summary.c.pending == 0,
        )
    elif context == "pending":
        statement = statement.where(
            summary.c.active == 0,
            or_(
                summary.c.issued == 0, summary.c.returned < summary.c.issued, summary.c.pending > 0
            ),
        )
    membership = (
        select(t.batch_id)
        .join(Machine, t.machine_id == Machine.id)
        .where(category_scope(db, "transfers", f))
    )
    if f.q:
        membership = membership.where(
            search(
                f, Machine.inventory_number, Machine.name, Machine.serial_number, t.protocol_number
            )
        )
        statement = statement.where(
            or_(TransferBatch.id.in_(membership), search(f, TransferBatch.batch_reference))
        )
    else:
        statement = statement.where(TransferBatch.id.in_(membership))
    # Search matches cannot bypass category membership.
    statement = statement.where(
        TransferBatch.id.in_(
            select(t.batch_id).join(Machine).where(category_scope(db, "transfers", f))
        )
    )
    if f.scope == "mixed":
        statement = statement.where(summary.c.category_count > 1)
    if f.machine_id:
        statement = statement.where(
            TransferBatch.id.in_(select(t.batch_id).where(t.machine_id == f.machine_id))
        )
    if f.record_id:
        statement = statement.where(TransferBatch.id == f.record_id)
    statement = dated(statement, TransferBatch.created_at, f)
    rows, meta = page_rows(db, statement, TransferBatch.created_at, TransferBatch.id, f)
    identifiers = [row[0].id for row in rows]
    members = {}
    for tid, number, category_id in db.execute(
        select(t.batch_id, Machine.inventory_number, Machine.category_id)
        .join(Machine)
        .where(t.batch_id.in_(identifiers))
        .order_by(t.id)
    ):
        members.setdefault(tid, []).append((number, category_id))
    items = []
    for row in rows:
        (
            batch,
            _,
            total,
            issued_count,
            active_count,
            returned_count,
            pending_count,
            category_count,
        ) = row
        # Present the same canonical relationship used to choose the context.
        # Legacy batch labels may be stale; never rewrite their stored history.
        state = batch.status
        if active_count:
            state = "PARTIALLY_RETURNED" if returned_count else "ACTIVE"
        elif issued_count and returned_count == issued_count and not pending_count:
            state = "RETURNED"
        elif not issued_count and pending_count and state != "CANCELLED":
            state = "AWAITING_SIGNATURE"
        items.append(
            {
                "batch_id": batch.id,
                "batch_reference": batch.batch_reference,
                "status": state,
                "stored_status": batch.status,
                "total_machines": issued_count,
                "registered_machines": total,
                "issued_machines": issued_count,
                "returned_machines": returned_count,
                "still_issued_machines": active_count,
                "awaiting_signature_machines": pending_count,
                "machine_numbers": [item[0] for item in members.get(batch.id, [])],
                "category_ids": sorted(
                    {item[1] for item in members.get(batch.id, []) if item[1] is not None}
                ),
                "mixed_categories": category_count > 1,
                "created_at": batch.created_at,
                "cancellable_batch_ids": [batch.id]
                if batch.issue_signing_status == "AWAITING_SIGNATURE"
                and batch.status != "CANCELLED"
                else [],
            }
        )
    return meta | {"items": items}


@router.get("/transfers")
def transfers(
    f: Filters = Depends(filters),
    user: User = Depends(require_permission(Permission.TRANSFERS_VIEW)),
    db: Session = Depends(get_db),
):
    t = TransferProtocol
    statement = (
        select(t)
        .join(Machine)
        .where(category_scope(db, "transfers", f))
        .options(
            joinedload(t.machine).joinedload(Machine.location),
            joinedload(t.machine).joinedload(Machine.category_definition),
        )
    )
    if f.q:
        statement = statement.where(
            search(
                f,
                Machine.inventory_number,
                Machine.serial_number,
                t.protocol_number,
                t.batch_reference,
            )
        )
    if f.status == "completed":
        statement = statement.where(
            t.issue_status == "COMPLETED", t.return_status == "COMPLETED", t.is_active.is_(False)
        )
    if f.record_id:
        statement = statement.where(t.id == f.record_id)
    if f.machine_id:
        statement = statement.where(t.machine_id == f.machine_id)
    rows, meta = page_rows(db, dated(statement, t.created_at, f), t.created_at, t.id, f)
    return meta | {
        "items": [
            {
                "id": value.id,
                "protocol_number": value.protocol_number,
                "batch_reference": value.batch_reference,
                "batch_id": value.batch_id,
                "is_active": value.is_active,
                "issue_status": value.issue_status,
                "return_status": value.return_status,
                "company_unit": value.company_unit,
                "vessel": value.vessel,
                "location_text": value.location_text,
                "issued_at": value.issued_at,
                "returned_at": value.returned_at,
                "created_at": value.created_at,
                "machine": _machine_with_capabilities(value.machine),
            }
            for (value,) in rows
        ]
    }


def recent_activity(db: Session, user: User, limit: int = 8) -> list[dict]:
    """Canonical business evidence, bounded SQL UNION. Never serialize audit payloads."""
    sources = []

    def event(
        statement,
        kind,
        module,
        record_id,
        timestamp,
        machine_id,
        reference,
        status,
        evidence_id=None,
    ):
        return statement.with_only_columns(
            literal(kind).label("event_type"),
            literal(module).label("module"),
            record_id.label("record_id"),
            timestamp.label("occurred_at"),
            machine_id.label("machine_id"),
            reference.label("reference"),
            status.label("status"),
            (record_id if evidence_id is None else evidence_id).label("evidence_id"),
        )

    if has_permission(user, Permission.TRANSFERS_VIEW):
        t = TransferProtocol
        sources.extend(
            [
                event(
                    select(t).where(t.issue_status == "COMPLETED", t.issued_at.is_not(None)),
                    "TRANSFER_ISSUED",
                    "transfers",
                    t.id,
                    t.issued_at,
                    t.machine_id,
                    t.protocol_number,
                    literal("ISSUED"),
                ),
                event(
                    select(t).where(t.return_status == "COMPLETED", t.returned_at.is_not(None)),
                    "TRANSFER_RETURNED",
                    "transfers",
                    t.id,
                    t.returned_at,
                    t.machine_id,
                    t.protocol_number,
                    literal("RETURNED"),
                ),
            ]
        )
    if has_permission(user, Permission.REPAIRS_VIEW):
        sources.append(
            event(
                select(Repair),
                "REPAIR_OPENED",
                "repairs",
                Repair.id,
                Repair.opened_at,
                Repair.machine_id,
                Repair.repair_reference,
                literal("ACCEPTED"),
            )
        )
        sources.append(
            event(
                select(Repair).where(Repair.closed_at.is_not(None)),
                "REPAIR_COMPLETED",
                "repairs",
                Repair.id,
                Repair.closed_at,
                Repair.machine_id,
                Repair.repair_reference,
                literal("COMPLETED"),
            )
        )
        for code in ("STATUS_CHANGE", "COMPLETED"):
            sources.append(
                event(
                    select(RepairEvent)
                    .join(Repair)
                    .where(
                        RepairEvent.event_type == code,
                        RepairEvent.created_at != Repair.opened_at,
                        Repair.closed_at.is_(None)
                        if code == "COMPLETED"
                        else or_(
                            RepairEvent.status_after.is_(None),
                            RepairEvent.status_after != "COMPLETED",
                        ),
                    ),
                    "REPAIR_COMPLETED" if code == "COMPLETED" else "REPAIR_STATUS_CHANGED",
                    "repairs",
                    Repair.id,
                    RepairEvent.created_at,
                    Repair.machine_id,
                    Repair.repair_reference,
                    RepairEvent.status_after,
                    RepairEvent.id,
                )
            )
    if has_permission(user, Permission.REQUESTS_VIEW):
        sources.append(
            event(
                select(PartRequest).outerjoin(Repair, PartRequest.repair_id == Repair.id),
                "PART_REQUEST_CREATED",
                "parts",
                PartRequest.id,
                PartRequest.created_at,
                func.coalesce(PartRequest.machine_id, Repair.machine_id),
                PartRequest.request_reference,
                literal(None),
            )
        )
        for column, code, status in (
            (PartRequest.submitted_at, "PART_REQUEST_SUBMITTED", "WAITING_APPROVAL"),
            (PartRequest.decided_at, "PART_REQUEST_APPROVED", None),
            (PartRequest.ordered_at, "PART_REQUEST_ORDERED", "ORDERED"),
            (PartRequest.delivered_at, "PART_REQUEST_DELIVERED", "DELIVERED"),
        ):
            if status is None:
                # Approval history is authoritative even after fulfillment changes current status.
                for decision, event_type in (
                    ("APPROVED", "PART_REQUEST_APPROVED"),
                    ("REJECTED", "PART_REQUEST_REJECTED"),
                    ("RETURNED_FOR_CHANGES", "PART_REQUEST_RETURNED_FOR_CHANGES"),
                ):
                    sources.append(
                        event(
                            select(PartRequestApproval)
                            .join(PartRequest)
                            .outerjoin(Repair, PartRequest.repair_id == Repair.id)
                            .where(PartRequestApproval.decision == decision),
                            event_type,
                            "parts",
                            PartRequest.id,
                            PartRequestApproval.decided_at,
                            func.coalesce(PartRequest.machine_id, Repair.machine_id),
                            PartRequest.request_reference,
                            PartRequestApproval.decision,
                            PartRequestApproval.id,
                        )
                    )
            else:
                sources.append(
                    event(
                        select(PartRequest)
                        .outerjoin(Repair, PartRequest.repair_id == Repair.id)
                        .where(column.is_not(None)),
                        code,
                        "parts",
                        PartRequest.id,
                        column,
                        func.coalesce(PartRequest.machine_id, Repair.machine_id),
                        PartRequest.request_reference,
                        literal(status),
                    )
                )
    if not sources:
        return []
    combined = union_all(*sources).subquery()
    rows = db.execute(
        select(combined, Machine.inventory_number)
        .outerjoin(Machine, Machine.id == combined.c.machine_id)
        .order_by(
            combined.c.occurred_at.desc(),
            combined.c.module,
            combined.c.record_id.desc(),
            combined.c.event_type,
        )
        .limit(min(limit, 8))
    ).mappings()
    return [
        dict(row)
        | {
            "reference": operational_text(row["reference"]),
            "inventory_number": operational_text(row["inventory_number"]),
            "occurred_at": row["occurred_at"].replace(tzinfo=UTC),
            "event_key": f"{row['module']}:{row['evidence_id']}:{row['event_type']}:{row['occurred_at'].isoformat()}",
        }
        for row in rows
    ]
