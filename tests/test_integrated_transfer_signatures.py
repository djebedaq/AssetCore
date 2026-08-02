from __future__ import annotations

import base64
import io

from app.models import (
    DocumentParticipant,
    DocumentSignature,
    DocumentType,
    Machine,
    OfficialDocument,
    OfficialDocumentVersion,
    Repair,
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
            db.get(OfficialDocument, item["official_document_id"]).current_version_id,
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
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"], machine_ids["5"]),
    )
    assert issued.status_code == 201, issued.text
    first, second = issued.json()["transfers"]
    output = io.BytesIO()
    image = Image.new("RGB", (320, 120), "white")
    ImageDraw.Draw(image).line([(10, 70), (100, 20), (200, 80), (310, 30)], fill="black", width=5)
    image.save(output, format="PNG")
    reused_image = output.getvalue()
    assert _sign_task(client, first["signing_tasks"][0], 1, image=reused_image).status_code == 201
    rejected = _sign_task(client, second["signing_tasks"][0], 2, image=reused_image)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "signature_reuse_forbidden"


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
                "next_status": "INSPECTION",
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
        assert machine.status == "INSPECTION"
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
        {"status": "DIAGNOSIS", "inspection_complete": True, "diagnosis": "Тестова диагностика"},
        {"status": "REPAIRING", "work_performed": "Тестово извършена работа"},
        {"status": "TESTING"},
        {
            "status": "COMPLETED",
            "test_passed": True,
            "test_details": "Тестът е успешен",
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
