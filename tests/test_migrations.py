from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.models import User
from app.settings import Settings, settings
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable


def test_render_postgresql_url_uses_psycopg_v3_driver():
    configured = Settings(
        database_url="postgresql://assetcore:example@database/assetcore",
        _env_file=None,
    )
    assert configured.database_url.startswith("postgresql+psycopg://")


def test_legacy_sqlite_database_upgrades_without_changing_inventory(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL UNIQUE,
          full_name VARCHAR(255) NOT NULL, password_hash VARCHAR(255) NOT NULL,
          role VARCHAR(50) NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME NOT NULL);
        CREATE TABLE locations (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL UNIQUE, description TEXT);
        CREATE TABLE machines (id INTEGER PRIMARY KEY, inventory_number VARCHAR(50) NOT NULL UNIQUE,
          name VARCHAR(255) NOT NULL, category VARCHAR(120) NOT NULL, brand VARCHAR(120) NOT NULL,
          model VARCHAR(120), pressure_bar INTEGER NOT NULL, serial_number VARCHAR(120),
          status VARCHAR(80) NOT NULL, location_id INTEGER, notes TEXT,
          created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL);
        CREATE TABLE transfer_protocols (id INTEGER PRIMARY KEY, machine_id INTEGER NOT NULL,
          protocol_type VARCHAR(40) NOT NULL, protocol_number VARCHAR(80) NOT NULL UNIQUE,
          company_unit VARCHAR(255), vessel VARCHAR(255), location_text VARCHAR(255),
          handed_over_by VARCHAR(255), accepted_by VARCHAR(255), equipment TEXT,
          condition_text TEXT, remarks TEXT, created_at DATETIME NOT NULL);
        CREATE TABLE audit_logs (id INTEGER PRIMARY KEY, entity_type VARCHAR(80) NOT NULL,
          entity_id INTEGER, action VARCHAR(120) NOT NULL, details TEXT, user_name VARCHAR(255),
          created_at DATETIME NOT NULL);
        INSERT INTO users VALUES (1, 'admin@test', 'Администратор', 'x', 'admin', 1, CURRENT_TIMESTAMP);
        INSERT INTO users VALUES (2, 'manager@test', 'Manager', 'x', 'manager', 1, CURRENT_TIMESTAMP);
        INSERT INTO users VALUES (3, 'approver@test', 'Approver', 'x', 'approver', 1, CURRENT_TIMESTAMP);
        INSERT INTO users VALUES (4, 'viewer@test', 'Viewer', 'x', 'viewer', 1, CURRENT_TIMESTAMP);
        INSERT INTO users VALUES (5, 'mechanic@test', 'Mechanic', 'x', 'mechanic', 1, CURRENT_TIMESTAMP);
        INSERT INTO users VALUES (6, 'other-admin@test', 'Other admin', 'x', 'admin', 1, CURRENT_TIMESTAMP);
        INSERT INTO locations VALUES (1, 'Цех', NULL);
        INSERT INTO machines VALUES (1, '7', 'HPWJ №7', 'HPWJ', 'Falch', 'Wheel Jet 30-e',
          1000, 'G41200143', 'Готова', 1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        """
    )
    connection.commit()
    connection.close()

    config = Config(str(Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"))
    previous_url = settings.database_url
    previous_owner_email = settings.assetcore_owner_email
    settings.database_url = f"sqlite:///{database_path.as_posix()}"
    settings.assetcore_owner_email = "admin@test"
    try:
        command.upgrade(config, "head")
    finally:
        settings.database_url = previous_url
        settings.assetcore_owner_email = previous_owner_email

    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    assert {"transfer_batches", "protocol_documents", "part_catalog_images", "part_request_attachments", "departments", "alembic_version"}.issubset(
        inspector.get_table_names()
    )
    assert "is_active" in {
        column["name"] for column in inspector.get_columns("locations")
    }
    assert {
        "batch_id", "is_active", "returned_at", "department", "dock", "pier",
        "work_area", "hoses", "nozzles", "guns", "accessories",
        "return_missing_equipment", "return_damage", "return_contamination",
        "return_cleaning_required", "return_inspection_required", "return_repair_required",
    }.issubset(
        {column["name"] for column in inspector.get_columns("transfer_protocols")}
    )
    assert "preferred_language" in {
        column["name"] for column in inspector.get_columns("users")
    }
    assert {
        "updated_at",
        "last_login_at",
        "password_changed_at",
        "must_change_password",
        "is_system_owner",
        "token_version",
    }.issubset({column["name"] for column in inspector.get_columns("users")})
    assert "uq_users_single_system_owner" in {
        item["name"] for item in inspector.get_indexes("users")
    }
    assert "repair_id" in {
        column["name"] for column in inspector.get_columns("part_requests")
    }
    assert {"alternative_part_numbers", "replacement_part_ids"}.issubset(
        {column["name"] for column in inspector.get_columns("part_catalog")}
    )
    assert "confidence" in {
        column["name"] for column in inspector.get_columns("part_hotspots")
    }
    assert {"compatible_models", "revision"}.issubset(
        {column["name"] for column in inspector.get_columns("repair_kits")}
    )
    assert {
        "source_content", "effective_from", "effective_to", "required_fields",
        "numbering_rule", "department", "change_note",
    }.issubset(
        {
            column["name"]
            for column in inspector.get_columns("document_template_versions")
        }
    )
    with engine.connect() as upgraded:
        row = upgraded.exec_driver_sql(
            "SELECT inventory_number, serial_number, status FROM machines WHERE id=1"
        ).one()
        assert row == ("7", "G41200143", "READY")
        roles = dict(
            upgraded.exec_driver_sql("SELECT email, role FROM users ORDER BY id").all()
        )
        assert roles == {
            "admin@test": "administrator",
            "manager@test": "director",
            "approver@test": "director",
            "viewer@test": "observer",
            "mechanic@test": "mechanic",
            "other-admin@test": "director",
        }
        assert upgraded.exec_driver_sql(
            "SELECT COUNT(*) FROM users WHERE is_system_owner = 1"
        ).scalar_one() == 1
        assert upgraded.exec_driver_sql(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'Мигрирана потребителска роля'"
        ).scalar_one() == 6
    engine.dispose()

    previous_url = settings.database_url
    previous_owner_email = settings.assetcore_owner_email
    settings.database_url = f"sqlite:///{database_path.as_posix()}"
    settings.assetcore_owner_email = "admin@test"
    try:
        command.downgrade(config, "20260731_0001")
    finally:
        settings.database_url = previous_url
        settings.assetcore_owner_email = previous_owner_email
    downgraded_engine = create_engine(f"sqlite:///{database_path}")
    downgraded_inspector = inspect(downgraded_engine)
    assert "preferred_language" not in {
        column["name"] for column in downgraded_inspector.get_columns("users")
    }
    assert "departments" not in downgraded_inspector.get_table_names()
    assert "is_active" not in {
        column["name"] for column in downgraded_inspector.get_columns("locations")
    }
    with downgraded_engine.connect() as downgraded:
        assert downgraded.exec_driver_sql(
            "SELECT status FROM machines WHERE id=1"
        ).scalar_one() == "Готова"
    downgraded_engine.dispose()

    previous_url = settings.database_url
    previous_owner_email = settings.assetcore_owner_email
    settings.database_url = f"sqlite:///{database_path.as_posix()}"
    settings.assetcore_owner_email = "admin@test"
    try:
        command.upgrade(config, "head")
    finally:
        settings.database_url = previous_url
        settings.assetcore_owner_email = previous_owner_email
    reupgraded_engine = create_engine(f"sqlite:///{database_path}")
    with reupgraded_engine.connect() as reupgraded:
        assert reupgraded.exec_driver_sql(
            "SELECT role FROM users WHERE email = 'admin@test'"
        ).scalar_one() == "administrator"
        assert reupgraded.exec_driver_sql(
            "SELECT COUNT(*) FROM users WHERE is_system_owner = 1"
        ).scalar_one() == 1
    reupgraded_engine.dispose()


def test_owner_preflight_fails_before_user_schema_changes(tmp_path: Path):
    database_path = tmp_path / "unsafe-owner.db"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255), role VARCHAR(50))"
        )
        connection.exec_driver_sql(
            "INSERT INTO users VALUES (1, 'unmatched@example.invalid', 'admin')"
        )

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "alembic"
        / "versions"
        / "20260801_0004_final_user_roles.py"
    )
    spec = importlib.util.spec_from_file_location("assetcore_user_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    previous_owner_email = settings.assetcore_owner_email
    settings.assetcore_owner_email = "configured@example.invalid"
    try:
        with engine.connect() as connection, pytest.raises(RuntimeError):
            migration._preflight(connection)
    finally:
        settings.assetcore_owner_email = previous_owner_email
    assert {column["name"] for column in inspect(engine).get_columns("users")} == {
        "id",
        "email",
        "role",
    }
    engine.dispose()


def test_user_schema_and_partial_owner_index_compile_for_postgresql():
    table_ddl = str(CreateTable(User.__table__).compile(dialect=postgresql.dialect()))
    owner_index = next(
        index for index in User.__table__.indexes if index.name == "uq_users_single_system_owner"
    )
    index_ddl = str(CreateIndex(owner_index).compile(dialect=postgresql.dialect()))
    assert "administrator" in table_ddl
    assert "ck_users_owner_invariants" in table_ddl
    assert "CREATE UNIQUE INDEX" in index_ddl
    assert "WHERE is_system_owner" in index_ddl
