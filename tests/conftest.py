from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{ROOT / 'tests' / 'bootstrap.db'}")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ADMIN_EMAIL", "admin@assetcore.local")
os.environ.setdefault("ADMIN_PASSWORD", "AssetCore123!")

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Machine, User  # noqa: E402
from app.seed import seed_database  # noqa: E402


@pytest.fixture()
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    database_path = tmp_path / "assetcore-test.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as session:
        seed_database(session)
    yield factory
    engine.dispose()


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    def override_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    test_client = TestClient(app, raise_server_exceptions=False)
    try:
        yield test_client
    finally:
        test_client.close()
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@assetcore.local", "password": "AssetCore123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def machine_ids(session_factory: sessionmaker[Session]) -> dict[str, int]:
    with session_factory() as session:
        return {
            machine.inventory_number: machine.id
            for machine in session.query(Machine).all()
        }


@pytest.fixture()
def issue_payload():
    def make(*machine_ids: int) -> dict:
        return {
            "machine_ids": list(machine_ids),
            "company_unit": "",
            "vessel": "",
            "location_text": "",
            "handed_over_by": "",
            "accepted_by": "",
            "equipment": "",
            "condition_text": "",
            "remarks": "",
        }

    return make


@pytest.fixture()
def viewer_headers(
    client: TestClient, session_factory: sessionmaker[Session]
) -> dict[str, str]:
    from app.security import hash_password

    with session_factory() as session:
        session.add(
            User(
                email="viewer@assetcore.test",
                full_name="Тестов наблюдател",
                password_hash=hash_password("viewer-password"),
                role="viewer",
            )
        )
        session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "viewer@assetcore.test", "password": "viewer-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
