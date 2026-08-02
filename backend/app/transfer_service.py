from __future__ import annotations

import hashlib
from contextlib import nullcontext
from dataclasses import dataclass
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .audit import add_audit_log
from .document_generation import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    ConfirmedTemplateUnavailableError,
    TemplateValidationError,
    make_protocol_documents,
    make_return_documents,
    safe_filename,
)
from .localization import status_label, translate
from .models import (
    DocumentType,
    GeneratedDocument,
    Location,
    Machine,
    MachineStatus,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    ProtocolDocument,
    TransferBatch,
    TransferBatchStatus,
    TransferOperationStatus,
    TransferProtocol,
    User,
    utcnow,
)
from .schemas import BulkIssueRequest, BulkReturnRequest
from .transfer_signing import (
    TransferSigningConfigurationError,
    create_external_party,
    prepare_transfer_signing,
)
from .workflow import add_machine_event

_sqlite_transfer_lock = RLock()


def _sqlite_guard(db: Session):
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        return _sqlite_transfer_lock
    return nullcontext()


@dataclass
class TransferServiceError(Exception):
    status_code: int
    code: str
    message: str
    data: dict[str, Any]

    def as_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, **self.data}


def _for_update(db: Session, statement):
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        return statement.with_for_update()
    return statement


def _machine_numbers(machines: list[Machine]) -> list[str]:
    return [machine.inventory_number for machine in machines]


def _recipient_or_location(transfer: TransferProtocol) -> str | None:
    return next(
        (
            value
            for value in (
                transfer.accepted_by,
                transfer.company_unit,
                transfer.vessel,
                transfer.location_text,
            )
            if value
        ),
        None,
    )


def _conflict_item(
    machine: Machine, transfer: TransferProtocol | None, language: str = "bg"
) -> dict[str, Any]:
    return {
        "machine_id": machine.id,
        "machine_number": machine.inventory_number,
        "status": machine.status,
        "status_label": status_label(machine.status, language),
        "issue_status": transfer.issue_status if transfer else None,
        "return_status": transfer.return_status if transfer else None,
        "active_transfer_id": transfer.id if transfer else None,
        "protocol_number": transfer.protocol_number if transfer else None,
        "batch_reference": transfer.batch_reference if transfer else None,
        "issued_at": (transfer.issued_at or transfer.created_at).isoformat()
        if transfer
        else None,
        "current_recipient_or_location": _recipient_or_location(transfer)
        if transfer
        else (machine.location.name if machine.location else None),
    }


def _availability_message(
    machine: Machine, transfer: TransferProtocol | None, language: str = "bg"
) -> str:
    if transfer:
        details = [
            translate("issue.active", language, number=machine.inventory_number),
            translate(
                "issue.current_status",
                language,
                status=status_label(machine.status, language),
            ),
            translate(
                "issue.protocol", language, protocol=transfer.protocol_number
            ),
        ]
        issued_at = transfer.issued_at or transfer.created_at
        if issued_at:
            details.append(
                translate(
                    "issue.date", language, date=f"{issued_at:%d.%m.%Y %H:%M}"
                )
            )
        recipient = _recipient_or_location(transfer)
        if recipient:
            details.append(
                translate("issue.recipient", language, recipient=recipient)
            )
        return " ".join(details)
    return translate(
        "issue.not_ready",
        language,
        number=machine.inventory_number,
        status=status_label(machine.status, language),
        ready=status_label(MachineStatus.READY.value, language),
    )


def _record_rejection(
    db: Session,
    user: User,
    action: str,
    machine_ids: list[int],
    reason: str,
    conflicts: list[dict[str, Any]] | None = None,
) -> None:
    add_audit_log(
        db,
        user,
        "transfer_operation",
        None,
        action,
        {
            "заявени_machine_ids": machine_ids,
            "резултат": "отказано",
            "причина": reason,
            "конфликти": conflicts or [],
        },
    )
    db.commit()


def _active_transfers_for_machines(
    db: Session, machine_ids: list[int]
) -> dict[int, TransferProtocol]:
    statement = (
        select(TransferProtocol)
        .options(joinedload(TransferProtocol.batch))
        .where(
            TransferProtocol.machine_id.in_(machine_ids),
            TransferProtocol.is_active.is_(True),
        )
    )
    return {
        transfer.machine_id: transfer
        for transfer in db.scalars(statement).unique().all()
    }


def availability(db: Session, language: str = "bg") -> list[dict[str, Any]]:
    machines = db.scalars(
        select(Machine)
        .options(joinedload(Machine.location))
        .order_by(Machine.pressure_bar.desc(), Machine.inventory_number)
    ).all()
    active = _active_transfers_for_machines(db, [machine.id for machine in machines])
    result: list[dict[str, Any]] = []
    for machine in machines:
        transfer = active.get(machine.id)
        is_available = transfer is None and machine.status == MachineStatus.READY.value
        is_returnable = bool(
            transfer
            and transfer.issue_status == TransferOperationStatus.COMPLETED.value
            and transfer.return_status
            != TransferOperationStatus.AWAITING_SIGNATURE.value
        )
        result.append(
            {
                "machine_id": machine.id,
                "machine_number": machine.inventory_number,
                "brand": machine.brand,
                "pressure_bar": machine.pressure_bar,
                "status": machine.status,
                "status_label": status_label(machine.status, language),
                "location": machine.location.name if machine.location else None,
                "available": is_available,
                "returnable": is_returnable,
                "operation_status": (
                    transfer.return_status or transfer.issue_status if transfer else None
                ),
                "unavailable_reason": None
                if is_available
                else _availability_message(machine, transfer, language),
                "active_transfer_id": transfer.id if transfer else None,
                "protocol_number": transfer.protocol_number if transfer else None,
                "batch_reference": transfer.batch_reference if transfer else None,
                "issued_at": (transfer.issued_at or transfer.created_at)
                if transfer
                else None,
                "current_recipient_or_location": _recipient_or_location(transfer)
                if transfer
                else None,
            }
        )
    return result


def _load_issue_machines(
    db: Session, machine_ids: list[int], language: str
) -> tuple[list[Machine], dict[int, TransferProtocol]]:
    statement = (
        select(Machine)
        .where(Machine.id.in_(machine_ids))
        .order_by(Machine.id)
    )
    machines = db.scalars(_for_update(db, statement)).unique().all()
    found_ids = {machine.id for machine in machines}
    missing_ids = sorted(set(machine_ids) - found_ids)
    if missing_ids:
        raise TransferServiceError(
            404,
            "machines_not_found",
            translate("issue.machines_not_found", language),
            {"missing_machine_ids": missing_ids},
        )
    return machines, _active_transfers_for_machines(db, machine_ids)


def _validate_location_ids(
    db: Session, location_ids: set[int], language: str = "bg"
) -> None:
    if not location_ids:
        return
    found = set(
        db.scalars(select(Location.id).where(Location.id.in_(location_ids))).all()
    )
    missing = sorted(location_ids - found)
    if missing:
        raise TransferServiceError(
            404,
            "locations_not_found",
            translate("locations.not_found", language),
            {"missing_location_ids": missing},
        )


def _issue_conflicts(
    machines: list[Machine], active: dict[int, TransferProtocol], language: str
) -> list[dict[str, Any]]:
    conflicts = []
    for machine in machines:
        transfer = active.get(machine.id)
        if transfer is not None or machine.status != MachineStatus.READY.value:
            item = _conflict_item(machine, transfer, language)
            item["message"] = _availability_message(machine, transfer, language)
            conflicts.append(item)
    return conflicts


def _issue_result(
    batch: TransferBatch,
    language: str,
    signing: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    signing = signing or {}
    transfers = []
    for transfer in sorted(batch.transfers, key=lambda item: item.id):
        signing_data = signing.get(transfer.id, {})
        transfers.append(
            {
                "transfer_id": transfer.id,
                "protocol_number": transfer.protocol_number,
                "machine_id": transfer.machine_id,
                "machine_number": transfer.machine.inventory_number,
                "workflow_status": transfer.issue_status,
                "official_document_id": signing_data.get("official_document_id")
                or 0,
                "signing_tasks": signing_data.get("signing_tasks", []),
                "documents": [
                    {
                        "id": document.id,
                        "document_number": document.document_number,
                        "language": document.language,
                        "format": document.format,
                        "filename": document.filename,
                        "download_endpoint": f"/api/protocol-documents/{document.id}/download",
                    }
                    for document in sorted(
                        transfer.documents, key=lambda item: item.format
                    )
                ],
            }
        )
    return {
        "message": translate("issue.awaiting_signature", language),
        "batch_id": batch.id,
        "batch_reference": batch.batch_reference,
        "transfers": transfers,
        "zip_download_endpoint": f"/api/transfer-batches/{batch.id}/documents.zip",
    }


def _bulk_issue_impl(
    db: Session, user: User, data: BulkIssueRequest
) -> dict[str, Any]:
    machine_ids = list(data.machine_ids)
    language = user.preferred_language
    try:
        if data.recipient is None:
            raise TransferServiceError(
                422,
                "recipient_identity_required",
                translate("issue.recipient_identity_required", language),
                {},
            )
        machines, active = _load_issue_machines(db, machine_ids, language)
        _validate_location_ids(
            db,
            {data.location_id} if data.location_id is not None else set(),
            language,
        )
        conflicts = _issue_conflicts(machines, active, language)
        if conflicts:
            raise TransferServiceError(
                409,
                "issue_conflict",
                conflicts[0]["message"],
                {"conflicts": conflicts},
            )

        now = utcnow()
        recipient = data.recipient
        recipient_name = " ".join(
            value
            for value in (
                recipient.first_name,
                recipient.middle_name,
                recipient.last_name,
            )
            if value
        )
        external_signer = create_external_party(
            db, recipient, user, "ACCEPTANCE"
        )
        batch = TransferBatch(
            batch_reference=f"TEMP-{uuid4().hex}",
            status=TransferBatchStatus.ACTIVE.value,
            created_by_id=user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(batch)
        db.flush()
        batch.batch_reference = f"HPWJ-B-{now:%Y%m%d}-{batch.id:06d}"

        machine_by_id = {machine.id: machine for machine in machines}
        transfers: list[TransferProtocol] = []
        document_ids: list[int] = []
        signing_by_transfer: dict[int, dict[str, Any]] = {}
        for machine_id in machine_ids:
            machine = machine_by_id[machine_id]
            previous_status = machine.status
            previous_location_id = machine.location_id
            transfer = TransferProtocol(
                machine_id=machine.id,
                batch_id=batch.id,
                protocol_type="Предаване",
                protocol_number=f"TEMP-{uuid4().hex}",
                is_active=True,
                issue_status=TransferOperationStatus.AWAITING_SIGNATURE.value,
                company_unit=data.company_unit,
                department=data.department,
                vessel=data.vessel,
                dock=data.dock,
                pier=data.pier,
                work_area=data.work_area,
                location_text=data.location_text,
                handed_over_by=user.full_name,
                handed_over_job_title=user.job_title,
                handed_over_department=(
                    user.profile_department.name_bg
                    if user.profile_department
                    else None
                ),
                accepted_by=recipient_name,
                accepted_by_job_title=recipient.job_title,
                accepted_by_company=recipient.company_or_department,
                equipment=data.equipment,
                hoses=data.hoses,
                nozzles=data.nozzles,
                guns=data.guns,
                accessories=data.accessories,
                condition_text=data.condition_text,
                remarks=data.remarks,
                previous_status=previous_status,
                previous_location_id=previous_location_id,
                issue_location_id=data.location_id,
                issued_by_id=user.id,
                issued_at=None,
                created_at=now,
            )
            db.add(transfer)
            db.flush()
            transfer.protocol_number = f"HPWJ-{now:%Y%m%d}-{transfer.id:06d}"
            transfer.machine = machine
            documents = make_protocol_documents(
                db, transfer, batch, user.id, data.document_language.value
            )
            db.add_all(documents)
            db.flush()
            official_document, signing_tasks = prepare_transfer_signing(
                db,
                document_number=transfer.protocol_number,
                document_type=DocumentType.TRANSFER_ISSUE.value,
                actor=user,
                external_signer=external_signer,
                external_slot_code="ACCEPTANCE",
                internal_slot_code="HANDOVER",
            )
            signing_by_transfer[transfer.id] = {
                "official_document_id": official_document.id,
                "signing_tasks": signing_tasks,
            }
            document_ids.extend(document.id for document in documents)
            transfers.append(transfer)
            add_machine_event(
                db,
                machine,
                user,
                "TRANSFER_ISSUE_AWAITING_SIGNATURE",
                reference=transfer.protocol_number,
                previous_status=previous_status,
                new_status=previous_status,
                previous_location_id=previous_location_id,
                new_location_id=previous_location_id,
                details={
                    "batch_reference": batch.batch_reference,
                    "transfer_id": transfer.id,
                    "company_unit": data.company_unit,
                    "department": data.department,
                    "vessel": data.vessel,
                    "dock": data.dock,
                    "pier": data.pier,
                    "work_area": data.work_area,
                    "protocol_document_ids": [document.id for document in documents],
                },
            )
            add_audit_log(
                db,
                user,
                "transfer",
                transfer.id,
                "Издаването очаква подписи",
                {
                    "machine_number": machine.inventory_number,
                    "previous_status": previous_status,
                    "new_status": previous_status,
                    "previous_location_id": previous_location_id,
                    "new_location_id": previous_location_id,
                    "batch_reference": batch.batch_reference,
                    "transfer_id": transfer.id,
                    "protocol_number": transfer.protocol_number,
                    "company_unit": data.company_unit,
                    "department": data.department,
                    "vessel": data.vessel,
                    "dock": data.dock,
                    "pier": data.pier,
                    "work_area": data.work_area,
                    "equipment": data.equipment,
                    "hoses": data.hoses,
                    "nozzles": data.nozzles,
                    "guns": data.guns,
                    "accessories": data.accessories,
                    "protocol_document_ids": [document.id for document in documents],
                    "official_document_id": official_document.id,
                    "workflow_status": transfer.issue_status,
                },
                batch.batch_reference,
            )

        add_audit_log(
            db,
            user,
            "transfer_batch",
            batch.id,
            "Групово издаване – очаква подписи",
            {
                "machine_numbers": _machine_numbers(machines),
                "previous_statuses": {
                    transfer.machine.inventory_number: transfer.previous_status
                    for transfer in transfers
                },
                "new_status": "UNCHANGED_UNTIL_SIGNATURES",
                "transfer_ids": [transfer.id for transfer in transfers],
                "protocol_document_ids": document_ids,
            },
            batch.batch_reference,
        )
        db.commit()
        loaded = db.scalar(
            select(TransferBatch)
            .options(
                selectinload(TransferBatch.transfers)
                .selectinload(TransferProtocol.machine),
                selectinload(TransferBatch.transfers)
                .selectinload(TransferProtocol.documents),
            )
            .where(TransferBatch.id == batch.id)
        )
        assert loaded is not None
        return _issue_result(loaded, language, signing_by_transfer)
    except TransferServiceError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово издаване",
            machine_ids,
            exc.message,
            exc.data.get("conflicts"),
        )
        raise
    except ConfirmedTemplateUnavailableError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово издаване",
            machine_ids,
            exc.message,
        )
        raise TransferServiceError(
            409,
            "document_template_unavailable",
            exc.message,
            {
                "document_type": exc.document_type,
                "requested_language": exc.language,
                "fallback_language": "bg",
            },
        ) from exc
    except TemplateValidationError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово издаване",
            machine_ids,
            str(exc),
        )
        raise TransferServiceError(
            409,
            "document_generation_validation_failed",
            str(exc),
        ) from exc
    except TransferSigningConfigurationError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово издаване",
            machine_ids,
            str(exc),
        )
        raise TransferServiceError(
            409,
            "signature_configuration_invalid",
            str(exc),
            {},
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        active = _active_transfers_for_machines(db, machine_ids)
        machines = db.scalars(
            select(Machine)
            .options(joinedload(Machine.location))
            .where(Machine.id.in_(machine_ids))
        ).unique().all()
        conflicts = [
            {
                **_conflict_item(machine, active.get(machine.id), language),
                "message": _availability_message(
                    machine, active.get(machine.id), language
                ),
            }
            for machine in machines
            if machine.id in active
        ]
        message = (
            conflicts[0]["message"]
            if conflicts
            else translate("issue.concurrent", language)
        )
        _record_rejection(
            db,
            user,
            "Отказано групово издаване",
            machine_ids,
            message,
            conflicts,
        )
        raise TransferServiceError(
            409,
            "concurrent_issue_conflict",
            message,
            {"conflicts": conflicts},
        ) from exc
    except Exception:
        db.rollback()
        try:
            _record_rejection(
                db,
                user,
                "Неуспешно групово издаване",
                machine_ids,
                "Операцията е върната изцяло поради вътрешна грешка.",
            )
        except Exception:
            db.rollback()
        raise


def bulk_issue(
    db: Session, user: User, data: BulkIssueRequest
) -> dict[str, Any]:
    # SQLite has no row-level SELECT FOR UPDATE. A process-local guard provides
    # deterministic development/test behavior; the partial unique index remains
    # authoritative across processes and PostgreSQL uses real row locks.
    with _sqlite_guard(db):
        return _bulk_issue_impl(db, user, data)


def _batch_progress(db: Session, batch: TransferBatch) -> dict[str, Any]:
    total = db.scalar(
        select(func.count(TransferProtocol.id)).where(
            TransferProtocol.batch_id == batch.id
        )
    ) or 0
    still_issued = db.scalar(
        select(func.count(TransferProtocol.id)).where(
            TransferProtocol.batch_id == batch.id,
            TransferProtocol.is_active.is_(True),
            TransferProtocol.issue_status
            == TransferOperationStatus.COMPLETED.value,
        )
    ) or 0
    returned = db.scalar(
        select(func.count(TransferProtocol.id)).where(
            TransferProtocol.batch_id == batch.id,
            TransferProtocol.return_status
            == TransferOperationStatus.COMPLETED.value,
        )
    ) or 0
    awaiting_signature = db.scalar(
        select(func.count(TransferProtocol.id)).where(
            TransferProtocol.batch_id == batch.id,
            (
                (TransferProtocol.issue_status == TransferOperationStatus.AWAITING_SIGNATURE.value)
                | (TransferProtocol.return_status == TransferOperationStatus.AWAITING_SIGNATURE.value)
            ),
        )
    ) or 0
    return {
        "batch_id": batch.id,
        "batch_reference": batch.batch_reference,
        "status": batch.status,
        "total_machines": total,
        "returned_machines": returned,
        "still_issued_machines": still_issued,
        "awaiting_signature_machines": awaiting_signature,
    }


def _set_batch_status(db: Session, batch: TransferBatch) -> dict[str, Any]:
    progress = _batch_progress(db, batch)
    if progress["still_issued_machines"] == 0:
        batch.status = TransferBatchStatus.RETURNED.value
    elif progress["returned_machines"] > 0:
        batch.status = TransferBatchStatus.PARTIALLY_RETURNED.value
    else:
        batch.status = TransferBatchStatus.ACTIVE.value
    batch.updated_at = utcnow()
    progress["status"] = batch.status
    return progress


def finalize_signed_transfer_workflow(
    db: Session,
    document: OfficialDocument,
    version: OfficialDocumentVersion,
    actor: User,
) -> None:
    """Apply the machine movement only after the bound version is fully signed."""
    if document.document_type not in {
        DocumentType.TRANSFER_ISSUE.value,
        DocumentType.TRANSFER_RETURN.value,
    }:
        return
    if version.status != OfficialDocumentStatus.SIGNED.value:
        raise TransferServiceError(
            409,
            "signatures_incomplete",
            "Операцията не може да приключи преди всички задължителни подписи.",
            {"official_document_id": document.id},
        )
    transfer_statement = select(TransferProtocol).where(
        TransferProtocol.id == document.transfer_id
    )
    transfer = db.scalar(_for_update(db, transfer_statement))
    if transfer is None:
        raise TransferServiceError(
            409,
            "transfer_for_document_missing",
            "Свързаното предаване не е намерено; документът не е приложен.",
            {"official_document_id": document.id},
        )
    machine = db.scalar(
        _for_update(db, select(Machine).where(Machine.id == transfer.machine_id))
    )
    if machine is None:
        raise TransferServiceError(
            409,
            "machine_for_transfer_missing",
            "Свързаната машина не е намерена; документът не е приложен.",
            {"transfer_id": transfer.id},
        )
    now = version.finalized_at or utcnow()

    if document.document_type == DocumentType.TRANSFER_ISSUE.value:
        if transfer.issue_status == TransferOperationStatus.COMPLETED.value:
            return
        if transfer.issue_status != TransferOperationStatus.AWAITING_SIGNATURE.value:
            raise TransferServiceError(
                409,
                "issue_workflow_not_pending",
                "Издаването не е в статус „Очаква подпис“.",
                {"transfer_id": transfer.id},
            )
        if machine.status != transfer.previous_status or machine.location_id != transfer.previous_location_id:
            raise TransferServiceError(
                409,
                "machine_changed_during_signing",
                "Машината е променена след началото на подписването; операцията не е приложена.",
                {"transfer_id": transfer.id, "machine_number": machine.inventory_number},
            )
        previous_status = machine.status
        previous_location_id = machine.location_id
        machine.status = MachineStatus.ISSUED.value
        if transfer.issue_location_id is not None:
            machine.location_id = transfer.issue_location_id
        machine.updated_at = now
        transfer.issue_status = TransferOperationStatus.COMPLETED.value
        transfer.issued_at = now
        published_ids: list[int] = []
        for protocol_document in db.scalars(
            select(ProtocolDocument).where(
                ProtocolDocument.transfer_id == transfer.id
            )
        ):
            content = (
                version.docx_content
                if protocol_document.format == "docx"
                else version.pdf_content
            )
            if content:
                protocol_document.content = content
                protocol_document.sha256 = hashlib.sha256(content).hexdigest()
            published_ids.append(protocol_document.id)
        add_machine_event(
            db,
            machine,
            actor,
            "TRANSFER_ISSUED",
            reference=transfer.protocol_number,
            previous_status=previous_status,
            new_status=machine.status,
            previous_location_id=previous_location_id,
            new_location_id=machine.location_id,
            details={
                "batch_reference": transfer.batch_reference,
                "transfer_id": transfer.id,
                "official_document_id": document.id,
                "document_version": version.version,
                "signing_sha256": version.signing_sha256,
                "protocol_document_ids": published_ids,
            },
        )
        add_audit_log(
            db,
            actor,
            "transfer",
            transfer.id,
            "Издаването е приключено след задължителните подписи",
            {
                "machine_number": machine.inventory_number,
                "previous_status": previous_status,
                "new_status": machine.status,
                "previous_location_id": previous_location_id,
                "new_location_id": machine.location_id,
                "batch_reference": transfer.batch_reference,
                "official_document_id": document.id,
                "document_version": version.version,
                "signing_sha256": version.signing_sha256,
                "protocol_document_ids": published_ids,
            },
            transfer.batch_reference,
        )
    else:
        if transfer.return_status == TransferOperationStatus.COMPLETED.value:
            return
        if transfer.return_status != TransferOperationStatus.AWAITING_SIGNATURE.value:
            raise TransferServiceError(
                409,
                "return_workflow_not_pending",
                "Връщането не е в статус „Очаква подпис“.",
                {"transfer_id": transfer.id},
            )
        if not transfer.is_active:
            raise TransferServiceError(
                409,
                "return_already_completed",
                "Предаването вече е приключено и не може да се върне повторно.",
                {"transfer_id": transfer.id},
            )
        if (
            machine.status != transfer.return_previous_status
            or machine.location_id != transfer.return_previous_location_id
        ):
            raise TransferServiceError(
                409,
                "machine_changed_during_signing",
                "Машината е променена след началото на подписването; връщането не е приложено.",
                {"transfer_id": transfer.id, "machine_number": machine.inventory_number},
            )
        previous_status = machine.status
        previous_location_id = machine.location_id
        transfer.is_active = False
        transfer.return_status = TransferOperationStatus.COMPLETED.value
        transfer.returned_at = now
        transfer.returned_by_id = actor.id
        machine.status = transfer.return_next_status or MachineStatus.INSPECTION.value
        if transfer.return_location_id is not None:
            machine.location_id = transfer.return_location_id
        machine.updated_at = now
        generated_ids: list[int] = []
        for format_name, media_type, content in (
            ("docx", DOCX_MEDIA_TYPE, version.docx_content),
            ("pdf", PDF_MEDIA_TYPE, version.pdf_content),
        ):
            if not content:
                continue
            generated = db.scalar(
                select(GeneratedDocument).where(
                    GeneratedDocument.document_number == document.document_number,
                    GeneratedDocument.format == format_name,
                )
            )
            if generated is None:
                generated = GeneratedDocument(
                    document_number=document.document_number,
                    document_type=document.document_type,
                    format=format_name,
                    language=version.language,
                    filename=f"{safe_filename(document.document_number)}.{format_name}",
                    media_type=media_type,
                    content=content,
                    sha256=hashlib.sha256(content).hexdigest(),
                    template_version_id=version.template_version_id,
                    machine_id=machine.id,
                    transfer_id=transfer.id,
                    batch_id=transfer.batch_id,
                    snapshot=version.snapshot,
                    created_by_id=actor.id,
                )
                db.add(generated)
                db.flush()
            else:
                generated.content = content
                generated.sha256 = hashlib.sha256(content).hexdigest()
            generated_ids.append(generated.id)
        add_machine_event(
            db,
            machine,
            actor,
            "TRANSFER_RETURNED",
            reference=document.document_number,
            previous_status=previous_status,
            new_status=machine.status,
            previous_location_id=previous_location_id,
            new_location_id=machine.location_id,
            details={
                "batch_reference": transfer.batch_reference,
                "transfer_id": transfer.id,
                "official_document_id": document.id,
                "document_version": version.version,
                "signing_sha256": version.signing_sha256,
                "generated_document_ids": generated_ids,
            },
        )
        add_audit_log(
            db,
            actor,
            "transfer",
            transfer.id,
            "Връщането е приключено след задължителните подписи",
            {
                "machine_number": machine.inventory_number,
                "previous_status": previous_status,
                "new_status": machine.status,
                "previous_location_id": previous_location_id,
                "new_location_id": machine.location_id,
                "batch_reference": transfer.batch_reference,
                "official_document_id": document.id,
                "document_version": version.version,
                "signing_sha256": version.signing_sha256,
                "generated_document_ids": generated_ids,
                "condition": transfer.return_condition_text,
                "result": transfer.return_result_text,
                "notes": transfer.return_notes,
            },
            transfer.batch_reference,
        )

    db.flush()
    if transfer.batch_id is not None:
        batch = db.get(TransferBatch, transfer.batch_id)
        if batch is not None:
            progress = _set_batch_status(db, batch)
            add_audit_log(
                db,
                actor,
                "transfer_batch",
                batch.id,
                "Актуализиран подписан transfer workflow",
                {**progress, "transfer_id": transfer.id, "machine_number": machine.inventory_number},
                batch.batch_reference,
            )


def _bulk_return_impl(
    db: Session, user: User, data: BulkReturnRequest
) -> dict[str, Any]:
    machine_ids = [item.machine_id for item in data.items]
    transfer_ids = [item.transfer_id for item in data.items]
    language = user.preferred_language
    try:
        machine_statement = (
            select(Machine)
            .where(Machine.id.in_(machine_ids))
            .order_by(Machine.id)
        )
        machines = db.scalars(_for_update(db, machine_statement)).unique().all()
        machine_by_id = {machine.id: machine for machine in machines}
        missing_machine_ids = sorted(set(machine_ids) - set(machine_by_id))
        if missing_machine_ids:
            raise TransferServiceError(
                404,
                "machines_not_found",
                translate("return.machines_not_found", language),
                {"missing_machine_ids": missing_machine_ids},
            )

        transfer_statement = (
            select(TransferProtocol)
            .options(joinedload(TransferProtocol.batch))
            .where(TransferProtocol.id.in_(transfer_ids))
            .order_by(TransferProtocol.id)
        )
        transfers = db.scalars(_for_update(db, transfer_statement)).unique().all()
        transfer_by_id = {transfer.id: transfer for transfer in transfers}
        missing_transfer_ids = sorted(set(transfer_ids) - set(transfer_by_id))
        if missing_transfer_ids:
            raise TransferServiceError(
                404,
                "transfers_not_found",
                translate("return.transfers_not_found", language),
                {"missing_transfer_ids": missing_transfer_ids},
            )

        _validate_location_ids(
            db,
            {item.location_id for item in data.items if item.location_id is not None},
            language,
        )

        conflicts: list[dict[str, Any]] = []
        for item in data.items:
            transfer = transfer_by_id[item.transfer_id]
            machine = machine_by_id[item.machine_id]
            if transfer.machine_id != item.machine_id:
                conflicts.append(
                    {
                        "machine_id": machine.id,
                        "machine_number": machine.inventory_number,
                        "transfer_id": transfer.id,
                        "protocol_number": transfer.protocol_number,
                        "message": translate("return.wrong_transfer", language),
                    }
                )
            elif not transfer.is_active:
                conflicts.append(
                    {
                        "machine_id": machine.id,
                        "machine_number": machine.inventory_number,
                        "transfer_id": transfer.id,
                        "protocol_number": transfer.protocol_number,
                        "message": translate(
                            "return.already_returned",
                            language,
                            number=machine.inventory_number,
                            protocol=transfer.protocol_number,
                        ),
                    }
                )
            elif transfer.issue_status != TransferOperationStatus.COMPLETED.value:
                conflicts.append(
                    {
                        "machine_id": machine.id,
                        "machine_number": machine.inventory_number,
                        "transfer_id": transfer.id,
                        "protocol_number": transfer.protocol_number,
                        "message": translate(
                            "return.issue_not_finalized", language
                        ),
                    }
                )
            elif transfer.return_status == TransferOperationStatus.AWAITING_SIGNATURE.value:
                conflicts.append(
                    {
                        "machine_id": machine.id,
                        "machine_number": machine.inventory_number,
                        "transfer_id": transfer.id,
                        "protocol_number": transfer.protocol_number,
                        "message": translate(
                            "return.already_awaiting_signature", language
                        ),
                    }
                )
            elif item.returned_person is None:
                conflicts.append(
                    {
                        "machine_id": machine.id,
                        "machine_number": machine.inventory_number,
                        "transfer_id": transfer.id,
                        "protocol_number": transfer.protocol_number,
                        "message": translate(
                            "return.returner_identity_required", language
                        ),
                    }
                )
        if conflicts:
            raise TransferServiceError(
                409,
                "return_conflict",
                conflicts[0]["message"],
                {"conflicts": conflicts},
            )

        now = utcnow()
        returned_results: list[dict[str, Any]] = []
        affected_batches: dict[int, TransferBatch] = {}
        for item in data.items:
            transfer = transfer_by_id[item.transfer_id]
            machine = machine_by_id[item.machine_id]
            previous_status = machine.status
            previous_location_id = machine.location_id
            returned_person = item.returned_person
            assert returned_person is not None
            returned_name = " ".join(
                value
                for value in (
                    returned_person.first_name,
                    returned_person.middle_name,
                    returned_person.last_name,
                )
                if value
            )
            external_signer = create_external_party(
                db, returned_person, user, "RETURNED_BY"
            )
            transfer.return_status = TransferOperationStatus.AWAITING_SIGNATURE.value
            transfer.return_requested_at = now
            transfer.returned_at = None
            transfer.return_condition_text = item.condition_text
            transfer.return_result_text = item.result_text
            transfer.return_notes = item.notes
            transfer.return_missing_equipment = item.missing_equipment
            transfer.return_damage = item.damage
            transfer.return_contamination = item.contamination
            transfer.return_cleaning_required = item.cleaning_required
            transfer.return_inspection_required = item.inspection_required
            transfer.return_repair_required = item.repair_required
            transfer.returned_by_name = returned_name
            transfer.returned_by_job_title = returned_person.job_title
            transfer.returned_by_company = returned_person.company_or_department
            transfer.return_accepted_by = user.full_name
            transfer.return_accepted_job_title = user.job_title
            transfer.return_accepted_department = (
                user.profile_department.name_bg if user.profile_department else None
            )
            transfer.return_location_id = item.location_id
            transfer.return_next_status = item.next_status.value
            transfer.return_previous_status = previous_status
            transfer.return_previous_location_id = previous_location_id
            if transfer.batch is not None:
                affected_batches[transfer.batch.id] = transfer.batch
            transfer.machine = machine
            return_documents = make_return_documents(
                db,
                transfer,
                transfer.batch,
                user.id,
                data.document_language.value,
            )
            db.add_all(return_documents)
            db.flush()
            official_document = db.scalar(
                select(OfficialDocument)
                .where(
                    OfficialDocument.transfer_id == transfer.id,
                    OfficialDocument.document_type
                    == DocumentType.TRANSFER_RETURN.value,
                )
                .order_by(OfficialDocument.id.desc())
            )
            if official_document is None:
                raise TransferSigningConfigurationError(
                    "Официалният документ за връщането не е намерен."
                )
            official_document, signing_tasks = prepare_transfer_signing(
                db,
                document_number=official_document.document_number,
                document_type=DocumentType.TRANSFER_RETURN.value,
                actor=user,
                external_signer=external_signer,
                external_slot_code="RETURNED_BY",
                internal_slot_code="ACCEPTED_RETURN",
            )
            add_machine_event(
                db,
                machine,
                user,
                "TRANSFER_RETURN_AWAITING_SIGNATURE",
                reference=f"{transfer.protocol_number}-R",
                previous_status=previous_status,
                new_status=previous_status,
                previous_location_id=previous_location_id,
                new_location_id=previous_location_id,
                details={
                    "batch_reference": transfer.batch_reference,
                    "transfer_id": transfer.id,
                    "condition": item.condition_text,
                    "result": item.result_text,
                    "missing_equipment": item.missing_equipment,
                    "damage": item.damage,
                    "contamination": item.contamination,
                    "cleaning_required": item.cleaning_required,
                    "inspection_required": item.inspection_required,
                    "repair_required": item.repair_required,
                    "generated_document_ids": [
                        document.id for document in return_documents
                    ],
                },
            )
            add_audit_log(
                db,
                user,
                "transfer",
                transfer.id,
                "Връщането очаква подписи",
                {
                    "machine_number": machine.inventory_number,
                    "previous_status": previous_status,
                    "new_status": previous_status,
                    "previous_location_id": previous_location_id,
                    "new_location_id": previous_location_id,
                    "batch_reference": transfer.batch_reference,
                    "transfer_id": transfer.id,
                    "protocol_number": transfer.protocol_number,
                    "condition": item.condition_text,
                    "result": item.result_text,
                    "notes": item.notes,
                    "missing_equipment": item.missing_equipment,
                    "damage": item.damage,
                    "contamination": item.contamination,
                    "cleaning_required": item.cleaning_required,
                    "inspection_required": item.inspection_required,
                    "repair_required": item.repair_required,
                    "returned_by": returned_name,
                    "accepted_by": user.full_name,
                    "workflow_status": transfer.return_status,
                    "official_document_id": official_document.id,
                    "generated_document_ids": [
                        document.id for document in return_documents
                    ],
                },
                transfer.batch_reference,
            )
            returned_results.append(
                {
                    "transfer_id": transfer.id,
                    "machine_id": machine.id,
                    "machine_number": machine.inventory_number,
                    "new_status": item.next_status.value,
                    "returned_at": None,
                    "workflow_status": transfer.return_status,
                    "official_document_id": official_document.id,
                    "signing_tasks": signing_tasks,
                    "documents": [
                        {
                            "id": document.id,
                            "document_number": document.document_number,
                            "language": document.language,
                            "format": document.format,
                            "filename": document.filename,
                            "download_endpoint": (
                                f"/api/generated-documents/{document.id}/download"
                            ),
                        }
                        for document in return_documents
                    ],
                }
            )

        db.flush()
        progresses = [_batch_progress(db, batch) for batch in affected_batches.values()]
        db.commit()
        return {
            "message": translate("return.awaiting_signature", language),
            "returned": returned_results,
            "batches": sorted(progresses, key=lambda item: item["batch_id"]),
        }
    except TransferServiceError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово връщане",
            machine_ids,
            exc.message,
            exc.data.get("conflicts"),
        )
        raise
    except ConfirmedTemplateUnavailableError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово връщане",
            machine_ids,
            exc.message,
        )
        raise TransferServiceError(
            409,
            "document_template_unavailable",
            exc.message,
            {
                "document_type": exc.document_type,
                "requested_language": exc.language,
                "fallback_language": "bg",
            },
        ) from exc
    except TemplateValidationError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово връщане",
            machine_ids,
            str(exc),
        )
        raise TransferServiceError(
            409,
            "document_generation_validation_failed",
            str(exc),
        ) from exc
    except TransferSigningConfigurationError as exc:
        db.rollback()
        _record_rejection(
            db,
            user,
            "Отказано групово връщане",
            machine_ids,
            str(exc),
        )
        raise TransferServiceError(
            409,
            "signature_configuration_invalid",
            str(exc),
            {},
        ) from exc
    except Exception:
        db.rollback()
        try:
            _record_rejection(
                db,
                user,
                "Неуспешно групово връщане",
                machine_ids,
                "Операцията е върната изцяло поради вътрешна грешка.",
            )
        except Exception:
            db.rollback()
        raise


def bulk_return(
    db: Session, user: User, data: BulkReturnRequest
) -> dict[str, Any]:
    with _sqlite_guard(db):
        return _bulk_return_impl(db, user, data)


def batch_progress(
    db: Session, batch_id: int, language: str = "bg"
) -> dict[str, Any]:
    batch = db.get(TransferBatch, batch_id)
    if batch is None:
        raise TransferServiceError(
            404,
            "batch_not_found",
            translate("batch.not_found", language),
            {"batch_id": batch_id},
        )
    return _batch_progress(db, batch)


def batch_details(
    db: Session, batch_id: int, language: str = "bg"
) -> dict[str, Any]:
    batch = db.scalar(
        select(TransferBatch)
        .options(
            selectinload(TransferBatch.transfers)
            .selectinload(TransferProtocol.machine)
            .selectinload(Machine.location),
            selectinload(TransferBatch.transfers)
            .selectinload(TransferProtocol.documents),
        )
        .where(TransferBatch.id == batch_id)
    )
    if batch is None:
        raise TransferServiceError(
            404,
            "batch_not_found",
            translate("batch.not_found", language),
            {"batch_id": batch_id},
        )
    progress = _batch_progress(db, batch)
    return {
        **progress,
        "created_at": batch.created_at,
        "transfers": [
            {
                "transfer_id": transfer.id,
                "machine_id": transfer.machine_id,
                "machine_number": transfer.machine.inventory_number,
                "machine_name": transfer.machine.name,
                "brand": transfer.machine.brand,
                "pressure_bar": transfer.machine.pressure_bar,
                "protocol_number": transfer.protocol_number,
                "is_active": transfer.is_active,
                "issue_status": transfer.issue_status,
                "return_status": transfer.return_status,
                "issued_at": transfer.issued_at,
                "returned_at": transfer.returned_at,
                "current_status": transfer.machine.status,
                "location": transfer.machine.location.name
                if transfer.machine.location
                else None,
                "documents": [
                    {
                        "id": document.id,
                        "document_number": document.document_number,
                        "language": document.language,
                        "format": document.format,
                        "filename": document.filename,
                        "download_endpoint": f"/api/protocol-documents/{document.id}/download",
                    }
                    for document in sorted(
                        transfer.documents, key=lambda item: item.format
                    )
                ],
            }
            for transfer in sorted(batch.transfers, key=lambda item: item.id)
        ],
        "zip_download_endpoint": f"/api/transfer-batches/{batch.id}/documents.zip",
    }


def list_batches(db: Session) -> list[dict[str, Any]]:
    batches = db.scalars(
        select(TransferBatch).order_by(TransferBatch.created_at.desc())
    ).all()
    return [_batch_progress(db, batch) | {"created_at": batch.created_at} for batch in batches]


def get_protocol_document(
    db: Session, document_id: int, language: str = "bg"
) -> ProtocolDocument:
    document = db.get(ProtocolDocument, document_id)
    if document is None:
        raise TransferServiceError(
            404,
            "protocol_document_not_found",
            translate("document.protocol_not_found", language),
            {"document_id": document_id},
        )
    return document
