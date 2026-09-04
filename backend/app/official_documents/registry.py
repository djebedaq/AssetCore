from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    DocumentParticipant,
    DocumentSignature,
    DocumentType,
    GeneratedDocument,
    Machine,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    PartRequest,
    PartRequestStatus,
    ProtocolDocument,
    Repair,
    RepairStatus,
    SignatureSlot,
    TransferBatch,
    TransferOperationStatus,
    TransferProtocol,
)
from .schemas import OfficialRegistryCategory

SignatureState = str

_TRANSFER_DOCUMENT_TYPES = frozenset(
    {
        DocumentType.TRANSFER_ISSUE.value,
        DocumentType.TRANSFER_RETURN.value,
    }
)
_REPAIR_DOCUMENT_TYPES = frozenset({DocumentType.REPAIR_PROTOCOL.value})
_PART_DOCUMENT_TYPES = frozenset({DocumentType.PART_REQUEST.value})
_REGISTRY_DOCUMENT_TYPES = (
    _TRANSFER_DOCUMENT_TYPES | _REPAIR_DOCUMENT_TYPES | _PART_DOCUMENT_TYPES
)
_DOCUMENT_TYPES_BY_CATEGORY = {
    OfficialRegistryCategory.TRANSFERS: _TRANSFER_DOCUMENT_TYPES,
    OfficialRegistryCategory.REPAIRS: _REPAIR_DOCUMENT_TYPES,
    OfficialRegistryCategory.PARTS: _PART_DOCUMENT_TYPES,
}


@dataclass(frozen=True)
class _DocumentRecord:
    source_key: str
    source_family: str
    source_ids: tuple[int, ...]
    document_type: str
    document_number: str
    machine_id: int | None
    transfer_id: int | None
    repair_id: int | None
    part_request_id: int | None
    official_document_id: int | None
    version: int | None
    version_status: str | None
    created_at: datetime
    finalized_at: datetime | None
    signature_status: SignatureState
    files: tuple[dict[str, Any], ...]

    @property
    def effective_at(self) -> datetime:
        return self.finalized_at or self.created_at

    def output(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "document_number": self.document_number,
            "official_document_id": self.official_document_id,
            "version": self.version,
            "version_status": self.version_status,
            "files": list(self.files),
        }


@dataclass(frozen=True)
class _RegistryCandidate:
    registry_key: str
    domain_id: int | None
    machine_id: int | None
    created_at: datetime | None
    started_at: datetime | None
    search_values: tuple[str, ...]
    records: tuple[_DocumentRecord, ...]

    @property
    def effective_at(self) -> datetime:
        return self.created_at or self.started_at or datetime.min

    def matches(self, query: str) -> bool:
        folded = query.casefold()
        return any(folded in value.casefold() for value in self.search_values)


def _snapshot_id(snapshot: object, key: str) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(key)
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _signature_states(
    db: Session, version_rows: list[tuple[int, str]]
) -> dict[int, SignatureState]:
    if not version_rows:
        return {}
    version_ids = [version_id for version_id, _ in version_rows]
    document_types = {document_type for _, document_type in version_rows}
    required_by_type: dict[str, set[str]] = defaultdict(set)
    for document_type, code in db.execute(
        select(SignatureSlot.document_type, SignatureSlot.code).where(
            SignatureSlot.document_type.in_(document_types),
            SignatureSlot.required.is_(True),
            SignatureSlot.is_active.is_(True),
        )
    ):
        required_by_type[document_type].add(code)

    participant_slots: dict[int, dict[int, str]] = defaultdict(dict)
    for participant_id, version_id, slot_code in db.execute(
        select(
            DocumentParticipant.id,
            DocumentParticipant.document_version_id,
            DocumentParticipant.slot_code,
        ).where(DocumentParticipant.document_version_id.in_(version_ids))
    ):
        participant_slots[version_id][participant_id] = slot_code

    signed_participants: dict[int, set[int]] = defaultdict(set)
    for version_id, participant_id in db.execute(
        select(
            DocumentSignature.document_version_id,
            DocumentSignature.participant_id,
        ).where(
            DocumentSignature.document_version_id.in_(version_ids),
            DocumentSignature.confirmed_at.is_not(None),
        )
    ):
        signed_participants[version_id].add(participant_id)

    states: dict[int, SignatureState] = {}
    for version_id, document_type in version_rows:
        required_slots = required_by_type.get(document_type, set())
        if not required_slots:
            states[version_id] = "NOT_REQUIRED"
            continue
        signed_slots = {
            slot_code
            for participant_id, slot_code in participant_slots.get(version_id, {}).items()
            if participant_id in signed_participants.get(version_id, set())
        }
        if required_slots.issubset(signed_slots):
            states[version_id] = "SIGNED"
        elif signed_slots:
            states[version_id] = "PARTIALLY_SIGNED"
        else:
            states[version_id] = "UNSIGNED"
    return states


def _official_records(
    db: Session,
    *,
    document_types: Collection[str] = _REGISTRY_DOCUMENT_TYPES,
    document_ids: Collection[int] | None = None,
    machine_id: int | None = None,
    include_signatures: bool = True,
    include_files: bool = True,
) -> list[_DocumentRecord]:
    if not document_types or document_ids is not None and not document_ids:
        return []
    statement = (
        select(
            OfficialDocument.id,
            OfficialDocument.document_number,
            OfficialDocument.document_type,
            OfficialDocument.machine_id,
            OfficialDocument.transfer_id,
            OfficialDocument.created_at,
            OfficialDocumentVersion.id.label("version_id"),
            OfficialDocumentVersion.version,
            OfficialDocumentVersion.status,
            OfficialDocumentVersion.snapshot,
            OfficialDocumentVersion.docx_sha256,
            OfficialDocumentVersion.pdf_sha256,
            OfficialDocumentVersion.created_at.label("version_created_at"),
            OfficialDocumentVersion.finalized_at,
        )
        .join(
            OfficialDocumentVersion,
            OfficialDocumentVersion.id == OfficialDocument.current_version_id,
        )
        .where(OfficialDocument.document_type.in_(document_types))
    )
    if document_ids is not None:
        statement = statement.where(OfficialDocument.id.in_(document_ids))
    if machine_id is not None:
        statement = statement.where(
            or_(
                OfficialDocument.machine_id == machine_id,
                OfficialDocument.transfer_id.in_(
                    select(TransferProtocol.id).where(
                        TransferProtocol.machine_id == machine_id
                    )
                ),
            )
        )
    rows = list(
        db.execute(
            statement.order_by(
                OfficialDocument.created_at.desc(), OfficialDocument.id.desc()
            )
        )
    )
    signature_states = (
        _signature_states(db, [(row.version_id, row.document_type) for row in rows])
        if include_signatures
        else {}
    )
    records: list[_DocumentRecord] = []
    for row in rows:
        files: list[dict[str, Any]] = []
        if include_files:
            for file_format, sha256 in (
                ("docx", row.docx_sha256),
                ("pdf", row.pdf_sha256),
            ):
                if sha256:
                    endpoint = (
                        f"/official-documents/{row.id}/versions/"
                        f"{row.version}/download/{file_format}"
                    )
                    files.append(
                        {
                            "format": file_format,
                            "download_endpoint": endpoint,
                            "preview_endpoint": (
                                f"/official-documents/{row.id}/preview/{file_format}"
                            ),
                        }
                    )
        records.append(
            _DocumentRecord(
                source_key=f"official:{row.id}",
                source_family="official",
                source_ids=(row.id,),
                document_type=row.document_type,
                document_number=row.document_number,
                machine_id=row.machine_id,
                transfer_id=row.transfer_id,
                repair_id=_snapshot_id(row.snapshot, "repair_id"),
                part_request_id=_snapshot_id(row.snapshot, "request_id"),
                official_document_id=row.id,
                version=row.version,
                version_status=row.status,
                created_at=row.version_created_at or row.created_at,
                finalized_at=row.finalized_at,
                signature_status=signature_states.get(row.version_id, "UNKNOWN"),
                files=tuple(files),
            )
        )
    return records


def _legacy_generated_records(
    db: Session,
    *,
    document_types: Collection[str] = _REGISTRY_DOCUMENT_TYPES,
    row_ids: Collection[int] | None = None,
    machine_id: int | None = None,
    include_files: bool = True,
) -> list[_DocumentRecord]:
    if not document_types or row_ids is not None and not row_ids:
        return []
    statement = select(
        GeneratedDocument.id,
        GeneratedDocument.document_number,
        GeneratedDocument.document_type,
        GeneratedDocument.format,
        GeneratedDocument.machine_id,
        GeneratedDocument.repair_id,
        GeneratedDocument.part_request_id,
        GeneratedDocument.transfer_id,
        GeneratedDocument.created_at,
    ).where(GeneratedDocument.document_type.in_(document_types))
    if row_ids is not None:
        statement = statement.where(GeneratedDocument.id.in_(row_ids))
    if machine_id is not None:
        statement = statement.where(
            or_(
                GeneratedDocument.machine_id == machine_id,
                GeneratedDocument.transfer_id.in_(
                    select(TransferProtocol.id).where(
                        TransferProtocol.machine_id == machine_id
                    )
                ),
                GeneratedDocument.repair_id.in_(
                    select(Repair.id).where(Repair.machine_id == machine_id)
                ),
                GeneratedDocument.part_request_id.in_(
                    select(PartRequest.id).where(
                        PartRequest.machine_id == machine_id
                    )
                ),
            )
        )
    rows = list(
        db.execute(
            statement.order_by(
                GeneratedDocument.created_at.desc(), GeneratedDocument.id.desc()
            )
        )
    )
    grouped: dict[tuple[Any, ...], list[Any]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row.document_type,
                row.document_number,
                row.transfer_id,
                row.repair_id,
                row.part_request_id,
            )
        ].append(row)
    records: list[_DocumentRecord] = []
    for group_rows in grouped.values():
        first = group_rows[0]
        files_by_format: dict[str, dict[str, Any]] = {}
        if include_files:
            for row in group_rows:
                if (
                    row.format in {"docx", "pdf"}
                    and row.format not in files_by_format
                ):
                    files_by_format[row.format] = {
                        "format": row.format,
                        "download_endpoint": f"/generated-documents/{row.id}/download",
                        "preview_endpoint": None,
                    }
        records.append(
            _DocumentRecord(
                source_key=f"generated:{first.id}",
                source_family="generated",
                source_ids=tuple(row.id for row in group_rows),
                document_type=first.document_type,
                document_number=first.document_number,
                machine_id=first.machine_id,
                transfer_id=first.transfer_id,
                repair_id=first.repair_id,
                part_request_id=first.part_request_id,
                official_document_id=None,
                version=None,
                version_status=None,
                created_at=first.created_at,
                finalized_at=None,
                signature_status="UNKNOWN",
                files=tuple(files_by_format.values()),
            )
        )
    return records


def _legacy_issue_records(
    db: Session,
    *,
    row_ids: Collection[int] | None = None,
    machine_id: int | None = None,
    include_files: bool = True,
) -> list[_DocumentRecord]:
    if row_ids is not None and not row_ids:
        return []
    statement = (
        select(
            ProtocolDocument.id,
            ProtocolDocument.document_number,
            ProtocolDocument.format,
            ProtocolDocument.machine_id,
            ProtocolDocument.transfer_id,
            ProtocolDocument.created_at,
            TransferProtocol.protocol_number,
        )
        .join(TransferProtocol, TransferProtocol.id == ProtocolDocument.transfer_id)
    )
    if row_ids is not None:
        statement = statement.where(ProtocolDocument.id.in_(row_ids))
    if machine_id is not None:
        statement = statement.where(ProtocolDocument.machine_id == machine_id)
    rows = list(
        db.execute(
            statement.order_by(
                ProtocolDocument.created_at.desc(), ProtocolDocument.id.desc()
            )
        )
    )
    grouped: dict[tuple[int, str], list[Any]] = defaultdict(list)
    for row in rows:
        grouped[(row.transfer_id, row.document_number or row.protocol_number)].append(row)
    records: list[_DocumentRecord] = []
    for (transfer_id, number), group_rows in grouped.items():
        first = group_rows[0]
        files_by_format: dict[str, dict[str, Any]] = {}
        if include_files:
            for row in group_rows:
                if (
                    row.format in {"docx", "pdf"}
                    and row.format not in files_by_format
                ):
                    files_by_format[row.format] = {
                        "format": row.format,
                        "download_endpoint": f"/protocol-documents/{row.id}/download",
                        "preview_endpoint": None,
                    }
        records.append(
            _DocumentRecord(
                source_key=f"protocol:{first.id}",
                source_family="protocol",
                source_ids=tuple(row.id for row in group_rows),
                document_type=DocumentType.TRANSFER_ISSUE.value,
                document_number=number,
                machine_id=first.machine_id,
                transfer_id=transfer_id,
                repair_id=None,
                part_request_id=None,
                official_document_id=None,
                version=None,
                version_status=None,
                created_at=first.created_at,
                finalized_at=None,
                signature_status="UNKNOWN",
                files=tuple(files_by_format.values()),
            )
        )
    return records


def _combine_signature_status(records: list[_DocumentRecord]) -> SignatureState:
    states = {record.signature_status for record in records}
    if not states or states == {"UNKNOWN"}:
        return "UNKNOWN"
    if states == {"NOT_REQUIRED"}:
        return "NOT_REQUIRED"
    if states.issubset({"SIGNED", "NOT_REQUIRED"}):
        return "SIGNED" if "SIGNED" in states else "NOT_REQUIRED"
    if "SIGNED" in states or "PARTIALLY_SIGNED" in states:
        return "PARTIALLY_SIGNED"
    if "UNSIGNED" in states:
        return "UNSIGNED"
    return "UNKNOWN"


def _deduplicate_records(
    official: list[_DocumentRecord], legacy: list[_DocumentRecord]
) -> list[_DocumentRecord]:
    official_keys = {
        (
            record.document_type,
            record.document_number,
            record.transfer_id,
            record.repair_id,
            record.part_request_id,
        )
        for record in official
    }
    return official + [
        record
        for record in legacy
        if (
            record.document_type,
            record.document_number,
            record.transfer_id,
            record.repair_id,
            record.part_request_id,
        )
        not in official_keys
    ]


def _candidate_document_records(
    db: Session,
    category: OfficialRegistryCategory,
    *,
    machine_id: int | None = None,
) -> list[_DocumentRecord]:
    """Load selected-category identity metadata without signatures or file payloads."""
    document_types = _DOCUMENT_TYPES_BY_CATEGORY[category]
    official = _official_records(
        db,
        document_types=document_types,
        machine_id=machine_id,
        include_signatures=False,
        include_files=False,
    )
    legacy = _legacy_generated_records(
        db,
        document_types=document_types,
        machine_id=machine_id,
        include_files=False,
    )
    if category == OfficialRegistryCategory.TRANSFERS:
        legacy += _legacy_issue_records(
            db, machine_id=machine_id, include_files=False
        )
    return _deduplicate_records(official, legacy)


def _machine_number_map(
    db: Session, machine_ids: Collection[int | None]
) -> dict[int, str]:
    ids = {machine_id for machine_id in machine_ids if machine_id is not None}
    if not ids:
        return {}
    return dict(
        db.execute(
            select(Machine.id, Machine.inventory_number).where(Machine.id.in_(ids))
        ).all()
    )


def _candidate_search_values(
    records: Collection[_DocumentRecord], *values: object
) -> tuple[str, ...]:
    return tuple(
        str(value)
        for value in (
            *(record.document_number for record in records),
            *values,
        )
        if value is not None and str(value)
    )


def _transfer_candidates(
    db: Session, records: list[_DocumentRecord]
) -> list[_RegistryCandidate]:
    by_transfer: dict[int, list[_DocumentRecord]] = defaultdict(list)
    for record in records:
        if record.transfer_id is not None and record.document_type in (
            _TRANSFER_DOCUMENT_TYPES
        ):
            by_transfer[record.transfer_id].append(record)
    if not by_transfer:
        return []
    rows = {
        row.transfer_id: row
        for row in db.execute(
            select(
                TransferProtocol.id.label("transfer_id"),
                TransferProtocol.machine_id,
                TransferProtocol.protocol_number,
                TransferProtocol.issue_status,
                TransferProtocol.return_status,
                TransferProtocol.issued_at,
                TransferProtocol.returned_at,
                Machine.inventory_number.label("machine_number"),
                TransferBatch.batch_reference,
            )
            .join(Machine, Machine.id == TransferProtocol.machine_id)
            .outerjoin(TransferBatch, TransferBatch.id == TransferProtocol.batch_id)
            .where(TransferProtocol.id.in_(by_transfer))
        )
    }
    candidates: list[_RegistryCandidate] = []
    for transfer_id, transfer_records in by_transfer.items():
        row = rows.get(transfer_id)
        if row is None:
            continue
        unique_records = list(
            {record.source_key: record for record in transfer_records}.values()
        )
        unique_records.sort(
            key=lambda record: (
                record.document_type == DocumentType.TRANSFER_RETURN.value,
                record.effective_at,
                record.source_key,
            )
        )
        issue_records = [
            record
            for record in unique_records
            if record.document_type == DocumentType.TRANSFER_ISSUE.value
        ]
        return_records = [
            record
            for record in unique_records
            if record.document_type == DocumentType.TRANSFER_RETURN.value
        ]
        completed = bool(issue_records) and bool(return_records) and (
            row.return_status == TransferOperationStatus.COMPLETED.value
            or row.returned_at is not None
        )
        started_candidates = [record.effective_at for record in issue_records]
        if row.issued_at:
            started_candidates.append(row.issued_at)
        completed_candidates = [
            record.finalized_at or record.created_at for record in return_records
        ]
        if row.returned_at:
            completed_candidates.append(row.returned_at)
        candidates.append(
            _RegistryCandidate(
                registry_key=f"transfer:{transfer_id}",
                domain_id=transfer_id,
                machine_id=row.machine_id,
                created_at=max(completed_candidates) if completed else None,
                started_at=(
                    max(started_candidates) if started_candidates else None
                ),
                search_values=_candidate_search_values(
                    unique_records,
                    row.machine_number,
                    row.protocol_number,
                    row.batch_reference,
                ),
                records=tuple(unique_records),
            )
        )
    return candidates


def _repair_candidates(
    db: Session, records: list[_DocumentRecord]
) -> list[_RegistryCandidate]:
    repair_records = [
        record
        for record in records
        if record.document_type == DocumentType.REPAIR_PROTOCOL.value
    ]
    if not repair_records:
        return []
    references = {record.document_number for record in repair_records}
    repair_ids = {
        record.repair_id
        for record in repair_records
        if record.repair_id is not None
    }
    predicates = []
    if repair_ids:
        predicates.append(Repair.id.in_(repair_ids))
    if references:
        predicates.append(Repair.repair_reference.in_(references))
    rows = list(
        db.execute(
            select(
                Repair.id.label("repair_id"),
                Repair.machine_id,
                Repair.repair_reference,
                Repair.opened_at,
                Repair.closed_at,
                Machine.inventory_number.label("machine_number"),
            )
            .join(Machine, Machine.id == Repair.machine_id)
            .where(or_(*predicates))
        )
    )
    rows_by_id = {row.repair_id: row for row in rows}
    rows_by_reference = {
        row.repair_reference: row for row in rows if row.repair_reference
    }
    official_repair_ids: set[int] = set()
    resolved: list[tuple[_DocumentRecord, Any | None]] = []
    for record in repair_records:
        row = rows_by_id.get(record.repair_id) or rows_by_reference.get(
            record.document_number
        )
        resolved.append((record, row))
        if record.official_document_id is not None and row is not None:
            official_repair_ids.add(row.repair_id)

    grouped: dict[str, list[tuple[_DocumentRecord, Any | None]]] = defaultdict(
        list
    )
    for record, row in resolved:
        if (
            record.official_document_id is None
            and row is not None
            and row.repair_id in official_repair_ids
        ):
            continue
        key = f"repair:{row.repair_id}" if row is not None else record.source_key
        grouped[key].append((record, row))

    machine_numbers = _machine_number_map(
        db, [record.machine_id for record in repair_records]
    )
    candidates: list[_RegistryCandidate] = []
    for registry_key, values in grouped.items():
        records_for_item = [record for record, _ in values]
        row = next((value for _, value in values if value is not None), None)
        records_for_item.sort(key=lambda record: (record.effective_at, record.source_key))
        machine_number = (
            row.machine_number
            if row is not None
            else machine_numbers.get(records_for_item[-1].machine_id)
        )
        candidates.append(
            _RegistryCandidate(
                registry_key=registry_key,
                domain_id=row.repair_id if row is not None else None,
                machine_id=(
                    row.machine_id
                    if row is not None
                    else records_for_item[-1].machine_id
                ),
                created_at=max(
                    [record.effective_at for record in records_for_item]
                    + ([row.closed_at] if row is not None and row.closed_at else [])
                ),
                started_at=row.opened_at if row is not None else None,
                search_values=_candidate_search_values(
                    records_for_item,
                    machine_number,
                    row.repair_reference if row is not None else None,
                ),
                records=tuple(records_for_item),
            )
        )
    return candidates


def _part_candidates(
    db: Session, records: list[_DocumentRecord]
) -> list[_RegistryCandidate]:
    part_records = [
        record
        for record in records
        if record.document_type == DocumentType.PART_REQUEST.value
    ]
    if not part_records:
        return []
    references = {record.document_number for record in part_records}
    request_ids = {
        record.part_request_id
        for record in part_records
        if record.part_request_id is not None
    }
    predicates = []
    if request_ids:
        predicates.append(PartRequest.id.in_(request_ids))
    if references:
        predicates.append(PartRequest.request_reference.in_(references))
    rows = list(
        db.execute(
            select(
                PartRequest.id.label("request_id"),
                PartRequest.machine_id,
                PartRequest.request_reference,
                PartRequest.created_at,
                Machine.inventory_number.label("machine_number"),
            )
            .outerjoin(Machine, Machine.id == PartRequest.machine_id)
            .where(or_(*predicates))
        )
    )
    rows_by_id = {row.request_id: row for row in rows}
    rows_by_reference = {
        row.request_reference: row for row in rows if row.request_reference
    }
    official_request_ids: set[int] = set()
    resolved: list[tuple[_DocumentRecord, Any | None]] = []
    for record in part_records:
        row = rows_by_id.get(record.part_request_id) or rows_by_reference.get(
            record.document_number
        )
        resolved.append((record, row))
        if record.official_document_id is not None and row is not None:
            official_request_ids.add(row.request_id)

    grouped: dict[str, list[tuple[_DocumentRecord, Any | None]]] = defaultdict(
        list
    )
    for record, row in resolved:
        if (
            record.official_document_id is None
            and row is not None
            and row.request_id in official_request_ids
        ):
            continue
        key = (
            f"part-request:{row.request_id}"
            if row is not None
            else record.source_key
        )
        grouped[key].append((record, row))

    machine_numbers = _machine_number_map(
        db, [record.machine_id for record in part_records]
    )
    candidates: list[_RegistryCandidate] = []
    for registry_key, values in grouped.items():
        records_for_item = [record for record, _ in values]
        row = next((value for _, value in values if value is not None), None)
        records_for_item.sort(key=lambda record: (record.effective_at, record.source_key))
        machine_number = (
            row.machine_number
            if row is not None
            else machine_numbers.get(records_for_item[-1].machine_id)
        )
        candidates.append(
            _RegistryCandidate(
                registry_key=registry_key,
                domain_id=row.request_id if row is not None else None,
                machine_id=(
                    row.machine_id
                    if row is not None
                    else records_for_item[-1].machine_id
                ),
                created_at=max(record.effective_at for record in records_for_item),
                started_at=row.created_at if row is not None else None,
                search_values=_candidate_search_values(
                    records_for_item,
                    machine_number,
                    row.request_reference if row is not None else None,
                ),
                records=tuple(records_for_item),
            )
        )
    return candidates


def _registry_candidates(
    db: Session,
    category: OfficialRegistryCategory,
    query: str = "",
    *,
    machine_id: int | None = None,
) -> list[_RegistryCandidate]:
    records = _candidate_document_records(db, category, machine_id=machine_id)
    if category == OfficialRegistryCategory.TRANSFERS:
        candidates = _transfer_candidates(db, records)
    elif category == OfficialRegistryCategory.REPAIRS:
        candidates = _repair_candidates(db, records)
    else:
        candidates = _part_candidates(db, records)
    if machine_id is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.machine_id == machine_id
        ]
    if query:
        candidates = [candidate for candidate in candidates if candidate.matches(query)]
    candidates.sort(
        key=lambda candidate: (candidate.effective_at, candidate.registry_key),
        reverse=True,
    )
    return candidates


def _transfer_items(db: Session, records: list[_DocumentRecord]) -> list[dict[str, Any]]:
    by_transfer: dict[int, list[_DocumentRecord]] = defaultdict(list)
    for record in records:
        if record.transfer_id is not None and record.document_type in {
            DocumentType.TRANSFER_ISSUE.value,
            DocumentType.TRANSFER_RETURN.value,
        }:
            by_transfer[record.transfer_id].append(record)
    if not by_transfer:
        return []
    transfers = {
        transfer.id: transfer
        for transfer in db.scalars(
            select(TransferProtocol)
            .options(selectinload(TransferProtocol.machine))
            .where(TransferProtocol.id.in_(by_transfer))
        )
    }
    items: list[dict[str, Any]] = []
    for transfer_id, transfer_records in by_transfer.items():
        transfer = transfers.get(transfer_id)
        if transfer is None:
            continue
        unique_records = list({record.source_key: record for record in transfer_records}.values())
        unique_records.sort(
            key=lambda record: (
                record.document_type == DocumentType.TRANSFER_RETURN.value,
                record.effective_at,
                record.source_key,
            )
        )
        issue_records = [
            record
            for record in unique_records
            if record.document_type == DocumentType.TRANSFER_ISSUE.value
        ]
        return_records = [
            record
            for record in unique_records
            if record.document_type == DocumentType.TRANSFER_RETURN.value
        ]
        completed = bool(issue_records) and bool(return_records) and (
            transfer.return_status == TransferOperationStatus.COMPLETED.value
            or transfer.returned_at is not None
        )
        started_candidates = [record.effective_at for record in issue_records]
        if transfer.issued_at:
            started_candidates.append(transfer.issued_at)
        completed_candidates = [
            record.finalized_at or record.created_at for record in return_records
        ]
        if transfer.returned_at:
            completed_candidates.append(transfer.returned_at)
        items.append(
            {
                "registry_key": f"transfer:{transfer.id}",
                "domain_id": transfer.id,
                "machine_id": transfer.machine_id,
                "machine_number": transfer.machine.inventory_number,
                "status": "COMPLETE" if completed else "INCOMPLETE",
                "signature_status": _combine_signature_status(unique_records),
                "created_at": max(completed_candidates) if completed else None,
                "started_at": max(started_candidates) if started_candidates else None,
                "documents": [record.output() for record in unique_records],
            }
        )
    return items


def _repair_items(db: Session, records: list[_DocumentRecord]) -> list[dict[str, Any]]:
    repair_records = [
        record
        for record in records
        if record.document_type == DocumentType.REPAIR_PROTOCOL.value
    ]
    if not repair_records:
        return []
    references = {record.document_number for record in repair_records}
    repair_ids = {record.repair_id for record in repair_records if record.repair_id is not None}
    repairs = list(
        db.scalars(
            select(Repair)
            .options(selectinload(Repair.machine))
            .where(
                (Repair.id.in_(repair_ids) if repair_ids else False)
                | Repair.repair_reference.in_(references)
            )
        )
    )
    repairs_by_id = {repair.id: repair for repair in repairs}
    repairs_by_reference = {
        repair.repair_reference: repair
        for repair in repairs
        if repair.repair_reference
    }
    official_repair_ids: set[int] = set()
    for record in repair_records:
        repair = repairs_by_id.get(record.repair_id) or repairs_by_reference.get(
            record.document_number
        )
        if record.official_document_id is not None and repair is not None:
            official_repair_ids.add(repair.id)

    grouped: dict[str, list[tuple[_DocumentRecord, Repair | None]]] = defaultdict(list)
    for record in repair_records:
        repair = repairs_by_id.get(record.repair_id) or repairs_by_reference.get(
            record.document_number
        )
        if (
            record.official_document_id is None
            and repair is not None
            and repair.id in official_repair_ids
        ):
            continue
        key = f"repair:{repair.id}" if repair else record.source_key
        grouped[key].append((record, repair))

    items: list[dict[str, Any]] = []
    for registry_key, values in grouped.items():
        records_for_item = [record for record, _ in values]
        repair = next((value for _, value in values if value is not None), None)
        records_for_item.sort(key=lambda record: (record.effective_at, record.source_key))
        status = records_for_item[-1].version_status or (
            repair.status if repair else "UNKNOWN"
        )
        if repair is not None and repair.status == RepairStatus.COMPLETED.value:
            status = "COMPLETE"
        machine_id = repair.machine_id if repair else records_for_item[-1].machine_id
        machine_number = repair.machine.inventory_number if repair else None
        items.append(
            {
                "registry_key": registry_key,
                "domain_id": repair.id if repair else None,
                "machine_id": machine_id,
                "machine_number": machine_number,
                "status": status,
                "signature_status": _combine_signature_status(records_for_item),
                "created_at": max(
                    [record.effective_at for record in records_for_item]
                    + ([repair.closed_at] if repair and repair.closed_at else [])
                ),
                "started_at": repair.opened_at if repair else None,
                "documents": [record.output() for record in records_for_item],
            }
        )
    return items


def _part_items(db: Session, records: list[_DocumentRecord]) -> list[dict[str, Any]]:
    part_records = [
        record
        for record in records
        if record.document_type == DocumentType.PART_REQUEST.value
    ]
    if not part_records:
        return []
    references = {record.document_number for record in part_records}
    request_ids = {
        record.part_request_id
        for record in part_records
        if record.part_request_id is not None
    }
    requests = list(
        db.scalars(
            select(PartRequest)
            .options(selectinload(PartRequest.machine))
            .where(
                (PartRequest.id.in_(request_ids) if request_ids else False)
                | PartRequest.request_reference.in_(references)
            )
        )
    )
    requests_by_id = {request.id: request for request in requests}
    requests_by_reference = {
        request.request_reference: request
        for request in requests
        if request.request_reference
    }
    official_request_ids: set[int] = set()
    for record in part_records:
        request = requests_by_id.get(
            record.part_request_id
        ) or requests_by_reference.get(record.document_number)
        if record.official_document_id is not None and request is not None:
            official_request_ids.add(request.id)

    grouped: dict[str, list[tuple[_DocumentRecord, PartRequest | None]]] = defaultdict(
        list
    )
    for record in part_records:
        request = requests_by_id.get(
            record.part_request_id
        ) or requests_by_reference.get(record.document_number)
        if (
            record.official_document_id is None
            and request is not None
            and request.id in official_request_ids
        ):
            continue
        key = f"part-request:{request.id}" if request else record.source_key
        grouped[key].append((record, request))

    items: list[dict[str, Any]] = []
    for registry_key, values in grouped.items():
        records_for_item = [record for record, _ in values]
        request = next((value for _, value in values if value is not None), None)
        records_for_item.sort(key=lambda record: (record.effective_at, record.source_key))
        current_record = records_for_item[-1]
        if request is not None and request.status == PartRequestStatus.CANCELLED.value:
            status = PartRequestStatus.CANCELLED.value
        elif current_record.version_status in {
            OfficialDocumentStatus.SIGNED.value,
            OfficialDocumentStatus.FINALIZED.value,
        }:
            status = "COMPLETE"
        elif request is not None and request.status in {
            PartRequestStatus.APPROVED.value,
            PartRequestStatus.ORDERED.value,
            PartRequestStatus.PARTIALLY_DELIVERED.value,
            PartRequestStatus.DELIVERED.value,
        }:
            status = "COMPLETE"
        else:
            status = (
                request.status
                if request
                else (current_record.version_status or "UNKNOWN")
            )
        items.append(
            {
                "registry_key": registry_key,
                "domain_id": request.id if request else None,
                "machine_id": (
                    request.machine_id if request else current_record.machine_id
                ),
                "machine_number": (
                    request.machine.inventory_number
                    if request is not None and request.machine is not None
                    else None
                ),
                "status": status,
                "signature_status": _combine_signature_status(records_for_item),
                "created_at": max(
                    record.effective_at for record in records_for_item
                ),
                "started_at": request.created_at if request else None,
                "documents": [record.output() for record in records_for_item],
            }
        )
    return items


def _fill_machine_numbers(db: Session, sections: list[list[dict[str, Any]]]) -> None:
    missing_ids = {
        item["machine_id"]
        for section in sections
        for item in section
        if item["machine_id"] is not None and not item["machine_number"]
    }
    if not missing_ids:
        return
    numbers = dict(
        db.execute(
            select(Machine.id, Machine.inventory_number).where(Machine.id.in_(missing_ids))
        )
    )
    for section in sections:
        for item in section:
            if not item["machine_number"]:
                item["machine_number"] = numbers.get(item["machine_id"])


def _sort_items(items: list[dict[str, Any]]) -> None:
    minimum = datetime.min
    items.sort(
        key=lambda item: (
            item["created_at"] or item["started_at"] or minimum,
            item["registry_key"],
        ),
        reverse=True,
    )


def _hydrate_registry_candidates(
    db: Session,
    category: OfficialRegistryCategory,
    candidates: list[_RegistryCandidate],
) -> list[dict[str, Any]]:
    if not candidates:
        return []
    source_ids: dict[str, set[int]] = defaultdict(set)
    for candidate in candidates:
        for record in candidate.records:
            source_ids[record.source_family].update(record.source_ids)

    document_types = _DOCUMENT_TYPES_BY_CATEGORY[category]
    official = _official_records(
        db,
        document_types=document_types,
        document_ids=source_ids["official"],
    )
    legacy = _legacy_generated_records(
        db,
        document_types=document_types,
        row_ids=source_ids["generated"],
    )
    if category == OfficialRegistryCategory.TRANSFERS:
        legacy += _legacy_issue_records(db, row_ids=source_ids["protocol"])
    records = _deduplicate_records(official, legacy)

    if category == OfficialRegistryCategory.TRANSFERS:
        items = _transfer_items(db, records)
    elif category == OfficialRegistryCategory.REPAIRS:
        items = _repair_items(db, records)
    else:
        items = _part_items(db, records)
    _fill_machine_numbers(db, [items])
    items_by_key = {item["registry_key"]: item for item in items}
    return [
        items_by_key[candidate.registry_key]
        for candidate in candidates
        if candidate.registry_key in items_by_key
    ]


def query_official_document_registry_items(
    db: Session,
    *,
    category: OfficialRegistryCategory,
    query: str = "",
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """Return one stable, category-scoped page without hydrating other pages."""
    normalized_query = query.strip()
    candidates = _registry_candidates(db, category, normalized_query)
    total = len(candidates)
    total_pages = (total + page_size - 1) // page_size if total else 0
    offset = (page - 1) * page_size
    page_candidates = candidates[offset : offset + page_size]
    items = _hydrate_registry_candidates(db, category, page_candidates)
    return {
        "category": category.value,
        "total": total,
        "count": len(items),
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "has_previous": total > 0 and page > 1,
        "has_next": page < total_pages,
        "items": items,
    }


def count_official_document_registry_items(db: Session) -> dict[str, int]:
    """Count grouped identities without signature, file, or binary hydration."""
    return {
        category.value: len(_registry_candidates(db, category))
        for category in OfficialRegistryCategory
    }


def machine_official_document_registry_items(
    db: Session, machine_id: int
) -> list[dict[str, Any]]:
    """Return exact machine-linked registry items using canonical DOCS-01 rules."""
    items: list[dict[str, Any]] = []
    for category in OfficialRegistryCategory:
        candidates = _registry_candidates(db, category, machine_id=machine_id)
        category_items = _hydrate_registry_candidates(db, category, candidates)
        for item in category_items:
            item["category"] = category.value
        items.extend(category_items)
    _sort_items(items)
    return items


def build_official_document_registry(db: Session) -> dict[str, Any]:
    """Aggregate canonical and historical official documents without mutations."""
    official = _official_records(db)
    legacy = _legacy_generated_records(db) + _legacy_issue_records(db)
    records = _deduplicate_records(official, legacy)
    transfers = _transfer_items(db, records)
    repairs = _repair_items(db, records)
    parts = _part_items(db, records)
    _fill_machine_numbers(db, [transfers, repairs, parts])
    for section in (transfers, repairs, parts):
        _sort_items(section)
    return {
        "transfers": {"count": len(transfers), "items": transfers},
        "repairs": {"count": len(repairs), "items": repairs},
        "parts": {"count": len(parts), "items": parts},
    }
