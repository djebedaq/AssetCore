"""ASSET-01C contracts use only disposable synthetic records."""

from __future__ import annotations

from app.models import (
    AssetCategory,
    CategoryFieldDefinition,
    Machine,
    MachineFieldValue,
    PartCatalog,
)
from sqlalchemy import select


def _category(client, headers, code, capabilities=None):
    response = client.post("/api/categories", headers=headers, json={
        "code": code, "name_bg": "Тестова категория", "name_en": "Test category",
        "name_ru": "Тестовая категория", "capabilities": capabilities or [],
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _field(client, headers, category_id, code, kind="TEXT", **extra):
    response = client.post(f"/api/categories/{category_id}/fields", headers=headers, json={
        "code": code, "label_bg": f"Поле {code}", "label_en": f"Field {code}",
        "label_ru": f"Поле {code}", "field_type": kind, **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _asset(client, headers, number, category_id, fields=None):
    payload = {"inventory_number": number, "name": "Тестов актив", "brand": "QA",
               "category_id": category_id}
    if fields is not None:
        payload["custom_fields"] = fields
    return client.post("/api/machines", headers=headers, json=payload)


def test_form_projection_atomic_writes_and_field_lifecycle(
    client, auth_headers, viewer_headers, session_factory, machine_ids,
):
    assert len(machine_ids) == 19
    with session_factory() as db:
        hpwj_before = {
            item.id: (item.inventory_number, item.category_id, item.pressure_bar)
            for item in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))
        }
    source = _category(client, auth_headers, "QA_DYNAMIC_SOURCE")
    target = _category(client, auth_headers, "QA_DYNAMIC_TARGET")
    text_id = _field(client, auth_headers, source, "QA_TEXT", is_required=True,
                     validation_rules={"min_length": 2, "max_length": 8, "pattern": "[A-Z]+"}, sort_order=2)
    integer_id = _field(client, auth_headers, source, "QA_INTEGER", "INTEGER",
                        validation_rules={"min": 1, "max": 10}, sort_order=1, unit="mm")
    decimal_id = _field(client, auth_headers, source, "QA_DECIMAL", "DECIMAL")
    boolean_id = _field(client, auth_headers, source, "QA_BOOLEAN", "BOOLEAN")
    date_id = _field(client, auth_headers, source, "QA_DATE", "DATE")
    active_date_id = _field(client, auth_headers, source, "QA_ACTIVE_DATE", "DATE")
    select_id = _field(client, auth_headers, source, "QA_SELECT", "SELECT", options=["A", "B"])
    target_id = _field(client, auth_headers, target, "QA_TARGET", is_required=True)
    with session_factory() as db:
        inactive = db.get(CategoryFieldDefinition, date_id)
        inactive.is_active = False
        db.commit()

    projection = client.get(f"/api/asset-categories/{source}/form-definition", headers=auth_headers)
    assert projection.status_code == 200, projection.text
    body = projection.json()
    assert set(body) == {"id", "code", "name_bg", "name_en", "name_ru", "is_active", "capabilities", "fields"}
    ordered_ids = [field["id"] for field in body["fields"]]
    assert ordered_ids.index(integer_id) < ordered_ids.index(text_id)
    assert date_id not in {field["id"] for field in body["fields"]}
    assert next(field for field in body["fields"] if field["id"] == integer_id)["unit"] == "mm"
    assert next(field for field in body["fields"] if field["id"] == text_id)["label_en"] == "Field QA_TEXT"
    assert client.get(f"/api/asset-categories/{source}/form-definition", headers=viewer_headers).status_code == 403

    missing = _asset(client, auth_headers, "QA-DYNAMIC-MISSING", source)
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "required_custom_field"
    invalid = _asset(client, auth_headers, "QA-DYNAMIC-INVALID", source,
                     [{"field_id": text_id, "value": "AB"}, {"field_id": integer_id, "value": "11"}])
    assert invalid.status_code == 422 and invalid.json()["detail"]["code"] == "invalid_custom_field_value"
    invalid_text = _asset(client, auth_headers, "QA-DYNAMIC-BAD-TEXT", source,
                          [{"field_id": text_id, "value": "lower"}])
    assert invalid_text.status_code == 422 and invalid_text.json()["detail"]["code"] == "invalid_custom_field_value"
    with session_factory() as db:
        assert db.scalar(select(Machine).where(Machine.inventory_number.in_([
            "QA-DYNAMIC-MISSING", "QA-DYNAMIC-INVALID", "QA-DYNAMIC-BAD-TEXT"]))) is None
    values = [
        {"field_id": text_id, "value": "AB"}, {"field_id": integer_id, "value": "5"},
        {"field_id": decimal_id, "value": "1.50"}, {"field_id": boolean_id, "value": "1"},
        {"field_id": select_id, "value": "A"},
        {"field_id": active_date_id, "value": "2026-09-24"},
    ]
    created = _asset(client, auth_headers, "QA-DYNAMIC-VALID", source, values)
    assert created.status_code == 201, created.text
    machine_id = created.json()["id"]
    edit = client.get(f"/api/machines/{machine_id}/form-data", headers=auth_headers).json()
    assert edit["category"]["id"] == source
    assert {item["field_id"]: item["value"] for item in edit["values"]}[decimal_id] == "1.5"
    assert {item["field_id"]: item["value"] for item in edit["values"]}[active_date_id] == "2026-09-24"
    assert date_id not in {item["id"] for item in edit["category"]["fields"]}
    assert client.get(f"/api/machines/{machine_id}/form-data", headers=viewer_headers).status_code == 403
    with session_factory() as db:
        db.get(CategoryFieldDefinition, active_date_id).is_active = False
        db.commit()
    passport = client.get(f"/api/machines/{machine_id}/passport", headers=auth_headers).json()
    assert date_id not in {item["field_id"] for item in passport["custom_fields"]}
    assert active_date_id not in {item["field_id"] for item in passport["custom_fields"]}
    with session_factory() as db:
        assert db.scalar(select(MachineFieldValue.value).where(
            MachineFieldValue.machine_id == machine_id,
            MachineFieldValue.field_id == active_date_id,
        )) == "2026-09-24"
    assert passport["current_state"]["allowed_actions"]["issue"] is False
    assert passport["current_state"]["allowed_actions"]["repair"] is False

    _field(client, auth_headers, source, "QA_LATER_REQUIRED", is_required=True)
    unrelated = client.patch(f"/api/machines/{machine_id}", headers=auth_headers,
                             json={"notes": "still editable"})
    assert unrelated.status_code == 200, unrelated.text

    bad_select = client.put(f"/api/machines/{machine_id}/custom-fields", headers=auth_headers,
                            json={"values": [{"field_id": select_id, "value": "C"}]})
    assert bad_select.status_code == 422
    inactive_write = client.put(f"/api/machines/{machine_id}/custom-fields", headers=auth_headers,
                                json={"values": [{"field_id": date_id, "value": "2026-01-01"}]})
    assert inactive_write.status_code == 422
    assert inactive_write.json()["detail"]["code"] == "inactive_custom_field"
    wrong_category = client.patch(f"/api/machines/{machine_id}", headers=auth_headers,
                                  json={"custom_fields": [{"field_id": target_id, "value": "X"}]})
    assert wrong_category.status_code == 409

    transition = client.patch(f"/api/machines/{machine_id}", headers=auth_headers,
                              json={"category_id": target, "notes": "not committed"})
    assert transition.status_code == 422
    assert client.get(f"/api/machines/{machine_id}", headers=auth_headers).json()["category_id"] == source
    changed = client.patch(f"/api/machines/{machine_id}", headers=auth_headers,
                           json={"category_id": target,
                                 "custom_fields": [{"field_id": target_id, "value": "Ready"}]})
    assert changed.status_code == 200, changed.text
    with session_factory() as db:
        assert db.get(Machine, machine_id).category_id == target
        stored = {item.field_id: item.value for item in db.scalars(select(MachineFieldValue).where(
            MachineFieldValue.machine_id == machine_id))}
        assert stored[text_id] == "AB" and stored[target_id] == "Ready"
        hpwj_after = {
            item.id: (item.inventory_number, item.category_id, item.pressure_bar)
            for item in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))
        }
    assert hpwj_after == hpwj_before
    assert {item["field_id"] for item in client.get(
        f"/api/machines/{machine_id}/passport", headers=auth_headers).json()["custom_fields"]} == {target_id}


def test_capabilities_are_independent_at_new_workflow_and_catalog_boundaries(
    client, auth_headers, issue_payload, session_factory,
):
    basic = _category(client, auth_headers, "QA_NO_WORKFLOWS")
    repair = _category(client, auth_headers, "QA_REPAIR_ONLY", ["HAS_REPAIR_WORKFLOW"])
    transfer = _category(client, auth_headers, "QA_TRANSFER_ONLY", ["HAS_TRANSFER_WORKFLOW"])
    catalog = _category(client, auth_headers, "QA_CATALOG_ONLY", ["HAS_PARTS_CATALOG"])
    ids = {}
    for code, category_id in (("BASIC", basic), ("REPAIR", repair), ("TRANSFER", transfer), ("CATALOG", catalog)):
        response = _asset(client, auth_headers, f"QA-CAP-{code}", category_id)
        assert response.status_code == 201, response.text
        ids[code] = response.json()["id"]
    availability = {item["machine_id"]: item for item in client.get(
        "/api/transfers/availability", headers=auth_headers).json()}
    assert availability[ids["BASIC"]]["available"] is False
    assert availability[ids["TRANSFER"]]["available"] is True
    for code in ("BASIC", "REPAIR", "CATALOG"):
        blocked = client.post("/api/transfers/bulk-issue", headers=auth_headers,
                              json=issue_payload(ids[code]))
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "workflow_not_supported"
    for code in ("BASIC", "TRANSFER", "CATALOG"):
        blocked = client.post("/api/repairs", headers=auth_headers,
                              json={"machine_id": ids[code], "reported_problem": "QA"})
        assert blocked.status_code == 409, blocked.text
        assert blocked.json()["detail"]["code"] == "workflow_not_supported"
    opened = client.post("/api/repairs", headers=auth_headers,
                         json={"machine_id": ids["REPAIR"], "reported_problem": "QA"})
    assert opened.status_code == 201, opened.text
    repair_id = opened.json()["id"]
    with session_factory() as db:
        db.get(AssetCategory, repair).capabilities = []
        db.commit()
    assert client.get(f"/api/repair-cases/{repair_id}", headers=auth_headers).status_code == 200
    continued = client.patch(f"/api/repairs/{repair_id}", headers=auth_headers,
                             json={"diagnosis": "Тестова диагноза"})
    assert continued.status_code == 200, continued.text
    for payload in (
        {"status": "DIAGNOSIS", "condition_before": "Тестово състояние",
         "inspection_complete": True, "diagnosis": "Тестова диагноза",
         "required_work": "Тестова работа", "diagnosis_minutes": 10},
        {"status": "REPAIRING", "work_performed": "Тестова работа", "repair_minutes": 20,
         "result": "Изпълнено"},
        {"test_passed": True, "test_method": "Тест", "test_details": "Успешен",
         "functional_test_result": "Успешен", "condition_after": "Добро", "testing_minutes": 10},
        {"status": "COMPLETED", "test_passed": True, "test_method": "Тест",
         "testing_minutes": 10, "work_performed": "Тестова работа", "result": "Изпълнено",
         "test_details": "Успешен", "condition_after": "Добро"},
    ):
        finished = client.patch(f"/api/repair-cases/{repair_id}", headers=auth_headers, json=payload)
        assert finished.status_code == 200, finished.text
    history = client.get(f"/api/machines/{ids['REPAIR']}/passport", headers=auth_headers).json()
    assert len(history["repairs"]) == 1
    assert history["repairs"][0]["status"] == "COMPLETED"
    assert history["current_state"]["allowed_actions"]["repair"] is False
    for code in ("BASIC", "REPAIR", "TRANSFER"):
        context = client.get(f"/api/catalog/v2/machines/{ids[code]}", headers=auth_headers)
        assert context.status_code == 200 and context.json()["supported"] is False
    assert client.get(f"/api/catalog/v2/machines/{ids['CATALOG']}", headers=auth_headers).json()["supported"] is False
    with session_factory() as db:
        catalog_part_id = db.scalar(select(PartCatalog.id).limit(1))
    assert catalog_part_id is not None
    catalog_request = client.post("/api/part-requests/multi", headers=auth_headers, json={
        "machine_id": ids["BASIC"], "lines": [{"catalog_part_id": catalog_part_id,
        "description": "Тестова каталожна част", "quantity": 1}],
    })
    assert catalog_request.status_code == 409
    assert catalog_request.json()["detail"]["code"] == "workflow_not_supported"
    manual_request = client.post("/api/part-requests/multi", headers=auth_headers, json={
        "machine_id": ids["BASIC"], "lines": [{"part_number": "QA-MANUAL",
        "description": "Тестова ръчна част", "quantity": 1}],
    })
    assert manual_request.status_code == 201, manual_request.text


def test_hpwj_catalog_capability_can_be_removed_without_changing_fleet(
    client, auth_headers, session_factory, machine_ids,
):
    assert len(machine_ids) == 19
    machine_id = machine_ids["9"]
    before = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
    assert before.status_code == 200 and before.json()["supported"] is True
    with session_factory() as db:
        hpwj = db.scalar(select(AssetCategory).where(AssetCategory.code == "HPWJ"))
        expected = ["HAS_PRESSURE", "HAS_PARTS_CATALOG", "HAS_REPAIR_WORKFLOW", "HAS_TRANSFER_WORKFLOW"]
        assert set(hpwj.capabilities) == set(expected)
        inventory_before = {
            row.id: (row.inventory_number, row.category_id, row.pressure_bar)
            for row in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))
        }
        hpwj.capabilities = [code for code in expected if code != "HAS_PARTS_CATALOG"]
        db.commit()
    disabled = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
    assert disabled.status_code == 200 and disabled.json()["supported"] is False
    source_id = before.json()["assemblies"][0]["source_id"]
    direct = client.get(f"/api/catalog/v2/assemblies/{source_id}?machine_id={machine_id}", headers=auth_headers)
    assert direct.status_code == 409 and direct.json()["detail"]["code"] == "workflow_not_supported"
    with session_factory() as db:
        hpwj = db.scalar(select(AssetCategory).where(AssetCategory.code == "HPWJ"))
        hpwj.capabilities = expected
        db.commit()
    restored = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
    assert restored.status_code == 200 and restored.json()["supported"] is True
    with session_factory() as db:
        inventory_after = {
            row.id: (row.inventory_number, row.category_id, row.pressure_bar)
            for row in db.scalars(select(Machine).where(Machine.id.in_(machine_ids.values())))
        }
    assert inventory_after == inventory_before
