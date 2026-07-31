"""Offline release verification for AssetCore Director Edition."""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT / "backend")
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{ROOT / 'release_check.db'}")
os.environ.setdefault("ADMIN_EMAIL", "admin@assetcore.local")
os.environ.setdefault("ADMIN_PASSWORD", "AssetCore123!")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

with TestClient(app) as client:
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    login = client.post("/api/auth/login", json={"email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    machines = client.get("/api/machines", headers=headers)
    assert machines.status_code == 200, machines.text
    assert len(machines.json()) == 19, f"Очаквани 19 HPWJ машини, получени {len(machines.json())}"
    docs = client.get("/api/documents", headers=headers)
    assert docs.status_code == 200, docs.text
    assert len(docs.json()) >= 40, f"Недостатъчна документална библиотека: {len(docs.json())}"
    catalog = client.get("/api/catalog/parts", headers=headers)
    assert catalog.status_code == 200, catalog.text
    assert len(catalog.json()) >= 10, f"Недостатъчен проверен parts catalog: {len(catalog.json())}"
    dashboard = client.get("/api/dashboard", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    assert dashboard.json()["total_machines"] == 19

print("RELEASE CHECK: PASS")
print("- API health: OK")
print("- Authentication: OK")
print("- HPWJ registry: 19 machines")
print(f"- Document library: {len(docs.json())} files")
print(f"- Verified parts catalog: {len(catalog.json())} records")
print("- Dashboard: OK")
