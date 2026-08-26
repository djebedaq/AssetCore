from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    DocumentParticipant,
    ExternalSigner,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    SignatureSession,
    SignatureSlot,
    User,
    utcnow,
)
from .official_documents.integrity import set_current_version
from .schemas import TransferPartyInput


class TransferSigningConfigurationError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _slot_label(slot: SignatureSlot, language: str) -> str:
    return {
        "bg": slot.label_bg,
        "en": slot.label_en or slot.label_bg,
        "ru": slot.label_ru or slot.label_bg,
    }.get(language, slot.label_bg)


def _internal_snapshot(user: User, operation_role: str) -> dict:
    return {
        "participant_kind": "INTERNAL",
        "user_id": user.id,
        "first_name": user.first_name,
        "middle_name": user.middle_name,
        "last_name": user.last_name,
        "display_name": user.full_name,
        "job_title": user.job_title,
        "department_id": user.department_id,
        "department": (
            user.profile_department.name_bg if user.profile_department else None
        ),
        "operation_role": operation_role,
        "captured_at": utcnow().isoformat(timespec="seconds") + "Z",
    }


def _external_snapshot(signer: ExternalSigner, operation_role: str) -> dict:
    display_name = " ".join(
        value
        for value in (signer.first_name, signer.middle_name, signer.last_name)
        if value
    )
    return {
        "participant_kind": "EXTERNAL",
        "external_signer_id": signer.id,
        "first_name": signer.first_name,
        "middle_name": signer.middle_name,
        "last_name": signer.last_name,
        "display_name": display_name,
        "job_title": signer.job_title,
        "company": signer.company,
        "is_foreign_person": signer.is_foreign_person,
        "name_exception_reason": signer.name_exception_reason,
        "operation_role": operation_role,
        "captured_at": utcnow().isoformat(timespec="seconds") + "Z",
    }


def create_external_party(
    db: Session,
    party: TransferPartyInput,
    actor: User,
    participant_role: str,
) -> ExternalSigner:
    signer = ExternalSigner(
        first_name=party.first_name,
        middle_name=party.middle_name,
        last_name=party.last_name,
        job_title=party.job_title,
        company=party.company_or_department,
        participant_role=participant_role,
        is_foreign_person=party.is_foreign_person,
        name_exception_reason=party.name_exception_reason,
        note="Създаден като участник в конкретен приемо-предавателен workflow.",
        created_by_id=actor.id,
    )
    db.add(signer)
    db.flush()
    return signer


def prepare_transfer_signing(
    db: Session,
    *,
    document_number: str,
    document_type: str,
    actor: User,
    external_signer: ExternalSigner,
    external_slot_code: str,
    internal_slot_code: str,
    expires_minutes: int = 30,
) -> tuple[OfficialDocument, list[dict]]:
    document = db.scalar(
        select(OfficialDocument).where(
            OfficialDocument.document_number == document_number,
            OfficialDocument.document_type == document_type,
        )
    )
    if document is None:
        raise TransferSigningConfigurationError(
            "Официалният документ за подписване не е намерен."
        )
    version = db.get(OfficialDocumentVersion, document.current_version_id)
    if version is None or version.status != OfficialDocumentStatus.DRAFT.value:
        raise TransferSigningConfigurationError(
            "Документът не е в допустим статус за подготовка на подписи."
        )
    slots = list(
        db.scalars(
            select(SignatureSlot)
            .where(
                SignatureSlot.document_type == document_type,
                SignatureSlot.required.is_(True),
                SignatureSlot.is_active.is_(True),
            )
            .order_by(SignatureSlot.sequence, SignatureSlot.id)
        )
    )
    by_code = {slot.code: slot for slot in slots}
    expected = {external_slot_code, internal_slot_code}
    if set(by_code) != expected:
        raise TransferSigningConfigurationError(
            "Конфигурацията на задължителните подписни позиции за документа е невалидна."
        )

    participants: list[DocumentParticipant] = []
    for slot in slots:
        operation_role = _slot_label(slot, version.language)
        if slot.code == internal_slot_code:
            snapshot = _internal_snapshot(actor, operation_role)
            participant = DocumentParticipant(
                document_version_id=version.id,
                slot_code=slot.code,
                participant_kind="INTERNAL",
                user_id=actor.id,
                operation_role=operation_role,
                identity_snapshot=snapshot,
                identity_snapshot_sha256=_sha(_canonical(snapshot)),
            )
        else:
            snapshot = _external_snapshot(external_signer, operation_role)
            participant = DocumentParticipant(
                document_version_id=version.id,
                slot_code=slot.code,
                participant_kind="EXTERNAL",
                external_signer_id=external_signer.id,
                operation_role=operation_role,
                identity_snapshot=snapshot,
                identity_snapshot_sha256=_sha(_canonical(snapshot)),
            )
        db.add(participant)
        db.flush()
        participants.append(participant)

    version.status = OfficialDocumentStatus.READY_FOR_SIGNATURE.value
    tasks: list[dict] = []
    for participant in participants:
        raw_token = secrets.token_urlsafe(32)
        expires_at = utcnow() + timedelta(minutes=expires_minutes)
        db.add(
            SignatureSession(
                participant_id=participant.id,
                token_hash=_sha(raw_token.encode("utf-8")),
                expires_at=expires_at,
                created_by_id=actor.id,
            )
        )
        tasks.append(
            {
                "participant_id": participant.id,
                "slot_code": participant.slot_code,
                "operation_role": participant.operation_role,
                "signer_name": str(participant.identity_snapshot["display_name"]),
                "signing_token": raw_token,
                "signing_endpoint": f"/api/signing/{raw_token}",
                "expires_at": expires_at,
            }
        )
    return document, tasks


def prepare_issue_batch_signing(
    db: Session,
    *,
    batch,
    transfers: list,
    actor: User,
    external_signer: ExternalSigner,
    language: str,
    expires_minutes: int = 30,
) -> tuple[OfficialDocument, list[dict]]:
    """Create one immutable signing act for every issue protocol in a batch."""
    from .models import DocumentType, TransferOperationStatus

    manifest_items: list[dict] = []
    for transfer in transfers:
        official = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.transfer_id == transfer.id,
                OfficialDocument.document_type == DocumentType.TRANSFER_ISSUE.value,
            )
        )
        if official is None or official.current_version_id is None:
            raise TransferSigningConfigurationError(
                f"Липсва официален протокол за машина №{transfer.machine.inventory_number}."
            )
        version = db.get(OfficialDocumentVersion, official.current_version_id)
        if version is None or version.status != OfficialDocumentStatus.DRAFT.value:
            raise TransferSigningConfigurationError(
                f"Протоколът за машина №{transfer.machine.inventory_number} не е готов за batch подписване."
            )
        manifest_items.append(
            {
                "transfer_id": transfer.id,
                "machine_id": transfer.machine_id,
                "machine_number": transfer.machine.inventory_number,
                "brand": transfer.machine.brand,
                "model": transfer.machine.model,
                "protocol_number": transfer.protocol_number,
                "official_document_id": official.id,
                "official_document_version_id": version.id,
                "official_document_signing_sha256": version.signing_sha256,
            }
        )

    manifest = {
        "operation": "ISSUE",
        "batch_id": batch.id,
        "batch_reference": batch.batch_reference,
        "created_by_id": actor.id,
        "created_at": utcnow().isoformat(timespec="seconds") + "Z",
        "recipient_external_signer_id": external_signer.id,
        "machine_count": len(manifest_items),
        "machines": manifest_items,
    }
    manifest_sha256 = _sha(_canonical(manifest))
    document_number = f"{batch.batch_reference}-ISSUE-SIGN"
    if db.scalar(
        select(OfficialDocument.id).where(
            OfficialDocument.document_number == document_number
        )
    ):
        raise TransferSigningConfigurationError(
            "За този batch вече съществува подписващ акт."
        )

    snapshot = {
        "batch_signing": manifest,
        "batch_manifest_sha256": manifest_sha256,
        "prepared_by": _internal_snapshot(actor, "PREPARER"),
    }
    snapshot_sha256 = _sha(_canonical(snapshot))
    signing_sha256 = _sha(
        _canonical(
            {
                "document_number": document_number,
                "document_type": DocumentType.TRANSFER_ISSUE.value,
                "version": 1,
                "snapshot_sha256": snapshot_sha256,
                "batch_manifest_sha256": manifest_sha256,
            }
        )
    )
    document = OfficialDocument(
        document_number=document_number,
        document_type=DocumentType.TRANSFER_ISSUE.value,
        machine_id=None,
        transfer_id=None,
        batch_id=batch.id,
        created_by_id=actor.id,
    )
    db.add(document)
    db.flush()
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status=OfficialDocumentStatus.DRAFT.value,
        language=language,
        snapshot=snapshot,
        snapshot_sha256=snapshot_sha256,
        signing_sha256=signing_sha256,
        docx_content=None,
        docx_sha256=None,
        pdf_content=None,
        pdf_sha256=None,
        prepared_by_id=actor.id,
    )
    db.add(version)
    db.flush()
    set_current_version(db, document, version)
    batch.issue_manifest = manifest
    batch.issue_manifest_sha256 = manifest_sha256
    batch.issue_signing_document_id = document.id
    batch.issue_signing_status = TransferOperationStatus.AWAITING_SIGNATURE.value

    return prepare_transfer_signing(
        db,
        document_number=document_number,
        document_type=DocumentType.TRANSFER_ISSUE.value,
        actor=actor,
        external_signer=external_signer,
        external_slot_code="ACCEPTANCE",
        internal_slot_code="HANDOVER",
        expires_minutes=expires_minutes,
    )


def prepare_return_batch_signing(
    db: Session,
    *,
    batch,
    transfers: list,
    actor: User,
    external_signer: ExternalSigner,
    language: str,
    expires_minutes: int = 30,
) -> tuple[OfficialDocument, list[dict]]:
    """Create one immutable signing act for selected return protocols."""
    from .models import DocumentType, TransferOperationStatus

    manifest_items: list[dict] = []
    for transfer in transfers:
        official = db.scalar(
            select(OfficialDocument)
            .where(
                OfficialDocument.transfer_id == transfer.id,
                OfficialDocument.document_type == DocumentType.TRANSFER_RETURN.value,
            )
            .order_by(OfficialDocument.id.desc())
        )
        if official is None or official.current_version_id is None:
            raise TransferSigningConfigurationError(
                f"Липсва официален протокол за приемане на машина №{transfer.machine.inventory_number}."
            )
        version = db.get(OfficialDocumentVersion, official.current_version_id)
        if version is None or version.status != OfficialDocumentStatus.DRAFT.value:
            raise TransferSigningConfigurationError(
                f"Протоколът за приемане на машина №{transfer.machine.inventory_number} не е готов за batch подписване."
            )
        manifest_items.append(
            {
                "transfer_id": transfer.id,
                "issue_batch_id": transfer.batch_id,
                "issue_batch_reference": transfer.batch_reference,
                "machine_id": transfer.machine_id,
                "machine_number": transfer.machine.inventory_number,
                "brand": transfer.machine.brand,
                "model": transfer.machine.model,
                "protocol_number": official.document_number,
                "official_document_id": official.id,
                "official_document_version_id": version.id,
                "official_document_signing_sha256": version.signing_sha256,
                "next_status": transfer.return_next_status,
                "return_location_id": transfer.return_location_id,
            }
        )

    manifest = {
        "operation": "RETURN",
        "batch_id": batch.id,
        "batch_reference": batch.batch_reference,
        "created_by_id": actor.id,
        "created_at": utcnow().isoformat(timespec="seconds") + "Z",
        "returner_external_signer_id": external_signer.id,
        "machine_count": len(manifest_items),
        "machines": manifest_items,
    }
    manifest_sha256 = _sha(_canonical(manifest))
    document_number = f"{batch.batch_reference}-RETURN-SIGN"
    if db.scalar(
        select(OfficialDocument.id).where(
            OfficialDocument.document_number == document_number
        )
    ):
        raise TransferSigningConfigurationError(
            "За тази batch операция по приемане вече съществува подписващ акт."
        )

    snapshot = {
        "batch_signing": manifest,
        "batch_manifest_sha256": manifest_sha256,
        "prepared_by": _internal_snapshot(actor, "PREPARER"),
    }
    snapshot_sha256 = _sha(_canonical(snapshot))
    signing_sha256 = _sha(
        _canonical(
            {
                "document_number": document_number,
                "document_type": DocumentType.TRANSFER_RETURN.value,
                "version": 1,
                "snapshot_sha256": snapshot_sha256,
                "batch_manifest_sha256": manifest_sha256,
            }
        )
    )
    document = OfficialDocument(
        document_number=document_number,
        document_type=DocumentType.TRANSFER_RETURN.value,
        machine_id=None,
        transfer_id=None,
        batch_id=batch.id,
        created_by_id=actor.id,
    )
    db.add(document)
    db.flush()
    version = OfficialDocumentVersion(
        document_id=document.id,
        version=1,
        status=OfficialDocumentStatus.DRAFT.value,
        language=language,
        snapshot=snapshot,
        snapshot_sha256=snapshot_sha256,
        signing_sha256=signing_sha256,
        docx_content=None,
        docx_sha256=None,
        pdf_content=None,
        pdf_sha256=None,
        prepared_by_id=actor.id,
    )
    db.add(version)
    db.flush()
    set_current_version(db, document, version)
    batch.return_manifest = manifest
    batch.return_manifest_sha256 = manifest_sha256
    batch.return_signing_document_id = document.id
    batch.return_signing_status = TransferOperationStatus.AWAITING_SIGNATURE.value

    return prepare_transfer_signing(
        db,
        document_number=document_number,
        document_type=DocumentType.TRANSFER_RETURN.value,
        actor=actor,
        external_signer=external_signer,
        external_slot_code="RETURNED_BY",
        internal_slot_code="ACCEPTED_RETURN",
        expires_minutes=expires_minutes,
    )
