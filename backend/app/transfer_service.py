from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .audit import add_audit_log
from .document_generation import make_protocol_documents
from .models import (
    Location,
    Machine,
    MachineStatus,
    ProtocolDocument,
    TransferBatch,
    TransferBatchStatus,
    TransferProtocol,
    User,
    utcnow,
)
from .schemas import BulkIssueRequest, BulkReturnRequest

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


def _conflict_item(machine: Machine, transfer: TransferProtocol | None) -> dict[str, Any]:
    return {
        "machine_id": machine.id,
        "machine_number": machine.inventory_number,
        "status": machine.status,
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


def _availability_message(machine: Machine, transfer: TransferProtocol | None) -> str:
    if transfer:
        details = [
            f"Машина №{machine.inventory_number} не може да бъде издадена, "
            "защото има активно предаване и все още не е върната.",
            f"Текущ статус: {machine.status}.",
            f"Протокол: {transfer.protocol_number}.",
        ]
        issued_at = transfer.issued_at or transfer.created_at
        if issued_at:
            details.append(f"Дата на издаване: {issued_at:%d.%m.%Y %H:%M}.")
        recipient = _recipient_or_location(transfer)
        if recipient:
            details.append(f"Получател или място: {recipient}.")
        return " ".join(details)
    return (
        f"Машина №{machine.inventory_number} не може да бъде издадена при статус "
        f"„{machine.status}“. Необходимо е първо да бъде отбелязана като „Готова“."
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


def availability(db: Session) -> list[dict[str, Any]]:
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
        result.append(
            {
                "machine_id": machine.id,
                "machine_number": machine.inventory_number,
                "brand": machine.brand,
                "pressure_bar": machine.pressure_bar,
                "status": machine.status,
                "location": machine.location.name if machine.location else None,
                "available": is_available,
                "unavailable_reason": None
                if is_available
                else _availability_message(machine, transfer),
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
    db: Session, machine_ids: list[int]
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
            "Една или повече избрани машини не са намерени.",
            {"missing_machine_ids": missing_ids},
        )
    return machines, _active_transfers_for_machines(db, machine_ids)


def _validate_location_ids(db: Session, location_ids: set[int]) -> None:
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
            "Едно или повече избрани местоположения не са намерени.",
            {"missing_location_ids": missing},
        )


def _issue_conflicts(
    machines: list[Machine], active: dict[int, TransferProtocol]
) -> list[dict[str, Any]]:
    conflicts = []
    for machine in machines:
        transfer = active.get(machine.id)
        if transfer is not None or machine.status != MachineStatus.READY.value:
            item = _conflict_item(machine, transfer)
            item["message"] = _availability_message(machine, transfer)
            conflicts.append(item)
    return conflicts


def _issue_result(batch: TransferBatch) -> dict[str, Any]:
    transfers = []
    for transfer in sorted(batch.transfers, key=lambda item: item.id):
        transfers.append(
            {
                "transfer_id": transfer.id,
                "protocol_number": transfer.protocol_number,
                "machine_id": transfer.machine_id,
                "machine_number": transfer.machine.inventory_number,
                "documents": [
                    {
                        "id": document.id,
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
        "message": "Груповото издаване е завършено успешно.",
        "batch_id": batch.id,
        "batch_reference": batch.batch_reference,
        "transfers": transfers,
        "zip_download_endpoint": f"/api/transfer-batches/{batch.id}/documents.zip",
    }


def _bulk_issue_impl(
    db: Session, user: User, data: BulkIssueRequest
) -> dict[str, Any]:
    machine_ids = list(data.machine_ids)
    try:
        machines, active = _load_issue_machines(db, machine_ids)
        _validate_location_ids(
            db, {data.location_id} if data.location_id is not None else set()
        )
        conflicts = _issue_conflicts(machines, active)
        if conflicts:
            raise TransferServiceError(
                409,
                "issue_conflict",
                conflicts[0]["message"],
                {"conflicts": conflicts},
            )

        now = utcnow()
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
                company_unit=data.company_unit,
                vessel=data.vessel,
                location_text=data.location_text,
                handed_over_by=data.handed_over_by,
                accepted_by=data.accepted_by,
                equipment=data.equipment,
                condition_text=data.condition_text,
                remarks=data.remarks,
                previous_status=previous_status,
                previous_location_id=previous_location_id,
                issue_location_id=data.location_id,
                issued_by_id=user.id,
                issued_at=now,
                created_at=now,
            )
            db.add(transfer)
            db.flush()
            transfer.protocol_number = f"HPWJ-{now:%Y%m%d}-{transfer.id:06d}"
            machine.status = MachineStatus.ISSUED.value
            if data.location_id is not None:
                machine.location_id = data.location_id
            machine.updated_at = now
            transfer.machine = machine
            documents = make_protocol_documents(transfer, batch, user.id)
            db.add_all(documents)
            db.flush()
            document_ids.extend(document.id for document in documents)
            transfers.append(transfer)
            add_audit_log(
                db,
                user,
                "transfer",
                transfer.id,
                "Издадена машина",
                {
                    "machine_number": machine.inventory_number,
                    "previous_status": previous_status,
                    "new_status": machine.status,
                    "previous_location_id": previous_location_id,
                    "new_location_id": machine.location_id,
                    "batch_reference": batch.batch_reference,
                    "transfer_id": transfer.id,
                    "protocol_number": transfer.protocol_number,
                    "protocol_document_ids": [document.id for document in documents],
                },
                batch.batch_reference,
            )

        add_audit_log(
            db,
            user,
            "transfer_batch",
            batch.id,
            "Групово издаване",
            {
                "machine_numbers": _machine_numbers(machines),
                "previous_statuses": {
                    transfer.machine.inventory_number: transfer.previous_status
                    for transfer in transfers
                },
                "new_status": MachineStatus.ISSUED.value,
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
        return _issue_result(loaded)
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
                **_conflict_item(machine, active.get(machine.id)),
                "message": _availability_message(machine, active.get(machine.id)),
            }
            for machine in machines
            if machine.id in active
        ]
        message = (
            conflicts[0]["message"]
            if conflicts
            else "Издаването е отказано поради едновременна конфликтна операция."
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
        )
    ) or 0
    returned = total - still_issued
    return {
        "batch_id": batch.id,
        "batch_reference": batch.batch_reference,
        "status": batch.status,
        "total_machines": total,
        "returned_machines": returned,
        "still_issued_machines": still_issued,
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


def _bulk_return_impl(
    db: Session, user: User, data: BulkReturnRequest
) -> dict[str, Any]:
    machine_ids = [item.machine_id for item in data.items]
    transfer_ids = [item.transfer_id for item in data.items]
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
                "Една или повече машини за връщане не са намерени.",
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
                "Едно или повече предавания не са намерени.",
                {"missing_transfer_ids": missing_transfer_ids},
            )

        _validate_location_ids(
            db, {item.location_id for item in data.items if item.location_id is not None}
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
                        "message": "Избраното предаване не принадлежи на тази машина.",
                    }
                )
            elif not transfer.is_active:
                conflicts.append(
                    {
                        "machine_id": machine.id,
                        "machine_number": machine.inventory_number,
                        "transfer_id": transfer.id,
                        "protocol_number": transfer.protocol_number,
                        "message": (
                            f"Машина №{machine.inventory_number} вече е върната по "
                            f"протокол {transfer.protocol_number}."
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
            transfer.is_active = False
            transfer.returned_at = now
            transfer.returned_by_id = user.id
            transfer.return_condition_text = item.condition_text
            transfer.return_result_text = item.result_text
            transfer.return_notes = item.notes
            transfer.returned_by_name = item.returned_by
            transfer.return_accepted_by = item.accepted_by
            transfer.return_location_id = item.location_id
            machine.status = item.next_status.value
            if item.location_id is not None:
                machine.location_id = item.location_id
            machine.updated_at = now
            if transfer.batch is not None:
                affected_batches[transfer.batch.id] = transfer.batch
            add_audit_log(
                db,
                user,
                "transfer",
                transfer.id,
                "Върната машина",
                {
                    "machine_number": machine.inventory_number,
                    "previous_status": previous_status,
                    "new_status": machine.status,
                    "previous_location_id": previous_location_id,
                    "new_location_id": machine.location_id,
                    "batch_reference": transfer.batch_reference,
                    "transfer_id": transfer.id,
                    "protocol_number": transfer.protocol_number,
                    "condition": item.condition_text,
                    "result": item.result_text,
                    "notes": item.notes,
                    "returned_by": item.returned_by,
                    "accepted_by": item.accepted_by,
                },
                transfer.batch_reference,
            )
            returned_results.append(
                {
                    "transfer_id": transfer.id,
                    "machine_id": machine.id,
                    "machine_number": machine.inventory_number,
                    "new_status": machine.status,
                    "returned_at": now,
                }
            )

        db.flush()
        progresses = []
        for batch in affected_batches.values():
            progress = _set_batch_status(db, batch)
            progresses.append(progress)
            batch_transfers = [
                transfer
                for transfer in transfer_by_id.values()
                if transfer.batch_id == batch.id
            ]
            add_audit_log(
                db,
                user,
                "transfer_batch",
                batch.id,
                "Актуализирано връщане на партида",
                {
                    **progress,
                    "returned_transfer_ids": [
                        transfer.id for transfer in batch_transfers
                    ],
                    "returned_machine_numbers": [
                        machine_by_id[transfer.machine_id].inventory_number
                        for transfer in batch_transfers
                    ],
                },
                batch.batch_reference,
            )
        db.commit()
        return {
            "message": "Връщането е записано успешно.",
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


def batch_progress(db: Session, batch_id: int) -> dict[str, Any]:
    batch = db.get(TransferBatch, batch_id)
    if batch is None:
        raise TransferServiceError(
            404,
            "batch_not_found",
            "Партидата не е намерена.",
            {"batch_id": batch_id},
        )
    return _batch_progress(db, batch)


def batch_details(db: Session, batch_id: int) -> dict[str, Any]:
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
            "Партидата не е намерена.",
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
                "issued_at": transfer.issued_at,
                "returned_at": transfer.returned_at,
                "current_status": transfer.machine.status,
                "location": transfer.machine.location.name
                if transfer.machine.location
                else None,
                "documents": [
                    {
                        "id": document.id,
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


def get_protocol_document(db: Session, document_id: int) -> ProtocolDocument:
    document = db.get(ProtocolDocument, document_id)
    if document is None:
        raise TransferServiceError(
            404,
            "protocol_document_not_found",
            "Генерираният протокол не е намерен.",
            {"document_id": document_id},
        )
    return document
