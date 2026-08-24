from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import mimetypes
import re
import time
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .audit import add_audit_log
from .database import get_db
from .document_generation import (
    ConfirmedTemplateUnavailableError,
    TemplateValidationError,
    make_part_request_documents,
    make_repair_correction,
    make_repair_documents,
)
from .industrial_schemas import (
    AttachmentCreate,
    CatalogPartCreate,
    CatalogPartUpdate,
    CategoryCreate,
    CategoryFieldCreate,
    CustomFieldValuesUpdate,
    DepartmentCreate,
    DepartmentUpdate,
    HotspotCreate,
    ImportConfirmRequest,
    ImportPreviewRequest,
    LocationAdminCreate,
    LocationAdminUpdate,
    MultiPartRequestCreate,
    PartRequestDecision,
    PartRequestFulfillmentUpdate,
    PartRequestPendingActionCountOut,
    RepairCaseCreate,
    RepairCaseUpdate,
    RepairEventCreate,
    RepairKitCreate,
    RepairPartCreate,
    RepairParticipantCreate,
    RepairProtocolCorrection,
    TechnicalDocumentUpload,
    TemplateCreate,
    TemplateVersionCreate,
    UnknownPartCatalogLink,
    UnknownPartRequestCreate,
)
from .models import (
    AssetCategory,
    AuditLog,
    CategoryFieldDefinition,
    Department,
    DocumentTemplate,
    DocumentTemplateVersion,
    DocumentType,
    FieldType,
    GeneratedDocument,
    Location,
    Machine,
    MachineAttachment,
    MachineFieldValue,
    MachineStatus,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    PartCatalog,
    PartCatalogImage,
    PartHotspot,
    PartRequest,
    PartRequestApproval,
    PartRequestAttachment,
    PartRequestLine,
    PartRequestStatus,
    ProtocolDocument,
    Repair,
    RepairAttachment,
    RepairEvent,
    RepairEventType,
    RepairKit,
    RepairKitComponent,
    RepairPart,
    RepairParticipant,
    RepairStatus,
    TechnicalDocument,
    TechnicalDocumentRevision,
    TransferBatch,
    TransferProtocol,
    User,
    utcnow,
)
from .part_requests import (
    OFFICIAL_DOCUMENT_STATUSES,
    decide_request,
    load_request,
    part_request_document_generation_guard,
    pending_action_count,
    submit_for_approval,
)
from .permissions import (
    Permission,
    ensure_permission,
    has_permission,
    is_observer,
    require_permission,
)
from .repairs import (
    apply_repair_transition,
    generate_completion_documents_or_rollback,
)
from .settings import settings
from .template_engine import validate_template
from .workflow import (
    add_machine_event,
    business_conflict,
    ensure_machine_transition,
    ensure_repair_can_start_finalization,
)

router = APIRouter(prefix="/api", tags=["industrial-platform"])

MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/webp",
}
PROTECTED_HPWJ_NUMBERS = {
    "4", "5", "7", "9", "10", "11", "12", "13", "14", "15", "16",
    "17", "18", "19", "20", "21", "22", "23", "24",
}


require_admin = require_permission(Permission.SETTINGS_MANAGE)
require_repair_creator = require_permission(Permission.REPAIRS_CREATE)
require_repair_operator = require_permission(Permission.REPAIRS_EDIT)
require_parts_operator = require_permission(Permission.REQUESTS_CREATE)
require_request_approver = require_permission(Permission.REQUESTS_APPROVE)
require_asset_viewer = require_permission(Permission.ASSETS_VIEW)
require_repair_viewer = require_permission(Permission.REPAIRS_VIEW)
require_request_viewer = require_permission(Permission.REQUESTS_VIEW)
require_parts_viewer = require_permission(Permission.PARTS_VIEW)
require_parts_manager = require_permission(Permission.PARTS_MANAGE)
require_document_viewer = require_permission(Permission.DOCUMENTS_VIEW)
require_document_generator = require_permission(Permission.DOCUMENTS_GENERATE)
require_template_manager = require_permission(Permission.TEMPLATES_MANAGE)
require_audit_full = require_permission(Permission.AUDIT_VIEW_FULL)


def _decode_file(payload: AttachmentCreate | TechnicalDocumentUpload | TemplateVersionCreate) -> tuple[str, bytes]:
    filename = Path(payload.filename).name
    if filename != payload.filename or filename in {"", ".", ".."}:
        raise HTTPException(
            status_code=422,
            detail={"code": "unsafe_filename", "message": "Името на файла не е допустимо."},
        )
    if payload.media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_media_type",
                "message": "Файловият формат не се поддържа.",
            },
        )
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_file_content", "message": "Файлът не е валидно кодиран."},
        ) from exc
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_file_size",
                "message": "Файлът трябва да бъде с размер до 12 MB.",
            },
        )
    suffix = Path(filename).suffix.lower()
    signatures_valid = {
        "application/pdf": suffix == ".pdf" and content.startswith(b"%PDF-"),
        "image/png": suffix == ".png" and content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": suffix in {".jpg", ".jpeg"} and content.startswith(b"\xff\xd8\xff"),
        "image/webp": suffix == ".webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
    }
    office_roots = {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx", "word/document.xml"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (".xlsx", "xl/workbook.xml"),
    }
    if payload.media_type in office_roots:
        expected_suffix, required_member = office_roots[payload.media_type]
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as package:
                names = set(package.namelist())
            valid_signature = suffix == expected_suffix and {"[Content_Types].xml", required_member}.issubset(names)
        except zipfile.BadZipFile:
            valid_signature = False
    else:
        valid_signature = signatures_valid.get(payload.media_type, False)
    if not valid_signature:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "file_signature_mismatch",
                "message": "Съдържанието на файла не съответства на заявения формат.",
            },
        )
    return filename, content


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise business_conflict(
            "database_integrity_conflict",
            "Операцията е в конфликт с вече съществуващ запис.",
        ) from exc


def _attachment_dict(
    item: MachineAttachment | RepairAttachment | PartRequestAttachment, kind: str
) -> dict:
    return {
        "id": item.id,
        "filename": item.filename,
        "media_type": item.media_type,
        "sha256": item.sha256,
        "created_at": item.created_at,
        "description": getattr(item, "description", None),
        "kind": getattr(item, "kind", None),
        "caption": getattr(item, "caption", None),
        "stage": getattr(item, "stage", None),
        "request_line_id": getattr(item, "request_line_id", None),
        "download_endpoint": f"/{kind}-attachments/{item.id}/download",
    }


def _repair_event_dict(item: RepairEvent) -> dict:
    return {
        "id": item.id,
        "event_type": item.event_type,
        "status_before": item.status_before,
        "status_after": item.status_after,
        "description": item.description,
        "structured_data": item.structured_data,
        "user_id": item.user_id,
        "created_at": item.created_at,
    }


def _repair_part_dict(item: RepairPart) -> dict:
    return {
        "id": item.id,
        "repair_id": item.repair_id,
        "catalog_part_id": item.catalog_part_id,
        "part_number": item.part_number,
        "description": item.description,
        "quantity": item.quantity,
        "unit": item.unit,
        "source": item.source,
        "created_by_id": item.created_by_id,
        "created_at": item.created_at,
    }


def _repair_participant_dict(item: RepairParticipant) -> dict:
    return {
        "id": item.id,
        "repair_id": item.repair_id,
        "user_id": item.user_id,
        "full_name": item.full_name_snapshot,
        "job_title": item.job_title_snapshot,
        "contribution": item.contribution,
        "minutes_worked": item.minutes_worked,
        "created_by_id": item.created_by_id,
        "created_at": item.created_at,
    }


def _repair_dict(repair: Repair) -> dict:
    return {
        "id": repair.id,
        "repair_reference": repair.repair_reference,
        "machine_id": repair.machine_id,
        "source_return_transfer_id": repair.source_return_transfer_id,
        "source_return_document_id": repair.source_return_document_id,
        "source_return_batch_id": repair.source_return_batch_id,
        "machine_number": repair.machine.inventory_number,
        "machine_name": repair.machine.name,
        "reported_problem": repair.reported_problem,
        "diagnosis": repair.diagnosis,
        "work_performed": repair.work_performed,
        "result": repair.result,
        "status": repair.status,
        "repair_type": repair.repair_type,
        "severity": repair.severity,
        "condition_before": repair.condition_before,
        "condition_after": repair.condition_after,
        "reported_by_name": repair.reported_by_name,
        "symptoms": repair.symptoms,
        "required_work": repair.required_work,
        "required_parts_text": repair.required_parts_text,
        "removed_parts_text": repair.removed_parts_text,
        "diagnostic_cleaning": repair.diagnostic_cleaning,
        "diagnosis_minutes": repair.diagnosis_minutes,
        "repair_minutes": repair.repair_minutes,
        "testing_minutes": repair.testing_minutes,
        "total_work_minutes": sum(
            value or 0
            for value in (
                repair.diagnosis_minutes,
                repair.repair_minutes,
                repair.testing_minutes,
            )
        ),
        "participant_total_minutes": sum(
            item.minutes_worked or 0 for item in repair.participants
        ),
        "cleaning_required": repair.cleaning_required,
        "cleaning_completed_at": repair.cleaning_completed_at,
        "inspection_completed_at": repair.inspection_completed_at,
        "test_required": repair.test_required,
        "test_passed": repair.test_passed,
        "test_details": repair.test_details,
        "test_method": repair.test_method,
        "test_pressure_bar": repair.test_pressure_bar,
        "leaks_detected": repair.leaks_detected,
        "electrical_test_result": repair.electrical_test_result,
        "functional_test_result": repair.functional_test_result,
        "responsible_user_id": repair.responsible_user_id,
        "responsible_user": (
            {
                "id": repair.responsible_user.id,
                "full_name": repair.responsible_user.full_name,
                "job_title": repair.responsible_user.job_title,
            }
            if repair.responsible_user
            else None
        ),
        "participants": [
            _repair_participant_dict(item)
            for item in sorted(repair.participants, key=lambda value: (value.created_at, value.id))
        ],
        "accepted_by_id": repair.accepted_by_id,
        "accepted_by": (
            {
                "id": repair.accepted_by.id,
                "full_name": repair.accepted_by.full_name,
                "job_title": repair.accepted_by.job_title,
            }
            if repair.accepted_by
            else None
        ),
        "approved_by_id": repair.approved_by_id,
        "approved_by": (
            {
                "id": repair.approved_by.id,
                "full_name": repair.approved_by.full_name,
                "job_title": repair.approved_by.job_title,
            }
            if repair.approved_by
            else None
        ),
        "approved_at": repair.approved_at,
        "target_date": repair.target_date,
        "opened_at": repair.opened_at,
        "started_at": repair.started_at,
        "closed_at": repair.closed_at,
        "events": [
            _repair_event_dict(item)
            for item in sorted(repair.events, key=lambda value: (value.created_at, value.id))
        ],
        "parts_used": [_repair_part_dict(item) for item in repair.parts_used],
        "attachments": [_attachment_dict(item, "repair") for item in repair.attachments],
        "generated_documents": [
            {
                "id": document.id,
                "document_number": document.document_number,
                "document_type": document.document_type,
                "format": document.format,
                "filename": document.filename,
                "created_at": document.created_at,
                "download_endpoint": f"/generated-documents/{document.id}/download",
            }
            for document in sorted(
                repair.generated_documents,
                key=lambda value: (value.created_at, value.id),
                reverse=True,
            )
        ],
    }


def _load_repair(db: Session, repair_id: int, *, lock: bool = False) -> Repair:
    statement = (
        select(Repair)
        .options(
            selectinload(Repair.machine),
            selectinload(Repair.responsible_user),
            selectinload(Repair.accepted_by),
            selectinload(Repair.approved_by),
            selectinload(Repair.events),
            selectinload(Repair.parts_used),
            selectinload(Repair.participants),
            selectinload(Repair.attachments),
            selectinload(Repair.generated_documents),
        )
        .where(Repair.id == repair_id)
    )
    if lock and db.bind is not None and db.bind.dialect.name == "postgresql":
        statement = statement.with_for_update()
    repair = db.scalar(statement)
    if repair is None:
        raise HTTPException(404, "Ремонтът не е намерен.")
    return repair


def _part_request_dict(item: PartRequest, documents: list[GeneratedDocument]) -> dict:
    return {
        "id": item.id,
        "request_reference": item.request_reference or f"PR-{item.id:06d}",
        "machine_id": item.machine_id,
        "machine_number": item.machine.inventory_number if item.machine else None,
        "repair_id": item.repair_id,
        "repair_reference": item.repair.repair_reference if item.repair else None,
        "repair_kit_id": item.repair_kit_id,
        "repair_kit_mode": item.repair_kit_mode,
        "priority": item.priority,
        "status": item.status,
        "language": item.language,
        "reason": item.reason,
        "requested_by_id": item.requested_by_id,
        "requested_by_name": item.requested_by.full_name if item.requested_by else None,
        "decided_by_name": item.decided_by.full_name if item.decided_by else None,
        "submitted_at": item.submitted_at,
        "decided_at": item.decided_at,
        "decision_note": item.decision_note,
        "department": item.department,
        "supplier": item.supplier,
        "delivery_note": item.delivery_note,
        "ordered_at": item.ordered_at,
        "delivered_at": item.delivered_at,
        "created_at": item.created_at,
        "lines": [
            {
                "id": line.id,
                "request_id": line.request_id,
                "catalog_part_id": line.catalog_part_id,
                "position": line.position,
                "part_number": line.part_number,
                "description": line.description,
                "quantity": line.quantity,
                "unit": line.unit,
                "reason": line.reason,
                "source_document": line.source_document,
                "source_page": line.source_page,
                "delivered_quantity": line.delivered_quantity,
                "is_unknown_part": line.is_unknown_part,
                "assembly": line.assembly,
                "note": line.note,
                "linked_catalog_part_id": line.linked_catalog_part_id,
                "linked_part_number": line.linked_catalog_part.part_number if line.linked_catalog_part else None,
                "linked_part_description": line.linked_catalog_part.description if line.linked_catalog_part else None,
                "linked_by_id": line.linked_by_id,
                "linked_at": line.linked_at,
                "link_note": line.link_note,
            }
            for line in item.lines
        ],
        "approvals": [
            {
                "id": approval.id,
                "decision": approval.decision,
                "note": approval.note,
                "decided_by_id": approval.decided_by_id,
                "decided_by_name": approval.decided_by.full_name if approval.decided_by else None,
                "decided_at": approval.decided_at,
            }
            for approval in item.approvals
        ],
        "attachments": [
            _attachment_dict(attachment, "part-request")
            for attachment in sorted(
                item.attachments,
                key=lambda value: (value.created_at, value.id),
                reverse=True,
            )
        ],
        "documents": [
            {
                "id": document.id,
                "format": document.format,
                "filename": document.filename,
                "download_endpoint": f"/generated-documents/{document.id}/download",
            }
            for document in documents
        ],
    }


def _validated_custom_field_value(
    field: CategoryFieldDefinition, raw_value: str | None
) -> str | None:
    value = raw_value.strip() if raw_value is not None else None
    if value == "":
        value = None
    if value is None:
        if field.is_required:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "required_custom_field",
                    "message": f"Полето „{field.label_bg}“ е задължително.",
                    "field_id": field.id,
                },
            )
        return None
    normalized_value = value
    try:
        if field.field_type == FieldType.INTEGER.value:
            normalized_value = str(int(value))
        elif field.field_type == FieldType.DECIMAL.value:
            decimal_value = Decimal(value)
            if not decimal_value.is_finite():
                raise InvalidOperation
            normalized_value = format(decimal_value.normalize(), "f")
        elif field.field_type == FieldType.DATE.value:
            normalized_value = date.fromisoformat(value).isoformat()
        elif field.field_type == FieldType.BOOLEAN.value:
            normalized = value.lower()
            if normalized not in {"true", "false", "1", "0"}:
                raise ValueError
            normalized_value = "true" if normalized in {"true", "1"} else "false"
        elif field.field_type == FieldType.SELECT.value:
            options = field.options or []
            if value not in options:
                raise ValueError
        rules = field.validation_rules or {}
        if field.field_type in {FieldType.INTEGER.value, FieldType.DECIMAL.value}:
            numeric = Decimal(normalized_value)
            if rules.get("min") is not None and numeric < Decimal(str(rules["min"])):
                raise ValueError
            if rules.get("max") is not None and numeric > Decimal(str(rules["max"])):
                raise ValueError
        if rules.get("min_length") is not None and len(normalized_value) < int(rules["min_length"]):
            raise ValueError
        if rules.get("max_length") is not None and len(normalized_value) > int(rules["max_length"]):
            raise ValueError
        if rules.get("pattern") and re.fullmatch(str(rules["pattern"]), normalized_value) is None:
            raise ValueError
    except (InvalidOperation, ValueError, TypeError, re.error):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_custom_field_value",
                "message": f"Стойността за поле „{field.label_bg}“ е невалидна.",
                "field_id": field.id,
                "field_type": field.field_type,
            },
        ) from None
    return normalized_value


@router.get("/categories")
def list_categories(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    categories = db.scalars(
        select(AssetCategory)
        .options(selectinload(AssetCategory.fields))
        .where(AssetCategory.is_active.is_(True))
        .order_by(AssetCategory.name_bg)
    ).all()
    return [
        {
            "id": category.id,
            "code": category.code,
            "name_bg": category.name_bg,
            "name_en": category.name_en,
            "name_ru": category.name_ru,
            "description": category.description,
            "icon": category.icon,
            "validation_rules": category.validation_rules,
            "document_types": category.document_types,
            "checklists": category.checklists,
            "status_codes": category.status_codes,
            "is_active": category.is_active,
            "created_at": category.created_at,
            "fields": sorted(category.fields, key=lambda item: (item.sort_order, item.id)),
        }
        for category in categories
    ]


@router.post("/categories", status_code=201, response_model=None)
def create_category(
    payload: CategoryCreate,
    user: User = Depends(require_permission(Permission.ASSETS_CREATE)),
    db: Session = Depends(get_db),
) -> AssetCategory:
    category = AssetCategory(**payload.model_dump())
    db.add(category)
    db.flush()
    add_audit_log(db, user, "asset_category", category.id, "Създадена категория", payload.model_dump())
    _commit(db)
    db.refresh(category)
    return category


@router.post("/categories/{category_id}/fields", status_code=201, response_model=None)
def create_category_field(
    category_id: int,
    payload: CategoryFieldCreate,
    user: User = Depends(require_permission(Permission.ASSETS_EDIT)),
    db: Session = Depends(get_db),
) -> CategoryFieldDefinition:
    if db.get(AssetCategory, category_id) is None:
        raise HTTPException(404, "Категорията не е намерена.")
    field = CategoryFieldDefinition(category_id=category_id, **payload.model_dump(mode="json"))
    db.add(field)
    db.flush()
    add_audit_log(db, user, "category_field", field.id, "Създадено конфигурируемо поле", payload.model_dump(mode="json"))
    _commit(db)
    db.refresh(field)
    return field


@router.get("/machines/{machine_id}/passport")
def machine_passport(
    machine_id: int,
    user: User = Depends(require_asset_viewer),
    db: Session = Depends(get_db),
) -> dict:
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
        active_transfer = next(
            (item for item in machine.transfers if item.is_active), None
        )
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
                "available": machine.is_active
                and active_transfer is None
                and active_repair is None,
                "active_transfer": (
                    {"is_active": True} if active_transfer is not None else None
                ),
                "active_repair": (
                    {"status": active_repair.status}
                    if active_repair is not None
                    else None
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
    active_transfer = next(
        (item for item in machine.transfers if item.is_active), None
    )
    active_repair = next(
        (
            item
            for item in sorted(
                machine.repairs, key=lambda value: value.opened_at, reverse=True
            )
            if item.status != RepairStatus.COMPLETED.value
        ),
        None,
    )
    last_movement = next(
        (
            event
            for event in sorted(
                machine.events, key=lambda value: value.created_at, reverse=True
            )
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
    audit_conditions = [
        and_(AuditLog.entity_type == "machine", AuditLog.entity_id == machine.id)
    ]
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
            for event in sorted(
                machine.events, key=lambda item: item.created_at, reverse=True
            )
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
            for transfer in sorted(machine.transfers, key=lambda item: item.created_at, reverse=True)
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
            for repair in sorted(
                machine.repairs, key=lambda value: value.opened_at, reverse=True
            )
            for part in sorted(
                repair.parts_used, key=lambda value: value.created_at, reverse=True
            )
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
            "available": machine.is_active and active_transfer is None,
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
                and active_transfer is None,
                "return": has_permission(user, Permission.TRANSFERS_RETURN)
                and active_transfer is not None,
                "repair": has_permission(user, Permission.REPAIRS_CREATE)
                and active_repair is None,
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


@router.put("/machines/{machine_id}/custom-fields")
def update_custom_fields(
    machine_id: int,
    payload: CustomFieldValuesUpdate,
    user: User = Depends(require_permission(Permission.ASSETS_EDIT)),
    db: Session = Depends(get_db),
) -> dict:
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    field_ids = [item.field_id for item in payload.values]
    fields = db.scalars(
        select(CategoryFieldDefinition).where(CategoryFieldDefinition.id.in_(field_ids))
    ).all() if field_ids else []
    by_id = {field.id: field for field in fields}
    if len(by_id) != len(field_ids):
        raise HTTPException(404, "Едно или повече потребителски полета не са намерени.")
    current_values = {
        item.field_id: item
        for item in db.scalars(
            select(MachineFieldValue).where(MachineFieldValue.machine_id == machine.id)
        ).all()
    }
    previous = {
        by_id[field_id].code: current_values.get(field_id).value
        if field_id in current_values
        else None
        for field_id in field_ids
    }
    normalized: dict[int, str | None] = {}
    for item in payload.values:
        field = by_id[item.field_id]
        if machine.category_id != field.category_id:
            raise business_conflict(
                "field_category_mismatch",
                f"Полето „{field.label_bg}“ не принадлежи към категорията на машината.",
            )
        normalized[field.id] = _validated_custom_field_value(field, item.value)
        value = current_values.get(field.id)
        if value is None:
            value = MachineFieldValue(machine_id=machine.id, field_id=field.id)
            db.add(value)
            current_values[field.id] = value
        value.value = normalized[field.id]
        value.updated_by_id = user.id
    required_fields = db.scalars(
        select(CategoryFieldDefinition).where(
            CategoryFieldDefinition.category_id == machine.category_id,
            CategoryFieldDefinition.is_active.is_(True),
            CategoryFieldDefinition.is_required.is_(True),
        )
    ).all()
    for field in required_fields:
        candidate = normalized.get(
            field.id,
            current_values.get(field.id).value if field.id in current_values else None,
        )
        _validated_custom_field_value(field, candidate)
    changed = {
        by_id[field_id].code: normalized[field_id]
        for field_id in field_ids
        if previous[by_id[field_id].code] != normalized[field_id]
    }
    add_machine_event(
        db, machine, user, "CUSTOM_FIELDS_UPDATED",
        details={"field_ids": field_ids, "previous": previous, "new": changed},
    )
    add_audit_log(
        db,
        user,
        "machine",
        machine.id,
        "Обновени конфигурируеми полета",
        {"field_ids": field_ids, "previous": previous, "new": changed},
    )
    _commit(db)
    return {
        "message": "Потребителските полета са обновени.",
        "machine_id": machine.id,
        "values": [
            {"field_id": field_id, "value": normalized[field_id]}
            for field_id in field_ids
        ],
    }


@router.post("/machines/{machine_id}/attachments", status_code=201)
def add_machine_attachment(
    machine_id: int,
    payload: AttachmentCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> dict:
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    filename, content = _decode_file(payload)
    item = MachineAttachment(
        machine_id=machine.id,
        kind=payload.kind,
        filename=filename,
        media_type=payload.media_type,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        description=payload.description,
        created_by_id=user.id,
    )
    db.add(item)
    db.flush()
    add_machine_event(db, machine, user, "ATTACHMENT_ADDED", reference=str(item.id), details={"filename": filename, "kind": payload.kind})
    add_audit_log(db, user, "machine_attachment", item.id, "Добавен файл към машината", {"machine_number": machine.inventory_number, "filename": filename, "sha256": item.sha256})
    _commit(db)
    db.refresh(item)
    return _attachment_dict(item, "machine")


@router.get("/machine-attachments/{attachment_id}/download")
def download_machine_attachment(
    attachment_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(MachineAttachment, attachment_id)
    if item is None:
        raise HTTPException(404, "Файлът не е намерен.")
    return Response(
        item.content,
        media_type=item.media_type,
        headers={"Content-Disposition": f'attachment; filename="{item.filename}"', "X-Content-Type-Options": "nosniff"},
    )


@router.get("/repair-cases")
def list_repair_cases(
    _: User = Depends(require_repair_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    repairs = db.scalars(
        select(Repair)
        .options(
            joinedload(Repair.machine),
            joinedload(Repair.responsible_user),
            selectinload(Repair.events),
            selectinload(Repair.parts_used),
            selectinload(Repair.participants),
            selectinload(Repair.attachments),
            selectinload(Repair.generated_documents),
        )
        .order_by(Repair.opened_at.desc())
    ).all()
    return [_repair_dict(item) for item in repairs]


@router.get("/repair-cases/{repair_id}")
def get_repair_case(
    repair_id: int,
    _: User = Depends(require_repair_viewer),
    db: Session = Depends(get_db),
) -> dict:
    return _repair_dict(_load_repair(db, repair_id))


@router.post("/repair-cases/{repair_id}/documents", status_code=201)
def generate_repair_documents(
    repair_id: int,
    language: str = Query(default="bg", pattern=r"^(bg|en|ru)$"),
    user: User = Depends(require_document_generator),
    db: Session = Depends(get_db),
) -> dict:
    # Internal repair protocols are controlled Bulgarian documents regardless of UI locale.
    requested_language = language
    language = "bg"
    repair = _load_repair(db, repair_id, lock=True)
    existing_documents = list(
        db.scalars(
            select(GeneratedDocument)
            .where(
                GeneratedDocument.repair_id == repair.id,
                GeneratedDocument.language == language,
            )
            .order_by(GeneratedDocument.id)
        )
    )
    if existing_documents:
        return {
            "document_number": existing_documents[0].document_number,
            "language": "bg",
            "requested_language": requested_language,
            "documents": [
                {
                    "id": document.id,
                    "format": document.format,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "download_endpoint": f"/generated-documents/{document.id}/download",
                }
                for document in existing_documents
            ],
        }
    if repair.status != RepairStatus.COMPLETED.value:
        raise business_conflict(
            "repair_protocol_requires_completion",
            "Ремонтният протокол се заключва след приключване на ремонта.",
        )
    try:
        documents = make_repair_documents(db, repair, user.id, language)
    except ConfirmedTemplateUnavailableError as exc:
        raise business_conflict(
            "document_template_unavailable",
            exc.message,
            document_type=exc.document_type,
            requested_language=exc.language,
            fallback_language="bg",
        ) from exc
    except TemplateValidationError as exc:
        raise business_conflict(
            "document_generation_validation_failed", str(exc)
        ) from exc
    db.add_all(documents)
    db.flush()
    add_audit_log(
        db,
        user,
        "repair",
        repair.id,
        "Генериран ремонтен протокол",
        {
            "repair_reference": repair.repair_reference,
            "language": "bg",
            "requested_language": requested_language,
            "generated_document_ids": [document.id for document in documents],
            "document_number": documents[0].document_number,
        },
        repair.repair_reference,
    )
    _commit(db)
    return {
        "document_number": documents[0].document_number,
        "language": "bg",
        "requested_language": requested_language,
        "documents": [
            {
                "id": document.id,
                "format": document.format,
                "filename": document.filename,
                "sha256": document.sha256,
                "download_endpoint": f"/generated-documents/{document.id}/download",
            }
            for document in documents
        ],
    }


@router.post("/repair-cases/{repair_id}/documents/corrections", status_code=201)
def correct_repair_protocol(
    repair_id: int,
    payload: RepairProtocolCorrection,
    user: User = Depends(require_document_generator),
    db: Session = Depends(get_db),
) -> dict:
    repair = _load_repair(db, repair_id, lock=True)
    if repair.status != RepairStatus.COMPLETED.value:
        raise business_conflict(
            "repair_protocol_requires_completion",
            "Само протокол на приключен ремонт може да бъде коригиран.",
        )
    try:
        documents, official, version = make_repair_correction(
            db, repair, user.id, payload.reason, "bg"
        )
    except ConfirmedTemplateUnavailableError as exc:
        raise business_conflict(
            "document_template_unavailable",
            exc.message,
            document_type=exc.document_type,
            requested_language=exc.language,
            fallback_language="bg",
        ) from exc
    except TemplateValidationError as exc:
        raise business_conflict(
            "repair_protocol_correction_failed", str(exc)
        ) from exc
    db.add_all(documents)
    db.flush()
    add_audit_log(
        db,
        user,
        "repair",
        repair.id,
        "Създадена нова версия на вътрешен ремонтен протокол",
        {
            "repair_reference": repair.repair_reference,
            "official_document_id": official.id,
            "official_document_version": version.version,
            "supersedes_version_id": version.supersedes_version_id,
            "correction_reason": payload.reason,
            "generated_document_ids": [item.id for item in documents],
        },
        repair.repair_reference,
    )
    _commit(db)
    return {
        "official_document_id": official.id,
        "version": version.version,
        "status": version.status,
        "correction_reason": version.correction_reason,
        "documents": [
            {
                "id": document.id,
                "format": document.format,
                "filename": document.filename,
                "sha256": document.sha256,
                "download_endpoint": f"/generated-documents/{document.id}/download",
            }
            for document in documents
        ],
    }


@router.post("/repair-cases", status_code=201)
def create_repair_case(
    payload: RepairCaseCreate,
    user: User = Depends(require_repair_creator),
    db: Session = Depends(get_db),
) -> dict:
    machine_statement = select(Machine).where(Machine.id == payload.machine_id)
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        machine_statement = machine_statement.with_for_update()
    machine = db.scalar(machine_statement)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    if db.scalar(select(TransferProtocol.id).where(TransferProtocol.machine_id == machine.id, TransferProtocol.is_active.is_(True))):
        raise business_conflict(
            "active_transfer_blocks_repair",
            f"Машина №{machine.inventory_number} има активно предаване. Първо я върнете.",
            machine_number=machine.inventory_number,
        )
    if db.scalar(select(Repair.id).where(Repair.machine_id == machine.id, Repair.status != RepairStatus.COMPLETED.value)):
        raise business_conflict(
            "open_repair_exists",
            f"Машина №{machine.inventory_number} вече има незавършен ремонт.",
            machine_number=machine.inventory_number,
        )
    previous_status = machine.status
    ensure_machine_transition(previous_status, MachineStatus.REPAIR.value)
    repair = Repair(
        machine_id=machine.id,
        reported_problem=payload.reported_problem,
        diagnosis=payload.diagnosis,
        repair_type=payload.repair_type,
        severity=payload.severity,
        condition_before=payload.condition_before,
        reported_by_name=payload.reported_by_name,
        symptoms=payload.symptoms,
        required_work=payload.required_work,
        responsible_user_id=payload.responsible_user_id or user.id,
        accepted_by_id=user.id,
        cleaning_required=payload.cleaning_required,
        test_required=payload.test_required,
        target_date=payload.target_date,
        status=RepairStatus.ACCEPTED.value,
    )
    db.add(repair)
    db.flush()
    repair.repair_reference = f"REP-{repair.opened_at:%Y}-{repair.id:06d}"
    machine.status = MachineStatus.REPAIR.value
    event = RepairEvent(
        repair_id=repair.id,
        event_type=RepairEventType.ACCEPTED.value,
        status_after=repair.status,
        description=payload.reported_problem,
        user_id=user.id,
    )
    db.add(event)
    add_machine_event(
        db, machine, user, "REPAIR_ACCEPTED", reference=repair.repair_reference,
        previous_status=previous_status, new_status=machine.status,
        details={"repair_id": repair.id},
    )
    add_audit_log(db, user, "repair", repair.id, "Създаден вътрешен ремонт", {"repair_reference": repair.repair_reference, "machine_number": machine.inventory_number, "previous_status": previous_status, "new_status": machine.status})
    _commit(db)
    return _repair_dict(_load_repair(db, repair.id))


@router.patch("/repair-cases/{repair_id}")
def update_repair_case(
    repair_id: int,
    payload: RepairCaseUpdate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> dict:
    if payload.status == RepairStatus.COMPLETED:
        ensure_permission(user, Permission.REPAIRS_COMPLETE)
    repair = _load_repair(db, repair_id, lock=True)
    previous_status = repair.status
    previous_machine_status = repair.machine.status
    if previous_status == RepairStatus.COMPLETED.value:
        changed_fields = payload.model_dump(
            exclude_unset=True,
            exclude={"status", "advance_to_final", "inspection_complete", "cleaning_complete"},
        )
        requested_status = payload.status.value if payload.status is not None else None
        if changed_fields or (requested_status not in {None, RepairStatus.COMPLETED.value}):
            raise business_conflict(
                "completed_repair_is_locked",
                "Приключеният ремонт е заключен. Използвайте корекция на протокола.",
            )
        return _repair_dict(repair)
    data = payload.model_dump(
        exclude_unset=True,
        exclude={"status", "advance_to_final", "inspection_complete", "cleaning_complete"},
    )
    for key, value in data.items():
        setattr(repair, key, value)
    if payload.inspection_complete and repair.inspection_completed_at is None:
        repair.inspection_completed_at = utcnow()
    if payload.cleaning_complete and repair.cleaning_completed_at is None:
        repair.cleaning_completed_at = utcnow()
    transition_event_type: str | None = None
    previous_location_id = repair.machine.location_id
    if payload.status is not None and payload.status.value != repair.status:
        transition_event_type, previous_location_id = apply_repair_transition(
            db, repair, payload.status.value, user
        )
    if payload.advance_to_final:
        if repair.status != RepairStatus.REPAIRING.value:
            raise business_conflict(
                "repair_finalization_stage_unavailable",
                "Финалната проверка може да бъде отворена само след етап „В ремонт“.",
                current_status=repair.status,
            )
        ensure_repair_can_start_finalization(repair)
        transition_event_type = RepairEventType.REPAIR_ACTION.value
    event = RepairEvent(
        repair_id=repair.id,
        event_type=transition_event_type or RepairEventType.NOTE.value,
        status_before=previous_status,
        status_after=repair.status,
        description=(
            "Отворена е финалната проверка на ремонта"
            if payload.advance_to_final
            else "Променен етап на ремонта"
            if transition_event_type
            else "Записана ремонтна карта"
        ),
        structured_data={
            **{
                key: value
                for key, value in payload.model_dump(mode="json", exclude_unset=True).items()
                if key not in {"test_details", "diagnosis", "work_performed", "result", "condition_after", "advance_to_final"}
            },
            **({"wizard_stage": "COMPLETION"} if payload.advance_to_final else {}),
        },
        user_id=user.id,
    )
    db.add(event)
    generated_on_completion: list[GeneratedDocument] = []
    if transition_event_type == RepairEventType.COMPLETED.value:
        generated_on_completion = generate_completion_documents_or_rollback(
            db, repair, user
        )
        db.add(
            RepairEvent(
                repair_id=repair.id,
                event_type=RepairEventType.DOCUMENT_GENERATED.value,
                status_before=repair.status,
                status_after=repair.status,
                description="Генериран официален ремонтен протокол",
                structured_data={
                    "document_ids": [item.id for item in generated_on_completion],
                },
                user_id=user.id,
            )
        )
    if previous_machine_status != repair.machine.status:
        add_machine_event(
            db, repair.machine, user, "REPAIR_STATUS_CHANGED", reference=repair.repair_reference,
            previous_status=previous_machine_status, new_status=repair.machine.status,
            previous_location_id=previous_location_id,
            new_location_id=repair.machine.location_id,
            details={
                "repair_id": repair.id,
                "repair_status": repair.status,
                "event_code": (
                    "MACHINE_READY"
                    if repair.status == RepairStatus.COMPLETED.value
                    else "REPAIR_STATUS_CHANGED"
                ),
            },
        )
    add_audit_log(db, user, "repair", repair.id, "Обновена ремонтна карта", {"repair_reference": repair.repair_reference, "previous_status": previous_status, "new_status": repair.status, "machine_previous_status": previous_machine_status, "machine_new_status": repair.machine.status, "completed_by_user_id": user.id if payload.status == RepairStatus.COMPLETED else None, "generated_document_ids": [item.id for item in generated_on_completion]})
    _commit(db)
    return _repair_dict(_load_repair(db, repair.id))


@router.post("/repair-cases/{repair_id}/events", status_code=201)
def add_repair_event(
    repair_id: int,
    payload: RepairEventCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> dict:
    if payload.next_status == RepairStatus.COMPLETED:
        ensure_permission(user, Permission.REPAIRS_COMPLETE)
    repair = _load_repair(db, repair_id, lock=True)
    if repair.status == RepairStatus.COMPLETED.value:
        raise business_conflict(
            "completed_repair_is_locked",
            "Приключеният ремонт е заключен. Използвайте корекция на протокола.",
        )
    previous = repair.status
    old_machine_status = repair.machine.status
    previous_location_id = repair.machine.location_id
    generated_on_completion: list[GeneratedDocument] = []
    if payload.next_status is not None and payload.next_status.value != repair.status:
        _, previous_location_id = apply_repair_transition(
            db, repair, payload.next_status.value, user
        )
    event = RepairEvent(
        repair_id=repair.id,
        event_type=payload.event_type.value,
        status_before=previous,
        status_after=repair.status,
        description=payload.description,
        structured_data=payload.structured_data,
        user_id=user.id,
    )
    db.add(event)
    db.flush()
    if payload.next_status == RepairStatus.COMPLETED:
        generated_on_completion = generate_completion_documents_or_rollback(
            db, repair, user
        )
        db.add(
            RepairEvent(
                repair_id=repair.id,
                event_type=RepairEventType.DOCUMENT_GENERATED.value,
                status_before=repair.status,
                status_after=repair.status,
                description="Генериран официален ремонтен протокол",
                structured_data={
                    "document_ids": [item.id for item in generated_on_completion],
                },
                user_id=user.id,
            )
        )
    if (
        old_machine_status != repair.machine.status
        or previous_location_id != repair.machine.location_id
    ):
        add_machine_event(
            db,
            repair.machine,
            user,
            "REPAIR_EVENT",
            reference=repair.repair_reference,
            previous_status=old_machine_status,
            new_status=repair.machine.status,
            previous_location_id=previous_location_id,
            new_location_id=repair.machine.location_id,
            details={"event_type": payload.event_type.value},
        )
    add_audit_log(db, user, "repair_event", event.id, "Добавено събитие към ремонта", {"repair_reference": repair.repair_reference, "event_type": event.event_type, "previous_status": previous, "new_status": repair.status, "completed_by_user_id": user.id if generated_on_completion else None, "generated_document_ids": [item.id for item in generated_on_completion]})
    _commit(db)
    return {"id": event.id, "event_type": event.event_type, "status_before": event.status_before, "status_after": event.status_after, "description": event.description, "structured_data": event.structured_data, "user_id": event.user_id, "created_at": event.created_at}


@router.post("/repair-cases/{repair_id}/participants", status_code=201)
def add_repair_participant(
    repair_id: int,
    payload: RepairParticipantCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> dict:
    repair = _load_repair(db, repair_id, lock=True)
    if repair.status == RepairStatus.COMPLETED.value:
        raise business_conflict(
            "completed_repair_is_locked",
            "Не могат да се добавят участници към приключен ремонт.",
        )
    linked_user = db.get(User, payload.user_id) if payload.user_id is not None else None
    if payload.user_id is not None and (linked_user is None or not linked_user.is_active):
        raise HTTPException(404, "Потребителят не е намерен или не е активен.")
    full_name = linked_user.full_name if linked_user else (payload.full_name or "")
    job_title = linked_user.job_title if linked_user else payload.job_title
    normalized = " ".join(full_name.casefold().split())
    identity_key = (
        f"user:{linked_user.id}"
        if linked_user
        else f"name:{normalized}"
    )
    if any(" ".join(item.full_name_snapshot.casefold().split()) == normalized for item in repair.participants):
        raise business_conflict(
            "repair_participant_already_exists",
            "Този участник вече е добавен към ремонта.",
        )
    participant = RepairParticipant(
        repair_id=repair.id,
        user_id=linked_user.id if linked_user else None,
        full_name_snapshot=full_name,
        job_title_snapshot=job_title,
        contribution=payload.contribution,
        minutes_worked=payload.minutes_worked,
        identity_key=identity_key,
        created_by_id=user.id,
    )
    db.add(participant)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise business_conflict(
            "repair_participant_already_exists",
            "Този участник вече е добавен към ремонта.",
        ) from exc
    db.add(
        RepairEvent(
            repair_id=repair.id,
            event_type=RepairEventType.PARTICIPANT_ADDED.value,
            status_before=repair.status,
            status_after=repair.status,
            description=full_name,
            structured_data={
                "participant_id": participant.id,
                "job_title": job_title,
                "contribution": payload.contribution,
                "minutes_worked": payload.minutes_worked,
            },
            user_id=user.id,
        )
    )
    add_audit_log(
        db, user, "repair_participant", participant.id,
        "Добавен участник във вътрешен ремонт",
        {
            "repair_id": repair.id,
            "repair_reference": repair.repair_reference,
            "full_name": full_name,
            "minutes_worked": payload.minutes_worked,
        },
        repair.repair_reference,
    )
    _commit(db)
    return _repair_participant_dict(participant)


@router.delete("/repair-cases/{repair_id}/participants/{participant_id}", status_code=204)
def remove_repair_participant(
    repair_id: int,
    participant_id: int,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> Response:
    repair = _load_repair(db, repair_id, lock=True)
    if repair.status == RepairStatus.COMPLETED.value:
        raise business_conflict(
            "completed_repair_is_locked",
            "Не могат да се премахват участници от приключен ремонт.",
        )
    participant = db.get(RepairParticipant, participant_id)
    if participant is None or participant.repair_id != repair.id:
        raise HTTPException(404, "Участникът не е намерен.")
    snapshot = _repair_participant_dict(participant)
    db.add(
        RepairEvent(
            repair_id=repair.id,
            event_type=RepairEventType.PARTICIPANT_REMOVED.value,
            status_before=repair.status,
            status_after=repair.status,
            description=participant.full_name_snapshot,
            structured_data={"participant_id": participant.id},
            user_id=user.id,
        )
    )
    db.delete(participant)
    add_audit_log(
        db, user, "repair_participant", participant_id,
        "Премахнат участник от вътрешен ремонт",
        {"repair_id": repair.id, "participant": snapshot},
        repair.repair_reference,
    )
    _commit(db)
    return Response(status_code=204)


@router.post("/repair-cases/{repair_id}/parts", status_code=201, response_model=None)
def add_repair_part(
    repair_id: int,
    payload: RepairPartCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> RepairPart:
    repair = _load_repair(db, repair_id, lock=True)
    if repair.status == RepairStatus.COMPLETED.value:
        raise business_conflict("repair_is_closed", "Към завършен ремонт не могат да се добавят части.")
    values = payload.model_dump()
    if payload.catalog_part_id is not None:
        catalog_part = db.get(PartCatalog, payload.catalog_part_id)
        if catalog_part is None:
            raise HTTPException(404, "Частта от каталога не е намерена.")
        if not catalog_part.is_verified or not catalog_part.is_active:
            raise business_conflict(
                "unverified_catalog_part",
                "Непотвърдена каталожна част не може да бъде отчетена като използвана.",
                part_number=catalog_part.part_number,
            )
        compatible_numbers = {
            str(value) for value in (catalog_part.compatible_machine_numbers or [])
        }
        if str(repair.machine.inventory_number) not in compatible_numbers:
            raise business_conflict(
                "catalog_part_not_compatible_with_machine",
                "Избраната каталожна част не е потвърдена като съвместима с машината от ремонта.",
                machine_number=repair.machine.inventory_number,
                catalog_part_id=catalog_part.id,
                part_number=catalog_part.part_number,
            )
        values.update(
            {
                "part_number": catalog_part.part_number,
                "description": catalog_part.description,
                "unit": catalog_part.unit,
                "source": (
                    f"{catalog_part.source_document}, стр. {catalog_part.source_page}"
                    if catalog_part.source_document and catalog_part.source_page
                    else catalog_part.source_document
                ),
            }
        )
    item = RepairPart(repair_id=repair.id, created_by_id=user.id, **values)
    db.add(item)
    db.flush()
    db.add(RepairEvent(repair_id=repair.id, event_type=RepairEventType.PART_ADDED.value, status_before=repair.status, status_after=repair.status, description=item.description, structured_data={"catalog_part_id": item.catalog_part_id, "part_number": item.part_number, "quantity": item.quantity, "unit": item.unit, "source": item.source}, user_id=user.id))
    add_audit_log(db, user, "repair_part", item.id, "Добавена използвана част", {"repair_reference": repair.repair_reference, "catalog_part_id": item.catalog_part_id, "part_number": item.part_number, "quantity": item.quantity, "unit": item.unit, "source": item.source})
    _commit(db)
    db.refresh(item)
    return item


@router.post("/repair-cases/{repair_id}/attachments", status_code=201)
def add_repair_attachment(
    repair_id: int,
    payload: AttachmentCreate,
    user: User = Depends(require_repair_operator),
    db: Session = Depends(get_db),
) -> dict:
    repair = _load_repair(db, repair_id, lock=True)
    if repair.status == RepairStatus.COMPLETED.value:
        raise business_conflict(
            "repair_is_closed",
            "Към завършен ремонт не могат да се добавят файлове.",
        )
    filename, content = _decode_file(payload)
    item = RepairAttachment(repair_id=repair.id, stage=payload.stage, filename=filename, media_type=payload.media_type, content=content, sha256=hashlib.sha256(content).hexdigest(), caption=payload.description, created_by_id=user.id)
    db.add(item)
    db.flush()
    db.add(RepairEvent(repair_id=repair.id, event_type=RepairEventType.ATTACHMENT_ADDED.value, status_before=repair.status, status_after=repair.status, description="Добавен файл към ремонтната карта", structured_data={"filename": filename, "stage": payload.stage, "sha256": item.sha256}, user_id=user.id))
    add_audit_log(db, user, "repair_attachment", item.id, "Добавен файл към ремонта", {"repair_reference": repair.repair_reference, "filename": filename, "stage": payload.stage, "sha256": item.sha256})
    _commit(db)
    return _attachment_dict(item, "repair")


@router.get("/repair-attachments/{attachment_id}/download")
def download_repair_attachment(
    attachment_id: int,
    _: User = Depends(require_repair_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(RepairAttachment, attachment_id)
    if item is None:
        raise HTTPException(404, "Файлът не е намерен.")
    return Response(item.content, media_type=item.media_type, headers={"Content-Disposition": f'attachment; filename="{item.filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/part-requests/multi")
def list_multi_part_requests(
    _: User = Depends(require_request_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    requests = db.scalars(
        select(PartRequest)
        .options(joinedload(PartRequest.machine), joinedload(PartRequest.repair), joinedload(PartRequest.requested_by), joinedload(PartRequest.decided_by), selectinload(PartRequest.lines).selectinload(PartRequestLine.linked_catalog_part), selectinload(PartRequest.approvals).joinedload(PartRequestApproval.decided_by), selectinload(PartRequest.attachments))
        .order_by(PartRequest.created_at.desc())
    ).all()
    documents = db.scalars(select(GeneratedDocument).where(GeneratedDocument.part_request_id.in_([item.id for item in requests]))) .all() if requests else []
    by_request: dict[int, list[GeneratedDocument]] = {}
    for document in documents:
        by_request.setdefault(document.part_request_id or 0, []).append(document)
    return [_part_request_dict(item, by_request.get(item.id, [])) for item in requests]


@router.get(
    "/part-requests/pending-action-count",
    response_model=PartRequestPendingActionCountOut,
)
def get_part_request_pending_action_count(
    user: User = Depends(require_request_viewer), db: Session = Depends(get_db)
) -> dict[str, int]:
    return {"pending_action_count": pending_action_count(db, user)}


@router.post("/part-requests/multi", status_code=201)
def create_multi_part_request(
    payload: MultiPartRequestCreate,
    user: User = Depends(require_parts_operator),
    db: Session = Depends(get_db),
) -> dict:
    repair = db.get(Repair, payload.repair_id) if payload.repair_id is not None else None
    if payload.repair_id is not None and repair is None:
        raise HTTPException(404, "Ремонтът не е намерен.")
    resolved_machine_id = payload.machine_id or (repair.machine_id if repair else None)
    machine = db.get(Machine, resolved_machine_id) if resolved_machine_id is not None else None
    if payload.machine_id is not None and machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    if repair is not None and machine is not None and repair.machine_id != machine.id:
        raise business_conflict(
            "part_request_repair_machine_mismatch",
            "Избраните машина и ремонт не съответстват.",
            repair_id=repair.id,
            machine_id=machine.id,
        )
    unknown_lines = [line for line in payload.lines if line.is_unknown_part]
    if unknown_lines and machine is None:
        raise business_conflict(
            "unknown_part_machine_required",
            "За част без потвърден part number трябва да бъде избрана конкретна машина.",
        )
    catalog_ids = {line.catalog_part_id for line in payload.lines if line.catalog_part_id is not None}
    catalog_parts: dict[int, PartCatalog] = {}
    if catalog_ids:
        catalog_parts = {
            item.id: item
            for item in db.scalars(
                select(PartCatalog).where(PartCatalog.id.in_(catalog_ids))
            ).all()
        }
        if set(catalog_parts) != catalog_ids:
            raise HTTPException(404, "Една или повече каталожни части не са намерени.")
        unverified = [
            item.part_number
            for item in catalog_parts.values()
            if not item.is_verified or not item.is_active
        ]
        if unverified:
            raise business_conflict(
                "unverified_catalog_parts",
                "Непотвърдена каталожна част не може да бъде добавена към официална заявка.",
                part_numbers=sorted(unverified),
            )
        if machine is not None:
            incompatible = [
                item.part_number
                for item in catalog_parts.values()
                if str(machine.inventory_number)
                not in {str(value) for value in (item.compatible_machine_numbers or [])}
            ]
            if incompatible:
                raise business_conflict(
                    "catalog_parts_not_compatible_with_machine",
                    "Една или повече каталожни части не са потвърдени за избраната машина.",
                    machine_number=machine.inventory_number,
                    part_numbers=sorted(incompatible),
                )
    kit: RepairKit | None = None
    if payload.repair_kit_id is not None:
        kit = db.scalar(
            select(RepairKit)
            .options(selectinload(RepairKit.components))
            .where(RepairKit.id == payload.repair_kit_id)
        )
        if kit is None:
            raise HTTPException(404, "Ремонтният комплект не е намерен.")
        if not kit.is_approved or not kit.is_active:
            raise business_conflict(
                "repair_kit_not_approved",
                "Непотвърден ремонтен комплект не може да бъде използван в официална заявка.",
                repair_kit_id=kit.id,
            )
        if payload.repair_kit_mode == "KIT":
            if len(payload.lines) != 1 or catalog_ids:
                raise business_conflict(
                    "repair_kit_single_line_invalid",
                    "Комплектът като общ ред трябва да бъде подаден точно веднъж.",
                    repair_kit_id=kit.id,
                )
        else:
            component_by_part = {component.part_id: component for component in kit.components}
            if any(line.catalog_part_id is None for line in payload.lines) or not catalog_ids.issubset(component_by_part):
                raise business_conflict(
                    "repair_kit_component_mismatch",
                    "Редовете на заявката не съответстват на избрания ремонтен комплект.",
                    repair_kit_id=kit.id,
                )
            missing_required = sorted(
                component.part_id
                for component in kit.components
                if not component.is_optional and component.part_id not in catalog_ids
            )
            if missing_required:
                raise business_conflict(
                    "repair_kit_required_components_missing",
                    "Липсват задължителни компоненти от ремонтния комплект.",
                    repair_kit_id=kit.id,
                    missing_part_ids=missing_required,
                )
    first = payload.lines[0]
    first_catalog = catalog_parts.get(first.catalog_part_id) if first.catalog_part_id else None
    first_name = kit.name if kit and payload.repair_kit_mode == "KIT" else first_catalog.description if first_catalog else first.description
    first_number = kit.code if kit and payload.repair_kit_mode == "KIT" else (first_catalog.replaced_by_part_number or first_catalog.part_number) if first_catalog else first.part_number
    request_item = PartRequest(machine_id=resolved_machine_id, repair_id=payload.repair_id, repair_kit_id=payload.repair_kit_id, repair_kit_mode=payload.repair_kit_mode if kit else None, part_name=first_name, part_number=first_number, quantity=max(1, int(first.quantity)), reason=payload.reason, department=payload.department, priority=payload.priority.value, status=PartRequestStatus.DRAFT.value, language=payload.language.value, requested_by_id=user.id)
    db.add(request_item)
    db.flush()
    request_item.request_reference = f"PR-{request_item.created_at:%Y}-{request_item.id:06d}"
    for line in payload.lines:
        values = line.model_dump()
        if kit and payload.repair_kit_mode == "KIT":
            values.update(
                {
                    "catalog_part_id": None,
                    "position": None,
                    "part_number": kit.code,
                    "description": kit.name,
                    "unit": {"bg": "комплект", "en": "kit", "ru": "комплект"}[
                        payload.language.value
                    ],
                    "source_document": kit.source_document,
                    "source_page": kit.source_page,
                }
            )
        elif line.catalog_part_id is not None:
            part = catalog_parts[line.catalog_part_id]
            values.update(
                {
                    "position": part.position,
                    "part_number": part.replaced_by_part_number or part.part_number,
                    "description": part.description,
                    "unit": part.unit,
                    "source_document": part.source_document,
                    "source_page": part.source_page,
                }
            )
        db.add(PartRequestLine(request_id=request_item.id, **values))
    add_audit_log(db, user, "part_request", request_item.id, "Създадена многоредова заявка за части", {"request_reference": request_item.request_reference, "machine_number": machine.inventory_number if machine else None, "repair_id": payload.repair_id, "repair_reference": repair.repair_reference if repair else None, "repair_kit_id": payload.repair_kit_id, "line_count": len(payload.lines), "catalog_part_ids": sorted(catalog_ids), "priority": request_item.priority})
    if payload.submit_for_approval:
        submit_for_approval(
            db, request_item, user, line_count=len(payload.lines)
        )
    _commit(db)
    item = load_request(db, request_item.id)
    assert item is not None
    return _part_request_dict(item, [])


@router.post("/part-requests/unknown", status_code=201)
def create_unknown_part_request(
    payload: UnknownPartRequestCreate,
    user: User = Depends(require_parts_operator),
    db: Session = Depends(get_db),
) -> dict:
    machine = db.get(Machine, payload.machine_id)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    repair = db.get(Repair, payload.repair_id) if payload.repair_id is not None else None
    if payload.repair_id is not None and repair is None:
        raise HTTPException(404, "Ремонтът не е намерен.")
    if repair is not None and repair.machine_id != machine.id:
        raise business_conflict(
            "unknown_part_repair_machine_mismatch",
            "Избраните машина и ремонт не съответстват.",
            repair_id=repair.id,
            machine_id=machine.id,
        )
    filename, content = _decode_file(payload.photo)
    if payload.photo.media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unknown_part_photo_required",
                "message": "За непознатата част трябва да бъде приложена снимка във формат JPEG, PNG или WebP.",
            },
        )
    request_item = PartRequest(
        machine_id=machine.id,
        repair_id=repair.id if repair else None,
        part_name="Част без потвърден part number",
        part_number=None,
        quantity=max(1, int(payload.quantity)),
        reason=payload.note,
        department=payload.department,
        priority=payload.priority.value,
        status=PartRequestStatus.DRAFT.value,
        language=payload.language.value,
        requested_by_id=user.id,
    )
    db.add(request_item)
    db.flush()
    request_item.request_reference = f"PR-{request_item.created_at:%Y}-{request_item.id:06d}"
    line = PartRequestLine(
        request_id=request_item.id,
        catalog_part_id=None,
        position=None,
        part_number=None,
        description=payload.description.strip(),
        quantity=payload.quantity,
        unit=payload.unit,
        reason=payload.note,
        is_unknown_part=True,
        assembly=payload.assembly.strip(),
        note=payload.note,
    )
    db.add(line)
    db.flush()
    attachment = PartRequestAttachment(
        request_id=request_item.id,
        request_line_id=line.id,
        filename=filename,
        media_type=payload.photo.media_type,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        description="Снимка на част без потвърден part number",
        created_by_id=user.id,
    )
    db.add(attachment)
    db.flush()
    add_audit_log(
        db, user, "part_request", request_item.id,
        "Създадена заявка за част без потвърден part number",
        {
            "request_reference": request_item.request_reference,
            "machine_number": machine.inventory_number,
            "repair_id": repair.id if repair else None,
            "line_id": line.id,
            "assembly": line.assembly,
            "quantity": line.quantity,
            "photo_sha256": attachment.sha256,
            "catalog_inserted": False,
        },
        request_item.request_reference,
    )
    _commit(db)
    item = db.scalar(
        select(PartRequest)
        .options(
            joinedload(PartRequest.machine),
            joinedload(PartRequest.repair),
            selectinload(PartRequest.lines).selectinload(PartRequestLine.linked_catalog_part),
            selectinload(PartRequest.approvals),
            selectinload(PartRequest.attachments),
        )
        .where(PartRequest.id == request_item.id)
    )
    assert item is not None
    return _part_request_dict(item, [])


@router.post("/part-requests/{request_id}/lines/{line_id}/link-catalog-part")
def link_unknown_part_to_catalog(
    request_id: int,
    line_id: int,
    payload: UnknownPartCatalogLink,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    request_item = db.scalar(
        select(PartRequest)
        .options(
            joinedload(PartRequest.machine),
            joinedload(PartRequest.repair),
            selectinload(PartRequest.lines).selectinload(PartRequestLine.linked_catalog_part),
            selectinload(PartRequest.approvals),
            selectinload(PartRequest.attachments),
        )
        .where(PartRequest.id == request_id)
    )
    if request_item is None:
        raise HTTPException(404, "Заявката не е намерена.")
    line = next((value for value in request_item.lines if value.id == line_id), None)
    if line is None:
        raise HTTPException(404, "Редът на заявката не е намерен.")
    if not line.is_unknown_part:
        raise business_conflict(
            "part_request_line_is_not_unknown",
            "Само част без потвърден part number може да бъде свързана по този начин.",
            line_id=line.id,
        )
    part = db.get(PartCatalog, payload.catalog_part_id)
    if part is None:
        raise HTTPException(404, "Каталожната част не е намерена.")
    if not part.is_verified or not str(part.verification_status or "").startswith("VERIFIED") or not part.is_active:
        raise business_conflict(
            "catalog_part_not_verified_for_link",
            "Непозната част може да бъде свързана само с активна и потвърдена каталожна част.",
            catalog_part_id=part.id,
            part_number=part.part_number,
        )
    if request_item.machine is not None:
        compatible_numbers = {str(value) for value in (part.compatible_machine_numbers or [])}
        if str(request_item.machine.inventory_number) not in compatible_numbers:
            raise business_conflict(
                "catalog_part_not_compatible_with_machine",
                "Избраната каталожна част не е потвърдена като съвместима с машината от заявката.",
                machine_number=request_item.machine.inventory_number,
                catalog_part_id=part.id,
            )
    if line.linked_catalog_part_id == part.id:
        return _part_request_dict(request_item, [])
    if line.linked_catalog_part_id is not None:
        raise business_conflict(
            "unknown_part_already_linked",
            "Тази непозната част вече е свързана с каталожна част.",
            line_id=line.id,
            linked_catalog_part_id=line.linked_catalog_part_id,
        )
    line.linked_catalog_part_id = part.id
    line.linked_by_id = user.id
    line.linked_at = utcnow()
    line.link_note = payload.note
    add_audit_log(
        db, user, "part_request_line", line.id,
        "Част без потвърден part number е свързана с потвърдена каталожна част",
        {
            "request_reference": request_item.request_reference,
            "machine_number": request_item.machine.inventory_number if request_item.machine else None,
            "original_description": line.description,
            "assembly": line.assembly,
            "catalog_part_id": part.id,
            "part_number": part.part_number,
            "source_document": part.source_document,
            "source_page": part.source_page,
            "note": payload.note,
        },
        request_item.request_reference,
    )
    _commit(db)
    db.refresh(line)
    refreshed = db.scalar(
        select(PartRequest)
        .options(
            joinedload(PartRequest.machine),
            joinedload(PartRequest.repair),
            selectinload(PartRequest.lines).selectinload(PartRequestLine.linked_catalog_part),
            selectinload(PartRequest.approvals),
            selectinload(PartRequest.attachments),
        )
        .where(PartRequest.id == request_id)
    )
    assert refreshed is not None
    return _part_request_dict(refreshed, [])


@router.post("/part-requests/{request_id}/attachments", status_code=201)
def add_part_request_attachment(
    request_id: int,
    payload: AttachmentCreate,
    user: User = Depends(require_parts_operator),
    db: Session = Depends(get_db),
) -> dict:
    request_item = db.get(PartRequest, request_id)
    if request_item is None:
        raise HTTPException(404, "Заявката не е намерена.")
    filename, content = _decode_file(payload)
    item = PartRequestAttachment(
        request_id=request_item.id,
        filename=filename,
        media_type=payload.media_type,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        description=payload.description,
        created_by_id=user.id,
    )
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        user,
        "part_request_attachment",
        item.id,
        "Добавено приложение към заявка за резервни части",
        {
            "request_reference": request_item.request_reference,
            "filename": filename,
            "sha256": item.sha256,
        },
        request_item.request_reference,
    )
    _commit(db)
    return _attachment_dict(item, "part-request")


@router.get("/part-request-attachments/{attachment_id}/download")
def download_part_request_attachment(
    attachment_id: int,
    _: User = Depends(require_request_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(PartRequestAttachment, attachment_id)
    if item is None:
        raise HTTPException(404, "Приложението към заявката не е намерено.")
    return Response(
        item.content,
        media_type=item.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{item.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/part-requests/{request_id}/submit")
def submit_part_request(
    request_id: int,
    user: User = Depends(require_parts_operator),
    db: Session = Depends(get_db),
) -> dict:
    item = load_request(db, request_id, lock=True)
    if item is None:
        raise HTTPException(404, "Заявката не е намерена.")
    submit_for_approval(db, item, user)
    _commit(db)
    return _part_request_dict(item, [])


@router.post("/part-requests/{request_id}/decision")
def decide_part_request(
    request_id: int,
    payload: PartRequestDecision,
    user: User = Depends(require_request_approver),
    db: Session = Depends(get_db),
) -> dict:
    item = load_request(db, request_id, lock=True)
    if item is None:
        raise HTTPException(404, "Заявката не е намерена.")
    decide_request(db, item, user, payload.decision, payload.note)
    _commit(db)
    db.refresh(item)
    return _part_request_dict(item, [])


@router.patch("/part-requests/{request_id}/fulfillment")
def update_part_request_fulfillment(
    request_id: int,
    payload: PartRequestFulfillmentUpdate,
    user: User = Depends(require_parts_operator),
    db: Session = Depends(get_db),
) -> dict:
    item = load_request(db, request_id, lock=True)
    if item is None:
        raise HTTPException(404, "Заявката не е намерена.")
    allowed = {
        PartRequestStatus.APPROVED.value: {
            PartRequestStatus.ORDERED.value,
            PartRequestStatus.CANCELLED.value,
        },
        PartRequestStatus.ORDERED.value: {
            PartRequestStatus.PARTIALLY_DELIVERED.value,
            PartRequestStatus.DELIVERED.value,
            PartRequestStatus.CANCELLED.value,
        },
        PartRequestStatus.PARTIALLY_DELIVERED.value: {
            PartRequestStatus.PARTIALLY_DELIVERED.value,
            PartRequestStatus.DELIVERED.value,
            PartRequestStatus.CANCELLED.value,
        },
    }
    next_status = payload.status
    if next_status not in allowed.get(item.status, set()):
        raise business_conflict(
            "invalid_part_request_status_transition",
            "Преходът на заявката към избрания статус не е разрешен.",
            current_status=item.status,
            requested_status=next_status,
        )
    lines_by_id = {line.id: line for line in item.lines}
    requested_ids = {line.line_id for line in payload.lines}
    if not requested_ids.issubset(lines_by_id):
        raise business_conflict(
            "part_request_line_mismatch",
            "Подаден е ред, който не принадлежи към тази заявка.",
        )
    previous_quantities = {
        line.id: line.delivered_quantity for line in item.lines
    }
    for update in payload.lines:
        line = lines_by_id[update.line_id]
        if update.delivered_quantity < line.delivered_quantity or update.delivered_quantity > line.quantity:
            raise business_conflict(
                "invalid_delivered_quantity",
                "Доставеното количество не може да намалява или да надвишава заявеното.",
                line_id=line.id,
                requested_quantity=line.quantity,
                current_delivered_quantity=line.delivered_quantity,
            )
        line.delivered_quantity = update.delivered_quantity
    delivered_total = sum(line.delivered_quantity for line in item.lines)
    ordered_total = sum(line.quantity for line in item.lines)
    if next_status == PartRequestStatus.PARTIALLY_DELIVERED.value and not (0 < delivered_total < ordered_total):
        raise business_conflict(
            "partial_delivery_quantities_invalid",
            "Частична доставка изисква количество над нула и под общото заявено количество.",
        )
    if next_status == PartRequestStatus.DELIVERED.value and any(
        line.delivered_quantity != line.quantity for line in item.lines
    ):
        raise business_conflict(
            "delivery_incomplete",
            "Заявката може да бъде отбелязана като доставена само когато всички количества са получени.",
        )
    previous_status = item.status
    item.status = next_status
    if payload.supplier is not None:
        item.supplier = payload.supplier
    if payload.note is not None:
        item.delivery_note = payload.note
    if next_status == PartRequestStatus.ORDERED.value and item.ordered_at is None:
        item.ordered_at = utcnow()
    if next_status == PartRequestStatus.DELIVERED.value:
        item.delivered_at = utcnow()
    add_audit_log(
        db,
        user,
        "part_request",
        item.id,
        "Обновено изпълнение на заявка за части",
        {
            "request_reference": item.request_reference,
            "previous_status": previous_status,
            "new_status": item.status,
            "supplier": item.supplier,
            "previous_delivered_quantities": previous_quantities,
            "new_delivered_quantities": {
                line.id: line.delivered_quantity for line in item.lines
            },
        },
        item.request_reference,
    )
    _commit(db)
    return _part_request_dict(item, [])


@router.post("/part-requests/{request_id}/documents", status_code=201)
def generate_part_request_documents(
    request_id: int,
    language: str | None = Query(default=None, pattern=r"^(bg|en|ru)$"),
    user: User = Depends(require_document_generator),
    db: Session = Depends(get_db),
) -> dict:
    with part_request_document_generation_guard(db):
        item = load_request(db, request_id, lock=True)
        if item is None:
            raise HTTPException(404, "Заявката не е намерена.")
        canonical_number = item.request_reference or f"PR-{item.id:06d}"
        existing_documents = db.scalars(
            select(GeneratedDocument)
            .where(
                GeneratedDocument.part_request_id == item.id,
                GeneratedDocument.document_type == DocumentType.PART_REQUEST.value,
            )
            .order_by(GeneratedDocument.id)
        ).all()
        existing_official = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == canonical_number
            )
        )
        if existing_documents or existing_official is not None:
            raise business_conflict(
                "part_request_protocol_already_generated",
                "Официалният протокол за тази заявка вече е генериран.",
                request_reference=item.request_reference,
                document_number=(
                    existing_documents[0].document_number
                    if existing_documents
                    else canonical_number
                ),
                documents=[
                    {
                        "id": document.id,
                        "format": document.format,
                        "filename": document.filename,
                        "download_endpoint": f"/generated-documents/{document.id}/download",
                    }
                    for document in existing_documents
                ],
                official_document_id=(
                    existing_official.id if existing_official is not None else None
                ),
            )
        if item.status == PartRequestStatus.CANCELLED.value:
            raise business_conflict(
                "part_request_cancelled_no_protocol_generation",
                "За отказана заявка не може да бъде създаден нов официален протокол.",
                request_reference=item.request_reference,
                current_status=item.status,
            )
        if item.status not in OFFICIAL_DOCUMENT_STATUSES:
            raise business_conflict(
                "part_request_not_approved",
                "Официален документ може да бъде създаден само след одобрение на заявката.",
                request_reference=item.request_reference,
                current_status=item.status,
            )
        document_language = language or item.language
        try:
            documents = make_part_request_documents(
                db, item, user.id, document_language
            )
        except ConfirmedTemplateUnavailableError as exc:
            raise business_conflict(
                "document_template_unavailable",
                exc.message,
                document_type=exc.document_type,
                requested_language=exc.language,
                fallback_language="bg",
            ) from exc
        except TemplateValidationError as exc:
            raise business_conflict(
                "document_generation_validation_failed", str(exc)
            ) from exc
        db.add_all(documents)
        db.flush()
        add_audit_log(
            db,
            user,
            "part_request",
            item.id,
            "Генериран документ за заявка за части",
            {
                "request_reference": item.request_reference,
                "language": document_language,
                "generated_document_ids": [document.id for document in documents],
                "document_number": documents[0].document_number,
            },
            item.request_reference,
        )
        _commit(db)
        return {
            "document_number": documents[0].document_number,
            "documents": [
                {
                    "id": document.id,
                    "format": document.format,
                    "filename": document.filename,
                    "sha256": document.sha256,
                    "download_endpoint": f"/generated-documents/{document.id}/download",
                }
                for document in documents
            ],
        }


def _matching_catalog_part_id(
    db: Session, payload: CatalogPartCreate | CatalogPartUpdate
) -> int | None:
    return db.scalar(
        select(PartCatalog.id).where(
            PartCatalog.brand == payload.brand,
            PartCatalog.model == payload.model,
            PartCatalog.assembly == payload.assembly,
            PartCatalog.position == payload.position,
            PartCatalog.part_number == payload.part_number,
        )
    )


def _validate_catalog_part_payload(
    db: Session,
    payload: CatalogPartCreate | CatalogPartUpdate,
    *,
    current_part_id: int | None = None,
) -> None:
    numbers = set(payload.compatible_machine_numbers or [])
    if numbers:
        found = set(
            db.scalars(
                select(Machine.inventory_number).where(Machine.inventory_number.in_(numbers))
            ).all()
        )
        missing = sorted(numbers - found)
        if missing:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "compatible_machines_not_found",
                    "message": "Една или повече съвместими машини не са намерени в регистъра.",
                    "machine_numbers": missing,
                },
            )
    replacement_ids = set(payload.replacement_part_ids or [])
    if current_part_id is not None and current_part_id in replacement_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "catalog_self_replacement",
                "message": "Каталожната част не може да замества сама себе си.",
            },
        )
    if replacement_ids:
        found_ids = set(
            db.scalars(select(PartCatalog.id).where(PartCatalog.id.in_(replacement_ids))).all()
        )
        missing_ids = sorted(replacement_ids - found_ids)
        if missing_ids:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "replacement_parts_not_found",
                    "message": "Една или повече заместващи части не са намерени в каталога.",
                    "part_ids": missing_ids,
                },
            )


@router.post("/catalog/parts", status_code=201, response_model=None)
def create_catalog_part(
    payload: CatalogPartCreate,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> PartCatalog:
    _validate_catalog_part_payload(db, payload)
    if _matching_catalog_part_id(db, payload) is not None:
        raise business_conflict(
            "catalog_part_duplicate",
            "Вече съществува част със същия източник, позиция и номер.",
            part_number=payload.part_number,
        )
    item = PartCatalog(**payload.model_dump())
    db.add(item)
    db.flush()
    add_audit_log(db, user, "catalog_part", item.id, "Добавена част в каталога", {"part_number": item.part_number, "source_document": item.source_document, "source_page": item.source_page})
    _commit(db)
    db.refresh(item)
    return item


@router.put("/catalog/parts/{part_id}", response_model=None)
def update_catalog_part(
    part_id: int,
    payload: CatalogPartUpdate,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> PartCatalog:
    item = db.get(PartCatalog, part_id)
    if item is None:
        raise HTTPException(404, "Частта не е намерена.")
    _validate_catalog_part_payload(db, payload, current_part_id=item.id)
    duplicate_id = _matching_catalog_part_id(db, payload)
    if duplicate_id is not None and duplicate_id != item.id:
        raise business_conflict(
            "catalog_part_duplicate",
            "Вече съществува част със същия източник, позиция и номер.",
            part_number=payload.part_number,
        )
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    item.is_verified = False
    item.verified_by_id = None
    item.verified_at = None
    add_audit_log(db, user, "catalog_part", item.id, "Обновена каталожна част; необходима е нова проверка", {"part_number": item.part_number})
    _commit(db)
    return item


@router.post("/catalog/parts/{part_id}/verify", response_model=None)
def verify_catalog_part(
    part_id: int,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> PartCatalog:
    item = db.get(PartCatalog, part_id)
    if item is None:
        raise HTTPException(404, "Частта не е намерена.")
    if not item.source_document or item.source_page is None:
        raise business_conflict("part_provenance_missing", "Частта не може да бъде потвърдена без източник и страница.")
    item.is_verified = True
    item.verified_by_id = user.id
    item.verified_at = utcnow()
    add_audit_log(db, user, "catalog_part", item.id, "Потвърдена каталожна част", {"part_number": item.part_number, "source_document": item.source_document, "source_page": item.source_page})
    _commit(db)
    return item


@router.post("/catalog/parts/{part_id}/hotspots", status_code=201, response_model=None)
def create_part_hotspot(
    part_id: int,
    payload: HotspotCreate,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> PartHotspot:
    if db.get(PartCatalog, part_id) is None:
        raise HTTPException(404, "Частта не е намерена.")
    if payload.technical_document_id is not None and db.get(TechnicalDocument, payload.technical_document_id) is None:
        raise HTTPException(404, "Техническият документ не е намерен.")
    item = PartHotspot(part_id=part_id, created_by_id=user.id, **payload.model_dump())
    db.add(item)
    db.flush()
    add_audit_log(db, user, "part_hotspot", item.id, "Добавена визуална позиция на част", {"part_id": part_id, "page_number": item.page_number, "verified": False})
    _commit(db)
    db.refresh(item)
    return item


@router.get("/catalog/parts/{part_id}/images")
def list_catalog_part_images(
    part_id: int,
    _: User = Depends(require_parts_viewer),
    db: Session = Depends(get_db),
) -> list[dict]:
    if db.get(PartCatalog, part_id) is None:
        raise HTTPException(404, "Частта не е намерена.")
    items = db.scalars(
        select(PartCatalogImage)
        .where(PartCatalogImage.part_id == part_id)
        .order_by(PartCatalogImage.created_at.desc(), PartCatalogImage.id.desc())
    ).all()
    return [
        {
            "id": item.id,
            "filename": item.filename,
            "media_type": item.media_type,
            "sha256": item.sha256,
            "caption": item.caption,
            "created_at": item.created_at,
            "download_endpoint": f"/catalog/part-images/{item.id}/download",
        }
        for item in items
    ]


@router.post("/catalog/parts/{part_id}/images", status_code=201)
def add_catalog_part_image(
    part_id: int,
    payload: AttachmentCreate,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> dict:
    part = db.get(PartCatalog, part_id)
    if part is None:
        raise HTTPException(404, "Частта не е намерена.")
    filename, content = _decode_file(payload)
    if payload.media_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "catalog_part_image_required",
                "message": "Към каталожна част може да се качи само изображение.",
            },
        )
    item = PartCatalogImage(
        part_id=part.id,
        filename=filename,
        media_type=payload.media_type,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        caption=payload.description,
        created_by_id=user.id,
    )
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        user,
        "catalog_part_image",
        item.id,
        "Добавено изображение към каталожна част",
        {
            "part_id": part.id,
            "part_number": part.part_number,
            "filename": filename,
            "sha256": item.sha256,
        },
    )
    _commit(db)
    return {
        "id": item.id,
        "filename": item.filename,
        "media_type": item.media_type,
        "sha256": item.sha256,
        "caption": item.caption,
        "created_at": item.created_at,
        "download_endpoint": f"/catalog/part-images/{item.id}/download",
    }


@router.get("/catalog/part-images/{image_id}/download")
def download_catalog_part_image(
    image_id: int,
    _: User = Depends(require_parts_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(PartCatalogImage, image_id)
    if item is None:
        raise HTTPException(404, "Изображението не е намерено.")
    return Response(
        item.content,
        media_type=item.media_type,
        headers={
            "Content-Disposition": f'inline; filename="{item.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/catalog/parts/{part_id}/hotspots", response_model=None)
def list_part_hotspots(
    part_id: int,
    _: User = Depends(require_parts_viewer),
    db: Session = Depends(get_db),
) -> list[PartHotspot]:
    return db.scalars(select(PartHotspot).where(PartHotspot.part_id == part_id).order_by(PartHotspot.page_number, PartHotspot.id)).all()


@router.get("/catalog/hotspots", response_model=None)
def list_document_hotspots(
    technical_document_id: int,
    page_number: int = Query(ge=1),
    _: User = Depends(require_parts_viewer),
    db: Session = Depends(get_db),
) -> list[PartHotspot]:
    if db.get(TechnicalDocument, technical_document_id) is None:
        raise HTTPException(404, "Техническият документ не е намерен.")
    return db.scalars(
        select(PartHotspot)
        .where(
            PartHotspot.technical_document_id == technical_document_id,
            PartHotspot.page_number == page_number,
        )
        .order_by(PartHotspot.id)
    ).all()


@router.post("/catalog/hotspots/{hotspot_id}/verify", response_model=None)
def verify_part_hotspot(
    hotspot_id: int,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> PartHotspot:
    item = db.get(PartHotspot, hotspot_id)
    if item is None:
        raise HTTPException(404, "Визуалната позиция не е намерена.")
    if not item.provenance or item.technical_document_id is None:
        raise business_conflict(
            "hotspot_provenance_missing",
            "Визуалната позиция не може да бъде потвърдена без документ и описание на източника.",
        )
    item.is_verified = True
    add_audit_log(
        db,
        user,
        "part_hotspot",
        item.id,
        "Потвърдена визуална позиция на част",
        {
            "part_id": item.part_id,
            "technical_document_id": item.technical_document_id,
            "page_number": item.page_number,
        },
    )
    _commit(db)
    db.refresh(item)
    return item


@router.get("/repair-kits")
def list_repair_kits(
    _: User = Depends(require_parts_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    kits = db.scalars(select(RepairKit).options(selectinload(RepairKit.components).joinedload(RepairKitComponent.part)).where(RepairKit.is_active.is_(True)).order_by(RepairKit.name)).all()
    return [{"id": kit.id, "code": kit.code, "name": kit.name, "brand": kit.brand, "model": kit.model, "compatible_models": kit.compatible_models, "revision": kit.revision, "assembly": kit.assembly, "source_document": kit.source_document, "source_page": kit.source_page, "provenance": kit.provenance, "confidence": kit.confidence, "is_approved": kit.is_approved, "approved_by_id": kit.approved_by_id, "approved_at": kit.approved_at, "created_at": kit.created_at, "components": [{"id": component.id, "part_id": component.part_id, "part_number": component.part.part_number, "description": component.part.description, "quantity": component.quantity, "is_optional": component.is_optional, "note": component.note, "alternative_part_numbers": component.part.alternative_part_numbers, "replacement_part_ids": component.part.replacement_part_ids} for component in kit.components]} for kit in kits]


@router.post("/repair-kits", status_code=201)
def create_repair_kit(
    payload: RepairKitCreate,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(RepairKit.id).where(RepairKit.code == payload.code)) is not None:
        raise business_conflict(
            "repair_kit_code_exists",
            "Вече съществува ремонтен комплект с този код.",
            code=payload.code,
        )
    part_ids = {component.part_id for component in payload.components}
    if set(db.scalars(select(PartCatalog.id).where(PartCatalog.id.in_(part_ids))).all()) != part_ids:
        raise HTTPException(404, "Една или повече части не са намерени.")
    kit = RepairKit(code=payload.code, name=payload.name, brand=payload.brand, model=payload.model, compatible_models=payload.compatible_models, revision=payload.revision, assembly=payload.assembly, source_document=payload.source_document, source_page=payload.source_page, provenance=payload.provenance, confidence=payload.confidence, created_by_id=user.id)
    db.add(kit)
    db.flush()
    for component in payload.components:
        db.add(RepairKitComponent(kit_id=kit.id, **component.model_dump()))
    add_audit_log(db, user, "repair_kit", kit.id, "Създаден непотвърден ремонтен комплект", {"code": kit.code, "component_count": len(payload.components), "source_document": kit.source_document, "source_page": kit.source_page})
    _commit(db)
    return {"id": kit.id, "code": kit.code, "is_approved": kit.is_approved}


@router.post("/repair-kits/{kit_id}/approve")
def approve_repair_kit(
    kit_id: int,
    user: User = Depends(require_parts_manager),
    db: Session = Depends(get_db),
) -> dict:
    kit = db.scalar(select(RepairKit).options(selectinload(RepairKit.components).joinedload(RepairKitComponent.part)).where(RepairKit.id == kit_id))
    if kit is None:
        raise HTTPException(404, "Ремонтният комплект не е намерен.")
    if not kit.source_document or kit.source_page is None or not kit.provenance or kit.confidence is None or not kit.components:
        raise business_conflict("repair_kit_provenance_missing", "Комплектът не може да бъде одобрен без пълен източник, произход, увереност и състав.")
    unverified = sorted(
        component.part.part_number
        for component in kit.components
        if not component.part.is_verified
    )
    if unverified:
        raise business_conflict(
            "repair_kit_has_unverified_components",
            "Комплектът не може да бъде одобрен, докато съдържа непотвърдени части.",
            part_numbers=unverified,
        )
    kit.is_approved = True
    kit.approved_by_id = user.id
    kit.approved_at = utcnow()
    add_audit_log(db, user, "repair_kit", kit.id, "Одобрен ремонтен комплект от човек", {"code": kit.code, "confidence": kit.confidence})
    _commit(db)
    return {"id": kit.id, "code": kit.code, "is_approved": True, "approved_at": kit.approved_at}


@router.get("/technical-library")
def technical_library(
    q: str | None = None,
    brand: str | None = None,
    model: str | None = None,
    category: str | None = None,
    language: str | None = Query(default=None, pattern=r"^(bg|en|ru)$"),
    revision: str | None = None,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(TechnicalDocument).options(selectinload(TechnicalDocument.revisions)).where(TechnicalDocument.is_active.is_(True))
    if brand:
        statement = statement.where(TechnicalDocument.brand == brand)
    if model:
        statement = statement.where(TechnicalDocument.model == model)
    if category:
        statement = statement.where(TechnicalDocument.category == category)
    if language:
        statement = statement.where(TechnicalDocument.language == language)
    if revision:
        statement = statement.where(TechnicalDocument.revision.ilike(f"%{revision.strip()}%"))
    documents = db.scalars(statement.order_by(TechnicalDocument.brand, TechnicalDocument.category, TechnicalDocument.title)).all()
    if q:
        normalized = q.strip().casefold()
        matching_machine_numbers = set(
            db.scalars(
                select(Machine.inventory_number).where(
                    or_(
                        Machine.inventory_number.ilike(f"%{q.strip()}%"),
                        Machine.serial_number.ilike(f"%{q.strip()}%"),
                    )
                )
            ).all()
        )
        matching_sources = {
            source.casefold()
            for source in db.scalars(
                select(PartCatalog.source_document).where(
                    or_(
                        PartCatalog.part_number.ilike(f"%{q.strip()}%"),
                        PartCatalog.alternative_part_number.ilike(f"%{q.strip()}%"),
                        PartCatalog.name_bg.ilike(f"%{q.strip()}%"),
                        PartCatalog.name_en.ilike(f"%{q.strip()}%"),
                        PartCatalog.name_ru.ilike(f"%{q.strip()}%"),
                    ),
                    PartCatalog.source_document.is_not(None),
                )
            ).all()
            if source
        }

        def matches(document: TechnicalDocument) -> bool:
            searchable = " ".join(
                str(value or "")
                for value in (
                    document.title,
                    document.brand,
                    document.category,
                    document.model,
                    document.language,
                    document.revision,
                    document.source_label,
                    document.extracted_text,
                    document.notes,
                    " ".join(document.tags or []),
                )
            ).casefold()
            linked_numbers = set(document.linked_machine_numbers or [])
            source_candidates = {
                str(document.file_path or "").casefold(),
                str(document.source_label or "").casefold(),
            }
            return (
                normalized in searchable
                or bool(linked_numbers & matching_machine_numbers)
                or bool(source_candidates & matching_sources)
            )

        documents = [document for document in documents if matches(document)]
    return [{"id": item.id, "brand": item.brand, "model": item.model, "category": item.category, "title": item.title, "document_type": item.document_type, "language": item.language, "revision": item.revision, "source_label": item.source_label, "document_date": item.document_date, "tags": item.tags, "page_count": item.page_count, "notes": item.notes, "linked_machine_numbers": item.linked_machine_numbers, "sha256": item.sha256, "created_at": item.created_at, "source_key": item.file_path, "download_endpoint": f"/technical-library/{item.id}/download", "page_preview_endpoint": f"/technical-library/{item.id}/pages/{{page_number}}/preview", "revisions": [{"id": revision.id, "version": revision.version, "revision_label": revision.revision_label, "filename": revision.filename, "sha256": revision.sha256, "change_note": revision.change_note, "created_at": revision.created_at, "download_endpoint": f"/technical-library/revisions/{revision.id}/download"} for revision in sorted(item.revisions, key=lambda value: value.version, reverse=True)]} for item in documents]


def _validate_document_machine_links(db: Session, numbers: list[str] | None) -> None:
    requested = set(numbers or [])
    if not requested:
        return
    found = set(db.scalars(select(Machine.inventory_number).where(Machine.inventory_number.in_(requested))).all())
    missing = sorted(requested - found)
    if missing:
        raise HTTPException(status_code=422, detail={"code": "linked_machines_not_found", "message": "Една или повече свързани машини не са намерени в регистъра.", "machine_numbers": missing})


@router.post("/technical-library", status_code=201)
def upload_technical_document(
    payload: TechnicalDocumentUpload,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    _validate_document_machine_links(db, payload.linked_machine_numbers)
    filename, content = _decode_file(payload)
    digest = hashlib.sha256(content).hexdigest()
    item = TechnicalDocument(brand=payload.brand, model=payload.model, category=payload.category, title=payload.title, file_path=f"uploads/{uuid4().hex}/{filename}", language=payload.language.value if payload.language else None, revision=payload.revision, source_label=payload.source_label, document_date=payload.document_date, tags=payload.tags, extracted_text=payload.extracted_text, page_count=payload.page_count, notes=payload.notes, linked_machine_numbers=payload.linked_machine_numbers, sha256=digest, uploaded_content=content, uploaded_filename=filename, media_type=payload.media_type, uploaded_by_id=user.id, created_at=utcnow())
    db.add(item)
    db.flush()
    db.add(TechnicalDocumentRevision(document_id=item.id, version=1, revision_label=payload.revision, filename=filename, media_type=payload.media_type, content=content, sha256=digest, change_note=payload.change_note, created_by_id=user.id))
    add_audit_log(db, user, "technical_document", item.id, "Качен технически документ", {"title": item.title, "brand": item.brand, "model": item.model, "revision": item.revision, "sha256": digest})
    _commit(db)
    return {"id": item.id, "title": item.title, "revision": item.revision, "sha256": item.sha256, "download_endpoint": f"/technical-library/{item.id}/download"}


@router.post("/technical-library/{document_id}/revisions", status_code=201)
def upload_technical_revision(
    document_id: int,
    payload: TechnicalDocumentUpload,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    document = db.scalar(select(TechnicalDocument).options(selectinload(TechnicalDocument.revisions)).where(TechnicalDocument.id == document_id))
    if document is None:
        raise HTTPException(404, "Техническият документ не е намерен.")
    _validate_document_machine_links(db, payload.linked_machine_numbers)
    filename, content = _decode_file(payload)
    digest = hashlib.sha256(content).hexdigest()
    version = max((item.version for item in document.revisions), default=0) + 1
    revision = TechnicalDocumentRevision(document_id=document.id, version=version, revision_label=payload.revision, filename=filename, media_type=payload.media_type, content=content, sha256=digest, change_note=payload.change_note, created_by_id=user.id)
    db.add(revision)
    document.revision = payload.revision
    document.sha256 = digest
    document.uploaded_content = content
    document.uploaded_filename = filename
    document.media_type = payload.media_type
    document.language = payload.language.value if payload.language else document.language
    document.source_label = payload.source_label or document.source_label
    document.document_date = payload.document_date or document.document_date
    document.tags = payload.tags if payload.tags is not None else document.tags
    document.extracted_text = payload.extracted_text if payload.extracted_text is not None else document.extracted_text
    document.page_count = payload.page_count or document.page_count
    document.notes = payload.notes if payload.notes is not None else document.notes
    document.linked_machine_numbers = payload.linked_machine_numbers if payload.linked_machine_numbers is not None else document.linked_machine_numbers
    add_audit_log(db, user, "technical_document_revision", None, "Добавена версия на технически документ", {"document_id": document.id, "version": version, "revision": payload.revision, "sha256": digest})
    _commit(db)
    db.refresh(revision)
    return {"id": revision.id, "document_id": document.id, "version": version, "sha256": digest, "download_endpoint": f"/technical-library/revisions/{revision.id}/download"}



def _technical_document_content(item: TechnicalDocument) -> tuple[bytes, str, str]:
    """Return controlled technical-document bytes without exposing filesystem paths."""
    if item.uploaded_content is not None:
        return (
            item.uploaded_content,
            item.media_type or mimetypes.guess_type(item.uploaded_filename or "")[0] or "application/octet-stream",
            item.uploaded_filename or item.title or "document",
        )
    root = Path(__file__).resolve().parents[1] / "resources" / "technical_docs"
    path = (root / item.file_path).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Файлът не е намерен.")
    return (
        path.read_bytes(),
        mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        path.name,
    )


def _render_pdf_page_png(content: bytes, page_number: int, scale: float) -> tuple[bytes, int]:
    try:
        import fitz  # PyMuPDF, imported lazily to keep normal API startup lightweight.
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise HTTPException(503, detail={
            "code": "pdf_preview_unavailable",
            "message": "PDF визуализацията не е налична на сървъра.",
        }) from exc
    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise HTTPException(422, detail={
            "code": "technical_document_not_pdf",
            "message": "Избраният документ не може да бъде визуализиран като PDF.",
        }) from exc
    try:
        if page_number < 1 or page_number > document.page_count:
            raise HTTPException(404, detail={
                "code": "technical_document_page_not_found",
                "message": "Страницата не е намерена в техническия документ.",
                "page_count": document.page_count,
            })
        page = document.load_page(page_number - 1)
        width = max(1.0, float(page.rect.width) * scale)
        height = max(1.0, float(page.rect.height) * scale)
        max_pixels = 20_000_000
        if width * height > max_pixels:
            scale *= (max_pixels / (width * height)) ** 0.5
        matrix = fitz.Matrix(scale, scale)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
        return pixmap.tobytes("png"), document.page_count
    finally:
        document.close()

@router.get("/technical-library/{document_id}/download")
def download_technical_document(
    document_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(TechnicalDocument, document_id)
    if item is None:
        raise HTTPException(404, "Техническият документ не е намерен.")
    content, media_type, filename = _technical_document_content(item)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/technical-library/{document_id}/pages/{page_number}/preview")
def preview_technical_document_page(
    document_id: int,
    page_number: int,
    scale: float = Query(default=1.75, ge=0.75, le=3.0),
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(TechnicalDocument, document_id)
    if item is None:
        raise HTTPException(404, "Техническият документ не е намерен.")
    content, media_type, _ = _technical_document_content(item)
    if media_type != "application/pdf" and not (item.uploaded_filename or item.file_path or "").lower().endswith(".pdf"):
        raise HTTPException(422, detail={
            "code": "technical_document_not_pdf",
            "message": "Визуализация по страници се поддържа само за PDF документи.",
        })
    rendered, page_count = _render_pdf_page_png(content, page_number, scale)
    source_sha = item.sha256 or hashlib.sha256(content).hexdigest()
    preview_etag = hashlib.sha256(
        f"{source_sha}:{page_number}:{scale:.2f}".encode("utf-8")
    ).hexdigest()
    return Response(
        rendered,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="technical-document-{document_id}-page-{page_number}.png"',
            "Cache-Control": "private, max-age=3600",
            "ETag": preview_etag,
            "X-Document-SHA256": source_sha,
            "X-Document-Page-Count": str(page_count),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/technical-library/revisions/{revision_id}/download")
def download_technical_revision(
    revision_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(TechnicalDocumentRevision, revision_id)
    if item is None:
        raise HTTPException(404, "Версията не е намерена.")
    if item.content is not None:
        content = item.content
    elif item.file_path:
        root = Path(__file__).resolve().parents[1] / "resources" / "technical_docs"
        path = (root / item.file_path).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "Файлът не е намерен.")
        content = path.read_bytes()
    else:
        raise HTTPException(404, "Файлът не е намерен.")
    media_type = item.media_type
    if not media_type or media_type == "application/octet-stream":
        media_type = mimetypes.guess_type(item.filename)[0] or "application/octet-stream"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{item.filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/document-templates")
def list_document_templates(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    templates = db.scalars(select(DocumentTemplate).options(selectinload(DocumentTemplate.versions)).order_by(DocumentTemplate.document_type, DocumentTemplate.code)).all()
    return [{"id": item.id, "code": item.code, "document_type": item.document_type, "name_bg": item.name_bg, "name_en": item.name_en, "name_ru": item.name_ru, "is_active": item.is_active, "versions": [{"id": version.id, "version": version.version, "language": version.language, "source_filename": version.source_filename or (Path(version.source_path).name if version.source_path else None), "source_media_type": version.source_media_type, "source_sha256": version.source_sha256, "layout_contract": version.layout_contract, "effective_from": version.effective_from, "effective_to": version.effective_to, "required_fields": version.required_fields, "numbering_rule": version.numbering_rule, "department": version.department, "change_note": version.change_note, "validation_status": version.validation_status, "validation_report": version.validation_report, "validated_at": version.validated_at, "is_published": version.is_published, "created_by_id": version.created_by_id, "published_by_id": version.published_by_id, "created_at": version.created_at, "published_at": version.published_at, "download_endpoint": f"/document-template-versions/{version.id}/download"} for version in sorted(item.versions, key=lambda value: (value.language, value.version), reverse=True)]} for item in templates]


@router.post("/document-templates", status_code=201, response_model=None)
def create_document_template(
    payload: TemplateCreate,
    user: User = Depends(require_template_manager),
    db: Session = Depends(get_db),
) -> DocumentTemplate:
    item = DocumentTemplate(**payload.model_dump())
    db.add(item)
    db.flush()
    report = validate_template(item)
    item.validation_status = "PASSED" if report["valid"] else "FAILED"
    item.validation_report = report
    item.validated_at = utcnow()
    item.validated_by_id = user.id
    add_audit_log(db, user, "document_template", item.id, "Създаден документен шаблон", {"code": item.code, "document_type": item.document_type})
    _commit(db)
    db.refresh(item)
    return item


@router.post(
    "/document-templates/{template_id}/versions", status_code=201, response_model=None
)
def create_template_version(
    template_id: int,
    payload: TemplateVersionCreate,
    user: User = Depends(require_template_manager),
    db: Session = Depends(get_db),
) -> dict:
    template = db.get(DocumentTemplate, template_id)
    if template is None:
        raise HTTPException(404, "Шаблонът не е намерен.")
    filename, content = _decode_file(payload)
    version_number = (db.scalar(select(func.max(DocumentTemplateVersion.version)).where(DocumentTemplateVersion.template_id == template.id, DocumentTemplateVersion.language == payload.language.value)) or 0) + 1
    item = DocumentTemplateVersion(template_id=template.id, version=version_number, language=payload.language.value, source_filename=filename, source_media_type=payload.media_type, source_content=content, source_sha256=hashlib.sha256(content).hexdigest(), layout_contract=payload.layout_contract, effective_from=payload.effective_from, effective_to=payload.effective_to, required_fields=payload.required_fields, numbering_rule=payload.numbering_rule, department=payload.department, change_note=payload.change_note, created_by_id=user.id)
    db.add(item)
    db.flush()
    add_audit_log(db, user, "document_template_version", item.id, "Създадена версия на документен шаблон", {"template_code": template.code, "version": version_number, "language": item.language, "source_sha256": item.source_sha256, "effective_from": item.effective_from.isoformat() if item.effective_from else None, "effective_to": item.effective_to.isoformat() if item.effective_to else None, "required_fields": item.required_fields, "numbering_rule": item.numbering_rule, "department": item.department, "change_note": item.change_note})
    _commit(db)
    db.refresh(item)
    return {
        "id": item.id,
        "template_id": item.template_id,
        "version": item.version,
        "language": item.language,
        "source_filename": item.source_filename,
        "source_sha256": item.source_sha256,
        "effective_from": item.effective_from,
        "effective_to": item.effective_to,
        "required_fields": item.required_fields,
        "numbering_rule": item.numbering_rule,
        "department": item.department,
        "change_note": item.change_note,
        "validation_status": item.validation_status,
        "validation_report": item.validation_report,
        "is_published": item.is_published,
        "created_at": item.created_at,
        "download_endpoint": f"/document-template-versions/{item.id}/download",
    }


@router.post("/document-template-versions/{version_id}/validate")
def validate_template_version(
    version_id: int,
    user: User = Depends(require_template_manager),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(DocumentTemplateVersion, version_id)
    if item is None:
        raise HTTPException(404, "Версията на шаблона не е намерена.")
    report = validate_template(item)
    item.validation_status = "PASSED" if report["valid"] else "FAILED"
    item.validation_report = report
    item.validated_at = utcnow()
    item.validated_by_id = user.id
    add_audit_log(
        db,
        user,
        "document_template_version",
        item.id,
        "Проверена версия на документен шаблон",
        {"validation_status": item.validation_status, "source_sha256": item.source_sha256, "errors": report["errors"]},
    )
    _commit(db)
    return {"id": item.id, "validation_status": item.validation_status, "validation_report": report, "validated_at": item.validated_at}


@router.post("/document-template-versions/{version_id}/publish")
def publish_template_version(
    version_id: int,
    user: User = Depends(require_template_manager),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(DocumentTemplateVersion, version_id)
    if item is None:
        raise HTTPException(404, "Версията на шаблона не е намерена.")
    if not item.layout_contract or not item.source_sha256 or (item.source_content is None and not item.source_path):
        raise business_conflict("template_contract_missing", "Шаблонът не може да бъде публикуван без проверен изходен файл и договор за оформление.")
    report = validate_template(item)
    item.validation_status = "PASSED" if report["valid"] else "FAILED"
    item.validation_report = report
    item.validated_at = utcnow()
    item.validated_by_id = user.id
    if not report["valid"]:
        add_audit_log(db, user, "document_template_version", item.id, "Отказано публикуване на невалиден шаблон", {"validation_status": item.validation_status, "errors": report["errors"]})
        _commit(db)
        raise business_conflict(
            "template_validation_failed",
            "Шаблонът не може да бъде публикуван, защото проверката му е неуспешна.",
            errors=report["errors"],
        )
    if item.effective_to is not None and item.effective_to <= utcnow():
        raise business_conflict(
            "template_period_expired",
            "Шаблон с изтекъл срок на валидност не може да бъде публикуван.",
        )
    db.query(DocumentTemplateVersion).filter(DocumentTemplateVersion.template_id == item.template_id, DocumentTemplateVersion.language == item.language, DocumentTemplateVersion.is_published.is_(True)).update({"is_published": False, "published_at": None, "published_by_id": None}, synchronize_session=False)
    item.is_published = True
    item.published_by_id = user.id
    item.published_at = utcnow()
    add_audit_log(db, user, "document_template_version", item.id, "Публикувана версия на документен шаблон", {"template_id": item.template_id, "version": item.version, "language": item.language, "effective_from": item.effective_from.isoformat() if item.effective_from else None, "effective_to": item.effective_to.isoformat() if item.effective_to else None, "change_note": item.change_note})
    _commit(db)
    return {"id": item.id, "is_published": True, "published_at": item.published_at}


@router.get("/document-template-versions/{version_id}/download")
def download_template_version(
    version_id: int,
    _: User = Depends(require_template_manager),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(DocumentTemplateVersion, version_id)
    if item is None:
        raise HTTPException(404, "Версията на шаблона не е намерена.")
    if item.source_content is not None:
        content = item.source_content
        filename = item.source_filename or f"template-v{item.version}"
        media_type = item.source_media_type or "application/octet-stream"
    elif item.source_path:
        root = Path(__file__).resolve().parents[1] / "resources"
        path = (root / item.source_path).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise HTTPException(404, "Изходният файл на шаблона не е намерен.")
        content = path.read_bytes()
        filename = path.name
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    else:
        raise HTTPException(404, "Изходният файл на шаблона не е намерен.")
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/generated-documents/{document_id}/download")
def download_generated_document(
    document_id: int,
    _: User = Depends(require_document_viewer),
    db: Session = Depends(get_db),
) -> Response:
    item = db.get(GeneratedDocument, document_id)
    if item is None:
        raise HTTPException(404, "Генерираният документ не е намерен.")
    official = db.scalar(
        select(OfficialDocument).where(
            OfficialDocument.document_number == item.document_number
        )
    )
    version = (
        db.get(OfficialDocumentVersion, official.current_version_id)
        if official
        else None
    )
    if (
        item.document_type in {"TRANSFER_ISSUE", "TRANSFER_RETURN"}
        and version is not None
        and version.status != OfficialDocumentStatus.SIGNED.value
    ):
        raise HTTPException(
            409,
            detail={
                "code": "document_awaiting_signatures",
                "message": "Окончателният протокол ще бъде достъпен след всички задължителни подписи.",
            },
        )
    return Response(item.content, media_type=item.media_type, headers={"Content-Disposition": f'attachment; filename="{item.filename}"', "X-Content-Type-Options": "nosniff"})


@router.get("/search")
def global_search(
    q: str = Query(min_length=2, max_length=120),
    limit: int = Query(default=10, ge=1, le=50),
    user: User = Depends(require_asset_viewer),
    db: Session = Depends(get_db),
) -> dict:
    term = f"%{q.strip()}%"
    machine_conditions = [
        Machine.inventory_number.ilike(term),
        Machine.name.ilike(term),
        Machine.brand.ilike(term),
        Machine.model.ilike(term),
        Machine.location.has(Location.name.ilike(term)),
    ]
    if not is_observer(user):
        machine_conditions.append(Machine.serial_number.ilike(term))
    machines = db.scalars(
        select(Machine)
        .options(joinedload(Machine.location))
        .where(or_(*machine_conditions))
        .limit(limit)
    ).all()
    if is_observer(user):
        return {
            "query": q,
            "machines": [
                {
                    "id": item.id,
                    "inventory_number": item.inventory_number,
                    "name": item.name,
                    "brand": item.brand,
                    "model": item.model,
                    "status": item.status,
                    "location": item.location.name if item.location else None,
                }
                for item in machines
            ],
            "parts": [],
            "documents": [],
            "repairs": [],
            "part_requests": [],
            "transfers": [],
            "generated_documents": [],
        }
    parts = db.scalars(select(PartCatalog).where(PartCatalog.is_active.is_(True), or_(PartCatalog.part_number.ilike(term), PartCatalog.replaced_by_part_number.ilike(term), PartCatalog.alternative_part_number.ilike(term), PartCatalog.description.ilike(term), PartCatalog.name_bg.ilike(term), PartCatalog.name_en.ilike(term), PartCatalog.name_ru.ilike(term), PartCatalog.original_name.ilike(term), PartCatalog.brand.ilike(term), PartCatalog.model.ilike(term), PartCatalog.assembly.ilike(term), PartCatalog.position.ilike(term), PartCatalog.repair_kit_code.ilike(term))).limit(limit)).all()
    documents = db.scalars(select(TechnicalDocument).where(TechnicalDocument.is_active.is_(True), or_(TechnicalDocument.title.ilike(term), TechnicalDocument.brand.ilike(term), TechnicalDocument.category.ilike(term), TechnicalDocument.model.ilike(term), TechnicalDocument.extracted_text.ilike(term), TechnicalDocument.notes.ilike(term), TechnicalDocument.revision.ilike(term), TechnicalDocument.source_label.ilike(term))).limit(limit)).all()
    repairs = db.scalars(select(Repair).options(joinedload(Repair.machine)).where(or_(Repair.repair_reference.ilike(term), Repair.reported_problem.ilike(term), Repair.symptoms.ilike(term), Repair.diagnosis.ilike(term), Repair.required_work.ilike(term), Repair.work_performed.ilike(term), Repair.result.ilike(term))).limit(limit)).all()
    requests = db.scalars(select(PartRequest).where(or_(PartRequest.request_reference.ilike(term), PartRequest.part_name.ilike(term), PartRequest.part_number.ilike(term), PartRequest.reason.ilike(term), PartRequest.lines.any(or_(PartRequestLine.part_number.ilike(term), PartRequestLine.description.ilike(term), PartRequestLine.position.ilike(term))))).limit(limit)).all()
    transfers = db.scalars(
        select(TransferProtocol)
        .options(joinedload(TransferProtocol.machine), joinedload(TransferProtocol.batch))
        .where(
            or_(
                TransferProtocol.protocol_number.ilike(term),
                TransferProtocol.company_unit.ilike(term),
                TransferProtocol.department.ilike(term),
                TransferProtocol.vessel.ilike(term),
                TransferProtocol.dock.ilike(term),
                TransferProtocol.pier.ilike(term),
                TransferProtocol.work_area.ilike(term),
                TransferProtocol.location_text.ilike(term),
                TransferProtocol.accepted_by.ilike(term),
                TransferProtocol.batch.has(TransferBatch.batch_reference.ilike(term)),
            )
        )
        .limit(limit)
    ).all()
    generated_documents = db.scalars(
        select(GeneratedDocument)
        .where(or_(GeneratedDocument.document_number.ilike(term), GeneratedDocument.filename.ilike(term)))
        .order_by(GeneratedDocument.created_at.desc())
        .limit(limit)
    ).all()
    protocol_documents = db.scalars(
        select(ProtocolDocument)
        .where(or_(ProtocolDocument.document_number.ilike(term), ProtocolDocument.filename.ilike(term)))
        .order_by(ProtocolDocument.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "query": q,
        "machines": [{"id": item.id, "inventory_number": item.inventory_number, "name": item.name, "brand": item.brand, "model": item.model, "serial_number": item.serial_number, "status": item.status} for item in machines],
        "parts": [{"id": item.id, "part_number": item.part_number, "description": item.description, "brand": item.brand, "model": item.model, "assembly": item.assembly, "is_verified": item.is_verified} for item in parts],
        "documents": [{"id": item.id, "title": item.title, "brand": item.brand, "category": item.category, "download_endpoint": f"/technical-library/{item.id}/download"} for item in documents],
        "repairs": [{"id": item.id, "repair_reference": item.repair_reference, "machine_number": item.machine.inventory_number, "reported_problem": item.reported_problem, "status": item.status} for item in repairs],
        "part_requests": [{"id": item.id, "request_reference": item.request_reference, "status": item.status, "part_name": item.part_name} for item in requests],
        "transfers": [{"id": item.id, "protocol_number": item.protocol_number, "batch_reference": item.batch_reference, "machine_number": item.machine.inventory_number, "company_unit": item.company_unit, "vessel": item.vessel, "location_text": item.location_text, "is_active": item.is_active} for item in transfers],
        "generated_documents": (
            [{"id": item.id, "document_number": item.document_number, "document_type": item.document_type, "format": item.format, "filename": item.filename, "download_endpoint": f"/generated-documents/{item.id}/download"} for item in generated_documents]
            + [{"id": item.id, "document_number": item.document_number or f"PROTOCOL-{item.id}", "document_type": "TRANSFER_ISSUE", "format": item.format, "filename": item.filename, "download_endpoint": f"/protocol-documents/{item.id}/download"} for item in protocol_documents]
        )[:limit],
    }


def _location_dict(item: Location) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "is_active": item.is_active,
    }


def _department_dict(item: Department) -> dict:
    return {
        "id": item.id,
        "code": item.code,
        "name_bg": item.name_bg,
        "name_en": item.name_en,
        "name_ru": item.name_ru,
        "description": item.description,
        "is_active": item.is_active,
        "created_at": item.created_at,
    }


@router.get("/departments")
def list_departments(
    _: User = Depends(require_document_viewer), db: Session = Depends(get_db)
) -> list[dict]:
    items = db.scalars(select(Department).order_by(Department.code)).all()
    return [_department_dict(item) for item in items]


@router.get("/admin/reference-data")
def admin_reference_data(
    _: User = Depends(require_admin), db: Session = Depends(get_db)
) -> dict:
    locations = db.scalars(select(Location).order_by(Location.name)).all()
    departments = db.scalars(select(Department).order_by(Department.code)).all()
    return {
        "locations": [_location_dict(item) for item in locations],
        "departments": [_department_dict(item) for item in departments],
    }


@router.post("/admin/locations", status_code=201)
def create_location(
    payload: LocationAdminCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    name = payload.name.strip()
    if any(
        existing.casefold() == name.casefold()
        for existing in db.scalars(select(Location.name)).all()
    ):
        raise business_conflict(
            "location_duplicate",
            "Вече съществува местоположение със същото име.",
            name=name,
        )
    item = Location(name=name, description=payload.description)
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        user,
        "location",
        item.id,
        "Добавено местоположение",
        {"name": item.name, "is_active": item.is_active},
    )
    _commit(db)
    db.refresh(item)
    return _location_dict(item)


@router.patch("/admin/locations/{location_id}")
def update_location(
    location_id: int,
    payload: LocationAdminUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(Location, location_id)
    if item is None:
        raise HTTPException(404, "Местоположението не е намерено.")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        name = changes["name"].strip()
        duplicate = any(
            existing.casefold() == name.casefold()
            for existing in db.scalars(
                select(Location.name).where(Location.id != item.id)
            ).all()
        )
        if duplicate:
            raise business_conflict(
                "location_duplicate",
                "Вече съществува местоположение със същото име.",
                name=name,
            )
        changes["name"] = name
    previous = _location_dict(item)
    for key, value in changes.items():
        setattr(item, key, value)
    add_audit_log(
        db,
        user,
        "location",
        item.id,
        "Обновено местоположение",
        {"previous": previous, "changes": changes},
    )
    _commit(db)
    db.refresh(item)
    return _location_dict(item)


@router.post("/admin/departments", status_code=201)
def create_department(
    payload: DepartmentCreate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    code = payload.code.strip().upper()
    if db.scalar(select(Department.id).where(Department.code == code)):
        raise business_conflict(
            "department_duplicate",
            "Вече съществува отдел със същия системен код.",
            department_code=code,
        )
    item = Department(**payload.model_dump(exclude={"code"}), code=code)
    db.add(item)
    db.flush()
    add_audit_log(
        db,
        user,
        "department",
        item.id,
        "Добавен отдел",
        {"code": item.code, "name_bg": item.name_bg, "is_active": item.is_active},
    )
    _commit(db)
    db.refresh(item)
    return _department_dict(item)


@router.patch("/admin/departments/{department_id}")
def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    item = db.get(Department, department_id)
    if item is None:
        raise HTTPException(404, "Отделът не е намерен.")
    changes = payload.model_dump(exclude_unset=True)
    if "code" in changes:
        code = changes["code"].strip().upper()
        duplicate = db.scalar(
            select(Department.id).where(
                Department.code == code, Department.id != item.id
            )
        )
        if duplicate:
            raise business_conflict(
                "department_duplicate",
                "Вече съществува отдел със същия системен код.",
                department_code=code,
            )
        changes["code"] = code
    previous = _department_dict(item)
    for key, value in changes.items():
        setattr(item, key, value)
    add_audit_log(
        db,
        user,
        "department",
        item.id,
        "Обновен отдел",
        {"previous": previous, "changes": changes},
    )
    _commit(db)
    db.refresh(item)
    return _department_dict(item)


def _sign_preview(records: list[dict]) -> str:
    payload = {"exp": int(time.time()) + 900, "records": records}
    body = base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _verify_preview(token: str) -> list[dict]:
    try:
        body, signature = token.rsplit(".", 1)
        expected = hmac.new(settings.secret_key.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        decoded = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(decoded)
        if int(payload["exp"]) < int(time.time()):
            raise ValueError("expired")
        return payload["records"]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise HTTPException(422, {"code": "invalid_import_preview", "message": "Прегледът за импорт е невалиден или е изтекъл."}) from exc


def _validate_import_records(records: list[dict], db: Session) -> tuple[list[dict], list[dict]]:
    allowed = {"inventory_number", "name", "category", "brand", "model", "pressure_bar", "serial_number", "notes"}
    seen: set[str] = set()
    valid: list[dict] = []
    errors: list[dict] = []
    existing = {value for value in db.scalars(select(Machine.inventory_number)).all()}
    for index, source in enumerate(records):
        record = {key: value for key, value in source.items() if key in allowed}
        number = str(record.get("inventory_number", "")).strip()
        if not number:
            errors.append({"row": index + 1, "message": "Липсва инвентарен номер."})
            continue
        if number in seen:
            errors.append({"row": index + 1, "message": f"Дублиран инвентарен номер {number}."})
            continue
        seen.add(number)
        if number in existing:
            errors.append({"row": index + 1, "message": f"Инвентарен номер {number} вече съществува."})
            continue
        category = str(record.get("category", "")).strip()
        if category.upper() == "HPWJ" or number in PROTECTED_HPWJ_NUMBERS:
            errors.append({"row": index + 1, "message": f"Провереният HPWJ регистър е защитен; ред {number} не може да се импортира."})
            continue
        missing = [field for field in ("name", "category", "brand") if not str(record.get(field, "")).strip()]
        if missing:
            errors.append({"row": index + 1, "message": f"Липсват задължителни полета: {', '.join(missing)}."})
            continue
        try:
            pressure = int(record.get("pressure_bar") or 0)
        except (ValueError, TypeError):
            errors.append({"row": index + 1, "message": "Налягането трябва да бъде цяло число."})
            continue
        record["inventory_number"] = number
        record["pressure_bar"] = pressure
        valid.append(record)
    return valid, errors


@router.post("/admin/import-preview")
def import_preview(
    payload: ImportPreviewRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    valid, errors = _validate_import_records(payload.records, db)
    return {"valid_records": valid, "errors": errors, "can_confirm": bool(valid) and not errors, "preview_token": _sign_preview(valid) if valid and not errors else None, "message": "Прегледът не записва данни в базата."}


@router.post("/admin/import-confirm", status_code=201)
def import_confirm(
    payload: ImportConfirmRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    records = _verify_preview(payload.preview_token)
    valid, errors = _validate_import_records(records, db)
    if errors or len(valid) != len(records):
        raise business_conflict("import_changed_since_preview", "Данните са се променили след прегледа. Направете нов преглед.", errors=errors)
    created: list[Machine] = []
    for record in valid:
        machine = Machine(status=MachineStatus.READY.value, **record)
        db.add(machine)
        db.flush()
        created.append(machine)
        add_machine_event(db, machine, user, "IMPORTED", details={"source": "admin_import", "fields": sorted(record)})
    add_audit_log(db, user, "machine_import", None, "Потвърден импорт на активи", {"count": len(created), "inventory_numbers": [item.inventory_number for item in created]})
    _commit(db)
    return {"message": "Импортът е завършен.", "created": [{"id": item.id, "inventory_number": item.inventory_number} for item in created]}


@router.get("/audit/export.json")
def export_audit_log(
    _: User = Depends(require_audit_full), db: Session = Depends(get_db)
) -> Response:
    entries = db.scalars(select(AuditLog).order_by(AuditLog.created_at, AuditLog.id)).all()
    content = json.dumps([{"id": item.id, "entity_type": item.entity_type, "entity_id": item.entity_id, "action": item.action, "details": item.details, "user_id": item.user_id, "user_name": item.user_name, "operation_reference": item.operation_reference, "created_at": item.created_at.replace(tzinfo=UTC).isoformat()} for item in entries], ensure_ascii=False, indent=2).encode()
    return Response(content, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="assetcore-audit-{datetime.now(UTC):%Y%m%d}.json"', "X-Content-Type-Options": "nosniff"})
