from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from app.settings import Settings, settings
from sqlalchemy import create_engine, inspect


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
        INSERT INTO locations VALUES (1, 'Цех', NULL);
        INSERT INTO machines VALUES (1, '7', 'HPWJ №7', 'HPWJ', 'Falch', 'Wheel Jet 30-e',
          1000, 'G41200143', 'Готова', 1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
        """
    )
    connection.commit()
    connection.close()

    config = Config(str(Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"))
    previous_url = settings.database_url
    settings.database_url = f"sqlite:///{database_path.as_posix()}"
    try:
        command.upgrade(config, "head")
    finally:
        settings.database_url = previous_url

    engine = create_engine(f"sqlite:///{database_path}")
    inspector = inspect(engine)
    assert {"transfer_batches", "protocol_documents", "alembic_version"}.issubset(
        inspector.get_table_names()
    )
    assert {"batch_id", "is_active", "returned_at"}.issubset(
        {column["name"] for column in inspector.get_columns("transfer_protocols")}
    )
    with engine.connect() as upgraded:
        row = upgraded.exec_driver_sql(
            "SELECT inventory_number, serial_number FROM machines WHERE id=1"
        ).one()
        assert row == ("7", "G41200143")
    engine.dispose()
