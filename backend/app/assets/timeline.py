"""Read-only machine lifecycle: canonical facts first, exact legacy fallbacks second.

See docs/MACHINE_LIFECYCLE_TIMELINE_BG.md for source precedence and tie ordering.
No workflow mutation, audit creation, binary/signature hydration or repair rules.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, raiseload

from ..models import (
    ApprovalDecision,
    AuditLog,
    Machine,
    MachineEvent,
    MachineStatus,
    PartRequest,
    PartRequestApproval,
    PartRequestStatus,
    Repair,
    RepairEvent,
    RepairPart,
    RepairStatus,
    TransferOperationStatus,
    TransferProtocol,
    User,
)
from ..official_documents.registry import machine_official_document_metadata
from ..permissions import Permission, ensure_permission, is_observer
from .timeline_details import (
    ASSET_DETAILS,
    PART_FIELDS,
    REPAIR_DETAILS,
    asset_details,
    exact_id,
    operational_text,
    project,
)
from .timeline_schemas import (
    MachineTimelineItem,
    MachineTimelinePage,
    TimelineCategory,
    TimelineRelated,
)

_SOURCE_RANK = {
    "machine_event": 0,
    "transfer": 1,
    "repair": 2,
    "repair_event": 3,
    "repair_part": 4,
    "part_request": 5,
    "part_request_approval": 6,
    "part_request_transition": 7,
    "protocol_document": 8,
    "generated_document": 9,
    "official_document": 10,
}
_EVENT_RANK = {
    "PART_REQUEST_CREATED": 0,
    "PART_REQUEST_SUBMITTED": 1,
    "PART_REQUEST_APPROVED": 2,
    "PART_REQUEST_REJECTED": 2,
    "PART_REQUEST_RETURNED_FOR_CHANGES": 2,
    "PART_REQUEST_ORDERED": 3,
    "PART_REQUEST_PARTIALLY_DELIVERED": 4,
    "PART_REQUEST_DELIVERED": 5,
    "PART_REQUEST_CANCELLED": 6,
    "TRANSFER_ISSUED": 0,
    "TRANSFER_RETURN_REQUESTED": 1,
    "TRANSFER_RETURNED": 2,
    "REPAIR_OPENED": 0,
    "REPAIR_COMPLETED": 1,
}


def _item(
    machine_id,
    source_type,
    source_id,
    event_type,
    occurred_at,
    category,
    *,
    key=None,
    reference=None,
    status_before=None,
    status_after=None,
    description=None,
    related=None,
    details=None,
) -> MachineTimelineItem:
    return MachineTimelineItem(
        event_key=key or f"{source_type}:{source_id}",
        category=category,
        event_type=event_type,
        occurred_at=occurred_at,
        reference=operational_text(reference),
        source_type=source_type,
        source_id=source_id,
        status_before=operational_text(status_before),
        status_after=operational_text(status_after),
        description=operational_text(description),
        machine_id=machine_id,
        related=TimelineRelated(**(related or {})),
        details=details or {},
    )


def _sort_key(item: MachineTimelineItem) -> tuple:
    instant = item.occurred_at
    if instant.tzinfo is not None:
        instant = instant.astimezone(timezone.utc).replace(tzinfo=None)
    return (
        instant,
        _SOURCE_RANK[item.source_type],
        item.source_id,
        _EVENT_RANK.get(item.event_type, 0),
        item.event_key,
    )


def _transfer_events(machine_id, transfers) -> list[MachineTimelineItem]:
    items = []
    for transfer in transfers.values():
        common = {"reference": transfer.protocol_number, "related": {"transfer_id": transfer.id}}
        if (
            transfer.issued_at is not None
            and transfer.issue_status == TransferOperationStatus.COMPLETED.value
        ):
            items.append(
                _item(
                    machine_id,
                    "transfer",
                    transfer.id,
                    "TRANSFER_ISSUED",
                    transfer.issued_at,
                    TimelineCategory.TRANSFER,
                    key=f"transfer:{transfer.id}:issued",
                    **common,
                    status_before=transfer.previous_status,
                    status_after=MachineStatus.ISSUED.value,
                    details=project(
                        {
                            "batch_id": transfer.batch_id,
                            "previous_location_id": transfer.previous_location_id,
                            "new_location_id": transfer.issue_location_id,
                            "location_text": transfer.location_text,
                            "accepted_by": transfer.accepted_by,
                        },
                        "batch_id",
                        "previous_location_id",
                        "new_location_id",
                        "location_text",
                        "accepted_by",
                    ),
                )
            )
        if transfer.return_requested_at is not None:
            items.append(
                _item(
                    machine_id,
                    "transfer",
                    transfer.id,
                    "TRANSFER_RETURN_REQUESTED",
                    transfer.return_requested_at,
                    TimelineCategory.TRANSFER,
                    key=f"transfer:{transfer.id}:return_requested",
                    **common,
                    details=project({"batch_id": transfer.batch_id}, "batch_id"),
                )
            )
        if (
            transfer.returned_at is not None
            and transfer.return_status == TransferOperationStatus.COMPLETED.value
        ):
            items.append(
                _item(
                    machine_id,
                    "transfer",
                    transfer.id,
                    "TRANSFER_RETURNED",
                    transfer.returned_at,
                    TimelineCategory.TRANSFER,
                    key=f"transfer:{transfer.id}:returned",
                    **common,
                    status_before=transfer.return_previous_status,
                    status_after=transfer.return_next_status,
                    description=transfer.return_notes,
                    details=project(
                        {
                            "batch_id": transfer.batch_id,
                            "previous_location_id": transfer.return_previous_location_id,
                            "new_location_id": transfer.return_location_id,
                            "condition": transfer.return_condition_text,
                            "result": transfer.return_result_text,
                        },
                        "batch_id",
                        "previous_location_id",
                        "new_location_id",
                        "condition",
                        "result",
                    ),
                )
            )
    return items


def _repair_events(machine_id, repairs, events) -> list[MachineTimelineItem]:
    items = []
    for repair in repairs.values():
        actual = events[repair.id]
        for event in actual:
            if event.event_type not in REPAIR_DETAILS:
                continue
            items.append(
                _item(
                    machine_id,
                    "repair_event",
                    event.id,
                    event.event_type,
                    event.created_at,
                    TimelineCategory.PARTS
                    if event.event_type == "PART_ADDED"
                    else TimelineCategory.REPAIR,
                    reference=repair.repair_reference,
                    status_before=event.status_before,
                    status_after=event.status_after,
                    description=event.description,
                    related={"repair_id": repair.id},
                    details=project(event.structured_data, *REPAIR_DETAILS[event.event_type]),
                )
            )
        types = {event.event_type for event in actual}
        if not types.intersection({"ACCEPTED", "RETURN_DIRECTED_TO_REPAIR"}):
            items.append(
                _item(
                    machine_id,
                    "repair",
                    repair.id,
                    "REPAIR_OPENED",
                    repair.opened_at,
                    TimelineCategory.REPAIR,
                    key=f"repair:{repair.id}:opened",
                    reference=repair.repair_reference,
                    description=repair.reported_problem,
                    related={"repair_id": repair.id},
                )
            )
        if (
            repair.status == RepairStatus.COMPLETED.value
            and repair.closed_at is not None
            and not any(
                e.event_type == "COMPLETED"
                or (
                    e.status_after == RepairStatus.COMPLETED.value
                    and e.status_before != RepairStatus.COMPLETED.value
                )
                for e in actual
            )
        ):
            items.append(
                _item(
                    machine_id,
                    "repair",
                    repair.id,
                    "REPAIR_COMPLETED",
                    repair.closed_at,
                    TimelineCategory.REPAIR,
                    key=f"repair:{repair.id}:completed",
                    reference=repair.repair_reference,
                    status_after=repair.status,
                    description=repair.result,
                    related={"repair_id": repair.id},
                )
            )
    return items


def _part_signature(part) -> tuple:
    return tuple(getattr(part, field) for field in PART_FIELDS) + (
        part.description,
        part.created_by_id,
    )


def _used_part_events(machine_id, repairs, events, parts) -> list[MachineTimelineItem]:
    # The current PART_ADDED writer has no repair_part_id. Match its complete
    # persisted fact tuple + actor one-to-one, in chronology order. No substring
    # part-number matching and one event can never suppress two consumed rows.
    unmatched = defaultdict(list)
    for part in sorted(parts, key=lambda p: (p.created_at, p.id)):
        unmatched[(part.repair_id, _part_signature(part))].append(part)
    represented = set()
    for repair_events in events.values():
        for event in sorted(repair_events, key=lambda e: (e.created_at, e.id)):
            if event.event_type != "PART_ADDED" or not isinstance(event.structured_data, dict):
                continue
            data = event.structured_data
            if any(isinstance(data.get(field), (dict, list)) for field in PART_FIELDS):
                continue
            signature = tuple(data.get(field) for field in PART_FIELDS) + (
                event.description,
                event.user_id,
            )
            candidates = unmatched[(event.repair_id, signature)]
            part_id = exact_id(data.get("repair_part_id"))
            match = next(
                (
                    p
                    for p in candidates
                    if p.id not in represented
                    and p.created_at <= event.created_at
                    and (part_id is None or p.id == part_id)
                ),
                None,
            )
            if match is not None:
                represented.add(match.id)
    return [
        _item(
            machine_id,
            "repair_part",
            part.id,
            "PART_USED",
            part.created_at,
            TimelineCategory.PARTS,
            key=f"repair_part:{part.id}:used",
            reference=repairs[part.repair_id].repair_reference,
            description=part.description,
            related={"repair_id": part.repair_id},
            details=project({field: getattr(part, field) for field in PART_FIELDS}, *PART_FIELDS),
        )
        for part in parts
        if part.id not in represented
    ]


def _request_events(machine_id, requests, approvals, transitions) -> list[MachineTimelineItem]:
    items = []
    decisions = {
        ApprovalDecision.APPROVED.value: PartRequestStatus.APPROVED.value,
        ApprovalDecision.REJECTED.value: PartRequestStatus.REJECTED.value,
        ApprovalDecision.RETURNED_FOR_CHANGES.value: PartRequestStatus.DRAFT.value,
    }
    for request in requests.values():
        related = {"part_request_id": request.id, "repair_id": request.repair_id}
        common = {"reference": request.request_reference, "related": related}
        milestones = [
            ("created", "CREATED", request.created_at, None),
            (
                "submitted",
                "SUBMITTED",
                request.submitted_at,
                PartRequestStatus.WAITING_APPROVAL.value,
            ),
            ("ordered", "ORDERED", request.ordered_at, PartRequestStatus.ORDERED.value),
            ("delivered", "DELIVERED", request.delivered_at, PartRequestStatus.DELIVERED.value),
        ]
        for key, code, occurred_at, status in milestones:
            if occurred_at is not None:
                items.append(
                    _item(
                        machine_id,
                        "part_request",
                        request.id,
                        f"PART_REQUEST_{code}",
                        occurred_at,
                        TimelineCategory.PARTS,
                        key=f"part_request:{request.id}:{key}",
                        **common,
                        status_after=status,
                    )
                )
        for approval in approvals[request.id]:
            if approval.decision in decisions:
                items.append(
                    _item(
                        machine_id,
                        "part_request_approval",
                        approval.id,
                        f"PART_REQUEST_{approval.decision}",
                        approval.decided_at,
                        TimelineCategory.PARTS,
                        **common,
                        status_after=decisions[approval.decision],
                        description=approval.note,
                    )
                )
        # Compatibility for a pre-approval-history row, only when its decision
        # timestamp AND explicit terminal decision state survive. Do not guess
        # a past approval from a currently ORDERED/DELIVERED request.
        if (
            not approvals[request.id]
            and request.decided_at is not None
            and request.status
            in {PartRequestStatus.APPROVED.value, PartRequestStatus.REJECTED.value}
        ):
            items.append(
                _item(
                    machine_id,
                    "part_request",
                    request.id,
                    f"PART_REQUEST_{request.status}",
                    request.decided_at,
                    TimelineCategory.PARTS,
                    key=f"part_request:{request.id}:decision",
                    **common,
                    status_after=request.status,
                    description=request.decision_note,
                )
            )
    for transition in transitions:
        try:
            data = json.loads(transition.details or "null")
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        previous, new = data.get("previous_status"), data.get("new_status")
        allowed = {
            PartRequestStatus.PARTIALLY_DELIVERED.value: {
                PartRequestStatus.ORDERED.value,
                PartRequestStatus.PARTIALLY_DELIVERED.value,
            },
            PartRequestStatus.CANCELLED.value: {
                PartRequestStatus.APPROVED.value,
                PartRequestStatus.ORDERED.value,
                PartRequestStatus.PARTIALLY_DELIVERED.value,
            },
        }
        if (
            not isinstance(new, str)
            or not isinstance(previous, str)
            or previous not in allowed.get(new, set())
        ):
            continue
        request = requests[transition.entity_id]
        items.append(
            _item(
                machine_id,
                "part_request_transition",
                transition.id,
                f"PART_REQUEST_{new}",
                transition.created_at,
                TimelineCategory.PARTS,
                reference=request.request_reference,
                status_before=previous,
                status_after=new,
                related={"part_request_id": request.id, "repair_id": request.repair_id},
            )
        )
    return items


def _machine_events(machine_id, events, transfers, repairs, canonical) -> list[MachineTimelineItem]:
    items = []
    transfer_refs = {t.protocol_number: t for t in transfers.values()}
    repair_refs = {r.repair_reference: r for r in repairs.values() if r.repair_reference}
    represented_transfer = {(e.related.transfer_id, e.event_type) for e in canonical}
    represented_repair = defaultdict(list)
    for item in canonical:
        if item.related.repair_id is not None and item.category == TimelineCategory.REPAIR:
            represented_repair[item.related.repair_id].append(item)
    for event in events:
        details = event.details if isinstance(event.details, dict) else {}
        related = {}
        if event.event_type in ASSET_DETAILS:
            category = TimelineCategory.ASSET
        elif event.event_type in {"TRANSFER_ISSUED", "TRANSFER_RETURNED"}:
            transfer = transfers.get(exact_id(details.get("transfer_id")))
            if transfer is None and "transfer_id" not in details:
                transfer = transfer_refs.get(event.reference)
            if transfer is not None:
                related = {"transfer_id": transfer.id}
                if (transfer.id, event.event_type) in represented_transfer:
                    continue
                # A surviving machine event cannot override a pending/cancelled
                # canonical operation or turn an active issue into a return.
                if event.event_type == "TRANSFER_RETURNED" and (
                    transfer.is_active
                    or transfer.return_status
                    in {
                        TransferOperationStatus.AWAITING_SIGNATURE.value,
                        TransferOperationStatus.CANCELLED.value,
                    }
                ):
                    continue
                if (
                    event.event_type == "TRANSFER_ISSUED"
                    and transfer.issue_status != TransferOperationStatus.COMPLETED.value
                ):
                    continue
            category = TimelineCategory.TRANSFER
        elif event.event_type in {"REPAIR_ACCEPTED", "REPAIR_STATUS_CHANGED", "REPAIR_EVENT"}:
            repair = repairs.get(exact_id(details.get("repair_id")))
            if repair is None and "repair_id" not in details:
                repair = repair_refs.get(event.reference)
            if repair is not None:
                related = {"repair_id": repair.id}
                actual = represented_repair[repair.id]
                if event.event_type == "REPAIR_ACCEPTED" and any(
                    e.event_type in {"ACCEPTED", "RETURN_DIRECTED_TO_REPAIR", "REPAIR_OPENED"}
                    for e in actual
                ):
                    continue
                target = details.get("repair_status")
                if target is None and event.new_status == MachineStatus.READY.value:
                    target = RepairStatus.COMPLETED.value
                if target is not None and any(e.status_after == target for e in actual):
                    continue
                if event.event_type == "REPAIR_EVENT" and any(
                    e.event_type == details.get("event_type") for e in actual
                ):
                    continue
            category = TimelineCategory.REPAIR
        else:
            continue
        items.append(
            _item(
                machine_id,
                "machine_event",
                event.id,
                event.event_type,
                event.created_at,
                category,
                reference=event.reference,
                status_before=event.previous_status,
                status_after=event.new_status,
                related=related,
                details=asset_details(event),
            )
        )
    return items


def _document_events(db, machine_id) -> list[MachineTimelineItem]:
    items = []
    for record in machine_official_document_metadata(db, machine_id):
        official = record["official_document_id"] is not None
        source = {
            "official": "official_document",
            "generated": "generated_document",
            "protocol": "protocol_document",
        }[record["source_family"]]
        key = (
            f"official_document:{record['official_document_id']}:v{record['version']}"
            if official
            else f"{source}:{record['source_id']}"
        )
        related = {
            k: record[k]
            for k in ("transfer_id", "repair_id", "part_request_id", "official_document_id")
        }
        # Registry grouping may resolve a legacy reference, but ownership was
        # already restricted by exact numeric machine/domain linkage above.
        items.append(
            _item(
                machine_id,
                source,
                record["source_id"],
                (
                    "OFFICIAL_DOCUMENT_FINALIZED"
                    if record["finalized"]
                    else "OFFICIAL_DOCUMENT_CREATED"
                )
                if official
                else "LEGACY_DOCUMENT_CREATED",
                record["occurred_at"],
                TimelineCategory.DOCUMENT,
                key=key,
                reference=record["document_number"],
                status_after=record["version_status"],
                related=related,
                details=project(
                    record,
                    "document_type",
                    "document_number",
                    "version",
                    "version_status",
                    "registry_category",
                    "registry_key",
                    "domain_id",
                ),
            )
        )
    return items


def machine_timeline(
    db: Session,
    *,
    machine_id: int,
    user: User,
    category: TimelineCategory = TimelineCategory.ALL,
    page: int = 1,
    page_size: int = 50,
) -> MachineTimelinePage:
    """Aggregate/filter/sort before slicing; never issue SQL writes or autoflush."""
    with db.no_autoflush:
        ensure_permission(user, Permission.ASSETS_VIEW)
        if db.scalar(select(Machine.id).where(Machine.id == machine_id)) is None:
            raise HTTPException(404, "Машината не е намерена.")
        limited_view = is_observer(user)
        items = []
        if not limited_view:
            transfers = {
                t.id: t
                for t in db.scalars(
                    select(TransferProtocol)
                    .options(raiseload("*"))
                    .where(TransferProtocol.machine_id == machine_id)
                )
            }
            repairs = {
                r.id: r
                for r in db.scalars(
                    select(Repair).options(raiseload("*")).where(Repair.machine_id == machine_id)
                )
            }
            repair_events = defaultdict(list)
            for event in db.scalars(
                select(RepairEvent)
                .options(raiseload("*"))
                .where(RepairEvent.repair_id.in_(repairs))
            ):
                repair_events[event.repair_id].append(event)
            used_parts = list(
                db.scalars(
                    select(RepairPart)
                    .options(raiseload("*"))
                    .where(RepairPart.repair_id.in_(repairs))
                )
            )
            requests = {
                r.id: r
                for r in db.scalars(
                    select(PartRequest)
                    .options(raiseload("*"))
                    .where(
                        or_(
                            PartRequest.machine_id == machine_id,
                            and_(
                                PartRequest.machine_id.is_(None), PartRequest.repair_id.in_(repairs)
                            ),
                        )
                    )
                )
            }
            approvals = defaultdict(list)
            for approval in db.scalars(
                select(PartRequestApproval)
                .options(raiseload("*"))
                .where(PartRequestApproval.request_id.in_(requests))
            ):
                approvals[approval.request_id].append(approval)
            # This is a domain-transition fallback, not an audit feed. Never read
            # auth/governance entries, raw action text, user names or unrelated rows.
            transitions = (
                list(
                    db.execute(
                        select(
                            AuditLog.id, AuditLog.entity_id, AuditLog.details, AuditLog.created_at
                        ).where(
                            AuditLog.entity_type == "part_request",
                            AuditLog.entity_id.in_(requests),
                            AuditLog.action == "Обновено изпълнение на заявка за части",
                        )
                    )
                )
                if requests
                else []
            )
            items.extend(_transfer_events(machine_id, transfers))
            items.extend(_repair_events(machine_id, repairs, repair_events))
            items.extend(_used_part_events(machine_id, repairs, repair_events, used_parts))
            items.extend(_request_events(machine_id, requests, approvals, transitions))
            events = list(
                db.scalars(
                    select(MachineEvent)
                    .options(raiseload("*"))
                    .where(MachineEvent.machine_id == machine_id)
                )
            )
            items.extend(_machine_events(machine_id, events, transfers, repairs, items))
            items.extend(_document_events(db, machine_id))
    if category != TimelineCategory.ALL:
        items = [item for item in items if item.category == category]
    items.sort(key=_sort_key, reverse=True)
    total = len(items)
    total_pages = (total + page_size - 1) // page_size
    selected = items[(page - 1) * page_size : page * page_size]
    return MachineTimelinePage(
        machine_id=machine_id,
        limited_view=limited_view,
        category=category,
        total=total,
        count=len(selected),
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_previous=total > 0 and page > 1,
        has_next=page < total_pages,
        items=selected,
    )
