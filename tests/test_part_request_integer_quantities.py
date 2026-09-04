from __future__ import annotations

import base64
import io
import re

import pytest
from app.industrial_schemas import PartRequestLineOut
from app.models import AuditLog, GeneratedDocument, PartRequest, PartRequestLine, User
from docx import Document
from pypdf import PdfReader
from sqlalchemy import select


def _catalog_line(client, headers, machine_id: int, quantity: int | float) -> dict:
    parts = client.get(
        f"/api/catalog/parts?verified_only=true&machine_id={machine_id}",
        headers=headers,
    ).json()
    assert parts
    part = parts[0]
    return {
        "catalog_part_id": part["id"],
        "position": part["position"],
        "part_number": part["part_number"],
        "description": part["description"],
        "quantity": quantity,
        "unit": part["unit"],
        "source_document": part["source_document"],
        "source_page": part["source_page"],
    }


def _create_request(client, headers, machine_id: int, quantity: int) -> dict:
    response = client.post(
        "/api/part-requests/multi",
        headers=headers,
        json={
            "machine_id": machine_id,
            "priority": "NORMAL",
            "language": "bg",
            "lines": [_catalog_line(client, headers, machine_id, quantity)],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approve_request(client, headers, request_id: int) -> None:
    submitted = client.post(
        f"/api/part-requests/{request_id}/submit", headers=headers
    )
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=headers,
        json={"decision": "APPROVED", "note": "test-only integer quantity approval"},
    )
    assert approved.status_code == 200, approved.text


def _unknown_payload(machine_id: int, quantity: int | float) -> dict:
    return {
        "machine_id": machine_id,
        "assembly": "test-only quantity validation assembly",
        "description": "test-only unidentified component",
        "quantity": quantity,
        "unit": "бр.",
        "photo": {
            "filename": "test-only-unknown.png",
            "media_type": "image/png",
            "content_base64": base64.b64encode(
                b"\x89PNG\r\n\x1a\n" + b"test-only-integer-quantity-photo"
            ).decode(),
        },
    }


def _create_legacy_request(
    session_factory,
    *,
    status: str,
    quantity: float = 1.04,
    delivered_quantity: float = 0.0,
) -> tuple[int, int]:
    with session_factory() as session:
        user_id = session.scalar(
            select(User.id).where(User.email == "admin@assetcore.local")
        )
        request = PartRequest(
            part_name="test-only legacy compatibility request",
            quantity=quantity,
            priority="NORMAL",
            status=status,
            language="bg",
            requested_by_id=user_id,
        )
        session.add(request)
        session.flush()
        request.request_reference = f"PR-LEGACY-{request.id:06d}"
        line = PartRequestLine(
            request_id=request.id,
            description="test-only preserved fractional line",
            quantity=quantity,
            delivered_quantity=delivered_quantity,
            unit="бр.",
        )
        session.add(line)
        session.commit()
        return request.id, line.id


def test_multi_part_request_accepts_whole_quantities_and_rejects_fractional_values(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["9"]
    for quantity in (1, 2, 20):
        created = _create_request(client, auth_headers, machine_id, quantity)
        assert created["lines"][0]["quantity"] == quantity

    with session_factory() as session:
        count_before = len(session.scalars(select(PartRequest)).all())

    for quantity in (0.5, 1.04, 1.5, -1):
        rejected = client.post(
            "/api/part-requests/multi",
            headers=auth_headers,
            json={
                "machine_id": machine_id,
                "lines": [_catalog_line(client, auth_headers, machine_id, quantity)],
            },
        )
        assert rejected.status_code == 422, rejected.text

    with session_factory() as session:
        assert len(session.scalars(select(PartRequest)).all()) == count_before


def test_unknown_part_request_accepts_integer_and_rejects_fractional_quantity(
    client, auth_headers, machine_ids
):
    accepted = client.post(
        "/api/part-requests/unknown",
        headers=auth_headers,
        json=_unknown_payload(machine_ids["4"], 2),
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["lines"][0]["quantity"] == 2

    for quantity in (0.5, 1.04, 1.5, -1):
        rejected = client.post(
            "/api/part-requests/unknown",
            headers=auth_headers,
            json=_unknown_payload(machine_ids["4"], quantity),
        )
        assert rejected.status_code == 422, rejected.text


def test_fulfillment_uses_whole_progress_and_preserves_existing_status_semantics(
    client, auth_headers, machine_ids
):
    created = _create_request(client, auth_headers, machine_ids["9"], 4)
    request_id = created["id"]
    line_id = created["lines"][0]["id"]
    _approve_request(client, auth_headers, request_id)

    ordered = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={"status": "ORDERED", "lines": []},
    )
    assert ordered.status_code == 200, ordered.text

    partial = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "PARTIALLY_DELIVERED",
            "lines": [{"line_id": line_id, "delivered_quantity": 1}],
        },
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["lines"][0]["delivered_quantity"] == 1

    for quantity in (0.06, 1.5):
        fractional = client.patch(
            f"/api/part-requests/{request_id}/fulfillment",
            headers=auth_headers,
            json={
                "status": "PARTIALLY_DELIVERED",
                "lines": [{"line_id": line_id, "delivered_quantity": quantity}],
            },
        )
        assert fractional.status_code == 422, fractional.text

    decreased = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "PARTIALLY_DELIVERED",
            "lines": [{"line_id": line_id, "delivered_quantity": 0}],
        },
    )
    assert decreased.status_code == 409, decreased.text
    assert decreased.json()["detail"]["code"] == "invalid_delivered_quantity"

    exceeded = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "PARTIALLY_DELIVERED",
            "lines": [{"line_id": line_id, "delivered_quantity": 5}],
        },
    )
    assert exceeded.status_code == 409, exceeded.text
    assert exceeded.json()["detail"]["code"] == "invalid_delivered_quantity"

    progressed = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "PARTIALLY_DELIVERED",
            "lines": [{"line_id": line_id, "delivered_quantity": 3}],
        },
    )
    assert progressed.status_code == 200, progressed.text

    incomplete = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "DELIVERED",
            "lines": [{"line_id": line_id, "delivered_quantity": 3}],
        },
    )
    assert incomplete.status_code == 409, incomplete.text
    assert incomplete.json()["detail"]["code"] == "delivery_incomplete"

    delivered = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "DELIVERED",
            "lines": [{"line_id": line_id, "delivered_quantity": 4}],
        },
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "DELIVERED"
    assert delivered.json()["lines"][0]["delivered_quantity"] == 4


def test_legacy_fractional_rows_remain_readable_without_mutation(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        user_id = session.scalar(select(User.id).where(User.email == "admin@assetcore.local"))
        request = PartRequest(
            part_name="test-only legacy historical line",
            quantity=1,
            priority="NORMAL",
            status="ORDERED",
            language="bg",
            requested_by_id=user_id,
        )
        session.add(request)
        session.flush()
        request.request_reference = f"PR-LEGACY-{request.id:06d}"
        line = PartRequestLine(
            request_id=request.id,
            description="test-only retained historical fractional quantity",
            quantity=1.5,
            delivered_quantity=0.5,
            unit="бр.",
        )
        session.add(line)
        session.commit()
        request_id = request.id
        line_id = line.id

    listed = client.get("/api/part-requests/multi", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = next(item for item in listed.json() if item["id"] == request_id)
    assert body["lines"][0]["quantity"] == 1.5
    assert body["lines"][0]["delivered_quantity"] == 0.5
    assert body["quantity_compatibility"] == {
        "status": "LEGACY_FRACTIONAL",
        "affected_line_ids": [line_id],
        "recovery_action": "CANCEL_AND_RECREATE",
        "affected_lines": [
            {
                "line_id": line_id,
                "quantity": 1.5,
                "delivered_quantity": 0.5,
            }
        ],
    }
    PartRequestLineOut.model_validate(body["lines"][0])

    with session_factory() as session:
        stored = session.get(PartRequestLine, line_id)
        assert stored is not None
        assert stored.quantity == 1.5
        assert stored.delivered_quantity == 0.5


def test_legacy_fractional_draft_is_identified_and_cannot_be_submitted(
    client, auth_headers, session_factory
):
    request_id, line_id = _create_legacy_request(
        session_factory, status="DRAFT"
    )

    listed = client.get("/api/part-requests/multi", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    body = next(item for item in listed.json() if item["id"] == request_id)
    assert body["quantity_compatibility"] == {
        "status": "LEGACY_FRACTIONAL",
        "affected_line_ids": [line_id],
        "recovery_action": "CREATE_REPLACEMENT",
        "affected_lines": [
            {
                "line_id": line_id,
                "quantity": 1.04,
                "delivered_quantity": 0.0,
            }
        ],
    }

    rejected = client.post(
        f"/api/part-requests/{request_id}/submit", headers=auth_headers
    )
    assert rejected.status_code == 409, rejected.text
    detail = rejected.json()["detail"]
    assert detail["code"] == "legacy_fractional_part_request_requires_recovery"
    assert detail["recovery_action"] == "CREATE_REPLACEMENT"
    assert detail["affected_line_ids"] == [line_id]

    with session_factory() as session:
        request = session.get(PartRequest, request_id)
        line = session.get(PartRequestLine, line_id)
        assert request is not None and request.status == "DRAFT"
        assert line is not None and line.quantity == 1.04
        assert line.delivered_quantity == 0.0


def test_legacy_fractional_waiting_request_cannot_be_approved_but_can_be_rejected(
    client, auth_headers, session_factory
):
    request_id, line_id = _create_legacy_request(
        session_factory, status="WAITING_APPROVAL"
    )

    approved = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=auth_headers,
        json={"decision": "APPROVED"},
    )
    assert approved.status_code == 409, approved.text
    assert approved.json()["detail"]["recovery_action"] == "REJECT_AND_RECREATE"

    rejected = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=auth_headers,
        json={"decision": "REJECTED", "note": "test-only legacy recovery"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["quantity_compatibility"]["recovery_action"] == (
        "HISTORICAL_ONLY"
    )

    with session_factory() as session:
        line = session.get(PartRequestLine, line_id)
        assert line is not None and line.quantity == 1.04
        assert line.delivered_quantity == 0.0


@pytest.mark.parametrize(
    ("status", "next_status", "delivered_quantity"),
    [
        ("APPROVED", "ORDERED", None),
        ("ORDERED", "PARTIALLY_DELIVERED", 1),
        ("PARTIALLY_DELIVERED", "DELIVERED", 1),
    ],
)
def test_active_legacy_fractional_request_rejects_normal_fulfillment_without_rounding(
    client,
    auth_headers,
    session_factory,
    status,
    next_status,
    delivered_quantity,
):
    initial_delivered = 1.0 if status == "PARTIALLY_DELIVERED" else 0.0
    request_id, line_id = _create_legacy_request(
        session_factory,
        status=status,
        delivered_quantity=initial_delivered,
    )
    lines = (
        []
        if delivered_quantity is None
        else [{"line_id": line_id, "delivered_quantity": delivered_quantity}]
    )

    response = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={"status": next_status, "lines": lines},
    )
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "legacy_fractional_part_request_requires_recovery"
    assert detail["recovery_action"] == "CANCEL_AND_RECREATE"
    assert detail["affected_line_ids"] == [line_id]

    with session_factory() as session:
        request = session.get(PartRequest, request_id)
        line = session.get(PartRequestLine, line_id)
        assert request is not None and request.status == status
        assert line is not None and line.quantity == 1.04
        assert line.delivered_quantity == initial_delivered


def test_legacy_fractional_cancellation_preserves_exact_lines_and_audit_history(
    client, auth_headers, session_factory
):
    request_id, line_id = _create_legacy_request(
        session_factory,
        status="ORDERED",
        delivered_quantity=0.5,
    )

    mutation_attempt = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "CANCELLED",
            "lines": [{"line_id": line_id, "delivered_quantity": 1}],
        },
    )
    assert mutation_attempt.status_code == 409, mutation_attempt.text
    assert mutation_attempt.json()["detail"]["code"] == (
        "legacy_fractional_cancellation_requires_no_line_updates"
    )

    cancelled = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={"status": "CANCELLED", "lines": []},
    )
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["status"] == "CANCELLED"
    assert body["lines"][0]["quantity"] == 1.04
    assert body["lines"][0]["delivered_quantity"] == 0.5
    assert body["quantity_compatibility"]["recovery_action"] == "HISTORICAL_ONLY"

    with session_factory() as session:
        line = session.get(PartRequestLine, line_id)
        assert line is not None and line.quantity == 1.04
        assert line.delivered_quantity == 0.5
        audit = session.scalar(
            select(AuditLog)
            .where(
                AuditLog.entity_type == "part_request",
                AuditLog.entity_id == request_id,
                AuditLog.action == "Обновено изпълнение на заявка за части",
            )
            .order_by(AuditLog.id.desc())
        )
        assert audit is not None
        assert audit.operation_reference == f"PR-LEGACY-{request_id:06d}"


def test_part_request_documents_render_integer_quantity_and_retries_preserve_integrity(
    client, auth_headers, machine_ids, session_factory
):
    created = _create_request(client, auth_headers, machine_ids["9"], 4)
    _approve_request(client, auth_headers, created["id"])
    generated = client.post(
        f"/api/part-requests/{created['id']}/documents?language=bg",
        headers=auth_headers,
    )
    assert generated.status_code == 201, generated.text

    with session_factory() as session:
        documents = session.scalars(
            select(GeneratedDocument)
            .where(GeneratedDocument.part_request_id == created["id"])
            .order_by(GeneratedDocument.id)
        ).all()
        assert {document.format for document in documents} == {"docx", "pdf"}
        state_before = [
            (document.id, document.sha256, document.document_number, document.snapshot)
            for document in documents
        ]
        assert all(document.snapshot["lines"][0]["quantity"] == 4 for document in documents)
        docx = next(document.content for document in documents if document.format == "docx")
        pdf = next(document.content for document in documents if document.format == "pdf")

    rendered = Document(io.BytesIO(docx))
    cell_text = [
        cell.text
        for table in rendered.tables
        for row in table.rows
        for cell in row.cells
    ]
    assert any(value == "4" or value.startswith("4 ") for value in cell_text)
    fractional_quantity = re.compile(r"(?<!\d)4\.0(?:\s|$)")
    assert not any(fractional_quantity.search(value) for value in cell_text)
    pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    assert fractional_quantity.search(pdf_text) is None

    repeated = client.post(
        f"/api/part-requests/{created['id']}/documents?language=bg",
        headers=auth_headers,
    )
    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["detail"]["code"] == "part_request_protocol_already_generated"

    with session_factory() as session:
        documents = session.scalars(
            select(GeneratedDocument)
            .where(GeneratedDocument.part_request_id == created["id"])
            .order_by(GeneratedDocument.id)
        ).all()
        state_after = [
            (document.id, document.sha256, document.document_number, document.snapshot)
            for document in documents
        ]
    assert state_after == state_before


@pytest.mark.parametrize("value", [0.5, 1.04, 1.5])
def test_part_request_input_models_do_not_silently_truncate_fractional_values(value):
    from app.industrial_schemas import (
        PartRequestDeliveryLine,
        PartRequestLineCreate,
        UnknownPartRequestCreate,
    )
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PartRequestLineCreate(description="test-only", quantity=value)
    with pytest.raises(ValidationError):
        PartRequestDeliveryLine(line_id=1, delivered_quantity=value)
    with pytest.raises(ValidationError):
        UnknownPartRequestCreate(**_unknown_payload(1, value))
