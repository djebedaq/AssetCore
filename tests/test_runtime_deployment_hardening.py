from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from app import database
from app.database import build_engine
from app.main import app, lifespan
from app.migrations import MigrationLockTimeout, migration_guard, run_migrations
from app.runtime import (
    RuntimeDependencyError,
    RuntimeState,
    readiness_report,
    verify_catalog,
    verify_cryptography,
    verify_license,
)
from app.settings import Settings, settings
from pydantic import ValidationError
from sqlalchemy import create_engine


def _ready_state() -> RuntimeState:
    state = RuntimeState()
    state.mark_ready(
        {
            "configuration": {"status": "pass", "code": "configuration_valid"},
            "catalog": {"status": "pass", "code": "catalog_integrity_verified"},
            "cryptography": {"status": "pass", "code": "cryptography_operational"},
            "license": {"status": "pass", "code": "license_not_applicable"},
        }
    )
    return state


def _migrated_sqlite(tmp_path: Path):
    database_path = tmp_path / "runtime-ready.db"
    previous_url = settings.database_url
    previous_timeout = settings.migration_lock_timeout_seconds
    try:
        settings.database_url = f"sqlite:///{database_path.as_posix()}"
        settings.migration_lock_timeout_seconds = 5
        run_migrations()
    finally:
        settings.database_url = previous_url
        settings.migration_lock_timeout_seconds = previous_timeout
    return create_engine(f"sqlite:///{database_path.as_posix()}")


def test_liveness_only_proves_the_process_is_alive(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "checks" not in response.json()


def test_readiness_succeeds_for_healthy_current_database(tmp_path: Path):
    database_engine = _migrated_sqlite(tmp_path)
    try:
        status_code, payload = readiness_report(
            database_engine=database_engine,
            state=_ready_state(),
        )
    finally:
        database_engine.dispose()

    assert status_code == 200
    assert payload["status"] == "ready"
    assert payload["checks"]["database"]["code"] == "database_connected"
    assert payload["checks"]["schema"]["code"] == "database_schema_current"


def test_readiness_fails_safely_when_database_is_unavailable():
    class UnavailableEngine:
        def connect(self):
            raise OSError("connection detail that must not be returned")

    status_code, payload = readiness_report(
        database_engine=UnavailableEngine(),
        state=_ready_state(),
    )

    serialized = json.dumps(payload)
    assert status_code == 503
    assert payload["checks"]["database"]["code"] == "database_unavailable"
    assert "connection detail" not in serialized


def test_readiness_reports_schema_behind_without_inventing_a_revision(tmp_path: Path):
    database_engine = create_engine(f"sqlite:///{(tmp_path / 'behind.db').as_posix()}")
    try:
        status_code, payload = readiness_report(
            database_engine=database_engine,
            state=_ready_state(),
        )
    finally:
        database_engine.dispose()

    assert status_code == 503
    assert payload["checks"]["database"]["status"] == "pass"
    assert payload["checks"]["schema"]["code"] == "database_schema_behind"


def test_catalog_crypto_and_non_enforced_license_startup_checks_are_operational(
    session_factory,
):
    with session_factory() as session:
        catalog = verify_catalog(session)
        license_check = verify_license(session)

    assert catalog == {"status": "pass", "code": "catalog_integrity_verified"}
    assert verify_cryptography()["code"] == "cryptography_operational"
    assert license_check == {"status": "pass", "code": "license_not_applicable"}


def _production_values() -> dict[str, object]:
    return {
        "_env_file": None,
        "deployment_environment": "production",
        "production_mode": True,
        "database_url": "postgresql+psycopg://assetcore@database/assetcore",
        "secret_key": "s" * 48,
        "owner_email": "owner@example.invalid",
        "owner_job_title": "Production owner",
        "signature_encryption_key": "e" * 48,
        "license_enforcement_enabled": True,
        "license_public_key": "configured-public-key",
        "installation_id": "configured-installation",
        "frontend_origin": "https://assetcore.example.invalid",
        "public_base_url": "https://assetcore.example.invalid",
        "migration_strategy": "external",
    }


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    (
        ("secret_key", "short"),
        ("signature_encryption_key", "short"),
        ("license_enforcement_enabled", False),
        ("migration_strategy", "startup"),
        ("public_base_url", "http://assetcore.example.invalid"),
        ("database_url", "sqlite:///production.db"),
    ),
)
def test_production_dangerous_or_default_configuration_fails_closed(
    field: str,
    unsafe_value: object,
):
    values = _production_values()
    values[field] = unsafe_value

    with pytest.raises(ValidationError):
        Settings(**values)


def test_explicit_development_and_staging_configuration_remain_supported():
    development = Settings(_env_file=None)
    staging = Settings(
        _env_file=None,
        deployment_environment="staging",
        production_mode=False,
        database_url="postgresql+psycopg://assetcore@database/assetcore",
        secret_key="s" * 48,
        owner_email="owner@example.invalid",
        owner_job_title="Staging owner",
        signature_encryption_key="e" * 48,
        frontend_origin="https://staging.example.invalid",
        public_base_url="https://staging.example.invalid",
        migration_strategy="startup",
    )

    assert development.migration_strategy == "startup"
    assert staging.migration_strategy == "startup"
    assert staging.browser_cookie_secure is True


def test_enforced_license_configuration_is_cryptographically_checked(session_factory):
    configuration = Settings(**_production_values())

    with session_factory() as session:
        with pytest.raises(RuntimeDependencyError) as caught:
            verify_license(session, configuration)

    assert caught.value.code == "license_evaluation_failed"


def test_postgresql_pool_options_are_applied_without_touching_sqlite(monkeypatch):
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_create_engine(url: str, **options):
        captured["url"] = url
        captured.update(options)
        return sentinel

    monkeypatch.setattr(database, "create_engine", fake_create_engine)
    configuration = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://assetcore@database/assetcore",
        db_pool_size=7,
        db_max_overflow=11,
        db_pool_timeout_seconds=41,
        db_pool_recycle_seconds=1900,
        db_connect_timeout_seconds=12,
        db_statement_timeout_ms=0,
    )

    assert build_engine(configuration) is sentinel
    assert captured["pool_pre_ping"] is True
    assert captured["pool_size"] == 7
    assert captured["max_overflow"] == 11
    assert captured["pool_timeout"] == 41
    assert captured["pool_recycle"] == 1900
    assert captured["connect_args"] == {"connect_timeout": 12}


def test_local_migration_start_is_serialized(tmp_path: Path):
    database_engine = create_engine(f"sqlite:///{(tmp_path / 'lock.db').as_posix()}")
    entered = threading.Event()
    finished = threading.Event()

    def contender() -> None:
        with database_engine.connect() as connection:
            with migration_guard(connection, timeout_seconds=2):
                entered.set()
        finished.set()

    with database_engine.connect() as first_connection:
        with migration_guard(first_connection, timeout_seconds=2):
            thread = threading.Thread(target=contender)
            thread.start()
            assert not entered.wait(0.1)
        assert entered.wait(1)
    thread.join(timeout=2)
    database_engine.dispose()

    assert finished.is_set()


def test_postgresql_migration_lock_times_out_with_a_safe_error(monkeypatch):
    class Result:
        def scalar_one(self):
            return False

    class Dialect:
        name = "postgresql"

    class Connection:
        dialect = Dialect()

        def execute(self, *_args, **_kwargs):
            return Result()

        def commit(self):
            return None

    ticks = iter((0.0, 0.0, 2.0, 2.0))
    monkeypatch.setattr("app.migrations.time.monotonic", lambda: next(ticks, 2.0))
    monkeypatch.setattr("app.migrations.time.sleep", lambda _seconds: None)

    with pytest.raises(MigrationLockTimeout) as caught:
        with migration_guard(Connection(), timeout_seconds=1):
            pass

    assert str(caught.value) == (
        "Timed out waiting for the AssetCore PostgreSQL migration lock."
    )


def test_failed_startup_does_not_enter_lifespan_and_shutdown_disposes_engine(monkeypatch):
    calls: list[str] = []

    def fail_startup() -> None:
        calls.append("startup")
        raise RuntimeError("safe startup failure")

    monkeypatch.setattr("app.main.initialize_runtime", fail_startup)
    monkeypatch.setattr("app.main.engine.dispose", lambda: calls.append("dispose"))

    async def exercise_failure() -> None:
        with pytest.raises(RuntimeError):
            async with lifespan(app):
                calls.append("serving")

    asyncio.run(exercise_failure())
    assert calls == ["startup"]

    calls.clear()
    monkeypatch.setattr("app.main.initialize_runtime", lambda: calls.append("startup"))

    async def exercise_shutdown() -> None:
        async with lifespan(app):
            calls.append("serving")

    asyncio.run(exercise_shutdown())
    assert calls == ["startup", "serving", "dispose"]
