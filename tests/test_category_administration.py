"""ASSET-01D master-data safety with disposable records only."""

import json

from app.models import AssetCategory, AuditLog, Machine, MachineFieldValue, ProtocolDocument
from sqlalchemy import select


def _create_category(client, headers, code, capabilities=None):
    response = client.post("/api/categories", headers=headers, json={
        "code": code, "name_bg": "Тестова категория", "name_en": "Test category",
        "name_ru": "Тестовая категория", "capabilities": capabilities or [],
    })
    assert response.status_code == 201, response.text
    return response.json()


def _create_asset(client, headers, category_id, number, **extra):
    return client.post("/api/machines", headers=headers, json={
        "inventory_number": number, "name": "Тестов актив", "brand": "QA",
        "category_id": category_id, **extra,
    })


def test_category_registry_lifecycle_pressure_safety_and_audit(
    client, auth_headers, viewer_headers, session_factory, machine_ids,
):
    assert len(machine_ids) == 19
    with session_factory() as db:
        before = {machine.id: (machine.inventory_number, machine.category_id, machine.pressure_bar)
                  for machine in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))}
        hpwj = db.scalar(select(AssetCategory).where(AssetCategory.code == "HPWJ"))
        assert hpwj is not None
        assert set(hpwj.capabilities) == {
            "HAS_PRESSURE", "HAS_PARTS_CATALOG", "HAS_REPAIR_WORKFLOW", "HAS_TRANSFER_WORKFLOW",
        }

    registry = client.get("/api/admin/asset-capabilities", headers=auth_headers)
    assert registry.status_code == 200
    assert {item["code"] for item in registry.json()} == {
        "HAS_PRESSURE", "HAS_PARTS_CATALOG", "HAS_REPAIR_WORKFLOW", "HAS_TRANSFER_WORKFLOW",
    }
    assert all(item[f"{kind}_{locale}"].strip() for item in registry.json()
               for kind in ("name", "description") for locale in ("bg", "en", "ru"))
    assert client.get("/api/admin/asset-capabilities", headers=viewer_headers).status_code == 403
    assert client.post("/api/categories", headers=viewer_headers, json={
        "code": "QA_DENIED", "name_bg": "Забранено",
    }).status_code == 403

    category = _create_category(client, auth_headers, "QA_ADMIN_PRESSURE", ["HAS_PRESSURE"])
    category_id = category["id"]
    duplicate = client.post("/api/categories", headers=auth_headers, json={
        "code": "QA_ADMIN_PRESSURE", "name_bg": "Дубликат",
    })
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "category_code_duplicate"
    assert client.post("/api/categories", headers=auth_headers, json={
        "code": "QA_UNKNOWN", "name_bg": "Неизвестна", "capabilities": ["UNKNOWN"],
    }).status_code == 422

    asset = _create_asset(client, auth_headers, category_id, "QA-ADMIN-PRESSURE", pressure_bar=500)
    assert asset.status_code == 201, asset.text
    asset_id = asset.json()["id"]
    path = f"/api/categories/{category_id}"
    conflict = client.patch(path, headers=auth_headers, json={"capabilities": []})
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "category_capability_in_use"
    assert conflict.json()["detail"]["affected_asset_count"] == 1
    with session_factory() as db:
        assert db.get(Machine, asset_id).pressure_bar == 500
        assert db.get(AssetCategory, category_id).capabilities == ["HAS_PRESSURE"]

    assert client.patch(f"/api/machines/{asset_id}", headers=auth_headers, json={"pressure_bar": None}).status_code == 200
    updated = client.patch(path, headers=auth_headers, json={
        "name_bg": "Обновена категория", "name_en": "Updated category", "capabilities": [],
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["capabilities"] == []
    assert updated.json()["name_bg"] == "Обновена категория"
    assert client.patch(path, headers=auth_headers, json={"code": "QA_RENAMED"}).status_code == 422
    assert client.patch(path, headers=viewer_headers, json={"is_active": False}).status_code == 403
    assert client.patch(path, headers=auth_headers, json={"is_active": False}).status_code == 200
    listed = next(item for item in client.get("/api/categories", headers=auth_headers).json() if item["id"] == category_id)
    assert listed["asset_count"] == 1 and listed["is_active"] is False
    navigation = client.get("/api/machines/category-navigation", headers=auth_headers).json()
    assert any(item["id"] == category_id and item["asset_count"] == 1 for item in navigation)
    assert client.get(f"/api/machines/{asset_id}", headers=auth_headers).status_code == 200
    assert _create_asset(client, auth_headers, category_id, "QA-ADMIN-DENIED").status_code == 422
    assert client.patch(path, headers=auth_headers, json={"is_active": True}).status_code == 200
    assert _create_asset(client, auth_headers, category_id, "QA-ADMIN-ALLOWED").status_code == 201
    empty = _create_category(client, auth_headers, "QA_ADMIN_EMPTY")
    assert client.patch(f"/api/categories/{empty['id']}", headers=auth_headers,
                        json={"is_active": False}).status_code == 200
    assert any(item["id"] == empty["id"] for item in client.get(
        "/api/categories", headers=auth_headers,
    ).json())
    assert all(item["id"] != empty["id"] for item in client.get(
        "/api/machines/category-navigation", headers=auth_headers,
    ).json())

    with session_factory() as db:
        after = {machine.id: (machine.inventory_number, machine.category_id, machine.pressure_bar)
                 for machine in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))}
        assert before == after
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "asset_category", AuditLog.entity_id == category_id)).all()
        assert any(row.action == "Обновена категория" and row.user_id and
                   "previous" in json.loads(row.details) and "changes" in json.loads(row.details)
                   for row in audits)


def test_field_administration_preserves_values_and_rejects_unsafe_changes(
    client, auth_headers, viewer_headers, session_factory,
):
    first = _create_category(client, auth_headers, "QA_FIELD_ADMIN_A")
    second = _create_category(client, auth_headers, "QA_FIELD_ADMIN_B")
    path = f"/api/categories/{first['id']}/fields"
    field = client.post(path, headers=auth_headers, json={
        "code": "QA_CHOICE", "label_bg": "Избор", "field_type": "SELECT", "options": ["A", "B"],
        "sort_order": 3,
    })
    assert field.status_code == 201, field.text
    field_id = field.json()["id"]
    duplicate = client.post(path, headers=auth_headers, json={
        "code": "QA_CHOICE", "label_bg": "Дубликат", "field_type": "TEXT",
    })
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "category_field_code_duplicate"
    assert client.post(f"/api/categories/{second['id']}/fields", headers=auth_headers, json={
        "code": "QA_CHOICE", "label_bg": "Друго поле", "field_type": "TEXT",
    }).status_code == 201
    asset = _create_asset(client, auth_headers, first["id"], "QA-FIELD-ADMIN",
                          custom_fields=[{"field_id": field_id, "value": "A"}])
    assert asset.status_code == 201, asset.text
    edit = f"{path}/{field_id}"
    assert client.patch(edit, headers=auth_headers, json={"code": "QA_RENAME"}).status_code == 422
    assert client.patch(f"/api/categories/{second['id']}/fields/{field_id}", headers=auth_headers,
                        json={"label_bg": "Грешно"}).status_code == 404
    assert client.patch(edit, headers=viewer_headers, json={"sort_order": 1}).status_code == 403
    incompatible = client.patch(edit, headers=auth_headers, json={"options": ["C", "D"]})
    assert incompatible.status_code == 409
    assert incompatible.json()["detail"]["code"] == "category_field_values_incompatible"
    assert client.patch(edit, headers=auth_headers, json={"field_type": "DATE", "options": None}).status_code == 409
    assert client.patch(edit, headers=auth_headers, json={
        "validation_rules": {"pattern": "^[AB]$", "source": "disposable QA"},
    }).status_code == 200
    tightened = client.patch(edit, headers=auth_headers, json={
        "validation_rules": {"pattern": "^[CD]$"},
    })
    assert tightened.status_code == 409
    assert tightened.json()["detail"]["code"] == "category_field_values_incompatible"
    assert client.patch(edit, headers=auth_headers, json={
        "validation_rules": {"pattern": "["},
    }).status_code == 422
    assert client.patch(edit, headers=auth_headers, json={"sort_order": -1}).status_code == 422
    assert client.patch(edit, headers=auth_headers, json={
        "label_bg": "Нов избор", "unit": "бр.", "sort_order": 1, "is_required": True,
    }).status_code == 200
    assert client.patch(edit, headers=auth_headers, json={"is_active": False}).status_code == 200
    listed = next(item for item in client.get("/api/categories", headers=auth_headers).json() if item["id"] == first["id"])
    assert listed["fields"][0]["is_active"] is False
    form = client.get(f"/api/asset-categories/{first['id']}/form-definition", headers=auth_headers).json()
    assert all(item["id"] != field_id for item in form["fields"])
    with session_factory() as db:
        stored = db.scalar(select(MachineFieldValue).where(MachineFieldValue.field_id == field_id))
        assert stored is not None and stored.value == "A"
    assert client.patch(edit, headers=auth_headers, json={"is_active": True}).status_code == 200
    passport = client.get(f"/api/machines/{asset.json()['id']}/passport", headers=auth_headers).json()
    assert any(item["field_id"] == field_id and item["value"] == "A" for item in passport["custom_fields"])
    form = client.get(f"/api/asset-categories/{first['id']}/form-definition", headers=auth_headers).json()
    assert any(item["id"] == field_id and item["label_bg"] == "Нов избор" for item in form["fields"])
    with session_factory() as db:
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "category_field", AuditLog.entity_id == field_id)).all()
        assert any(row.action == "Обновено конфигурируемо поле" and row.user_id for row in audits)


def test_workflow_capabilities_remain_independent(client, auth_headers):
    codes = ["HAS_REPAIR_WORKFLOW", "HAS_TRANSFER_WORKFLOW", "HAS_PARTS_CATALOG"]
    for index, code in enumerate(codes):
        category = _create_category(client, auth_headers, f"QA_CAPABILITY_{index}", [code])
        assert _create_asset(client, auth_headers, category["id"], f"QA-CAP-{index}").status_code == 201
        changed = client.patch(f"/api/categories/{category['id']}", headers=auth_headers,
                               json={"capabilities": []})
        assert changed.status_code == 200, changed.text
        assert changed.json()["capabilities"] == []


def test_active_transfer_can_finish_after_admin_removes_capability(
    client, auth_headers, issue_payload, finalize_signatures, session_factory,
):
    category = _create_category(client, auth_headers, "QA_TRANSFER_ADMIN", ["HAS_TRANSFER_WORKFLOW"])
    asset = _create_asset(client, auth_headers, category["id"], "QA-TRANSFER-ADMIN")
    assert asset.status_code == 201, asset.text
    asset_id = asset.json()["id"]
    issued = client.post("/api/transfers/bulk-issue", headers=auth_headers,
                         json=issue_payload(asset_id))
    assert issued.status_code == 201, issued.text
    finalize_signatures(client, issued)
    transfer_id = issued.json()["transfers"][0]["transfer_id"]
    with session_factory() as db:
        hashes = {item.id: item.sha256 for item in db.scalars(select(ProtocolDocument).where(
            ProtocolDocument.transfer_id == transfer_id,
        ))}
    assert client.patch(f"/api/categories/{category['id']}", headers=auth_headers,
                        json={"capabilities": []}).status_code == 200
    returned = client.post("/api/transfers/bulk-return", headers=auth_headers, json={
        "document_language": "bg", "items": [{
            "transfer_id": transfer_id, "machine_id": asset_id,
            "condition_text": "Тестово проверено състояние", "result_text": "Тестово приемане",
            "notes": "QA", "next_status": "READY",
        }],
    })
    assert returned.status_code == 200, returned.text
    finalize_signatures(client, returned)
    passport = client.get(f"/api/machines/{asset_id}/passport", headers=auth_headers).json()
    assert passport["current_state"]["active_transfer"] is None
    with session_factory() as db:
        assert {identifier: db.get(ProtocolDocument, identifier).sha256 for identifier in hashes} == hashes
    denied = client.post("/api/transfers/bulk-issue", headers=auth_headers,
                         json=issue_payload(asset_id))
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "workflow_not_supported"


def test_generic_category_end_to_end(client, auth_headers, issue_payload):
    category = _create_category(client, auth_headers, "QA_E2E_PAINT", ["HAS_REPAIR_WORKFLOW"])
    category_id = category["id"]
    fields = []
    for code, label, kind, extra in (
        ("QA_RATIO", "Съотношение", "TEXT", {}),
        ("QA_PUMP_TYPE", "Тип помпа", "SELECT", {"options": ["Piston", "Diaphragm"]}),
    ):
        response = client.post(f"/api/categories/{category_id}/fields", headers=auth_headers,
                               json={"code": code, "label_bg": label, "field_type": kind, **extra})
        assert response.status_code == 201, response.text
        fields.append(response.json()["id"])
    before = client.get("/api/machines/category-navigation", headers=auth_headers).json()
    assert next(item for item in before if item["id"] == category_id)["asset_count"] == 0
    asset = _create_asset(client, auth_headers, category_id, "QA-E2E-PAINT",
                          custom_fields=[{"field_id": fields[0], "value": "30:1"},
                                         {"field_id": fields[1], "value": "Piston"}])
    assert asset.status_code == 201, asset.text
    asset_id = asset.json()["id"]
    assert asset.json()["pressure_bar"] is None
    after = client.get("/api/machines/category-navigation", headers=auth_headers).json()
    assert next(item for item in after if item["id"] == category_id)["asset_count"] == 1
    filtered = client.get(f"/api/machines?category_id={category_id}", headers=auth_headers).json()
    assert [row["id"] for row in filtered] == [asset_id]
    form = client.get(f"/api/asset-categories/{category_id}/form-definition", headers=auth_headers).json()
    assert {item["code"] for item in form["fields"]} == {"QA_RATIO", "QA_PUMP_TYPE"}
    passport = client.get(f"/api/machines/{asset_id}/passport", headers=auth_headers).json()
    assert {(item["code"], item["value"]) for item in passport["custom_fields"]} == {
        ("QA_RATIO", "30:1"), ("QA_PUMP_TYPE", "Piston"),
    }
    assert client.get(f"/api/machines/{asset_id}/qr", headers=auth_headers).status_code == 200
    assert client.get(f"/api/machines/{asset_id}/timeline", headers=auth_headers).status_code == 200
    blocked_transfer = client.post("/api/transfers/bulk-issue", headers=auth_headers,
                                   json=issue_payload(asset_id))
    assert blocked_transfer.status_code == 409
    assert blocked_transfer.json()["detail"]["code"] == "workflow_not_supported"
    catalog = client.get(f"/api/catalog/v2/machines/{asset_id}", headers=auth_headers)
    assert catalog.status_code == 200 and catalog.json()["supported"] is False
    manual = client.post("/api/part-requests/multi", headers=auth_headers, json={
        "machine_id": asset_id, "lines": [{"part_number": "QA-MANUAL",
                                           "description": "Тестова ръчна част", "quantity": 1}],
    })
    assert manual.status_code == 201, manual.text
    repair = client.post("/api/repairs", headers=auth_headers,
                         json={"machine_id": asset_id, "reported_problem": "Тестов проблем"})
    assert repair.status_code == 201, repair.text
    assert client.patch(f"/api/categories/{category_id}", headers=auth_headers,
                        json={"is_active": False}).status_code == 200
    assert client.get(f"/api/machines/{asset_id}/passport", headers=auth_headers).status_code == 200
    assert client.get(f"/api/repair-cases/{repair.json()['id']}", headers=auth_headers).status_code == 200
    assert _create_asset(client, auth_headers, category_id, "QA-E2E-DENIED").status_code == 422


def test_disposable_cross_category_capability_matrix(client, auth_headers):
    matrix = {
        "BASIC": [],
        "PRESSURE_ONLY": ["HAS_PRESSURE"],
        "REPAIR_ONLY": ["HAS_REPAIR_WORKFLOW"],
        "TRANSFER_ONLY": ["HAS_TRANSFER_WORKFLOW"],
        "CATALOG_ONLY": ["HAS_PARTS_CATALOG"],
        "FULL": ["HAS_PRESSURE", "HAS_REPAIR_WORKFLOW", "HAS_TRANSFER_WORKFLOW", "HAS_PARTS_CATALOG"],
    }
    assets = {}
    for name, capabilities in matrix.items():
        category = _create_category(client, auth_headers, f"QA_MATRIX_{name}", capabilities)
        assert category["capabilities"] == capabilities
        response = _create_asset(client, auth_headers, category["id"], f"QA-MATRIX-{name}",
                                 pressure_bar=250 if "HAS_PRESSURE" in capabilities else None)
        assert response.status_code == 201, response.text
        assets[name] = response.json()["id"]
        assert response.json()["pressure_bar"] == (250 if "HAS_PRESSURE" in capabilities else None)
        form = client.get(f"/api/asset-categories/{category['id']}/form-definition",
                          headers=auth_headers).json()
        assert form["capabilities"] == capabilities
    transfer = {row["machine_id"]: row for row in client.get(
        "/api/transfers/availability", headers=auth_headers,
    ).json()}
    for name, asset_id in assets.items():
        assert transfer[asset_id]["available"] == (name in {"TRANSFER_ONLY", "FULL"})
        repair = client.post("/api/repairs", headers=auth_headers,
                             json={"machine_id": asset_id, "reported_problem": "QA"})
        assert repair.status_code == (201 if name in {"REPAIR_ONLY", "FULL"} else 409)
