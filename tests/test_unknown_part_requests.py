from __future__ import annotations

import base64

from app.models import AuditLog, PartCatalog, PartRequestAttachment, PartRequestLine
from sqlalchemy import func, select


def _png_payload() -> str:
    return base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"test-only-unknown-part-photo"
    ).decode()


def test_unknown_part_request_requires_machine_and_image_and_does_not_create_catalog_part(
    client, auth_headers, machine_ids, session_factory
):
    before_catalog = client.get("/api/catalog/parts", headers=auth_headers).json()
    created = client.post(
        "/api/part-requests/unknown",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "assembly": "test-only pump assembly",
            "description": "test-only unidentified metal component",
            "quantity": 2.5,
            "unit": "pcs",
            "note": "test-only note",
            "priority": "URGENT",
            "language": "bg",
            "photo": {
                "filename": "test-only-unknown.png",
                "media_type": "image/png",
                "content_base64": _png_payload(),
            },
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["machine_id"] == machine_ids["4"]
    assert len(body["lines"]) == 1
    line = body["lines"][0]
    assert line["is_unknown_part"] is True
    assert line["part_number"] is None
    assert line["catalog_part_id"] is None
    assert line["linked_catalog_part_id"] is None
    assert line["assembly"] == "test-only pump assembly"
    assert body["attachments"][0]["request_line_id"] == line["id"]
    assert body["attachments"][0]["media_type"] == "image/png"

    submitted = client.post(
        f"/api/part-requests/{body['id']}/submit", headers=auth_headers
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "WAITING_APPROVAL"

    after_catalog = client.get("/api/catalog/parts", headers=auth_headers).json()
    assert len(after_catalog) == len(before_catalog)
    with session_factory() as session:
        stored = session.get(PartRequestLine, line["id"])
        assert stored is not None and stored.is_unknown_part is True
        assert session.scalar(
            select(func.count(PartRequestAttachment.id)).where(
                PartRequestAttachment.request_line_id == line["id"]
            )
        ) == 1
        assert session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "part_request",
                AuditLog.entity_id == body["id"],
            )
        ) >= 1


def test_unknown_part_can_only_be_linked_by_admin_to_verified_compatible_catalog_part(
    client, auth_headers, machine_ids, session_factory
):
    created = client.post(
        "/api/part-requests/unknown",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "assembly": "test-only assembly",
            "description": "test-only unknown part",
            "quantity": 1,
            "photo": {
                "filename": "test-only-unknown.png",
                "media_type": "image/png",
                "content_base64": _png_payload(),
            },
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    line_id = created.json()["lines"][0]["id"]
    compatible = client.get(
        f"/api/catalog/parts?verified_only=true&machine_id={machine_ids['4']}",
        headers=auth_headers,
    ).json()
    assert compatible
    part = compatible[0]
    linked = client.post(
        f"/api/part-requests/{request_id}/lines/{line_id}/link-catalog-part",
        headers=auth_headers,
        json={"catalog_part_id": part["id"], "note": "test-only verified match"},
    )
    assert linked.status_code == 200, linked.text
    line = linked.json()["lines"][0]
    assert line["is_unknown_part"] is True
    assert line["part_number"] is None
    assert line["linked_catalog_part_id"] == part["id"]
    assert line["linked_part_number"] == part["part_number"]
    assert line["link_note"] == "test-only verified match"

    repeated = client.post(
        f"/api/part-requests/{request_id}/lines/{line_id}/link-catalog-part",
        headers=auth_headers,
        json={"catalog_part_id": part["id"], "note": "ignored idempotent retry"},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["lines"][0]["linked_catalog_part_id"] == part["id"]

    with session_factory() as session:
        stored = session.get(PartRequestLine, line_id)
        assert stored is not None
        assert stored.description == "test-only unknown part"
        assert stored.part_number is None
        assert stored.linked_catalog_part_id == part["id"]
        assert session.scalar(
            select(func.count(PartCatalog.id)).where(
                PartCatalog.description == "test-only unknown part"
            )
        ) == 0


def test_unknown_part_rejects_non_image_and_unverified_link(
    client, auth_headers, machine_ids, session_factory
):
    invalid = client.post(
        "/api/part-requests/unknown",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "assembly": "test-only assembly",
            "description": "test-only unknown",
            "quantity": 1,
            "photo": {
                "filename": "test-only.pdf",
                "media_type": "application/pdf",
                "content_base64": base64.b64encode(b"%PDF-1.4\ntest").decode(),
            },
        },
    )
    assert invalid.status_code == 422

    created = client.post(
        "/api/part-requests/unknown",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "assembly": "test-only assembly",
            "description": "test-only unknown",
            "quantity": 1,
            "photo": {
                "filename": "test-only.png",
                "media_type": "image/png",
                "content_base64": _png_payload(),
            },
        },
    ).json()
    with session_factory() as session:
        unverified = PartCatalog(
            brand="TEST-ONLY",
            model="TEST-ONLY",
            assembly="test-only assembly",
            position="1",
            part_number="TEST-UNVERIFIED-1",
            description="test-only unverified catalog part",
            compatible_machine_numbers=["4"],
            is_verified=False,
            verification_status="UNVERIFIED",
        )
        session.add(unverified)
        session.commit()
        unverified_id = unverified.id
    rejected = client.post(
        f"/api/part-requests/{created['id']}/lines/{created['lines'][0]['id']}/link-catalog-part",
        headers=auth_headers,
        json={"catalog_part_id": unverified_id},
    )
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"]["code"] == "catalog_part_not_verified_for_link"


def test_unknown_part_frontend_has_dedicated_safe_workflow():
    source = open("frontend/src/IndustrialPlatform.tsx", encoding="utf-8").read()
    assert "/part-requests/unknown" in source
    assert "UnknownPartRequestModal" in source
    assert "unknownPart.catalogWarning" in source
    assert "image/jpeg,image/png,image/webp" in source
    assert "link-catalog-part" in source
    assert "unknownPart.noCompatibleVerifiedParts" in source
