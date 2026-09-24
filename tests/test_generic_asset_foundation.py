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


def test_pressure_capability_is_enforced_on_create_update_and_category_change(
    client, auth_headers, machine_ids, session_factory,
):
    assert len(machine_ids) == 19
    with session_factory() as db:
        verified_before = {
            item.id: (item.category, item.category_id, item.pressure_bar)
            for item in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))
        }

    generic_response = client.post(
        "/api/categories", headers=auth_headers,
        json={"code": "QA_NO_PRESSURE", "name_bg": "Тестов актив"},
    )
    assert generic_response.status_code == 201, generic_response.text
    generic_id = generic_response.json()["id"]

    def create(number: str, category_id: int, **extra):
        return client.post(
            "/api/machines", headers=auth_headers,
            json={"inventory_number": number, "name": "QA asset", "brand": "QA",
                  "category_id": category_id, **extra},
        )

    rejected = create("QA-PRESSURE-REJECT", generic_id, pressure_bar=500)
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "pressure_not_applicable"

    omitted = create("QA-PRESSURE-OMITTED", generic_id)
    explicit_null = create("QA-PRESSURE-NULL", generic_id, pressure_bar=None)
    assert omitted.status_code == explicit_null.status_code == 201
    assert omitted.json()["pressure_bar"] is None
    assert explicit_null.json()["pressure_bar"] is None

    blocked_patch = client.patch(
        f"/api/machines/{omitted.json()['id']}", headers=auth_headers,
        json={"pressure_bar": 500},
    )
    assert blocked_patch.status_code == 422
    assert blocked_patch.json()["detail"]["code"] == "pressure_not_applicable"
    assert client.get(
        f"/api/machines/{omitted.json()['id']}", headers=auth_headers,
    ).json()["pressure_bar"] is None

    hpwj = next(item for item in client.get("/api/categories", headers=auth_headers).json()
                if item["code"] == "HPWJ")
    hpwj_asset = create("QA-HPWJ-TRANSITION", hpwj["id"], pressure_bar=500)
    assert hpwj_asset.status_code == 201, hpwj_asset.text
    hpwj_asset_id = hpwj_asset.json()["id"]
    blocked_transition = client.patch(
        f"/api/machines/{hpwj_asset_id}", headers=auth_headers,
        json={"category_id": generic_id},
    )
    assert blocked_transition.status_code == 422
    assert blocked_transition.json()["detail"]["code"] == "pressure_not_applicable"
    unchanged = client.get(f"/api/machines/{hpwj_asset_id}", headers=auth_headers).json()
    assert unchanged["category_id"] == hpwj["id"]
    assert unchanged["pressure_bar"] == 500
    cleared = client.patch(
        f"/api/machines/{hpwj_asset_id}", headers=auth_headers,
        json={"category_id": generic_id, "pressure_bar": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["category_id"] == generic_id
    assert cleared.json()["category"] == "QA_NO_PRESSURE"
    assert cleared.json()["pressure_bar"] is None

    capable_response = client.post(
        "/api/categories", headers=auth_headers,
        json={"code": "QA_PRESSURE_CAPABLE", "name_bg": "Тестово налягане",
              "capabilities": ["HAS_PRESSURE"]},
    )
    assert capable_response.status_code == 201, capable_response.text
    capable_id = capable_response.json()["id"]
    with_pressure = create("QA-CAPABLE-500", capable_id, pressure_bar=500)
    without_pressure = create("QA-CAPABLE-NULL", capable_id, pressure_bar=None)
    assert with_pressure.status_code == without_pressure.status_code == 201
    assert with_pressure.json()["pressure_bar"] == 500
    assert without_pressure.json()["pressure_bar"] is None

    with session_factory() as db:
        transitioned = db.get(Machine, hpwj_asset_id)
        assert transitioned.category_id == generic_id
        assert transitioned.pressure_bar is None
        verified_after = {
            item.id: (item.category, item.category_id, item.pressure_bar)
            for item in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))
        }
    assert verified_after == verified_before


def test_import_pressure_capability_uses_category_metadata(client, auth_headers):
    generic = client.post(
        "/api/categories", headers=auth_headers,
        json={"code": "QA_IMPORT_GENERIC", "name_bg": "Тестов импорт"},
    )
    assert generic.status_code == 201, generic.text
    invalid = client.post(
        "/api/admin/import-preview", headers=auth_headers,
        json={"records": [{"inventory_number": "QA-IMPORT-REJECT", "name": "QA",
                           "brand": "QA", "category": "QA_IMPORT_GENERIC",
                           "pressure_bar": 500}]},
    )
    assert invalid.status_code == 200
    assert invalid.json()["can_confirm"] is False
    assert invalid.json()["valid_records"] == []
    assert invalid.json()["errors"][0]["row"] == 1
    assert "Налягането не е приложимо" in invalid.json()["errors"][0]["message"]

    valid = client.post(
        "/api/admin/import-preview", headers=auth_headers,
        json={"records": [
            {"inventory_number": "QA-IMPORT-BLANK", "name": "QA", "brand": "QA",
             "category": "QA_IMPORT_GENERIC", "pressure_bar": ""},
            {"inventory_number": "QA-IMPORT-OMITTED", "name": "QA", "brand": "QA",
             "category": "QA_IMPORT_GENERIC"},
        ]},
    )
    assert valid.status_code == 200 and valid.json()["can_confirm"] is True
    assert [row["pressure_bar"] for row in valid.json()["valid_records"]] == [None, None]
    imported = client.post(
        "/api/admin/import-confirm", headers=auth_headers,
        json={"preview_token": valid.json()["preview_token"]},
    )
    assert imported.status_code == 201, imported.text
    assert len(imported.json()["created"]) == 2
    for item in imported.json()["created"]:
        assert client.get(
            f"/api/machines/{item['id']}", headers=auth_headers,
        ).json()["pressure_bar"] is None

    capable = client.post(
        "/api/categories", headers=auth_headers,
        json={"code": "QA_IMPORT_PRESSURE", "name_bg": "Тестово налягане",
              "capabilities": ["HAS_PRESSURE"]},
    )
    assert capable.status_code == 201, capable.text
    capable_preview = client.post(
        "/api/admin/import-preview", headers=auth_headers,
        json={"records": [{"inventory_number": "QA-IMPORT-500", "name": "QA",
                           "brand": "QA", "category": "QA_IMPORT_PRESSURE",
                           "pressure_bar": 500}]},
    )
    assert capable_preview.status_code == 200
    assert capable_preview.json()["can_confirm"] is True
    assert capable_preview.json()["valid_records"][0]["pressure_bar"] == 500
    capable_import = client.post(
        "/api/admin/import-confirm", headers=auth_headers,
        json={"preview_token": capable_preview.json()["preview_token"]},
    )
    assert capable_import.status_code == 201, capable_import.text
    assert client.get(
        f"/api/machines/{capable_import.json()['created'][0]['id']}",
        headers=auth_headers,
    ).json()["pressure_bar"] == 500


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
