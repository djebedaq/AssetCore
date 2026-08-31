"""Read-only passport assembly; no transfer, repair or document workflow ownership."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from ..attachment_io import _attachment_dict
from ..models import (
    AssetCategory,
    AuditLog,
    GeneratedDocument,
    Machine,
    MachineFieldValue,
    MachineStatus,
    PartRequest,
    Repair,
    RepairStatus,
    TechnicalDocument,
    TransferProtocol,
    User,
)
from ..permissions import Permission, has_permission, is_observer


def _passport_available(
    machine: Machine,
    active_transfer: TransferProtocol | None,
    active_repair: Repair | None,
) -> bool:
    return (
        machine.is_active
        and machine.status == MachineStatus.READY.value
        and active_transfer is None
        and active_repair is None
    )


def machine_passport(machine_id: int, user: User, db: Session) -> dict:
    machine = db.scalar(
        select(Machine)
        .options(
            joinedload(Machine.location),
            joinedload(Machine.category_definition).selectinload(AssetCategory.fields),
            selectinload(Machine.custom_values).joinedload(MachineFieldValue.field),
            selectinload(Machine.attachments),
            selectinload(Machine.events),
            selectinload(Machine.repairs).selectinload(Repair.parts_used),
            selectinload(Machine.transfers).joinedload(TransferProtocol.batch),
        )
        .where(Machine.id == machine_id)
    )
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    if is_observer(user):
        active_transfer = next((item for item in machine.transfers if item.is_active), None)
        active_repair = next(
            (
                item
                for item in sorted(
                    machine.repairs,
                    key=lambda value: value.opened_at,
                    reverse=True,
                )
                if item.status != RepairStatus.COMPLETED.value
            ),
            None,
        )
        return {
            "limited_view": True,
            "machine": {
                "id": machine.id,
                "inventory_number": machine.inventory_number,
                "name": machine.name,
                "brand": machine.brand,
                "model": machine.model,
                "status": machine.status,
                "is_active": machine.is_active,
                "location": (
                    {"id": machine.location.id, "name": machine.location.name}
                    if machine.location
                    else None
                ),
            },
            "custom_fields": [],
            "attachments": [],
            "history": [],
            "repairs": [],
            "transfers": [],
            "part_requests": [],
            "parts_used": [],
            "generated_documents": [],
            "technical_documents": [],
            "current_state": {
                "available": _passport_available(
                    machine, active_transfer, active_repair
                ),
                "active_transfer": ({"is_active": True} if active_transfer is not None else None),
                "active_repair": (
                    {"status": active_repair.status} if active_repair is not None else None
                ),
                "last_movement": None,
                "last_inspection": None,
                "last_test": None,
                "allowed_actions": {
                    "issue": False,
                    "return": False,
                    "repair": False,
                    "edit": False,
                },
            },
            "audit_visible": False,
            "audit": [],
            "qr_endpoint": None,
        }
    values = {item.field_id: item for item in machine.custom_values}
    fields = machine.category_definition.fields if machine.category_definition else []
    documents = db.scalars(
        select(GeneratedDocument)
        .where(GeneratedDocument.machine_id == machine.id)
        .order_by(GeneratedDocument.created_at.desc())
    ).all()
    part_requests = db.scalars(
        select(PartRequest)
        .where(PartRequest.machine_id == machine.id)
        .order_by(PartRequest.created_at.desc())
    ).all()
    technical_documents = [
        item
        for item in db.scalars(
            select(TechnicalDocument)
            .where(TechnicalDocument.is_active.is_(True))
            .options(selectinload(TechnicalDocument.revisions))
            .where(TechnicalDocument.linked_machine_numbers.is_not(None))
            .order_by(TechnicalDocument.title)
        ).all()
        if machine.inventory_number in (item.linked_machine_numbers or [])
    ]
    active_transfer = next((item for item in machine.transfers if item.is_active), None)
    active_repair = next(
        (
            item
            for item in sorted(machine.repairs, key=lambda value: value.opened_at, reverse=True)
            if item.status != RepairStatus.COMPLETED.value
        ),
        None,
    )
    available = _passport_available(machine, active_transfer, active_repair)
    last_movement = next(
        (
            event
            for event in sorted(machine.events, key=lambda value: value.created_at, reverse=True)
            if event.event_type in {"TRANSFER_ISSUED", "TRANSFER_RETURNED", "IMPORTED"}
        ),
        None,
    )
    last_inspection = next(
        (
            repair
            for repair in sorted(
                machine.repairs,
                key=lambda value: value.inspection_completed_at or value.opened_at,
                reverse=True,
            )
            if repair.inspection_completed_at is not None
        ),
        None,
    )
    last_test = next(
        (
            repair
            for repair in sorted(
                machine.repairs,
                key=lambda value: value.closed_at or value.opened_at,
                reverse=True,
            )
            if repair.test_passed is not None
        ),
        None,
    )
    repair_ids = [item.id for item in machine.repairs]
    transfer_ids = [item.id for item in machine.transfers]
    request_ids = [item.id for item in part_requests]
    document_ids = [item.id for item in documents]
    audit_conditions = [and_(AuditLog.entity_type == "machine", AuditLog.entity_id == machine.id)]
    for entity_type, identifiers in (
        ("repair", repair_ids),
        ("transfer", transfer_ids),
        ("part_request", request_ids),
        ("generated_document", document_ids),
    ):
        if identifiers:
            audit_conditions.append(
                and_(
                    AuditLog.entity_type == entity_type,
                    AuditLog.entity_id.in_(identifiers),
                )
            )
    audit_entries = (
        db.scalars(
            select(AuditLog)
            .where(or_(*audit_conditions))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        ).all()
        if has_permission(user, Permission.AUDIT_VIEW_OPERATIONAL)
        else []
    )
    return {
        "limited_view": False,
        "machine": {
            column.name: getattr(machine, column.name)
            for column in Machine.__table__.columns
            if column.name not in {"category_id"}
        }
        | {
            "location": (
                {
                    "id": machine.location.id,
                    "name": machine.location.name,
                    "description": machine.location.description,
                }
                if machine.location
                else None
            ),
            "category_definition": (
                {
                    "id": machine.category_definition.id,
                    "code": machine.category_definition.code,
                    "name_bg": machine.category_definition.name_bg,
                    "name_en": machine.category_definition.name_en,
                    "name_ru": machine.category_definition.name_ru,
                }
                if machine.category_definition
                else None
            ),
        },
        "custom_fields": [
            {
                "field_id": field.id,
                "code": field.code,
                "label_bg": field.label_bg,
                "label_en": field.label_en,
                "label_ru": field.label_ru,
                "field_type": field.field_type,
                "is_required": field.is_required,
                "options": field.options,
                "unit": field.unit,
                "validation_rules": field.validation_rules,
                "value": values.get(field.id).value if field.id in values else None,
            }
            for field in sorted(fields, key=lambda item: (item.sort_order, item.id))
        ],
        "attachments": [_attachment_dict(item, "machine") for item in machine.attachments],
        "history": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "reference": event.reference,
                "previous_status": event.previous_status,
                "new_status": event.new_status,
                "previous_location_id": event.previous_location_id,
                "new_location_id": event.new_location_id,
                "details": event.details,
                "user_id": event.user_id,
                "created_at": event.created_at,
            }
            for event in sorted(machine.events, key=lambda item: item.created_at, reverse=True)
        ],
        "repairs": [
            {
                "id": repair.id,
                "repair_reference": repair.repair_reference,
                "status": repair.status,
                "reported_problem": repair.reported_problem,
                "opened_at": repair.opened_at,
                "closed_at": repair.closed_at,
            }
            for repair in sorted(machine.repairs, key=lambda item: item.opened_at, reverse=True)
        ],
        "transfers": [
            {
                "id": transfer.id,
                "protocol_number": transfer.protocol_number,
                "batch_reference": transfer.batch_reference,
                "is_active": transfer.is_active,
                "issued_at": transfer.issued_at,
                "returned_at": transfer.returned_at,
                "location_text": transfer.location_text,
                "accepted_by": transfer.accepted_by,
            }
            for transfer in sorted(
                machine.transfers, key=lambda item: item.created_at, reverse=True
            )
        ],
        "part_requests": [
            {
                "id": item.id,
                "request_reference": item.request_reference,
                "status": item.status,
                "priority": item.priority,
                "created_at": item.created_at,
            }
            for item in part_requests
        ],
        "parts_used": [
            {
                "id": part.id,
                "repair_id": repair.id,
                "repair_reference": repair.repair_reference,
                "catalog_part_id": part.catalog_part_id,
                "part_number": part.part_number,
                "description": part.description,
                "quantity": part.quantity,
                "unit": part.unit,
                "source": part.source,
                "created_at": part.created_at,
            }
            for repair in sorted(machine.repairs, key=lambda value: value.opened_at, reverse=True)
            for part in sorted(repair.parts_used, key=lambda value: value.created_at, reverse=True)
        ],
        "generated_documents": [
            {
                "id": item.id,
                "document_number": item.document_number,
                "document_type": item.document_type,
                "format": item.format,
                "filename": item.filename,
                "created_at": item.created_at,
                "download_endpoint": f"/generated-documents/{item.id}/download",
            }
            for item in documents
        ],
        "technical_documents": [
            {
                "id": item.id,
                "brand": item.brand,
                "model": item.model,
                "category": item.category,
                "title": item.title,
                "document_type": item.document_type,
                "language": item.language,
                "revision": item.revision,
                "source_label": item.source_label,
                "document_date": item.document_date,
                "tags": item.tags,
                "page_count": item.page_count,
                "notes": item.notes,
                "linked_machine_numbers": item.linked_machine_numbers,
                "sha256": item.sha256,
                "created_at": item.created_at,
                "download_endpoint": f"/technical-library/{item.id}/download",
                "revisions": [
                    {
                        "id": revision.id,
                        "version": revision.version,
                        "revision_label": revision.revision_label,
                        "filename": revision.filename,
                        "sha256": revision.sha256,
                        "change_note": revision.change_note,
                        "created_at": revision.created_at,
                        "download_endpoint": (
                            f"/technical-library/revisions/{revision.id}/download"
                        ),
                    }
                    for revision in sorted(
                        item.revisions, key=lambda value: value.version, reverse=True
                    )
                ],
            }
            for item in technical_documents
        ],
        "current_state": {
            "available": available,
            "active_transfer": (
                {
                    "id": active_transfer.id,
                    "protocol_number": active_transfer.protocol_number,
                    "batch_reference": active_transfer.batch_reference,
                    "issued_at": active_transfer.issued_at,
                    "company_unit": active_transfer.company_unit,
                    "department": active_transfer.department,
                    "vessel": active_transfer.vessel,
                    "dock": active_transfer.dock,
                    "pier": active_transfer.pier,
                    "work_area": active_transfer.work_area,
                    "location_text": active_transfer.location_text,
                    "accepted_by": active_transfer.accepted_by,
                }
                if active_transfer
                else None
            ),
            "active_repair": (
                {
                    "id": active_repair.id,
                    "repair_reference": active_repair.repair_reference,
                    "status": active_repair.status,
                    "reported_problem": active_repair.reported_problem,
                    "opened_at": active_repair.opened_at,
                }
                if active_repair
                else None
            ),
            "last_movement": (
                {
                    "event_type": last_movement.event_type,
                    "reference": last_movement.reference,
                    "created_at": last_movement.created_at,
                }
                if last_movement
                else None
            ),
            "last_inspection": (
                {
                    "repair_reference": last_inspection.repair_reference,
                    "completed_at": last_inspection.inspection_completed_at,
                }
                if last_inspection
                else None
            ),
            "last_test": (
                {
                    "repair_reference": last_test.repair_reference,
                    "passed": last_test.test_passed,
                    "details": last_test.test_details,
                    "completed_at": last_test.closed_at,
                }
                if last_test
                else None
            ),
            "allowed_actions": {
                "issue": has_permission(user, Permission.TRANSFERS_CREATE)
                and available,
                "return": has_permission(user, Permission.TRANSFERS_RETURN)
                and active_transfer is not None,
                "repair": has_permission(user, Permission.REPAIRS_CREATE) and active_repair is None,
                "edit": has_permission(user, Permission.ASSETS_EDIT),
            },
        },
        "audit_visible": has_permission(user, Permission.AUDIT_VIEW_OPERATIONAL),
        "audit": [
            {
                "id": item.id,
                "entity_type": item.entity_type,
                "entity_id": item.entity_id,
                "action": item.action,
                "details": item.details,
                "user_name": item.user_name,
                "operation_reference": item.operation_reference,
                "created_at": item.created_at,
            }
            for item in audit_entries
        ],
        "qr_endpoint": f"/machines/{machine.id}/qr",
    }
