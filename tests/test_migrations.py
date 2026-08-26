from __future__ import annotations

import hashlib
import importlib.util
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.models import AuthenticationThrottle, AuthSession, Repair, RepairParticipant, User
from app.official_documents.integrity import validate_official_document_integrity
from app.settings import Settings, settings
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

ROOT = Path(__file__).resolve().parents[1]


def _migration_config() -> Config:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    return config


def _run_sqlite_revision(database_path: Path, operation, revision: str) -> None:
    previous_url = settings.database_url
    settings.database_url = f"sqlite:///{database_path.as_posix()}"
    try:
        operation(_migration_config(), revision)
    finally:
        settings.database_url = previous_url


def test_render_postgresql_url_uses_psycopg_v3_driver():
    configured = Settings(
        database_url="postgresql://assetcore:example@database/assetcore",
        _env_file=None,
    )
    assert configured.database_url.startswith("postgresql+psycopg://")


def test_published_industrial_platform_migration_content_is_immutable():
    migration = (
        ROOT
        / "backend"
        / "alembic"
        / "versions"
        / "20260731_0003_industrial_platform.py"
    )
    normalized_content = migration.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(normalized_content).hexdigest() == (
        "f23f3cc084352bfa4740641d992b16d44de9194d12c334248d95f19a1af2faa6"
    )


def test_official_document_integrity_migration_preserves_malformed_history_and_signed_data(
    tmp_path: Path,
):
    database_path = tmp_path / "official-document-integrity.db"
    _run_sqlite_revision(database_path, command.upgrade, "20260818_0019")
    snapshot_hash = "1" * 64
    signing_hash = "2" * 64
    docx_hash = "3" * 64
    pdf_hash = "4" * 64
    signature_hash = "5" * 64
    image_hash = "6" * 64
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "DROP INDEX IF EXISTS uq_official_document_version_owner"
        )
        connection.executemany(
            """
            INSERT INTO official_documents (
              id, document_number, document_type, current_version_id,
              created_by_id, created_at
            ) VALUES (?, ?, 'PART_REQUEST', ?, 1, '2026-08-25 10:00:00')
            """,
            [
                (100, "MIGRATION-VALID", 1000),
                (101, "MIGRATION-NULL", None),
                (102, "MIGRATION-MISSING", 1999),
                (103, "MIGRATION-WRONG-OWNER", 1000),
            ],
        )
        connection.executemany(
            """
            INSERT INTO official_document_versions (
              id, document_id, version, status, language, snapshot,
              snapshot_sha256, signing_sha256, docx_content, docx_sha256,
              pdf_content, pdf_sha256, prepared_by_id, created_at, finalized_at
            ) VALUES (?, ?, 1, 'SIGNED', 'bg', ?, ?, ?, ?, ?, ?, ?, 1,
              '2026-08-25 10:00:00', '2026-08-25 11:00:00')
            """,
            [
                (
                    1000,
                    100,
                    '{"source":"preserved"}',
                    snapshot_hash,
                    signing_hash,
                    b"preserved-docx",
                    docx_hash,
                    b"preserved-pdf",
                    pdf_hash,
                ),
                (
                    1001,
                    999,
                    '{"source":"orphan-preserved"}',
                    "7" * 64,
                    "8" * 64,
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO document_participants (
              id, document_version_id, slot_code, participant_kind, user_id,
              operation_role, identity_snapshot, identity_snapshot_sha256,
              created_at
            ) VALUES (
              2000, 1000, 'PREPARER', 'INTERNAL', 1, 'PREPARER',
              '{"identity":"preserved"}', ?, '2026-08-25 10:00:00'
            )
            """,
            ("9" * 64,),
        )
        connection.execute(
            """
            INSERT INTO document_signatures (
              id, participant_id, document_version_id, signature_kind,
              consent_text, strokes_encrypted, image_encrypted, canvas_width,
              canvas_height, stroke_count, point_count, document_sha256,
              image_sha256, signature_sha256, signed_at, confirmed_at
            ) VALUES (
              3000, 2000, 1000, 'MANUAL_GRAPHIC', 'Preserved consent',
              ?, ?, 320, 120, 1, 8, ?, ?, ?,
              '2026-08-25 10:30:00', '2026-08-25 10:31:00'
            )
            """,
            (
                b"preserved-strokes",
                b"preserved-image",
                signing_hash,
                image_hash,
                signature_hash,
            ),
        )
        connection.commit()

    _run_sqlite_revision(database_path, command.upgrade, "head")

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT id, document_number, current_version_id "
            "FROM official_documents ORDER BY id"
        ).fetchall() == [
            (100, "MIGRATION-VALID", 1000),
            (101, "MIGRATION-NULL", None),
            (102, "MIGRATION-MISSING", 1999),
            (103, "MIGRATION-WRONG-OWNER", 1000),
        ]
        assert connection.execute(
            "SELECT snapshot, snapshot_sha256, signing_sha256, docx_content, "
            "docx_sha256, pdf_content, pdf_sha256, status, finalized_at "
            "FROM official_document_versions WHERE id = 1000"
        ).fetchone() == (
            '{"source":"preserved"}',
            snapshot_hash,
            signing_hash,
            b"preserved-docx",
            docx_hash,
            b"preserved-pdf",
            pdf_hash,
            "SIGNED",
            "2026-08-25 11:00:00",
        )
        assert connection.execute(
            "SELECT consent_text, strokes_encrypted, image_encrypted, "
            "document_sha256, image_sha256, signature_sha256, confirmed_at "
            "FROM document_signatures WHERE id = 3000"
        ).fetchone() == (
            "Preserved consent",
            b"preserved-strokes",
            b"preserved-image",
            signing_hash,
            image_hash,
            signature_hash,
            "2026-08-25 10:31:00",
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE official_documents SET current_version_id = 2999 WHERE id = 100"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE official_documents SET current_version_id = 1000 WHERE id = 101"
            )

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with Session(engine) as session:
            report = validate_official_document_integrity(session)
            assert report["valid"] is True
            assert report["blocking_count"] == 0
            assert report["tolerated_history_count"] == 5
            assert {item["code"] for item in report["findings"]} == {
                "CURRENT_VERSION_NULL",
                "CURRENT_VERSION_TARGET_MISSING",
                "CURRENT_VERSION_WRONG_OWNER",
                "ORPHAN_DOCUMENT_VERSION",
                "CURRENT_VERSION_SHARED",
            }
            assert report["schema"]["sqlite_trigger_guard"] is True
    finally:
        engine.dispose()


def test_catalog_v2_safe_downgrade_restores_0018_schema_and_reupgrades(
    tmp_path: Path,
):
    database_path = tmp_path / "catalog-v2-safe-downgrade.db"
    _run_sqlite_revision(database_path, command.upgrade, "20260810_0018")
    _run_sqlite_revision(database_path, command.upgrade, "20260818_0019")
    _run_sqlite_revision(database_path, command.downgrade, "20260810_0018")

    downgraded_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    downgraded = inspect(downgraded_engine)
    try:
        assert "catalog_diagrams" not in downgraded.get_table_names()
        assert "catalog_position_hotspots" not in downgraded.get_table_names()
        assert "source_record_key" not in {
            column["name"] for column in downgraded.get_columns("part_catalog")
        }
        assert "uq_part_catalog_source_position" in {
            constraint["name"]
            for constraint in downgraded.get_unique_constraints("part_catalog")
        }
    finally:
        downgraded_engine.dispose()

    _run_sqlite_revision(database_path, command.upgrade, "20260818_0019")
    upgraded_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    upgraded = inspect(upgraded_engine)
    try:
        assert "catalog_diagrams" in upgraded.get_table_names()
        assert "catalog_position_hotspots" in upgraded.get_table_names()
        assert "source_record_key" in {
            column["name"] for column in upgraded.get_columns("part_catalog")
        }
        assert "uq_part_catalog_source_position" not in {
            constraint["name"]
            for constraint in upgraded.get_unique_constraints("part_catalog")
        }
    finally:
        upgraded_engine.dispose()


def test_catalog_v2_unsafe_downgrade_fails_before_sqlite_schema_changes(
    tmp_path: Path,
):
    database_path = tmp_path / "catalog-v2-unsafe-downgrade.db"
    _run_sqlite_revision(database_path, command.upgrade, "20260818_0019")
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO part_catalog (
              source_record_key, source_id, source_row_index, family,
              brand, model, assembly, position, part_number, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "test-only-source-variant-a",
                    "test-only-source-a",
                    1,
                    "TEST_ONLY_FAMILY",
                    "Test-only brand",
                    "Test-only model",
                    "TEST_ONLY_ASSEMBLY",
                    "1",
                    "TEST-ONLY-PART",
                    "Test-only source variant A",
                ),
                (
                    "test-only-source-variant-b",
                    "test-only-source-b",
                    2,
                    "TEST_ONLY_FAMILY",
                    "Test-only brand",
                    "Test-only model",
                    "TEST_ONLY_ASSEMBLY",
                    "1",
                    "TEST-ONLY-PART",
                    "Test-only source variant B",
                ),
            ],
        )

    before_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    before = inspect(before_engine)
    before_tables = set(before.get_table_names())
    before_columns = {
        column["name"] for column in before.get_columns("part_catalog")
    }
    before_engine.dispose()

    with pytest.raises(
        RuntimeError,
        match="Cannot downgrade PARTS_CATALOG_V2 to 0018 safely",
    ):
        _run_sqlite_revision(database_path, command.downgrade, "20260810_0018")

    after_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    after = inspect(after_engine)
    try:
        assert set(after.get_table_names()) == before_tables
        assert {
            column["name"] for column in after.get_columns("part_catalog")
        } == before_columns
        with after_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == "20260818_0019"
            assert connection.exec_driver_sql(
                "SELECT COUNT(*) FROM part_catalog WHERE source_record_key "
                "LIKE 'test-only-source-variant-%'"
            ).scalar_one() == 2
    finally:
        after_engine.dispose()


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
    assert {
        "source_return_transfer_id",
        "source_return_document_id",
        "source_return_batch_id",
    }.issubset({column["name"] for column in inspector.get_columns("repairs")})
    assert {
        "required_parts_text",
        "diagnostic_cleaning",
        "diagnosis_minutes",
        "repair_minutes",
        "testing_minutes",
    }.issubset({column["name"] for column in inspector.get_columns("repairs")})
    assert {"identity_key", "minutes_worked"}.issubset({
        column["name"]
        for column in inspector.get_columns("repair_participants")
    })
    assert "uq_repair_participants_identity_key" in {
        item["name"] for item in inspector.get_indexes("repair_participants")
    }
    assert {
        "ck_repairs_diagnosis_minutes_nonnegative",
        "ck_repairs_repair_minutes_nonnegative",
        "ck_repairs_testing_minutes_nonnegative",
    }.issubset(
        {
            item["name"]
            for item in inspector.get_check_constraints("repairs")
            if item.get("name")
        }
    )
    assert {
        "alternative_part_numbers", "replacement_part_ids", "source_figure",
        "diagram_page", "source_version", "source_document_sha256",
        "verification_status", "replaced_by_part_number",
    }.issubset({column["name"] for column in inspector.get_columns("part_catalog")})
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
        assert upgraded.exec_driver_sql(
            "SELECT is_active FROM locations WHERE name = 'Цех'"
        ).scalar_one() in (1, True)
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


def test_repair_duration_constraints_and_participant_identity_compile_for_postgresql():
    repair_ddl = str(
        CreateTable(Repair.__table__).compile(dialect=postgresql.dialect())
    )
    participant_index = next(
        index
        for index in RepairParticipant.__table__.indexes
        if index.name == "uq_repair_participants_identity_key"
    )
    participant_index_ddl = str(
        CreateIndex(participant_index).compile(dialect=postgresql.dialect())
    )
    assert "ck_repairs_diagnosis_minutes_nonnegative" in repair_ddl
    assert "ck_repairs_repair_minutes_nonnegative" in repair_ddl
    assert "ck_repairs_testing_minutes_nonnegative" in repair_ddl
    assert "CREATE UNIQUE INDEX" in participant_index_ddl
    assert "repair_id, identity_key" in participant_index_ddl
    participant_ddl = str(
        CreateTable(RepairParticipant.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "ck_repair_participants_minutes_positive" in participant_ddl


def test_auth_session_migration_upgrades_and_downgrades_on_sqlite(tmp_path: Path):
    database_path = tmp_path / "auth-session-migration.db"
    _run_sqlite_revision(database_path, command.upgrade, "20260826_0020")
    _run_sqlite_revision(database_path, command.upgrade, "20260826_0021")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert {"auth_sessions", "authentication_throttles"} <= set(
        inspector.get_table_names()
    )
    assert {column["name"] for column in inspector.get_columns("auth_sessions")} == {
        "id",
        "user_id",
        "token_hash",
        "csrf_token_hash",
        "user_token_version",
        "created_at",
        "expires_at",
        "last_seen_at",
        "revoked_at",
        "revoked_reason",
    }
    assert {
        "uq_authentication_throttle_scope_key",
    } <= {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("authentication_throttles")
    }
    engine.dispose()

    _run_sqlite_revision(database_path, command.downgrade, "20260826_0020")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    assert "auth_sessions" not in inspect(engine).get_table_names()
    assert "authentication_throttles" not in inspect(engine).get_table_names()
    engine.dispose()


def test_auth_session_tables_compile_for_postgresql():
    session_ddl = str(
        CreateTable(AuthSession.__table__).compile(dialect=postgresql.dialect())
    )
    throttle_ddl = str(
        CreateTable(AuthenticationThrottle.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "UNIQUE (token_hash)" in session_ddl
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in session_ddl
    assert "uq_authentication_throttle_scope_key" in throttle_ddl
    assert "ck_authentication_throttle_failures" in throttle_ddl


def test_repair_wizard_migration_normalizes_all_legacy_active_paths_without_data_loss(
    tmp_path: Path,
):
    database_path = tmp_path / "repair-legacy-paths.db"
    config = Config(str(Path(__file__).resolve().parents[1] / "backend" / "alembic.ini"))
    previous_url = settings.database_url
    settings.database_url = f"sqlite:///{database_path.as_posix()}"
    try:
        command.upgrade(config, "20260809_0017")
        connection = sqlite3.connect(database_path)
        connection.executemany(
            """
            INSERT INTO repairs (
              id, machine_id, reported_problem, diagnosis, work_performed,
              test_details, repair_minutes, cleaning_required, test_required,
              status, opened_at
            ) VALUES (?, 1, ?, ?, ?, ?, ?, 0, 1, ?, CURRENT_TIMESTAMP)
            """,
            [
                (1, "approval", "diagnosis approval", None, None, None, "WAITING_APPROVAL"),
                (2, "parts diagnosis", "diagnosis parts", None, None, None, "WAITING_PARTS"),
                (3, "parts repair", "diagnosis repair", "preserved work", None, 45, "WAITING_PARTS"),
                (4, "testing", "diagnosis testing", "preserved testing work", "preserved test", 60, "TESTING"),
                (5, "completed", "completed diagnosis", "completed work", "completed test", 30, "COMPLETED"),
            ],
        )
        connection.execute(
            """
            INSERT INTO repair_participants (
              id, repair_id, full_name_snapshot, contribution, identity_key,
              created_by_id, created_at
            ) VALUES (1, 4, 'Legacy participant', 'preserved contribution',
              'name:legacy participant', 1, CURRENT_TIMESTAMP)
            """
        )
        connection.commit()
        connection.close()

        command.upgrade(config, "head")
    finally:
        settings.database_url = previous_url

    connection = sqlite3.connect(database_path)
    rows = connection.execute(
        "SELECT status, diagnosis, work_performed, test_details, repair_minutes "
        "FROM repairs ORDER BY id"
    ).fetchall()
    participant = connection.execute(
        "SELECT full_name_snapshot, contribution, minutes_worked "
        "FROM repair_participants WHERE id = 1"
    ).fetchone()
    connection.close()
    assert [row[0] for row in rows] == [
        "DIAGNOSIS",
        "DIAGNOSIS",
        "REPAIRING",
        "REPAIRING",
        "COMPLETED",
    ]
    assert rows[2][2:] == ("preserved work", None, 45)
    assert rows[3][1:] == (
        "diagnosis testing",
        "preserved testing work",
        "preserved test",
        60,
    )
    assert participant == ("Legacy participant", "preserved contribution", None)
