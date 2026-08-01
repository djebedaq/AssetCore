from __future__ import annotations

import base64
import io
import zipfile

from app.models import (
    AuditLog,
    Department,
    GeneratedDocument,
    Location,
    Machine,
    MachineEvent,
    MachineFieldValue,
    PartCatalogImage,
    PartHotspot,
    PartRequest,
    PartRequestAttachment,
    PartRequestLine,
    Repair,
    RepairKit,
    RepairStatus,
    TechnicalDocument,
    TransferProtocol,
)
from sqlalchemy import func, select


def test_machine_crud_preserves_unknown_serial_and_records_history(
    client, auth_headers, session_factory
):
    created = client.post(
        "/api/machines",
        headers=auth_headers,
        json={
            "inventory_number": "TEST-ASSET-CRUD",
            "name": "test-only asset",
            "category": "TEST_ONLY_CATEGORY",
            "brand": "test-only brand",
            "pressure_bar": 0,
            "serial_number": None,
            "status": "READY",
        },
    )
    assert created.status_code == 201, created.text
    machine_id = created.json()["id"]
    assert created.json()["serial_number"] is None
    assert created.json()["category"] == "TEST_ONLY_CATEGORY"

    updated = client.patch(
        f"/api/machines/{machine_id}",
        headers=auth_headers,
        json={"notes": "test-only updated notes", "responsible_person": ""},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["notes"] == "test-only updated notes"
    passport = client.get(
        f"/api/machines/{machine_id}/passport", headers=auth_headers
    )
    assert passport.status_code == 200, passport.text
    assert [item["event_type"] for item in passport.json()["history"]][:2] == [
        "MACHINE_UPDATED",
        "MACHINE_CREATED",
    ]
    with session_factory() as session:
        assert session.get(Machine, machine_id).serial_number is None


def test_admin_reference_data_is_authorized_audited_and_deactivated_without_deletion(
    client, auth_headers, viewer_headers, session_factory
):
    forbidden = client.post(
        "/api/admin/locations",
        headers=viewer_headers,
        json={"name": "test-only forbidden location"},
    )
    assert forbidden.status_code == 403

    location = client.post(
        "/api/admin/locations",
        headers=auth_headers,
        json={
            "name": "Тестово местоположение",
            "description": "Само за автоматизиран тест",
        },
    )
    assert location.status_code == 201, location.text
    duplicate_location = client.post(
        "/api/admin/locations",
        headers=auth_headers,
        json={"name": "тестово местоположение"},
    )
    assert duplicate_location.status_code == 409
    assert duplicate_location.json()["detail"]["code"] == "location_duplicate"

    department = client.post(
        "/api/admin/departments",
        headers=auth_headers,
        json={
            "code": "TEST_DEPARTMENT",
            "name_bg": "Тестов отдел",
            "name_en": "Test department",
            "name_ru": "Тестовый отдел",
            "description": "Само за автоматизиран тест",
        },
    )
    assert department.status_code == 201, department.text
    assert client.post(
        "/api/admin/departments",
        headers=auth_headers,
        json={"code": "TEST_DEPARTMENT", "name_bg": "Дубликат"},
    ).status_code == 409

    public_departments = client.get("/api/departments", headers=viewer_headers)
    assert public_departments.status_code == 200
    assert any(item["id"] == department.json()["id"] for item in public_departments.json())

    deactivated_location = client.patch(
        f"/api/admin/locations/{location.json()['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )
    deactivated_department = client.patch(
        f"/api/admin/departments/{department.json()['id']}",
        headers=auth_headers,
        json={"is_active": False},
    )
    assert deactivated_location.status_code == 200
    assert deactivated_location.json()["is_active"] is False
    assert deactivated_department.status_code == 200
    assert deactivated_department.json()["is_active"] is False

    reference_data = client.get("/api/admin/reference-data", headers=auth_headers)
    assert reference_data.status_code == 200
    assert next(
        item
        for item in reference_data.json()["locations"]
        if item["id"] == location.json()["id"]
    )["is_active"] is False
    with session_factory() as session:
        assert session.get(Location, location.json()["id"]) is not None
        assert session.get(Department, department.json()["id"]) is not None
        actions = set(
            session.scalars(
                select(AuditLog.action).where(
                    AuditLog.entity_type.in_(["location", "department"])
                )
            ).all()
        )
        assert {
            "Добавено местоположение",
            "Обновено местоположение",
            "Добавен отдел",
            "Обновен отдел",
        }.issubset(actions)


def test_configurable_passport_fields_and_immutable_history(
    client, auth_headers, machine_ids, session_factory
):
    categories = client.get("/api/categories", headers=auth_headers)
    assert categories.status_code == 200
    hpwj = next(item for item in categories.json() if item["code"] == "HPWJ")

    created_field = client.post(
        f"/api/categories/{hpwj['id']}/fields",
        headers=auth_headers,
        json={
            "code": "TEST_ONLY_FIELD",
            "label_bg": "Тестово поле",
            "label_en": "Test field",
            "label_ru": "Тестовое поле",
            "field_type": "TEXT",
            "is_required": False,
            "sort_order": 10,
        },
    )
    assert created_field.status_code == 201, created_field.text
    field_id = created_field.json()["id"]

    updated = client.put(
        f"/api/machines/{machine_ids['4']}/custom-fields",
        headers=auth_headers,
        json={"values": [{"field_id": field_id, "value": "test-only-value"}]},
    )
    assert updated.status_code == 200, updated.text

    passport = client.get(
        f"/api/machines/{machine_ids['4']}/passport", headers=auth_headers
    )
    assert passport.status_code == 200, passport.text
    field = next(
        item
        for item in passport.json()["custom_fields"]
        if item["field_id"] == field_id
    )
    assert field["value"] == "test-only-value"
    assert any(
        event["event_type"] == "CUSTOM_FIELDS_UPDATED"
        for event in passport.json()["history"]
    )
    assert passport.json()["current_state"]["available"] is True
    assert passport.json()["current_state"]["active_transfer"] is None
    assert passport.json()["current_state"]["allowed_actions"]["issue"] is True

    with session_factory() as session:
        assert session.scalar(
            select(func.count(MachineFieldValue.id)).where(
                MachineFieldValue.machine_id == machine_ids["4"]
            )
        ) == 1
        assert session.scalar(
            select(func.count(MachineEvent.id)).where(
                MachineEvent.machine_id == machine_ids["4"]
            )
        ) == 1


def test_machine_attachment_upload_is_hashed_and_downloadable(
    client, auth_headers, machine_ids
):
    one_pixel_png = base64.b64encode(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    ).decode()
    response = client.post(
        f"/api/machines/{machine_ids['4']}/attachments",
        headers=auth_headers,
        json={
            "filename": "test-only.png",
            "media_type": "image/png",
            "content_base64": one_pixel_png,
            "kind": "PHOTO",
            "description": "test-only attachment",
        },
    )
    assert response.status_code == 201, response.text
    attachment = response.json()
    assert len(attachment["sha256"]) == 64
    downloaded = client.get(
        f"/api{attachment['download_endpoint']}", headers=auth_headers
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"


def test_complete_repair_workflow_requires_inspection_and_successful_test(
    client, auth_headers, machine_ids, session_factory
):
    created = client.post(
        "/api/repair-cases",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "reported_problem": "test-only reported problem",
            "condition_before": "test-only condition before",
            "cleaning_required": False,
            "test_required": True,
        },
    )
    assert created.status_code == 201, created.text
    repair_id = created.json()["id"]
    assert created.json()["repair_reference"].endswith(f"-{repair_id:06d}")

    catalog_part = client.get("/api/catalog/parts", headers=auth_headers).json()[0]
    request_payload = {
        "machine_id": machine_ids["4"],
        "repair_id": repair_id,
        "priority": "NORMAL",
        "language": "bg",
        "lines": [
            {
                "catalog_part_id": catalog_part["id"],
                "description": catalog_part["description"],
                "quantity": 1,
            }
        ],
    }
    mismatched = client.post(
        "/api/part-requests/multi",
        headers=auth_headers,
        json={**request_payload, "machine_id": machine_ids["5"]},
    )
    assert mismatched.status_code == 409, mismatched.text
    linked_request = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=request_payload
    )
    assert linked_request.status_code == 201, linked_request.text
    assert linked_request.json()["repair_id"] == repair_id
    assert linked_request.json()["repair_reference"] == created.json()[
        "repair_reference"
    ]

    diagnosis = client.patch(
        f"/api/repair-cases/{repair_id}",
        headers=auth_headers,
        json={
            "status": "DIAGNOSIS",
            "inspection_complete": True,
            "diagnosis": "test-only diagnosis",
        },
    )
    assert diagnosis.status_code == 200, diagnosis.text

    premature = client.patch(
        f"/api/repair-cases/{repair_id}",
        headers=auth_headers,
        json={"status": "COMPLETED", "result": "test-only result"},
    )
    assert premature.status_code == 409
    assert premature.json()["detail"]["code"] == "invalid_repair_status_transition"

    repairing = client.patch(
        f"/api/repair-cases/{repair_id}",
        headers=auth_headers,
        json={
            "status": "REPAIRING",
            "work_performed": "test-only repair actions",
        },
    )
    assert repairing.status_code == 200, repairing.text
    testing = client.patch(
        f"/api/repair-cases/{repair_id}",
        headers=auth_headers,
        json={"status": "TESTING"},
    )
    assert testing.status_code == 200, testing.text

    failed_completion = client.patch(
        f"/api/repair-cases/{repair_id}",
        headers=auth_headers,
        json={"status": "COMPLETED", "test_passed": False, "result": "failed"},
    )
    assert failed_completion.status_code == 409
    assert (
        failed_completion.json()["detail"]["code"]
        == "repair_completion_requirements_missing"
    )

    completed = client.patch(
        f"/api/repair-cases/{repair_id}",
        headers=auth_headers,
        json={
            "status": "COMPLETED",
            "test_passed": True,
            "test_details": "test-only successful test",
            "condition_after": "test-only condition after",
            "result": "test-only completed result",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["test_passed"] is True

    generated = client.post(
        f"/api/repair-cases/{repair_id}/documents?language=bg",
        headers=auth_headers,
    )
    assert generated.status_code == 201, generated.text
    assert {item["format"] for item in generated.json()["documents"]} == {
        "docx",
        "pdf",
    }

    with session_factory() as session:
        repair = session.get(Repair, repair_id)
        linked = session.get(PartRequest, linked_request.json()["id"])
        assert linked.repair_id == repair_id
        machine = session.get(Machine, machine_ids["4"])
        assert repair.status == RepairStatus.COMPLETED.value
        assert machine.status == "READY"
        assert session.scalar(
            select(func.count(GeneratedDocument.id)).where(
                GeneratedDocument.repair_id == repair_id
            )
        ) == 2


def test_multiline_part_request_approval_and_versioned_documents(
    client, auth_headers, machine_ids, session_factory
):
    catalog = client.get("/api/catalog/parts", headers=auth_headers)
    assert catalog.status_code == 200
    source_part = catalog.json()[0]
    created = client.post(
        "/api/part-requests/multi",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "priority": "URGENT",
            "language": "bg",
            "reason": "test-only request reason",
            "lines": [
                {
                    "catalog_part_id": source_part["id"],
                    "position": source_part["position"],
                    "part_number": source_part["part_number"],
                    "description": source_part["description"],
                    "quantity": 2,
                    "unit": "pcs",
                    "source_document": source_part["source_document"],
                    "source_page": source_part["source_page"],
                },
                {
                    "description": "test-only non-catalog line",
                    "quantity": 1,
                    "unit": "pcs",
                },
            ],
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]
    assert len(created.json()["lines"]) == 2

    attachment_content = base64.b64encode(b"%PDF-1.4\n% test-only request attachment\n").decode()
    attachment = client.post(
        f"/api/part-requests/{request_id}/attachments",
        headers=auth_headers,
        json={
            "filename": "test-only-request.pdf",
            "media_type": "application/pdf",
            "content_base64": attachment_content,
            "description": "test-only request attachment",
        },
    )
    assert attachment.status_code == 201, attachment.text
    assert len(attachment.json()["sha256"]) == 64
    listed_request = next(
        item
        for item in client.get("/api/part-requests/multi", headers=auth_headers).json()
        if item["id"] == request_id
    )
    assert listed_request["attachments"][0]["id"] == attachment.json()["id"]
    downloaded_attachment = client.get(
        f"/api{attachment.json()['download_endpoint']}", headers=auth_headers
    )
    assert downloaded_attachment.status_code == 200

    submitted = client.post(
        f"/api/part-requests/{request_id}/submit", headers=auth_headers
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "WAITING_APPROVAL"
    decided = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=auth_headers,
        json={"decision": "APPROVED", "note": "test-only approval"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "APPROVED"

    ordered = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={"status": "ORDERED", "supplier": "test-only supplier", "lines": []},
    )
    assert ordered.status_code == 200, ordered.text
    assert ordered.json()["status"] == "ORDERED"
    line_ids = [line["id"] for line in created.json()["lines"]]
    partial = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "PARTIALLY_DELIVERED",
            "lines": [
                {"line_id": line_ids[0], "delivered_quantity": 1},
                {"line_id": line_ids[1], "delivered_quantity": 0},
            ],
        },
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["status"] == "PARTIALLY_DELIVERED"
    delivered = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={
            "status": "DELIVERED",
            "lines": [
                {"line_id": line_ids[0], "delivered_quantity": 2},
                {"line_id": line_ids[1], "delivered_quantity": 1},
            ],
        },
    )
    assert delivered.status_code == 200, delivered.text
    assert delivered.json()["status"] == "DELIVERED"

    first_docs = client.post(
        f"/api/part-requests/{request_id}/documents",
        headers=auth_headers,
    )
    second_docs = client.post(
        f"/api/part-requests/{request_id}/documents",
        headers=auth_headers,
    )
    assert first_docs.status_code == 201, first_docs.text
    assert second_docs.status_code == 201, second_docs.text
    assert second_docs.json()["document_number"].endswith("-V2")

    with session_factory() as session:
        request_item = session.get(PartRequest, request_id)
        assert request_item.status == "DELIVERED"
        assert session.scalar(
            select(func.count(PartRequestAttachment.id)).where(
                PartRequestAttachment.request_id == request_id
            )
        ) == 1
        assert session.scalar(
            select(func.count(GeneratedDocument.id)).where(
                GeneratedDocument.part_request_id == request_id
            )
        ) == 4


def test_return_generates_individual_protocols_and_batch_zip(
    client, auth_headers, machine_ids, issue_payload
):
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"], machine_ids["5"]),
    )
    assert issued.status_code == 201, issued.text
    first = issued.json()["transfers"][0]
    returned = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": first["transfer_id"],
                    "machine_id": first["machine_id"],
                    "condition_text": "test-only return condition",
                    "result_text": "test-only return result",
                    "next_status": "INSPECTION",
                }
            ]
        },
    )
    assert returned.status_code == 200, returned.text
    assert {item["format"] for item in returned.json()["returned"][0]["documents"]} == {
        "docx",
        "pdf",
    }
    batch_id = issued.json()["batch_id"]
    archive = client.get(
        f"/api/transfer-batches/{batch_id}/documents.zip", headers=auth_headers
    )
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        names = zipped.namelist()
    assert len(names) == 6
    assert sum(name.endswith(".docx") for name in names) == 3
    assert sum(name.endswith(".pdf") for name in names) == 3


def test_technical_library_versions_search_and_protected_import_preview(
    client, auth_headers, machine_ids, session_factory
):
    content = base64.b64encode(b"%PDF-1.4\n% test-only technical document\n").decode()
    created = client.post(
        "/api/technical-library",
        headers=auth_headers,
        json={
            "brand": "test-only brand",
            "model": "test-only model",
            "category": "test-only category",
            "title": "test-only technical document",
            "language": "en",
            "revision": "A",
            "filename": "test-only.pdf",
            "media_type": "application/pdf",
            "content_base64": content,
            "change_note": "test-only initial version",
            "source_label": "test-only-source",
            "linked_machine_numbers": ["4", "7"],
        },
    )
    assert created.status_code == 201, created.text
    document_id = created.json()["id"]
    revision = client.post(
        f"/api/technical-library/{document_id}/revisions",
        headers=auth_headers,
        json={
            "brand": "test-only brand",
            "model": "test-only model",
            "category": "test-only category",
            "title": "test-only technical document",
            "language": "en",
            "revision": "B",
            "filename": "test-only-rev-b.pdf",
            "media_type": "application/pdf",
            "content_base64": content,
            "change_note": "test-only second version",
        },
    )
    assert revision.status_code == 201, revision.text
    assert revision.json()["version"] == 2

    search = client.get("/api/search?q=test-only%20technical", headers=auth_headers)
    assert search.status_code == 200
    assert any(item["id"] == document_id for item in search.json()["documents"])
    serial_search = client.get(
        "/api/technical-library?q=G41200143", headers=auth_headers
    )
    assert serial_search.status_code == 200, serial_search.text
    assert any(item["id"] == document_id for item in serial_search.json())
    source_part = client.post(
        "/api/catalog/parts",
        headers=auth_headers,
        json={
            "brand": "test-only brand",
            "part_number": "TEST-LIB-PART",
            "description": "test-only source-linked part",
            "source_document": "test-only-source",
            "source_page": 1,
        },
    )
    assert source_part.status_code == 201, source_part.text
    part_search = client.get(
        "/api/technical-library?q=TEST-LIB-PART", headers=auth_headers
    )
    assert part_search.status_code == 200, part_search.text
    assert any(item["id"] == document_id for item in part_search.json())
    passport = client.get(
        f"/api/machines/{machine_ids['4']}/passport", headers=auth_headers
    )
    assert passport.status_code == 200, passport.text
    assert [item["id"] for item in passport.json()["technical_documents"]] == [
        document_id
    ]

    protected = client.post(
        "/api/admin/import-preview",
        headers=auth_headers,
        json={
            "records": [
                {
                    "inventory_number": "25",
                    "name": "test-only HPWJ",
                    "category": "HPWJ",
                    "brand": "test-only",
                    "pressure_bar": 500,
                }
            ]
        },
    )
    assert protected.status_code == 200
    assert protected.json()["can_confirm"] is False
    assert "HPWJ" in protected.json()["errors"][0]["message"]

    with session_factory() as session:
        assert session.scalar(
            select(func.count(TechnicalDocument.id)).where(
                TechnicalDocument.id == document_id
            )
        ) == 1
        assert session.scalar(select(func.count(Machine.id))) == 19


def test_visual_part_hotspot_requires_provenance_and_human_verification(
    client, auth_headers, viewer_headers, session_factory
):
    content = base64.b64encode(b"%PDF-1.4\n% test-only visual source\n").decode()
    document = client.post(
        "/api/technical-library",
        headers=auth_headers,
        json={
            "brand": "CombiJet",
            "model": "JE60-500",
            "category": "test-only visual source",
            "title": "test-only hotspot source",
            "language": "bg",
            "revision": "T1",
            "filename": "test-only-hotspot.pdf",
            "media_type": "application/pdf",
            "content_base64": content,
        },
    )
    assert document.status_code == 201, document.text
    catalog = client.get("/api/catalog/parts", headers=auth_headers).json()
    part = next(item for item in catalog if item["brand"] == "CombiJet")

    forbidden = client.post(
        f"/api/catalog/parts/{part['id']}/hotspots",
        headers=viewer_headers,
        json={
            "technical_document_id": document.json()["id"],
            "page_number": 1,
            "x": 0.25,
            "y": 0.4,
            "provenance": "test-only source marker",
        },
    )
    assert forbidden.status_code == 403

    created = client.post(
        f"/api/catalog/parts/{part['id']}/hotspots",
        headers=auth_headers,
        json={
            "technical_document_id": document.json()["id"],
            "page_number": 1,
            "x": 0.25,
            "y": 0.4,
            "width": 0.04,
            "height": 0.04,
            "label": "test-only marker",
            "provenance": "test-only source marker",
            "confidence": 0.91,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_verified"] is False
    assert created.json()["confidence"] == 0.91
    document_hotspots = client.get(
        f"/api/catalog/hotspots?technical_document_id={document.json()['id']}&page_number=1",
        headers=viewer_headers,
    )
    assert document_hotspots.status_code == 200, document_hotspots.text
    assert [item["id"] for item in document_hotspots.json()] == [created.json()["id"]]
    verified = client.post(
        f"/api/catalog/hotspots/{created.json()['id']}/verify",
        headers=auth_headers,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["is_verified"] is True

    one_pixel_png = base64.b64encode(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    ).decode()
    viewer_upload = client.post(
        f"/api/catalog/parts/{part['id']}/images",
        headers=viewer_headers,
        json={
            "filename": "test-only-part.png",
            "media_type": "image/png",
            "content_base64": one_pixel_png,
        },
    )
    assert viewer_upload.status_code == 403
    uploaded = client.post(
        f"/api/catalog/parts/{part['id']}/images",
        headers=auth_headers,
        json={
            "filename": "test-only-part.png",
            "media_type": "image/png",
            "content_base64": one_pixel_png,
            "description": "test-only catalog image",
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    assert len(uploaded.json()["sha256"]) == 64
    listed = client.get(
        f"/api/catalog/parts/{part['id']}/images", headers=viewer_headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == uploaded.json()["id"]
    downloaded = client.get(
        f"/api{uploaded.json()['download_endpoint']}", headers=viewer_headers
    )
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "image/png"

    with session_factory() as session:
        assert session.get(PartHotspot, created.json()["id"]).is_verified is True
        assert session.get(PartCatalogImage, uploaded.json()["id"]).sha256 == uploaded.json()["sha256"]
        assert session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "part_hotspot"
            )
        ) == 2
        assert session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "catalog_part_image"
            )
        ) == 1


def test_catalog_alternative_numbers_and_replacements_are_validated(
    client, auth_headers
):
    catalog = client.get("/api/catalog/parts", headers=auth_headers).json()
    replacement = catalog[0]
    created = client.post(
        "/api/catalog/parts",
        headers=auth_headers,
        json={
            "brand": "test-only catalog brand",
            "part_number": "TEST-ONLY-PART",
            "description": "test-only replacement mapping",
            "alternative_part_numbers": ["TEST-ALT-A", "TEST-ALT-B"],
            "replacement_part_ids": [replacement["id"]],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["alternative_part_numbers"] == ["TEST-ALT-A", "TEST-ALT-B"]
    assert created.json()["replacement_part_ids"] == [replacement["id"]]
    rejected_self_reference = client.put(
        f"/api/catalog/parts/{created.json()['id']}",
        headers=auth_headers,
        json={
            "brand": "test-only catalog brand",
            "part_number": "TEST-ONLY-PART",
            "description": "test-only replacement mapping",
            "replacement_part_ids": [created.json()["id"]],
        },
    )
    assert rejected_self_reference.status_code == 422
    assert rejected_self_reference.json()["detail"]["code"] == "catalog_self_replacement"


def test_legacy_routes_cannot_bypass_repair_and_request_workflows(
    client, auth_headers, machine_ids, session_factory
):
    repair = client.post(
        "/api/repairs",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "reported_problem": "test-only legacy repair",
            "status": "ACCEPTED",
        },
    )
    assert repair.status_code == 201, repair.text
    unsafe_close = client.patch(
        f"/api/repairs/{repair.json()['id']}",
        headers=auth_headers,
        json={"status": "TESTING", "close": True, "result": "test-only"},
    )
    assert unsafe_close.status_code == 409

    invalid_request = client.post(
        "/api/parts",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "part_name": "test-only part",
            "quantity": 1,
            "status": "APPROVED",
        },
    )
    assert invalid_request.status_code == 409
    draft = client.post(
        "/api/parts",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "part_name": "test-only part",
            "part_number": "TEST-ONLY",
            "quantity": 1,
            "status": "DRAFT",
        },
    )
    assert draft.status_code == 201, draft.text

    with session_factory() as session:
        repair_row = session.get(Repair, repair.json()["id"])
        machine = session.get(Machine, machine_ids["4"])
        request = session.get(PartRequest, draft.json()["id"])
        assert repair_row.repair_reference.startswith("REP-")
        assert machine.status == "INSPECTION"
        assert request.request_reference.startswith("PR-")
        assert session.scalar(
            select(func.count(PartRequestLine.id)).where(
                PartRequestLine.request_id == request.id
            )
        ) == 1


def test_typed_required_custom_fields_are_validated_server_side(
    client, auth_headers, machine_ids, session_factory
):
    category = next(
        item for item in client.get("/api/categories", headers=auth_headers).json()
        if item["code"] == "HPWJ"
    )
    field = client.post(
        f"/api/categories/{category['id']}/fields",
        headers=auth_headers,
        json={
            "code": "TEST_REQUIRED_INTEGER",
            "label_bg": "Тестово задължително число",
            "field_type": "INTEGER",
            "is_required": True,
            "unit": "test-unit",
            "validation_rules": {"min": 1, "max": 10},
        },
    )
    assert field.status_code == 201, field.text
    field_id = field.json()["id"]

    invalid = client.put(
        f"/api/machines/{machine_ids['4']}/custom-fields",
        headers=auth_headers,
        json={"values": [{"field_id": field_id, "value": "not-a-number"}]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_custom_field_value"
    with session_factory() as session:
        assert session.scalar(
            select(func.count(MachineFieldValue.id)).where(
                MachineFieldValue.field_id == field_id
            )
        ) == 0

    valid = client.put(
        f"/api/machines/{machine_ids['4']}/custom-fields",
        headers=auth_headers,
        json={"values": [{"field_id": field_id, "value": "004"}]},
    )
    assert valid.status_code == 200, valid.text
    assert next(item for item in valid.json()["values"] if item["field_id"] == field_id)["value"] == "4"
    out_of_range = client.put(
        f"/api/machines/{machine_ids['4']}/custom-fields",
        headers=auth_headers,
        json={"values": [{"field_id": field_id, "value": "11"}]},
    )
    assert out_of_range.status_code == 422


def test_repair_kit_requires_verified_parts_and_expands_authoritatively(
    client, auth_headers, machine_ids, session_factory
):
    verified_part = client.get("/api/catalog/parts", headers=auth_headers).json()[0]
    unverified_part = client.post(
        "/api/catalog/parts",
        headers=auth_headers,
        json={
            "brand": "test-only brand",
            "part_number": "TEST-ONLY-UNVERIFIED",
            "description": "test-only unverified component",
            "unit": "pcs",
            "provenance": "test-only source pending human verification",
        },
    )
    assert unverified_part.status_code == 201, unverified_part.text
    unsafe_kit = client.post(
        "/api/repair-kits",
        headers=auth_headers,
        json={
            "code": "TEST-KIT-UNVERIFIED",
            "name": "test-only unsafe kit",
            "components": [{"part_id": unverified_part.json()["id"], "quantity": 1}],
        },
    )
    assert unsafe_kit.status_code == 201, unsafe_kit.text
    rejected = client.post(
        f"/api/repair-kits/{unsafe_kit.json()['id']}/approve",
        headers=auth_headers,
    )
    assert rejected.status_code == 409

    kit = client.post(
        "/api/repair-kits",
        headers=auth_headers,
        json={
            "code": "TEST-KIT-VERIFIED",
            "name": "test-only approved kit",
            "compatible_models": "test-only compatible model",
            "revision": "T1",
            "source_document": "test-only controlled source",
            "source_page": 1,
            "provenance": "test-only verified source",
            "confidence": 1,
            "components": [
                {"part_id": verified_part["id"], "quantity": 2, "is_optional": False}
            ],
        },
    )
    assert kit.status_code == 201, kit.text
    listed_kit = next(
        item
        for item in client.get("/api/repair-kits", headers=auth_headers).json()
        if item["id"] == kit.json()["id"]
    )
    assert listed_kit["compatible_models"] == "test-only compatible model"
    assert listed_kit["revision"] == "T1"
    approved = client.post(
        f"/api/repair-kits/{kit.json()['id']}/approve",
        headers=auth_headers,
    )
    assert approved.status_code == 200, approved.text
    request = client.post(
        "/api/part-requests/multi",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["4"],
            "repair_kit_id": kit.json()["id"],
            "repair_kit_mode": "COMPONENTS",
            "language": "bg",
            "lines": [
                {
                    "catalog_part_id": verified_part["id"],
                    "description": "client text must not override verified catalog",
                    "quantity": 2,
                }
            ],
        },
    )
    assert request.status_code == 201, request.text
    line = request.json()["lines"][0]
    assert line["part_number"] == verified_part["part_number"]
    assert line["description"] == verified_part["description"]
    with session_factory() as session:
        assert session.get(RepairKit, kit.json()["id"]).is_approved is True


def test_unconfirmed_document_language_rolls_back_issue_atomically(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    payload = issue_payload(machine_ids["4"])
    payload["document_language"] = "en"
    response = client.post(
        "/api/transfers/bulk-issue", headers=auth_headers, json=payload
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document_template_unavailable"
    with session_factory() as session:
        assert session.scalar(select(func.count(TransferProtocol.id))) == 0
        assert session.get(Machine, machine_ids["4"]).status == "READY"


def test_global_search_finds_protocol_batch_and_generated_document(
    client, auth_headers, machine_ids, issue_payload
):
    issued = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert issued.status_code == 201, issued.text
    transfer = issued.json()["transfers"][0]
    protocol_search = client.get(
        f"/api/search?q={transfer['protocol_number']}", headers=auth_headers
    )
    assert protocol_search.status_code == 200, protocol_search.text
    assert protocol_search.json()["transfers"][0]["protocol_number"] == transfer["protocol_number"]
    document_number = transfer["documents"][0]["document_number"]
    document_search = client.get(
        f"/api/search?q={document_number}", headers=auth_headers
    )
    assert document_search.status_code == 200, document_search.text
    assert any(
        item["document_number"] == document_number
        for item in document_search.json()["generated_documents"]
    )


def test_template_version_upload_is_draft_until_human_publish(
    client, auth_headers
):
    templates = client.get("/api/document-templates", headers=auth_headers).json()
    issue_template = next(
        item for item in templates if item["document_type"] == "TRANSFER_ISSUE"
    )
    source_buffer = io.BytesIO()
    with zipfile.ZipFile(source_buffer, "w") as document:
        document.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        document.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        )
    source = source_buffer.getvalue()
    created = client.post(
        f"/api/document-templates/{issue_template['id']}/versions",
        headers=auth_headers,
        json={
            "language": "en",
            "filename": "test-only-template.docx",
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "content_base64": base64.b64encode(source).decode(),
            "layout_contract": {"reference_only": True, "test_only": True},
            "required_fields": ["machine_number", "protocol_number"],
            "numbering_rule": "TEST-{year}-{sequence}",
            "department": "Тестов отдел",
            "change_note": "Тестова проверена промяна",
        },
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]
    refreshed = client.get("/api/document-templates", headers=auth_headers).json()
    version = next(
        version
        for item in refreshed if item["id"] == issue_template["id"]
        for version in item["versions"] if version["id"] == version_id
    )
    assert version["is_published"] is False
    assert version["source_filename"] == "test-only-template.docx"
    assert len(version["source_sha256"]) == 64
    assert version["required_fields"] == ["machine_number", "protocol_number"]
    assert version["numbering_rule"] == "TEST-{year}-{sequence}"
    assert version["department"] == "Тестов отдел"
    assert version["change_note"] == "Тестова проверена промяна"
    downloaded = client.get(f"/api{version['download_endpoint']}", headers=auth_headers)
    assert downloaded.status_code == 200
    assert downloaded.content == source
    published = client.post(
        f"/api/document-template-versions/{version_id}/publish",
        headers=auth_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["is_published"] is True
