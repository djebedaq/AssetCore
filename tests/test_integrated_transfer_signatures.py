from __future__ import annotations

import base64
import copy
import io

from app.models import (
    AuditLog,
    DocumentParticipant,
    DocumentSignature,
    DocumentType,
    Machine,
    OfficialDocument,
    OfficialDocumentVersion,
    Repair,
    SignatureSession,
    TransferProtocol,
)
from PIL import Image, ImageDraw
from sqlalchemy import func, select


def _signature_payload(consent: str, variant: int, *, image: bytes | None = None) -> dict:
    if image is None:
        output = io.BytesIO()
        canvas = Image.new("RGBA", (320, 120), "white")
        ImageDraw.Draw(canvas).line(
            [(15, 80), (70, 30 + variant), (135, 88), (205, 25), (300, 75)],
            fill="black",
            width=5,
        )
        canvas.save(output, format="PNG")
        image = output.getvalue()
    return {
        "consent_accepted": True,
        "consent_text": consent,
        "strokes": [[
            {"x": 20 + index * 20, "y": 30 + (index % 2) * 25, "t": index * 10}
            for index in range(8)
        ]],
        "image_base64": base64.b64encode(image).decode(),
        "canvas_width": 320,
        "canvas_height": 120,
    }


def _sign_task(client, task: dict, variant: int, *, image: bytes | None = None):
    token = task["signing_token"]
    summary = client.get(f"/api/signing/{token}")
    assert summary.status_code == 200, summary.text
    submitted = client.post(
        f"/api/signing/{token}",
        json=_signature_payload(summary.json()["consent_notice"], variant, image=image),
    )
    if submitted.status_code != 201:
        return submitted
    confirmed = client.post(f"/api/signing/{token}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    return submitted


def _returned_person() -> dict:
    return {
        "first_name": "Тестов",
        "middle_name": "Външен",
        "last_name": "Връщащ",
        "job_title": "Тестова длъжност",
        "company_or_department": "Тестово звено",
    }


def test_issue_remains_pending_and_changes_machine_only_after_both_signatures(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert issued.status_code == 201, issued.text
    item = issued.json()["transfers"][0]
    assert item["workflow_status"] == "AWAITING_SIGNATURE"
    assert [task["slot_code"] for task in item["signing_tasks"]] == [
        "ACCEPTANCE",
        "HANDOVER",
    ]
    pending_document = client.get(
        item["documents"][0]["download_endpoint"], headers=auth_headers
    )
    assert pending_document.status_code == 409
    assert pending_document.json()["detail"]["code"] == "document_awaiting_signatures"
    pending_zip = client.get(
        issued.json()["zip_download_endpoint"], headers=auth_headers
    )
    assert pending_zip.status_code == 409
    assert pending_zip.json()["detail"]["code"] == (
        "batch_documents_awaiting_signatures"
    )
    with session_factory() as db:
        assert db.get(Machine, machine_ids["4"]).status == "READY"
        transfer = db.get(TransferProtocol, item["transfer_id"])
        assert transfer.issue_status == "AWAITING_SIGNATURE"
        version = db.get(
            OfficialDocumentVersion,
            db.get(
                OfficialDocument, issued.json()["signing_document_id"]
            ).current_version_id,
        )
        expected_hash = version.signing_sha256

    _sign_task(client, item["signing_tasks"][0], 1)
    with session_factory() as db:
        assert db.get(Machine, machine_ids["4"]).status == "READY"
        signature = db.scalar(select(DocumentSignature))
        assert signature.document_sha256 == expected_hash

    _sign_task(client, item["signing_tasks"][1], 2)
    with session_factory() as db:
        assert db.get(Machine, machine_ids["4"]).status == "ISSUED"
        transfer = db.get(TransferProtocol, item["transfer_id"])
        assert transfer.issue_status == "COMPLETED"
        assert transfer.issued_at is not None
    for document in item["documents"]:
        assert client.get(document["download_endpoint"], headers=auth_headers).status_code == 200


def test_signature_image_cannot_be_reused_for_another_document(
    client, auth_headers, machine_ids, issue_payload
):
    first_issue = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    second_issue = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["5"]),
    )
    assert first_issue.status_code == 201, first_issue.text
    assert second_issue.status_code == 201, second_issue.text
    first = first_issue.json()["transfers"][0]
    second = second_issue.json()["transfers"][0]
    output = io.BytesIO()
    image = Image.new("RGB", (320, 120), "white")
    ImageDraw.Draw(image).line([(10, 70), (100, 20), (200, 80), (310, 30)], fill="black", width=5)
    image.save(output, format="PNG")
    reused_image = output.getvalue()
    assert _sign_task(client, first["signing_tasks"][0], 1, image=reused_image).status_code == 201
    rejected = _sign_task(client, second["signing_tasks"][0], 2, image=reused_image)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "signature_reuse_forbidden"


def test_superseded_issue_version_rejects_stale_signing_and_preserves_history(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert issued.status_code == 201, issued.text
    body = issued.json()
    transfer_result = body["transfers"][0]
    assert _sign_task(client, body["signing_tasks"][0], 100).status_code == 201
    stale_task = body["signing_tasks"][1]
    stale_token = stale_task["signing_token"]
    stale_summary = client.get(f"/api/signing/{stale_token}")
    assert stale_summary.status_code == 200, stale_summary.text
    submitted = client.post(
        f"/api/signing/{stale_token}",
        json=_signature_payload(stale_summary.json()["consent_notice"], 101),
    )
    assert submitted.status_code == 201, submitted.text

    document_id = body["signing_document_id"]
    with session_factory() as db:
        document = db.get(OfficialDocument, document_id)
        first_version = db.get(OfficialDocumentVersion, document.current_version_id)
        stale_participant = db.get(DocumentParticipant, stale_task["participant_id"])
        source_snapshot = copy.deepcopy(first_version.snapshot)
        source_docx = (
            bytes(first_version.docx_content) if first_version.docx_content else None
        )
        source_pdf = (
            bytes(first_version.pdf_content) if first_version.pdf_content else None
        )
        first_version_evidence = {
            "id": first_version.id,
            "snapshot": copy.deepcopy(first_version.snapshot),
            "snapshot_sha256": first_version.snapshot_sha256,
            "signing_sha256": first_version.signing_sha256,
            "docx_content": source_docx,
            "docx_sha256": first_version.docx_sha256,
            "pdf_content": source_pdf,
            "pdf_sha256": first_version.pdf_sha256,
        }
        participant_inputs = []
        for participant in db.scalars(
            select(DocumentParticipant)
            .where(DocumentParticipant.document_version_id == first_version.id)
            .order_by(DocumentParticipant.id)
        ):
            participant_inputs.append(
                {
                    "slot_code": participant.slot_code,
                    "operation_role": participant.operation_role,
                    "user_id": participant.user_id,
                    "external_signer_id": participant.external_signer_id,
                }
            )
        stale_signature = db.scalar(
            select(DocumentSignature).where(
                DocumentSignature.participant_id == stale_participant.id
            )
        )
        assert stale_signature is not None and stale_signature.confirmed_at is None
        stale_signature_id = stale_signature.id
        stale_session = db.scalar(
            select(SignatureSession).where(
                SignatureSession.participant_id == stale_participant.id
            )
        )
        stale_session_id = stale_session.id
        protocol_document = db.get(
            OfficialDocument, transfer_result["official_document_id"]
        )
        protocol_version = db.get(
            OfficialDocumentVersion, protocol_document.current_version_id
        )
        protocol_evidence = {
            "id": protocol_version.id,
            "status": protocol_version.status,
            "snapshot": copy.deepcopy(protocol_version.snapshot),
            "snapshot_sha256": protocol_version.snapshot_sha256,
            "signing_sha256": protocol_version.signing_sha256,
            "docx_content": bytes(protocol_version.docx_content),
            "docx_sha256": protocol_version.docx_sha256,
            "pdf_content": bytes(protocol_version.pdf_content),
            "pdf_sha256": protocol_version.pdf_sha256,
        }
        machine_before = db.get(Machine, machine_ids["4"])
        transfer_before = db.get(TransferProtocol, transfer_result["transfer_id"])
        workflow_before = (
            machine_before.status,
            machine_before.location_id,
            transfer_before.issue_status,
            transfer_before.issued_at,
        )

    corrected = client.post(
        f"/api/official-documents/{document_id}/supersede",
        headers=auth_headers,
        json={
            "reason": "QA correction for stale signing lifecycle regression.",
            "snapshot": source_snapshot,
            "docx_base64": (
                base64.b64encode(source_docx).decode() if source_docx else None
            ),
            "pdf_base64": (
                base64.b64encode(source_pdf).decode() if source_pdf else None
            ),
            "participants": participant_inputs,
        },
    )
    assert corrected.status_code == 201, corrected.text
    corrected_body = corrected.json()
    assert corrected_body["current_version"]["version"] == 2

    with session_factory() as db:
        document = db.get(OfficialDocument, document_id)
        first_version = db.get(OfficialDocumentVersion, first_version_evidence["id"])
        second_version = db.get(OfficialDocumentVersion, document.current_version_id)
        assert first_version.status == "SUPERSEDED"
        first_finalized_at = first_version.finalized_at
        current_version_id = document.current_version_id
        second_version_evidence = {
            "status": second_version.status,
            "snapshot": copy.deepcopy(second_version.snapshot),
            "snapshot_sha256": second_version.snapshot_sha256,
            "signing_sha256": second_version.signing_sha256,
            "docx_content": (
                bytes(second_version.docx_content)
                if second_version.docx_content
                else None
            ),
            "docx_sha256": second_version.docx_sha256,
            "pdf_content": (
                bytes(second_version.pdf_content)
                if second_version.pdf_content
                else None
            ),
            "pdf_sha256": second_version.pdf_sha256,
        }

    stale_responses = [
        client.get(f"/api/signing/{stale_token}"),
        client.post(
            f"/api/signing/{stale_token}",
            json=_signature_payload(stale_summary.json()["consent_notice"], 102),
        ),
        client.post(f"/api/signing/{stale_token}/confirm"),
        client.post(f"/api/signing/{stale_token}/reject"),
    ]
    assert [response.status_code for response in stale_responses] == [410, 410, 410, 410]
    assert {
        response.json()["detail"]["code"] for response in stale_responses
    } == {"signing_session_closed"}
    stale_session_create = client.post(
        "/api/signatures/sessions",
        headers=auth_headers,
        json={"participant_id": stale_task["participant_id"]},
    )
    assert stale_session_create.status_code == 409
    assert stale_session_create.json()["detail"]["code"] == "document_not_signable"

    with session_factory() as db:
        document = db.get(OfficialDocument, document_id)
        first_version = db.get(OfficialDocumentVersion, first_version_evidence["id"])
        second_version = db.get(OfficialDocumentVersion, current_version_id)
        assert document.current_version_id == current_version_id
        assert first_version.status == "SUPERSEDED"
        assert first_version.finalized_at == first_finalized_at
        for field, expected in first_version_evidence.items():
            if field != "id":
                assert getattr(first_version, field) == expected
        for field, expected in second_version_evidence.items():
            assert getattr(second_version, field) == expected
        stale_signature = db.get(DocumentSignature, stale_signature_id)
        stale_session = db.get(SignatureSession, stale_session_id)
        assert stale_signature.confirmed_at is None
        assert stale_session.consumed_at is None and stale_session.rejected_at is None
        assert db.scalar(select(func.count(DocumentSignature.id))) == 2
        assert db.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.action == "Потвърден ръчен графичен подпис"
            )
        ) == 1
        protocol_version = db.get(OfficialDocumentVersion, protocol_evidence["id"])
        for field, expected in protocol_evidence.items():
            if field != "id":
                assert getattr(protocol_version, field) == expected
        machine = db.get(Machine, machine_ids["4"])
        transfer = db.get(TransferProtocol, transfer_result["transfer_id"])
        assert (
            machine.status,
            machine.location_id,
            transfer.issue_status,
            transfer.issued_at,
        ) == workflow_before

    slot_order = {"ACCEPTANCE": 1, "HANDOVER": 2}
    current_participants = sorted(
        corrected_body["participants"], key=lambda item: slot_order[item["slot_code"]]
    )
    for index, participant in enumerate(current_participants, start=103):
        current_session = client.post(
            "/api/signatures/sessions",
            headers=auth_headers,
            json={"participant_id": participant["id"]},
        )
        assert current_session.status_code == 201, current_session.text
        assert _sign_task(client, current_session.json(), index).status_code == 201

    with session_factory() as db:
        document = db.get(OfficialDocument, document_id)
        first_version = db.get(OfficialDocumentVersion, first_version_evidence["id"])
        second_version = db.get(OfficialDocumentVersion, current_version_id)
        machine = db.get(Machine, machine_ids["4"])
        transfer = db.get(TransferProtocol, transfer_result["transfer_id"])
        assert document.current_version_id == current_version_id
        assert first_version.status == "SUPERSEDED"
        assert first_version.docx_content == first_version_evidence["docx_content"]
        assert first_version.pdf_content == first_version_evidence["pdf_content"]
        assert first_version.docx_sha256 == first_version_evidence["docx_sha256"]
        assert first_version.pdf_sha256 == first_version_evidence["pdf_sha256"]
        assert second_version.status == "SIGNED"
        assert machine.status == "ISSUED"
        assert transfer.issue_status == "COMPLETED"


def test_return_remains_pending_until_return_and_acceptance_signatures(
    client, auth_headers, machine_ids, issue_payload, finalize_signatures, session_factory
):
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    finalize_signatures(client, issued)
    transfer = issued.json()["transfers"][0]
    returned = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [{
                "transfer_id": transfer["transfer_id"],
                "machine_id": transfer["machine_id"],
                "condition_text": "Тестово състояние при връщане",
                "result_text": "Насочена към преглед",
                "next_status": "READY",
                "returned_person": _returned_person(),
            }]
        },
    )
    assert returned.status_code == 200, returned.text
    item = returned.json()["returned"][0]
    assert item["workflow_status"] == "AWAITING_SIGNATURE"
    with session_factory() as db:
        machine = db.get(Machine, machine_ids["4"])
        active = db.get(TransferProtocol, transfer["transfer_id"])
        assert machine.status == "ISSUED"
        assert active.is_active is True
        assert active.return_status == "AWAITING_SIGNATURE"

    for index, task in enumerate(item["signing_tasks"], start=20):
        _sign_task(client, task, index)
    with session_factory() as db:
        machine = db.get(Machine, machine_ids["4"])
        active = db.get(TransferProtocol, transfer["transfer_id"])
        assert machine.status == "READY"
        assert active.is_active is False
        assert active.return_status == "COMPLETED"


def test_completed_repair_creates_locked_internal_protocol_and_correction_version(
    client, auth_headers, machine_ids, session_factory
):
    created = client.post(
        "/api/repair-cases",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["5"],
            "reported_problem": "Тестово установен проблем",
            "condition_before": "Тестово начално състояние",
            "cleaning_required": False,
            "test_required": True,
        },
    )
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]
    for payload in (
        {"status": "DIAGNOSIS", "inspection_complete": True, "diagnosis": "Тестова диагностика", "required_work": "Тестова необходима работа", "diagnosis_minutes": 20},
        {"status": "REPAIRING", "work_performed": "Тестово извършена работа", "repair_minutes": 35},
        {
            "status": "COMPLETED",
            "test_passed": True,
            "test_method": "Тестова функционална проверка",
            "test_details": "Тестът е успешен",
            "testing_minutes": 10,
            "condition_after": "Тестово крайно състояние",
            "result": "Ремонтът е приключен",
        },
    ):
        completed = client.patch(
            f"/api/repair-cases/{repair_id}", headers=auth_headers, json=payload
        )
        assert completed.status_code == 200, completed.text

    with session_factory() as db:
        repair = db.get(Repair, repair_id)
        official = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_type == DocumentType.REPAIR_PROTOCOL.value,
                OfficialDocument.machine_id == machine_ids["5"],
            )
        )
        first_version_id = official.current_version_id
        first = db.get(OfficialDocumentVersion, first_version_id)
        assert repair.responsible_user_id is not None
        assert first.status == "FINALIZED"
        assert db.scalar(
            select(func.count(DocumentParticipant.id)).where(
                DocumentParticipant.document_version_id == first.id
            )
        ) == 0

    corrected = client.post(
        f"/api/repair-cases/{repair_id}/documents/corrections",
        headers=auth_headers,
        json={
            "reason": "Тестова мотивирана корекция на вътрешния протокол.",
            "language": "bg",
        },
    )
    assert corrected.status_code == 201, corrected.text
    assert corrected.json()["version"] == 2
    with session_factory() as db:
        first = db.get(OfficialDocumentVersion, first_version_id)
        official = db.get(OfficialDocument, corrected.json()["official_document_id"])
        second = db.get(OfficialDocumentVersion, official.current_version_id)
        assert first.status == "SUPERSEDED"
        assert second.status == "FINALIZED"
        assert second.supersedes_version_id == first.id
    assert client.get(
        f"/api/official-documents/{corrected.json()['official_document_id']}/versions/1/download/docx",
        headers=auth_headers,
    ).status_code == 200
