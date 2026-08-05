from __future__ import annotations

import base64
import io

from PIL import Image
from sqlalchemy import func, select

from app.models import (
    DocumentSignature,
    Machine,
    TransferBatch,
    TransferProtocol,
)


def _sign(client, task: dict, variant: int) -> None:
    token = task["signing_token"]
    summary = client.get(f"/api/signing/{token}")
    assert summary.status_code == 200, summary.text
    output = io.BytesIO()
    Image.new("RGB", (320, 120), (30 + variant, 70 + variant, 110)).save(
        output, format="PNG"
    )
    submitted = client.post(
        f"/api/signing/{token}",
        json={
            "consent_accepted": True,
            "consent_text": summary.json()["consent_notice"],
            "strokes": [[
                {"x": 20 + index * 12, "y": 40 + index, "t": index * 10}
                for index in range(8)
            ]],
            "image_base64": base64.b64encode(output.getvalue()).decode(),
            "canvas_width": 320,
            "canvas_height": 120,
        },
    )
    assert submitted.status_code == 201, submitted.text
    confirmed = client.post(f"/api/signing/{token}/confirm")
    assert confirmed.status_code == 200, confirmed.text


def test_return_batch_uses_two_signatures_across_different_issue_batches(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    issued_items: list[dict] = []
    signature_variant = 1
    for number in ("4", "5", "7"):
        issued = client.post(
            "/api/transfers/bulk-issue",
            headers=auth_headers,
            json=issue_payload(machine_ids[number]),
        )
        assert issued.status_code == 201, issued.text
        issued_items.append(issued.json()["transfers"][0])
        for task in issued.json()["signing_tasks"]:
            _sign(client, task, signature_variant)
            signature_variant += 1

    response = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": item["transfer_id"],
                    "machine_id": item["machine_id"],
                    "condition_text": "Проверено състояние при приемане",
                    "result_text": "Насочена към преглед",
                    "next_status": "INSPECTION",
                }
                for item in issued_items
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["batch_reference"].startswith("RET-")
    assert body["batch_manifest_sha256"]
    assert body["signing_document_id"]
    assert len(body["signing_tasks"]) == 2
    assert [task["slot_code"] for task in body["signing_tasks"]] == [
        "RETURNED_BY",
        "ACCEPTED_RETURN",
    ]
    assert sum(len(item["signing_tasks"]) for item in body["returned"]) == 2

    summary = client.get(
        f"/api/signing/{body['signing_tasks'][0]['signing_token']}"
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["batch_reference"] == body["batch_reference"]
    assert summary.json()["batch_manifest_sha256"] == body["batch_manifest_sha256"]
    assert [item["number"] for item in summary.json()["machines"]] == ["4", "5", "7"]
    assert "приемане" in summary.json()["operation_description"].lower()

    with session_factory() as db:
        operation_batch = db.get(TransferBatch, body["batch_id"])
        assert operation_batch.return_signing_status == "AWAITING_SIGNATURE"
        assert operation_batch.return_manifest["operation"] == "RETURN"
        assert operation_batch.return_manifest["machine_count"] == 3
        assert set(
            db.scalars(
                select(Machine.status).where(
                    Machine.id.in_([item["machine_id"] for item in issued_items])
                )
            ).all()
        ) == {"ISSUED"}

    for task in body["signing_tasks"]:
        _sign(client, task, signature_variant)
        signature_variant += 1

    with session_factory() as db:
        operation_batch = db.get(TransferBatch, body["batch_id"])
        assert operation_batch.return_signing_status == "COMPLETED"
        assert operation_batch.status == "RETURNED"
        transfers = list(
            db.scalars(
                select(TransferProtocol).where(
                    TransferProtocol.id.in_([item["transfer_id"] for item in issued_items])
                )
            )
        )
        assert {item.return_status for item in transfers} == {"COMPLETED"}
        assert {item.is_active for item in transfers} == {False}
        assert set(
            db.scalars(
                select(Machine.status).where(
                    Machine.id.in_([item["machine_id"] for item in issued_items])
                )
            ).all()
        ) == {"INSPECTION"}
        projections = db.scalar(
            select(func.count(DocumentSignature.id)).where(
                DocumentSignature.source_signature_id.is_not(None),
                DocumentSignature.batch_manifest_sha256
                == body["batch_manifest_sha256"],
            )
        )
        assert projections == 6

    details = client.get(
        f"/api/transfer-batches/{body['batch_id']}", headers=auth_headers
    )
    assert details.status_code == 200, details.text
    assert details.json()["operation"] == "RETURN"
    assert details.json()["batch_manifest_sha256"] == body["batch_manifest_sha256"]
    assert len(details.json()["transfers"]) == 3
    archive = client.get(
        f"/api/transfer-batches/{body['batch_id']}/documents.zip",
        headers=auth_headers,
    )
    assert archive.status_code == 200, archive.text
    assert archive.headers["content-type"] == "application/zip"


def test_pending_return_batch_can_be_cancelled_without_closing_issue(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert issued.status_code == 201, issued.text
    variant = 30
    for task in issued.json()["signing_tasks"]:
        _sign(client, task, variant)
        variant += 1
    transfer = issued.json()["transfers"][0]

    pending_return = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": transfer["transfer_id"],
                    "machine_id": transfer["machine_id"],
                    "condition_text": "Състояние за отменена операция",
                    "result_text": "Предстои повторно приемане",
                    "next_status": "INSPECTION",
                }
            ]
        },
    )
    assert pending_return.status_code == 200, pending_return.text
    return_batch_id = pending_return.json()["batch_id"]

    cancelled = client.post(
        f"/api/transfer-batches/{return_batch_id}/cancel",
        headers=auth_headers,
        json={"reason": "Подписването е отказано и операцията ще бъде започната отново."},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "CANCELLED"
    assert cancelled.json()["cancelled_transfers"] == 1
    assert cancelled.json()["invalidated_signing_sessions"] == 2

    with session_factory() as db:
        operation_batch = db.get(TransferBatch, return_batch_id)
        active = db.get(TransferProtocol, transfer["transfer_id"])
        machine = db.get(Machine, transfer["machine_id"])
        assert operation_batch.return_signing_status == "CANCELLED"
        assert active.return_status == "CANCELLED"
        assert active.is_active is True
        assert active.return_requested_at is None
        assert machine.status == "ISSUED"

    retried = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": transfer["transfer_id"],
                    "machine_id": transfer["machine_id"],
                    "condition_text": "Повторно проверено състояние",
                    "result_text": "Насочена към преглед",
                    "next_status": "INSPECTION",
                }
            ]
        },
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["batch_id"] != return_batch_id


def test_return_batch_rejects_machines_issued_to_different_people(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    first_payload = issue_payload(machine_ids["4"])
    second_payload = issue_payload(machine_ids["5"])
    second_payload["recipient"] = {
        "first_name": "Друг",
        "middle_name": "Външен",
        "last_name": "Получател",
    }
    issued_items = []
    variant = 60
    for payload in (first_payload, second_payload):
        issued = client.post(
            "/api/transfers/bulk-issue", headers=auth_headers, json=payload
        )
        assert issued.status_code == 201, issued.text
        issued_items.append(issued.json()["transfers"][0])
        for task in issued.json()["signing_tasks"]:
            _sign(client, task, variant)
            variant += 1

    rejected = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": item["transfer_id"],
                    "machine_id": item["machine_id"],
                    "condition_text": "Проверено състояние",
                    "result_text": "Насочена към преглед",
                    "next_status": "INSPECTION",
                }
                for item in issued_items
            ]
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "return_mixed_recipients"

    with session_factory() as db:
        assert db.scalar(
            select(func.count(TransferBatch.id)).where(
                TransferBatch.batch_reference.like("RET-%")
            )
        ) == 0
        transfers = list(
            db.scalars(
                select(TransferProtocol).where(
                    TransferProtocol.id.in_([item["transfer_id"] for item in issued_items])
                )
            )
        )
        assert {item.return_status for item in transfers} == {None}
        assert {item.is_active for item in transfers} == {True}
