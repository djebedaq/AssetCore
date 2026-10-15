import hashlib
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "backend/alembic/versions/20261015_0035_request_issues.py"


def revision():
    spec = importlib.util.spec_from_file_location("requests01_revision", REVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def simulate_old_schema(connection):
    """Only disposable QA fixtures: restore the pre-0035 shape, without rewriting old data."""
    if connection.dialect.name == "sqlite":
        triggers = list(
            connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'freeze_%'")
            )
        )
        for row in triggers:
            connection.execute(text(f'DROP TRIGGER "{row[0]}"'))
    else:
        triggers = list(
            connection.execute(
                text(
                    "SELECT tgname, relname FROM pg_trigger JOIN pg_class ON tgrelid=pg_class.oid JOIN pg_namespace n ON n.oid=pg_class.relnamespace WHERE n.nspname=current_schema() AND tgname LIKE 'freeze_%'"
                )
            )
        )
        for name, table in triggers:
            connection.execute(text(f'DROP TRIGGER "{name}" ON "{table}"'))
            connection.execute(text(f'DROP FUNCTION "{name}"()'))
    for table in (
        "request_delivery_events",
        "request_approval_snapshots",
        "request_number_counter",
    ):
        connection.execute(text(f"DROP TABLE {table}"))
    columns = (
        "request_kind",
        "generation_status",
        "generation_error",
        "cancelled_at",
        "cancelled_by_id",
        "cancellation_reason",
        "replacement_request_id",
    )
    if connection.dialect.name == "sqlite":
        operations = Operations(MigrationContext.configure(connection))
        with operations.batch_alter_table(
            "part_requests",
            naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
        ) as batch:
            batch.drop_constraint("fk_part_requests_cancelled_by_id_users", type_="foreignkey")
            batch.drop_constraint(
                "fk_part_requests_replacement_request_id_part_requests", type_="foreignkey"
            )
            for column in columns:
                batch.drop_column(column)
    else:
        for column in columns:
            connection.execute(text(f"ALTER TABLE part_requests DROP COLUMN {column}"))
    connection.execute(text("ALTER TABLE part_request_lines DROP COLUMN exact_quantity"))


def verify_upgrade(engine):
    with engine.begin() as connection:
        actor_id = connection.scalar(text("SELECT id FROM users ORDER BY id LIMIT 1"))
        connection.execute(
            text(
                "INSERT INTO part_requests (part_name, quantity, status, request_reference, language, created_at, priority) VALUES ('QA historical', 1, 'APPROVED', 'PR-QA-OLD', 'bg', CURRENT_TIMESTAMP, 'NORMAL')"
            )
        )
        request_id = connection.scalar(
            text("SELECT id FROM part_requests WHERE request_reference='PR-QA-OLD'")
        )
        connection.execute(
            text(
                "INSERT INTO part_request_lines (request_id, description, quantity, delivered_quantity, is_unknown_part) VALUES (:id, 'QA original Float', 1.04, 0.5, false)"
            ),
            {"id": request_id},
        )
        content = b"QA historical binary must remain identical"
        digest = hashlib.sha256(content).hexdigest()
        connection.execute(
            text(
                "INSERT INTO generated_documents (document_number, document_type, format, language, filename, media_type, content, sha256, created_by_id, created_at, snapshot) VALUES ('PR-QA-OLD', 'PART_REQUEST', 'pdf', 'bg', 'QA-original.pdf', 'application/pdf', :content, :digest, :actor, CURRENT_TIMESTAMP, '{}')"
            ),
            {"content": content, "digest": digest, "actor": actor_id},
        )
        before = connection.execute(
            text(
                "SELECT quantity, delivered_quantity FROM part_request_lines WHERE request_id=:id"
            ),
            {"id": request_id},
        ).one()
        simulate_old_schema(connection)
        migration = revision()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        after = connection.execute(
            text(
                "SELECT quantity, delivered_quantity, exact_quantity FROM part_request_lines WHERE request_id=:id"
            ),
            {"id": request_id},
        ).one()
        assert tuple(before) == tuple(after[:2]) and after[2] is None
        assert (
            connection.scalar(
                text("SELECT content FROM generated_documents WHERE document_number='PR-QA-OLD'")
            )
            == content
        )
        assert connection.scalar(text("SELECT COUNT(*) FROM request_approval_snapshots")) == 0
        assert (
            connection.scalar(
                text(
                    "SELECT COUNT(*) FROM machines WHERE inventory_number IN ('4','5','7','8','9','10','11','13','14','15','16','17','18','19','20','21','22','23','24')"
                )
            )
            == 19
        )
        with pytest.raises(RuntimeError, match="ROLL_FORWARD"):
            migration.downgrade()


def test_sqlite_upgrade_preserves_historical_float_and_binary(session_factory):
    verify_upgrade(session_factory.kw["bind"])


def test_historical_kk_conflict_fails_closed(session_factory):
    with session_factory.kw["bind"].begin() as connection:
        connection.execute(
            text(
                "INSERT INTO part_requests (part_name, quantity, status, request_reference, language, created_at, priority) VALUES ('QA conflict', 1, 'APPROVED', 'KK1000', 'bg', CURRENT_TIMESTAMP, 'NORMAL')"
            )
        )
        migration = revision()
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="HISTORICAL_KK_CONFLICT"):
            migration.upgrade()


def test_frozen_database_guards_match_application():
    from app.request_schema_guards import statements

    for dialect in ("sqlite", "postgresql"):
        assert revision().statements(dialect) == statements(dialect)
