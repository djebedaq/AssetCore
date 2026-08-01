"""Offline, isolated release verification for AssetCore Director Edition."""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

temporary_directory = tempfile.TemporaryDirectory(prefix="assetcore-release-")
database_path = Path(temporary_directory.name) / "release-check.db"
test_password = secrets.token_urlsafe(32)
os.environ["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
os.environ["SECRET_KEY"] = secrets.token_urlsafe(48)
os.environ["ADMIN_EMAIL"] = "release-check@example.invalid"
os.environ["ASSETCORE_OWNER_EMAIL"] = os.environ["ADMIN_EMAIL"]
os.environ["ADMIN_PASSWORD"] = test_password

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

EXPECTED_NUMBERS = {
    "4", "5", "7", "9", "10", "11", "12", "13", "14", "15", "16",
    "17", "18", "19", "20", "21", "22", "23", "24",
}
EXPECTED_SERIALS = {
    "7": "G41200143",
    "17": "G41200203",
    "18": "G41200204",
    "9": "G39300296",
    "10": "G39300297",
    "11": "G39300298",
    "12": "G39300299",
    "13": "G39300415",
    "14": "G39300416",
    "15": "G39300417",
    "16": "G39300418",
    "20": "2512005",
    "21": "2512004",
    "22": "2512001",
    "23": "2512003",
    "24": "2512002",
}

try:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200, health.text
        login = client.post(
            "/api/auth/login",
            json={"email": os.environ["ADMIN_EMAIL"], "password": test_password},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        machines = client.get("/api/machines", headers=headers)
        assert machines.status_code == 200, machines.text
        inventory = {item["inventory_number"]: item for item in machines.json()}
        assert set(inventory) == EXPECTED_NUMBERS
        for number, serial in EXPECTED_SERIALS.items():
            assert inventory[number]["serial_number"] == serial

        docs = client.get("/api/documents", headers=headers)
        assert docs.status_code == 200, docs.text
        assert len(docs.json()) >= 40
        assert all("file_path" not in item for item in docs.json())

        catalog = client.get("/api/catalog/parts", headers=headers)
        assert catalog.status_code == 200, catalog.text
        assert len(catalog.json()) >= 10
        assert all(item["is_verified"] for item in catalog.json())

        categories = client.get("/api/categories", headers=headers)
        assert categories.status_code == 200, categories.text
        assert any(item["code"] == "HPWJ" for item in categories.json())

        templates = client.get("/api/document-templates", headers=headers)
        assert templates.status_code == 200, templates.text
        assert len(templates.json()) == 4
        assert sum(len(item["versions"]) for item in templates.json()) == 12
        template_versions = [
            version for item in templates.json() for version in item["versions"]
        ]
        published = [version for version in template_versions if version["is_published"]]
        assert len(published) == 4
        assert all(version["language"] == "bg" for version in published)
        assert all("source_path" not in version for version in template_versions)

        library = client.get("/api/technical-library", headers=headers)
        assert library.status_code == 200, library.text
        assert len(library.json()) >= 40
        assert all(item["revisions"] for item in library.json())

        passport = client.get(
            f"/api/machines/{inventory['4']['id']}/passport", headers=headers
        )
        assert passport.status_code == 200, passport.text
        assert passport.json()["machine"]["inventory_number"] == "4"
        assert passport.json()["current_state"]["available"] is True
        assert "technical_documents" in passport.json()

        availability = client.get("/api/transfers/availability", headers=headers)
        assert availability.status_code == 200, availability.text
        assert len(availability.json()) == 19

        dashboard = client.get("/api/dashboard", headers=headers)
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["total_machines"] == 19
finally:
    engine.dispose()
    temporary_directory.cleanup()

print("RELEASE CHECK: PASS")
print("- API health and authentication: OK")
print("- Verified HPWJ registry: 19 machines and known serial numbers")
print(f"- Document library: {len(docs.json())} files")
print(f"- Verified parts catalog: {len(catalog.json())} records")
print("- Industrial category, passport and template versions: OK")
print(f"- Versioned technical library: {len(library.json())} files")
print("- Availability and dashboard: OK")
