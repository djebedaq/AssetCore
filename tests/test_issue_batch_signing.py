from __future__ import annotations

import base64
import io

from app.models import (
    DocumentSignature,
    Machine,
    OfficialDocument,
    TransferBatch,
    TransferProtocol,
)
from PIL import Image
from sqlalchemy import func, select


def _sign(client, task: dict, variant: int) -> None:
    token = task["signing_token"]
    summary = client.get(f"/api/signing/{token}")
    assert summary.status_code == 200, summary.text
    output = io.BytesIO()
    Image.new("RGB", (320, 120), (40 + variant, 80, 120)).save(
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


def test_issue_batch_uses_one_two_signature_act_for_three_machines(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    response = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"], machine_ids["5"], machine_ids["7"]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["signing_tasks"]) == 2
    assert [task["slot_code"] for task in body["signing_tasks"]] == [
        "ACCEPTANCE",
        "HANDOVER",
    ]
    assert body["batch_manifest_sha256"]
    assert body["signing_document_id"]
    assert sum(len(item["signing_tasks"]) for item in body["transfers"]) == 2

    summary = client.get(
        f"/api/signing/{body['signing_tasks'][0]['signing_token']}"
    )
    assert summary.status_code == 200, summary.text
    assert summary.json()["batch_reference"] == body["batch_reference"]
    assert [item["number"] for item in summary.json()["machines"]] == ["4", "5", "7"]
    assert summary.json()["batch_manifest_sha256"] == body["batch_manifest_sha256"]

    with session_factory() as db:
        assert db.scalar(select(func.count(TransferProtocol.id))) == 3
        assert set(db.scalars(select(Machine.status).where(Machine.id.in_([
            machine_ids["4"], machine_ids["5"], machine_ids["7"]
        ]))).all()) == {"READY"}

    for index, task in enumerate(body["signing_tasks"], start=1):
        _sign(client, task, index)

    with session_factory() as db:
        batch = db.get(TransferBatch, body["batch_id"])
        assert batch.issue_signing_status == "COMPLETED"
        assert batch.issue_manifest_sha256 == body["batch_manifest_sha256"]
        assert batch.issue_manifest["machine_count"] == 3
        assert set(db.scalars(select(Machine.status).where(Machine.id.in_([
            machine_ids["4"], machine_ids["5"], machine_ids["7"]
        ]))).all()) == {"ISSUED"}
        originals = db.scalar(
            select(func.count(DocumentSignature.id)).where(
                DocumentSignature.source_signature_id.is_(None)
            )
        )
        projections = db.scalar(
            select(func.count(DocumentSignature.id)).where(
                DocumentSignature.source_signature_id.is_not(None),
                DocumentSignature.batch_manifest_sha256
                == body["batch_manifest_sha256"],
            )
        )
        assert originals == 2
        assert projections == 6
        protocol_documents = list(
            db.scalars(
                select(OfficialDocument).where(
                    OfficialDocument.transfer_id.is_not(None),
                    OfficialDocument.document_type == "TRANSFER_ISSUE",
                )
            )
        )
        assert len(protocol_documents) == 3
