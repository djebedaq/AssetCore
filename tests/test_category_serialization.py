"""F01 regression coverage for the public category/custom-field response."""

from __future__ import annotations

import json

CATEGORY_KEYS = {
    "id",
    "code",
    "name_bg",
    "name_en",
    "name_ru",
    "description",
    "icon",
    "validation_rules",
    "document_types",
    "checklists",
    "status_codes",
    "is_active",
    "created_at",
    "fields",
}

FIELD_KEYS = {
    "id",
    "category_id",
    "code",
    "label_bg",
    "label_en",
    "label_ru",
    "field_type",
    "is_required",
    "options",
    "unit",
    "validation_rules",
    "sort_order",
    "is_active",
}


def _create_category(client, auth_headers, *, code: str, name_bg: str) -> dict:
    response = client.post(
        "/api/categories",
        headers=auth_headers,
        json={
            "code": code,
            "name_bg": name_bg,
            "name_en": "F01 QA category",
            "name_ru": "Категория F01 QA",
            "description": "Изолирани тестови данни за F01",
            "icon": "qa-f01",
            "validation_rules": {"source": "f01-regression"},
            "document_types": ["QA_F01"],
            "checklists": [{"code": "QA_F01_CHECK"}],
            "status_codes": ["READY"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_field(client, auth_headers, category_id: int, payload: dict) -> dict:
    response = client.post(
        f"/api/categories/{category_id}/fields",
        headers=auth_headers,
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_categories_without_custom_fields_keep_the_public_shape(client, auth_headers):
    category = _create_category(
        client,
        auth_headers,
        code="F01_EMPTY",
        name_bg="F01 категория без полета",
    )

    response = client.get("/api/categories", headers=auth_headers)

    assert response.status_code == 200, response.text
    listed = next(item for item in response.json() if item["id"] == category["id"])
    assert set(listed) == CATEGORY_KEYS
    assert listed["fields"] == []


def test_categories_serialize_created_custom_fields_as_ordered_json(client, auth_headers):
    category = _create_category(
        client,
        auth_headers,
        code="F01_FIELDS",
        name_bg="F01 категория с полета",
    )
    high = _create_field(
        client,
        auth_headers,
        category["id"],
        {
            "code": "PRESSURE_CLASS",
            "label_bg": "Клас налягане",
            "label_en": "Pressure class",
            "label_ru": "Класс давления",
            "field_type": "SELECT",
            "is_required": True,
            "options": ["500", "1000"],
            "unit": "bar",
            "validation_rules": {"allowed": ["500", "1000"]},
            "sort_order": 20,
        },
    )
    low_first = _create_field(
        client,
        auth_headers,
        category["id"],
        {
            "code": "QA_REFERENCE",
            "label_bg": "QA референция",
            "label_en": "QA reference",
            "label_ru": "QA ссылка",
            "field_type": "TEXT",
            "is_required": False,
            "unit": None,
            "validation_rules": {"max_length": 80},
            "sort_order": 5,
        },
    )
    low_second = _create_field(
        client,
        auth_headers,
        category["id"],
        {
            "code": "QA_FLAG",
            "label_bg": "QA флаг",
            "label_en": "QA flag",
            "label_ru": "QA флаг",
            "field_type": "BOOLEAN",
            "is_required": False,
            "sort_order": 5,
        },
    )

    response = client.get("/api/categories", headers=auth_headers)

    assert response.status_code == 200, response.text
    payload = response.json()
    listed = next(item for item in payload if item["id"] == category["id"])
    assert set(listed) == CATEGORY_KEYS
    assert [item["id"] for item in listed["fields"]] == [
        low_first["id"],
        low_second["id"],
        high["id"],
    ]
    assert all(set(item) == FIELD_KEYS for item in listed["fields"])
    assert listed["fields"][-1] == high
    assert listed["fields"][0] == low_first
    assert listed["fields"][1] == low_second

    # The final HTTP response must be ordinary JSON without persistence state,
    # relationship expansion or a category -> fields -> category cycle.
    reparsed = json.loads(response.content)
    assert reparsed == payload
    serialized = response.content.decode("utf-8")
    assert "_sa_instance_state" not in serialized
    assert all("category" not in field and "values" not in field for field in listed["fields"])


def test_category_read_permission_contract_is_unchanged(
    client, auth_headers, viewer_headers
):
    authorized = client.get("/api/categories", headers=auth_headers)
    forbidden = client.get("/api/categories", headers=viewer_headers)

    assert authorized.status_code == 200, authorized.text
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["detail"]["code"] == "permission_denied"
