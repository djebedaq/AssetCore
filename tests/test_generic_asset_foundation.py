"""Generic assets and the category identity contract use test database records only."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from types import SimpleNamespace

from app.documents import transfer_documents
from app.models import Machine
from app.transfer_service import _transfer_reference_prefix
from sqlalchemy import select


def test_generic_asset_flows_without_pressure(client, auth_headers, session_factory):
    created_category = client.post(
        "/api/categories", headers=auth_headers,
        json={"code": "QA_GENERIC_ASSET", "name_bg": "Тестов актив",
              "name_en": "QA asset", "name_ru": "Тестовый актив"},
    )
    assert created_category.status_code == 201, created_category.text
    category = created_category.json()
    assert category["capabilities"] == []
    field = client.post(
        f"/api/categories/{category['id']}/fields", headers=auth_headers,
        json={"code": "QA_NOTE", "label_bg": "Тестово поле", "field_type": "TEXT"},
    )
    assert field.status_code == 201, field.text
    asset = client.post(
        "/api/machines", headers=auth_headers,
        json={"inventory_number": "QA-GENERIC-001", "name": "Тестов актив",
              "category_id": category["id"], "brand": "Тестов производител",
              "model": "QA"},
    )
    assert asset.status_code == 201, asset.text
    machine = asset.json()
    machine_id = machine["id"]
    assert machine["category"] == category["code"]
    assert machine["category_id"] == category["id"]
    assert machine["pressure_bar"] is None
    assert client.get(f"/api/machines/{machine_id}", headers=auth_headers).json()["pressure_bar"] is None
    assert any(item["id"] == machine_id for item in client.get("/api/machines", headers=auth_headers).json())
    updated = client.patch(
        f"/api/machines/{machine_id}", headers=auth_headers,
        json={"notes": "Тестова промяна"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["pressure_bar"] is None
    custom = client.put(
        f"/api/machines/{machine_id}/custom-fields", headers=auth_headers,
        json={"values": [{"field_id": field.json()["id"], "value": "QA"}]},
    )
    assert custom.status_code == 200, custom.text
    attachment = client.post(
        f"/api/machines/{machine_id}/attachments", headers=auth_headers,
        json={"filename": "qa.pdf", "media_type": "application/pdf",
              "content_base64": base64.b64encode(b"%PDF-1.4\n% QA attachment").decode(),
              "kind": "DOCUMENT"},
    )
    assert attachment.status_code == 201, attachment.text
    passport = client.get(f"/api/machines/{machine_id}/passport", headers=auth_headers)
    assert passport.status_code == 200, passport.text
    body = passport.json()
    assert body["machine"]["category"] == "QA_GENERIC_ASSET"
    assert body["machine"]["category_definition"]["capabilities"] == []
    assert body["machine"]["pressure_bar"] is None
    assert any(value["code"] == "QA_NOTE" and value["value"] == "QA" for value in body["custom_fields"])
    assert any(value["id"] == attachment.json()["id"] for value in body["attachments"])
    qr = client.get(f"/api/machines/{machine_id}/qr", headers=auth_headers)
    assert qr.status_code == 200 and qr.headers["content-type"] == "image/png"
    timeline = client.get(f"/api/machines/{machine_id}/timeline", headers=auth_headers)
    assert timeline.status_code == 200, timeline.text
    assert {item["event_type"] for item in timeline.json()["items"]} >= {
        "MACHINE_CREATED", "MACHINE_UPDATED"
    }
    preview = client.post(
        "/api/admin/import-preview", headers=auth_headers,
        json={"records": [{"inventory_number": "QA-GENERIC-IMPORT", "name": "QA import",
                           "category": category["code"], "brand": "QA"}]},
    )
    assert preview.status_code == 200 and preview.json()["can_confirm"] is True
    assert preview.json()["valid_records"][0]["pressure_bar"] is None
    imported = client.post(
        "/api/admin/import-confirm", headers=auth_headers,
        json={"preview_token": preview.json()["preview_token"]},
    )
    assert imported.status_code == 201, imported.text
    imported_asset = client.get(
        f"/api/machines/{imported.json()['created'][0]['id']}", headers=auth_headers,
    )
    assert imported_asset.json()["category_id"] == category["id"]
    assert imported_asset.json()["pressure_bar"] is None
    with session_factory() as db:
        persisted = db.scalar(select(Machine).where(Machine.id == machine_id))
        assert persisted is not None and persisted.pressure_bar is None


def test_category_identity_rejects_conflicts_and_legacy_code_resolves(
    client, auth_headers, machine_ids,
):
    hpwj = next(item for item in client.get("/api/categories", headers=auth_headers).json()
                if item["code"] == "HPWJ")
    assert "HAS_PRESSURE" in hpwj["capabilities"]
    existing = client.get(f"/api/machines/{machine_ids['4']}", headers=auth_headers).json()
    assert existing["category_id"] == hpwj["id"]
    assert existing["pressure_bar"] == 500
    conflict = client.post(
        "/api/machines", headers=auth_headers,
        json={"inventory_number": "QA-CONFLICT", "name": "QA", "brand": "QA",
              "category_id": hpwj["id"], "category": "QA_OTHER"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "category_mismatch"
    legacy = client.post(
        "/api/machines", headers=auth_headers,
        json={"inventory_number": "QA-LEGACY-CODE", "name": "QA", "brand": "QA",
              "category": "HPWJ"},
    )
    assert legacy.status_code == 201, legacy.text
    assert legacy.json()["category_id"] == hpwj["id"]
    update = client.patch(
        f"/api/machines/{legacy.json()['id']}", headers=auth_headers,
        json={"category_id": hpwj["id"], "category": "QA_OTHER"},
    )
    assert update.status_code == 409
    assert update.json()["detail"]["code"] == "category_mismatch"
    attempted_machine_capability = client.patch(
        f"/api/machines/{legacy.json()['id']}", headers=auth_headers,
        json={"capabilities": ["HAS_PARTS_CATALOG"]},
    )
    assert attempted_machine_capability.status_code == 200
    assert "capabilities" not in attempted_machine_capability.json()
    hpwj_after = next(item for item in client.get("/api/categories", headers=auth_headers).json()
                      if item["id"] == hpwj["id"])
    assert hpwj_after["capabilities"] == hpwj["capabilities"]


def test_transfer_document_identity_uses_generic_category_without_hpwj_fallback(monkeypatch):
    machine = SimpleNamespace(
        category="QA_GENERIC_ASSET", brand="QA", manufacturer=None, model=None,
        pressure_bar=None, name="QA asset", inventory_number="QA-1", serial_number=None,
    )

    class TransferStub:
        created_at = datetime(2026, 9, 24, tzinfo=UTC)
        protocol_number = "QA-PROTOCOL"

        def __init__(self):
            self.machine = machine

        def __getattr__(self, _name):
            return None

    transfer = TransferStub()
    monkeypatch.setattr(transfer_documents, "_preparer_values", lambda *_: {})
    rows = transfer_documents._identity_rows(transfer, "issue", "bg")
    assert "QA_GENERIC_ASSET" in [value for _, value in rows]
    values = transfer_documents._protocol_template_values(
        None, transfer, "QA-BATCH", "issue", "bg", 1,
    )
    assert values["EQUIPMENT_TYPE"] == "QA_GENERIC_ASSET"
    assert values["PRESSURE_BAR"] == ""
    machine.category = ""
    assert transfer_documents._protocol_template_values(
        None, transfer, "QA-BATCH", "issue", "bg", 1,
    )["EQUIPMENT_TYPE"] == ""


def test_new_transfer_references_follow_category_identity():
    assert _transfer_reference_prefix(SimpleNamespace(category_id=1, category="HPWJ")) == "HPWJ"
    assert _transfer_reference_prefix(SimpleNamespace(category_id=2, category="QA_GENERIC_ASSET")) == "QA_GENERIC_ASSET"
    assert _transfer_reference_prefix(SimpleNamespace(category_id=None, category="HPWJ")) == "ASSET"
