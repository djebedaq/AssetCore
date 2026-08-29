"""PostgreSQL F01 regression for the public categories endpoint."""

from __future__ import annotations

import pytest
from app.database import get_db
from app.main import app
from fastapi.testclient import TestClient

# Reuse the existing disposable, migrated PostgreSQL schema fixture.
from test_concurrency import pg_factory as pg_factory

pytestmark = pytest.mark.postgres


def test_category_custom_fields_serialize_over_http_on_postgres(pg_factory):
    assert pg_factory.kw["bind"].dialect.name == "postgresql"

    def override_db():
        with pg_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app, raise_server_exceptions=False)
    client.headers.update({"X-AssetCore-Auth-Mode": "bearer"})
    try:
        login = client.post(
            "/api/auth/login",
            json={"email": "admin@assetcore.local", "password": "AssetCore123!"},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        created = client.post(
            "/api/categories",
            headers=headers,
            json={"code": "F01_PG", "name_bg": "F01 PostgreSQL категория"},
        )
        assert created.status_code == 201, created.text
        category_id = created.json()["id"]
        field = client.post(
            f"/api/categories/{category_id}/fields",
            headers=headers,
            json={
                "code": "PRESSURE_CLASS",
                "label_bg": "Клас налягане",
                "label_en": "Pressure class",
                "label_ru": "Класс давления",
                "field_type": "SELECT",
                "is_required": True,
                "options": ["500", "1000"],
                "unit": "bar",
                "validation_rules": {"allowed": ["500", "1000"]},
                "sort_order": 10,
            },
        )
        assert field.status_code == 201, field.text

        response = client.get("/api/categories", headers=headers)

        assert response.status_code == 200, response.text
        category = next(item for item in response.json() if item["id"] == category_id)
        assert category["fields"] == [field.json()]
        assert "_sa_instance_state" not in response.text
    finally:
        client.close()
        app.dependency_overrides.clear()
