"""Repair completion and controlled correction/version construction."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    DocumentType,
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    Repair,
    TransferBatch,
    utcnow,
)
from ..official_documents.integrity import (
    move_current_version,
    require_current_version,
)
from ..template_engine import TemplateValidationError, convert_docx_to_pdf, render_docx
from .common import (
    _language,
)
from .registration import (
    _generated_documents,
    _next_generated_number,
    _register_official_version,
)
from .repair_rendering import (
    _repair_duration,
    _repair_test_summary,
    build_repair_protocol_pdf,
)
from .templates import (
    _preparer_values,
    _signature_status,
    _template_version,
)


def make_repair_documents(
    db: Session, repair: Repair, created_by_id: int, language: str = "bg"
) -> list[GeneratedDocument]:
    template = _template_version(db, DocumentType.REPAIR_PROTOCOL.value, language)
    base = repair.repair_reference or f"REP-{repair.id:06d}"
    number = _next_generated_number(db, base)
    snapshot = {
        "repair_id": repair.id,
        "repair_reference": repair.repair_reference,
        "machine_id": repair.machine_id,
        "machine_number": repair.machine.inventory_number,
        "status": repair.status,
        "reported_problem": repair.reported_problem,
        "condition_before": repair.condition_before,
        "condition_after": repair.condition_after,
        "reported_by_name": repair.reported_by_name,
        "symptoms": repair.symptoms,
        "required_work": repair.required_work,
        "required_parts_text": repair.required_parts_text,
        "removed_parts_text": repair.removed_parts_text,
        "diagnostic_cleaning": repair.diagnostic_cleaning,
        "diagnosis": repair.diagnosis,
        "work_performed": repair.work_performed,
        "result": repair.result,
        "test_passed": repair.test_passed,
        "test_method": repair.test_method,
        "test_pressure_bar": repair.test_pressure_bar,
        "leaks_detected": repair.leaks_detected,
        "electrical_test_result": repair.electrical_test_result,
        "functional_test_result": repair.functional_test_result,
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
            participant.minutes_worked or 0 for participant in repair.participants
        ),
        "source_return_transfer_id": repair.source_return_transfer_id,
        "source_return_document_id": repair.source_return_document_id,
        "source_return_batch_id": repair.source_return_batch_id,
        "opened_at": repair.opened_at.isoformat(),
        "started_at": repair.started_at.isoformat() if repair.started_at else None,
        "closed_at": repair.closed_at.isoformat() if repair.closed_at else None,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "description": event.description,
                "created_at": event.created_at.isoformat(),
            }
            for event in repair.events
        ],
        "parts_used": [
            {
                "id": part.id,
                "part_number": part.part_number,
                "description": part.description,
                "quantity": part.quantity,
                "unit": part.unit,
                "source": part.source,
            }
            for part in repair.parts_used
        ],
        "participants": [
            {
                "id": participant.id,
                "user_id": participant.user_id,
                "full_name": participant.full_name_snapshot,
                "job_title": participant.job_title_snapshot,
                "contribution": participant.contribution,
                "minutes_worked": participant.minutes_worked,
            }
            for participant in repair.participants
        ],
        "attachment_ids": [attachment.id for attachment in repair.attachments],
        "responsible_user": {
            "user_id": repair.responsible_user.id if repair.responsible_user else None,
            "display_name": (
                repair.responsible_user.full_name if repair.responsible_user else None
            ),
            "job_title": (
                repair.responsible_user.job_title if repair.responsible_user else None
            ),
        },
        "accepted_by": {
            "user_id": repair.accepted_by.id if repair.accepted_by else None,
            "display_name": repair.accepted_by.full_name if repair.accepted_by else None,
            "job_title": repair.accepted_by.job_title if repair.accepted_by else None,
        },
        "approved_by": {
            "user_id": repair.approved_by.id if repair.approved_by else None,
            "display_name": repair.approved_by.full_name if repair.approved_by else None,
            "job_title": repair.approved_by.job_title if repair.approved_by else None,
        },
    }
    machine = repair.machine
    date_value = repair.closed_at or repair.opened_at
    source_document = (
        db.get(OfficialDocument, repair.source_return_document_id)
        if repair.source_return_document_id
        else None
    )
    source_batch = (
        db.get(TransferBatch, repair.source_return_batch_id)
        if repair.source_return_batch_id
        else None
    )
    source_reference = " · ".join(
        value
        for value in (
            source_document.document_number if source_document else None,
            source_batch.batch_reference if source_batch else None,
        )
        if value
    )
    participant_names = "; ".join(
        " — ".join(
            value
            for value in (
                participant.full_name_snapshot,
                participant.job_title_snapshot,
                participant.contribution,
                _repair_duration(participant.minutes_worked, language),
            )
            if value
        )
        for participant in repair.participants
    )
    total_work_minutes = sum(
        value or 0
        for value in (
            repair.diagnosis_minutes,
            repair.repair_minutes,
            repair.testing_minutes,
        )
    )
    participant_total_minutes = sum(
        participant.minutes_worked or 0 for participant in repair.participants
    )
    values: dict[str, object] = {
        "DOCUMENT_NUMBER": number,
        "CREATION_DATE": date_value.strftime("%d.%m.%Y"),
        "MACHINE_NAME": machine.name,
        "MACHINE_NUMBER": machine.inventory_number,
        "BRAND": machine.brand,
        "MODEL": machine.model or "",
        "SERIAL_NUMBER": machine.serial_number or "",
        "PRESSURE_BAR": machine.pressure_bar,
        "BATCH_REFERENCE": "",
        "REPAIR_REFERENCE": repair.repair_reference or base,
        "SOURCE_RETURN_REFERENCE": source_reference,
        "ACCEPTANCE_DATE": repair.opened_at.strftime("%d.%m.%Y"),
        "COMPLETION_DATE": date_value.strftime("%d.%m.%Y"),
        "OWNERSHIP": machine.ownership or "",
        "REPORTED_PROBLEM": repair.reported_problem,
        "CONDITION_BEFORE": repair.condition_before or "",
        "REQUIRED_WORK": repair.required_work or "",
        "REQUIRED_PARTS": repair.required_parts_text or "",
        "REMOVED_PARTS": repair.removed_parts_text or "",
        "DIAGNOSTIC_CLEANING": repair.diagnostic_cleaning or "",
        "DIAGNOSIS": repair.diagnosis or "",
        "DIAGNOSIS_DURATION": _repair_duration(repair.diagnosis_minutes, language),
        "WORK_PERFORMED": repair.work_performed or "",
        "REPAIR_DURATION": _repair_duration(repair.repair_minutes, language),
        "TESTING_DURATION": _repair_duration(repair.testing_minutes, language),
        "TOTAL_WORK_DURATION": _repair_duration(total_work_minutes, language),
        "PARTICIPANT_TOTAL_DURATION": _repair_duration(
            participant_total_minutes, language
        ),
        "TEST_RESULT": _repair_test_summary(repair, language),
        "CONDITION_AFTER": repair.condition_after or repair.result or "",
        "FINAL_RESULT": repair.result or "",
        "REPAIR_START": repair.started_at.strftime("%d.%m.%Y %H:%M") if repair.started_at else "",
        "REPAIR_END": repair.closed_at.strftime("%d.%m.%Y %H:%M") if repair.closed_at else "",
        "HANDED_OVER_NAME": repair.reported_by_name or "",
        "ACCEPTED_BY_NAME": repair.accepted_by.full_name if repair.accepted_by else "",
        "REPAIRER_NAMES": participant_names,
        "APPROVED_BY_NAME": repair.approved_by.full_name if repair.approved_by else "",
        "APPROVED_BY_JOB_TITLE": repair.approved_by.job_title if repair.approved_by else "",
        "REPAIR_STATUS": repair.status,
        "LEFT_SIGNER_NAME": repair.responsible_user.full_name if repair.responsible_user else "",
        "LEFT_SIGNER_JOB_TITLE": repair.responsible_user.job_title if repair.responsible_user else "",
        "RIGHT_SIGNER_NAME": "",
        "RIGHT_SIGNER_JOB_TITLE": "",
        "LEFT_SIGNATURE": "",
        "RIGHT_SIGNATURE": "",
        "SIGNATURE_STATUS": _signature_status(language, finalized_internal=True),
    }
    values.update(_preparer_values(db, created_by_id))
    event_type_labels = {
        "ACCEPTED": "Създаване",
        "STATUS_CHANGE": "Промяна на статус",
        "PARTS": "Използвани части",
        "DIAGNOSIS": "Диагностика",
        "WORK": "Извършена работа",
        "TEST": "Тест",
        "COMPLETED": "Приключване",
    }
    event_rows = [["Дата", "Тип", "Описание"]] + [
        [
            event.created_at.strftime("%d.%m.%Y %H:%M"),
            event_type_labels.get(event.event_type, event.event_type.replace("_", " ").title()),
            event.description,
        ]
        for event in repair.events
    ]
    part_rows = [["Поз.", "Номер", "Описание", "Количество"]] + [
        [str(index), part.part_number or "", part.description, f"{part.quantity:g} {part.unit or ''}".strip()]
        for index, part in enumerate(repair.parts_used, start=1)
    ]
    participant_rows = [["Три имена", "Длъжност", "Участие", "Време"]] + (
        [
            [
                participant.full_name_snapshot,
                participant.job_title_snapshot or "",
                participant.contribution or "",
                _repair_duration(participant.minutes_worked, language),
            ]
            for participant in repair.participants
        ]
        or [["Няма допълнителни участници", "", "", ""]]
    )
    attachment_rows = [["Файл", "Етап", "Описание"]] + (
        [
            [attachment.filename, attachment.stage, attachment.caption or ""]
            for attachment in repair.attachments
        ]
        or [["Няма приложения", "", ""]]
    )
    docx = render_docx(
        template,
        values,
        {
            "REPAIR_EVENTS": event_rows,
            "PARTS_USED": part_rows,
            "REPAIR_PARTICIPANTS": participant_rows,
            "REPAIR_ATTACHMENTS": attachment_rows,
        },
    )
    pdf = convert_docx_to_pdf(docx) or build_repair_protocol_pdf(
        repair, language, source_reference
    )
    _register_official_version(
        db,
        number=number,
        document_type=DocumentType.REPAIR_PROTOCOL.value,
        language=language,
        docx=docx,
        pdf=pdf,
        snapshot=snapshot,
        created_by_id=created_by_id,
        machine_id=repair.machine_id,
        template_version_id=template.id,
        initial_status=OfficialDocumentStatus.FINALIZED.value,
    )
    return _generated_documents(
        number=number,
        document_type=DocumentType.REPAIR_PROTOCOL.value,
        language=language,
        template_version=template,
        docx=docx,
        pdf=pdf,
        snapshot=snapshot,
        created_by_id=created_by_id,
        machine_id=repair.machine_id,
        repair_id=repair.id,
    )


def make_repair_correction(
    db: Session,
    repair: Repair,
    created_by_id: int,
    reason: str,
    language: str = "bg",
) -> tuple[list[GeneratedDocument], OfficialDocument, OfficialDocumentVersion]:
    """Create a locked new version without rewriting the completed repair protocol."""
    existing_numbers = list(
        db.scalars(
            select(GeneratedDocument.document_number)
            .where(
                GeneratedDocument.repair_id == repair.id,
                GeneratedDocument.language == _language(language),
            )
            .order_by(GeneratedDocument.id)
        )
    )
    original = db.scalar(
        select(OfficialDocument)
        .where(
            OfficialDocument.document_type == DocumentType.REPAIR_PROTOCOL.value,
            OfficialDocument.machine_id == repair.machine_id,
            OfficialDocument.document_number.in_(existing_numbers or [""]),
        )
        .order_by(OfficialDocument.id)
    )
    if original is None or original.current_version_id is None:
        raise TemplateValidationError("Липсва заключена начална версия на ремонтния протокол.")
    previous = require_current_version(db, original)
    if previous.status not in {
        OfficialDocumentStatus.FINALIZED.value,
        OfficialDocumentStatus.SIGNED.value,
    }:
        raise TemplateValidationError("Само окончателен ремонтен протокол може да бъде коригиран.")

    documents = make_repair_documents(db, repair, created_by_id, language)
    temporary = db.scalar(
        select(OfficialDocument).where(
            OfficialDocument.document_number == documents[0].document_number
        )
    )
    if temporary is None or temporary.current_version_id is None:
        raise TemplateValidationError("Новата версия на ремонтния протокол не беше регистрирана.")
    version = require_current_version(db, temporary)
    next_version = previous.version + 1
    snapshot = dict(version.snapshot)
    snapshot["correction"] = {
        "reason": reason,
        "supersedes_version": previous.version,
        "created_by_id": created_by_id,
        "created_at": utcnow().isoformat(timespec="seconds") + "Z",
    }
    snapshot_sha256 = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    signing_sha256 = hashlib.sha256(
        json.dumps(
            {
                "document_number": original.document_number,
                "document_type": original.document_type,
                "snapshot_sha256": snapshot_sha256,
                "docx_sha256": version.docx_sha256,
                "pdf_sha256": version.pdf_sha256,
                "version": next_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    version.version = next_version
    version.snapshot = snapshot
    version.snapshot_sha256 = snapshot_sha256
    version.signing_sha256 = signing_sha256
    version.correction_reason = reason
    version.supersedes_version_id = previous.id
    version.status = OfficialDocumentStatus.FINALIZED.value
    version.finalized_at = utcnow()
    previous.status = OfficialDocumentStatus.SUPERSEDED.value
    move_current_version(
        db,
        source_document=temporary,
        target_document=original,
        version=version,
    )
    db.delete(temporary)
    for document in documents:
        document.snapshot = {
            **document.snapshot,
            "official_document_id": original.id,
            "official_document_version": next_version,
            "correction_reason": reason,
        }
    db.flush()
    return documents, original, version
