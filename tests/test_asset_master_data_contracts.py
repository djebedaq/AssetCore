"""Contracts captured on main before the asset-domain extraction (PR #32)."""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
from pathlib import Path

import qrcode
from app.authorization_inventory import build_authorization_inventory
from app.main import app
from app.models import AuditLog, Machine, MachineEvent, MachineFieldValue
from app.settings import settings
from sqlalchemy import func, select

CONTRACT = json.loads(
    (Path(__file__).parent / "contracts" / "asset_master_data_routes.json").read_text(
        encoding="utf-8"
    )
)


def test_asset_routes_keep_openapi_schemas_and_permission_contract():
    schema = app.openapi()
    for path, expected in CONTRACT["paths"].items():
        assert schema["paths"][path] == expected, path
    for name, expected in CONTRACT["schemas"].items():
        assert schema["components"]["schemas"][name] == expected, name
    actual = build_authorization_inventory(app).summary()["routes"]
    paths = set(CONTRACT["paths"])
    assert [row for row in actual if row["path"] in paths] == CONTRACT["routes"]


def test_historical_route_imports_still_resolve_to_registered_asset_handlers():
    legacy_main = {"locations", "machines", "machine", "create_machine", "update_machine", "qr"}
    for row in CONTRACT["routes"]:
        module = importlib.import_module(
            "app.main" if row["name"] in legacy_main else "app.industrial_api"
        )
        owner = importlib.import_module(
            "app.assets.routes"
            if "machine" in row["name"] or row["name"] in {"qr", "update_custom_fields"}
            else "app.master_data.routes"
        )
        assert getattr(module, row["name"]) is getattr(owner, row["name"])


def test_every_asset_route_keeps_authentication_and_observer_boundaries(client, viewer_headers):
    for route in CONTRACT["routes"]:
        path = route["path"]
        for parameter in (
            "machine_id",
            "attachment_id",
            "category_id",
            "location_id",
            "department_id",
        ):
            path = path.replace("{" + parameter + "}", "-1")
        response = client.request(route["method"], path)
        assert response.status_code == 401, (route, response.text)
        if route["permission"] != "assets.view":
            response = client.request(route["method"], path, headers=viewer_headers)
            assert response.status_code == 403, (route, response.text)
            assert response.json()["detail"]["code"] == "permission_denied"


def test_machine_read_and_qr_contract(
    client, auth_headers, viewer_headers, machine_ids, monkeypatch
):
    listing = client.get("/api/machines", headers=auth_headers)
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 19
    assert rows == sorted(rows, key=lambda row: (-row["pressure_bar"], row["inventory_number"]))
    machine_id = machine_ids["7"]
    full = client.get(f"/api/machines/{machine_id}", headers=auth_headers)
    assert full.json() == next(row for row in rows if row["id"] == machine_id)
    assert full.json()["serial_number"] == "G41200143"
    limited = client.get(f"/api/machines/{machine_id}", headers=viewer_headers)
    assert limited.status_code == 200
    assert set(limited.json()) == {
        "id",
        "inventory_number",
        "name",
        "brand",
        "model",
        "status",
        "is_active",
        "location",
    }
    assert limited.json() == next(
        row
        for row in client.get("/api/machines", headers=viewer_headers).json()
        if row["id"] == machine_id
    )
    for public_base, expected_base in (
        ("https://example.invalid/assetcore/", "https://example.invalid/assetcore"),
        (None, "http://testserver"),
    ):
        monkeypatch.setattr(settings, "public_base_url", public_base)
        response = client.get(f"/api/machines/{machine_id}/qr", headers=auth_headers)
        expected = io.BytesIO()
        qrcode.make(f"{expected_base}/machine/{machine_id}").save(expected, format="PNG")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == expected.getvalue()


def test_missing_asset_records_keep_exact_errors(client, auth_headers):
    cases = [
        ("GET", "/api/machines/-1", None, "Машината не е намерена"),
        ("PATCH", "/api/machines/-1", {"notes": "test-only"}, "Машината не е намерена"),
        ("GET", "/api/machines/-1/qr", None, "Машината не е намерена"),
        ("GET", "/api/machines/-1/passport", None, "Машината не е намерена."),
        ("PUT", "/api/machines/-1/custom-fields", {"values": []}, "Машината не е намерена."),
        (
            "POST",
            "/api/categories/-1/fields",
            {"code": "TEST", "label_bg": "Тест"},
            "Категорията не е намерена.",
        ),
        ("GET", "/api/machine-attachments/-1/download", None, "Файлът не е намерен."),
        (
            "PATCH",
            "/api/admin/locations/-1",
            {"is_active": False},
            "Местоположението не е намерено.",
        ),
        ("PATCH", "/api/admin/departments/-1", {"is_active": False}, "Отделът не е намерен."),
    ]
    for method, path, payload, message in cases:
        response = client.request(method, path, headers=auth_headers, json=payload)
        assert response.status_code == 404, (path, response.text)
        assert response.json() == {"detail": message}


def test_category_create_custom_values_and_audit_contract(
    client, auth_headers, machine_ids, session_factory
):
    payload = {"code": "TEST_CONTRACT", "name_bg": "Тестова категория", "name_en": "Test only"}
    created = client.post("/api/categories", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.text
    category = created.json()
    assert category["code"] == payload["code"]
    assert category["is_active"] is True
    listed = client.get("/api/categories", headers=auth_headers).json()
    assert listed == sorted(listed, key=lambda row: row["name_bg"])
    assert next(row for row in listed if row["id"] == category["id"])["fields"] == []
    field = client.post(
        f"/api/categories/{category['id']}/fields",
        headers=auth_headers,
        json={"code": "TEST_FLAG", "label_bg": "Тестов флаг", "field_type": "BOOLEAN"},
    )
    assert field.status_code == 201, field.text
    field_id = field.json()["id"]
    conflict = client.put(
        f"/api/machines/{machine_ids['4']}/custom-fields",
        headers=auth_headers,
        json={"values": [{"field_id": field_id, "value": "1"}]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "field_category_mismatch"
    machine_payload = {
        "inventory_number": "TEST-CONTRACT",
        "name": "test-only asset",
        "brand": "test-only",
        "category_id": category["id"],
    }
    machine = client.post("/api/machines", headers=auth_headers, json=machine_payload)
    assert machine.status_code == 201, machine.text
    machine_id = machine.json()["id"]
    assert machine.json()["category"] == "TEST_CONTRACT"
    duplicate = client.post("/api/machines", headers=auth_headers, json=machine_payload)
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "Дублиран инвентарен номер"}
    updated = client.put(
        f"/api/machines/{machine_id}/custom-fields",
        headers=auth_headers,
        json={"values": [{"field_id": field_id, "value": "1"}]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json() == {
        "message": "Потребителските полета са обновени.",
        "machine_id": machine_id,
        "values": [{"field_id": field_id, "value": "true"}],
    }
    with session_factory() as db:
        audits = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
        assert [row.action for row in audits if row.entity_type == "asset_category"] == [
            "Създадена категория"
        ]
        assert [row.action for row in audits if row.entity_type == "category_field"] == [
            "Създадено конфигурируемо поле"
        ]
        entry = next(row for row in audits if row.action == "Обновени конфигурируеми полета")
        assert json.loads(entry.details) == {
            "field_ids": [field_id],
            "previous": {"TEST_FLAG": None},
            "new": {"TEST_FLAG": "true"},
        }
        assert entry.entity_id == machine_id
        assert entry.user_id is not None
        assert db.scalar(select(func.count(MachineFieldValue.id))) == 1


def test_attachment_bytes_metadata_history_and_rejection_contract(
    client, auth_headers, machine_ids, session_factory
):
    content = b"%PDF-1.4\n% test-only attachment contract\n"
    payload = {
        "filename": "test-only.pdf",
        "media_type": "application/pdf",
        "content_base64": base64.b64encode(content).decode(),
        "kind": "DOCUMENT",
        "description": "test-only contract",
    }
    machine_id = machine_ids["4"]
    response = client.post(
        f"/api/machines/{machine_id}/attachments", headers=auth_headers, json=payload
    )
    assert response.status_code == 201, response.text
    document = response.json()
    assert set(document) == {
        "id",
        "filename",
        "media_type",
        "sha256",
        "created_at",
        "description",
        "kind",
        "caption",
        "stage",
        "request_line_id",
        "download_endpoint",
    }
    assert document["sha256"] == hashlib.sha256(content).hexdigest()
    downloaded = client.get(f"/api{document['download_endpoint']}", headers=auth_headers)
    assert downloaded.content == content
    assert downloaded.headers["content-disposition"] == 'attachment; filename="test-only.pdf"'
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    for change, code in (
        ({"filename": "../test-only.pdf"}, "unsafe_filename"),
        ({"content_base64": "???"}, "invalid_file_content"),
        ({"media_type": "text/plain"}, "unsupported_media_type"),
        ({"filename": "test-only.png", "media_type": "image/png"}, "file_signature_mismatch"),
    ):
        rejected = client.post(
            f"/api/machines/{machine_id}/attachments",
            headers=auth_headers,
            json={**payload, **change},
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == code
    with session_factory() as db:
        events = db.scalars(select(MachineEvent).where(MachineEvent.machine_id == machine_id)).all()
        assert len(events) == 1
        assert events[0].event_type == "ATTACHMENT_ADDED"
        assert events[0].details == {"filename": "test-only.pdf", "kind": "DOCUMENT"}
        audit = db.scalar(select(AuditLog).where(AuditLog.entity_type == "machine_attachment"))
        assert audit.action == "Добавен файл към машината"
        assert json.loads(audit.details) == {
            "machine_number": "4",
            "filename": "test-only.pdf",
            "sha256": document["sha256"],
        }


def test_master_data_ordering_deactivation_and_exact_duplicate_errors(client, auth_headers):
    first = client.post(
        "/api/admin/locations", headers=auth_headers, json={"name": "  TEST-ONLY Place  "}
    ).json()
    second = client.post(
        "/api/admin/locations", headers=auth_headers, json={"name": "TEST-ONLY Other"}
    ).json()
    duplicate = client.patch(
        f"/api/admin/locations/{second['id']}",
        headers=auth_headers,
        json={"name": "test-only place"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {
        "code": "location_duplicate",
        "message": "Вече съществува местоположение със същото име.",
        "name": "test-only place",
    }
    assert (
        client.patch(
            f"/api/admin/locations/{first['id']}", headers=auth_headers, json={"is_active": False}
        ).status_code
        == 200
    )
    locations = client.get("/api/locations", headers=auth_headers).json()
    assert locations == sorted(locations, key=lambda row: row["name"])
    assert next(row for row in locations if row["id"] == first["id"])["is_active"] is False
    department = client.post(
        "/api/admin/departments",
        headers=auth_headers,
        json={"code": "TEST_CONTRACT", "name_bg": "Тестов отдел"},
    )
    assert department.status_code == 201, department.text
    assert department.json()["code"] == "TEST_CONTRACT"
    duplicate = client.post(
        "/api/admin/departments",
        headers=auth_headers,
        json={"code": "TEST_CONTRACT", "name_bg": "Тестов отдел"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == {
        "code": "department_duplicate",
        "message": "Вече съществува отдел със същия системен код.",
        "department_code": "TEST_CONTRACT",
    }
    department_id = department.json()["id"]
    assert (
        client.patch(
            f"/api/admin/departments/{department_id}",
            headers=auth_headers,
            json={"is_active": False},
        ).status_code
        == 200
    )
    departments = client.get("/api/departments", headers=auth_headers).json()
    assert departments == sorted(departments, key=lambda row: row["code"])
    assert next(row for row in departments if row["id"] == department_id)["is_active"] is False
    assert client.get("/api/admin/reference-data", headers=auth_headers).json() == {
        "locations": locations,
        "departments": departments,
    }


def test_machine_patch_cannot_override_repair_authority(
    client, auth_headers, machine_ids, session_factory
):
    machine_id = machine_ids["4"]
    repair = client.post(
        "/api/repair-cases",
        headers=auth_headers,
        json={"machine_id": machine_id, "reported_problem": "test-only repair contract"},
    )
    assert repair.status_code == 201, repair.text
    rejected = client.patch(
        f"/api/machines/{machine_id}", headers=auth_headers, json={"status": "READY"}
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == {
        "code": "authoritative_machine_status_conflict",
        "message": "Статусът на машина №4 не може да бъде сменен на „READY“. Текущите предавания и ремонтни карти изискват статус „REPAIR“.",
    }
    with session_factory() as db:
        assert db.get(Machine, machine_id).status == "REPAIR"
        assert not db.scalar(
            select(MachineEvent).where(MachineEvent.event_type == "MACHINE_UPDATED")
        )


def test_passport_and_machine_patch_preserve_active_transfer_authority(
    client,
    auth_headers,
    viewer_headers,
    machine_ids,
    issue_payload,
    finalize_signatures,
    session_factory,
):
    machine_id = machine_ids["7"]
    issued = client.post(
        "/api/transfers/bulk-issue", headers=auth_headers, json=issue_payload(machine_id)
    )
    assert issued.status_code == 201, issued.text
    finalize_signatures(client, issued)
    transfer = issued.json()["transfers"][0]
    rejected = client.patch(
        f"/api/machines/{machine_id}",
        headers=auth_headers,
        json={"status": "READY", "notes": "must not persist"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == {
        "code": "authoritative_machine_status_conflict",
        "message": "Статусът на машина №7 не може да бъде сменен на „READY“. Текущите предавания и ремонтни карти изискват статус „ISSUED“.",
    }
    passport = client.get(f"/api/machines/{machine_id}/passport", headers=auth_headers).json()
    assert passport["machine"]["status"] == "ISSUED"
    assert passport["current_state"]["available"] is False
    assert passport["current_state"]["active_transfer"]["id"] == transfer["transfer_id"]
    assert passport["current_state"]["allowed_actions"]["issue"] is False
    assert passport["current_state"]["allowed_actions"]["return"] is True
    assert passport["transfers"][0]["protocol_number"] == transfer["protocol_number"]
    # Transfer ProtocolDocument rows are not GeneratedDocument rows. The legacy
    # passport must not synthesize entries in its generated_documents collection.
    assert passport["generated_documents"] == []
    assert {document["format"] for document in transfer["documents"]} == {"docx", "pdf"}
    for document in transfer["documents"]:
        assert document["download_endpoint"] == f"/api/protocol-documents/{document['id']}/download"
        downloaded = client.get(document["download_endpoint"], headers=auth_headers)
        assert downloaded.status_code == 200
        media_type, file_signature = {
            "docx": (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                b"PK\x03\x04",
            ),
            "pdf": ("application/pdf", b"%PDF-"),
        }[document["format"]]
        # An HTML SPA fallback can also return 200; require actual document bytes.
        assert downloaded.headers["content-type"] == media_type
        assert downloaded.content.startswith(file_signature)
    assert passport["audit_visible"] is True
    limited = client.get(f"/api/machines/{machine_id}/passport", headers=viewer_headers).json()
    assert limited["current_state"]["active_transfer"] == {"is_active": True}
    assert (
        limited["transfers"]
        == limited["generated_documents"]
        == limited["history"]
        == limited["audit"]
        == []
    )
    assert limited["qr_endpoint"] is None
    with session_factory() as db:
        assert db.get(Machine, machine_id).notes != "must not persist"
        assert not db.scalar(
            select(MachineEvent).where(MachineEvent.event_type == "MACHINE_UPDATED")
        )
