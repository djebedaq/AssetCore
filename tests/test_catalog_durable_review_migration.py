"""Additive upgrade of an existing 0032 database, with irreversible-history guard."""
import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.models import Base
from sqlalchemy import create_engine, inspect, text
from test_migrations import _run_sqlite_revision

TABLES = ("catalog_source_review_decisions", "catalog_extraction_candidates",
          "catalog_extraction_attempts", "catalog_extraction_sources", "catalog_extraction_sessions")


def test_upgrade_does_not_infer_any_human_approval_and_protects_history(tmp_path):
    path = tmp_path / "qa-0032.db"
    _run_sqlite_revision(path, command.upgrade, "20261009_0032")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        # Bootstrap uses current metadata. Remove only the five empty new tables
        # to reproduce the pre-0033 shape without altering any historical table.
        for table in TABLES:
            connection.execute(text(f"DROP TABLE {table}"))
        connection.execute(text("CREATE TABLE qa_history (id INTEGER PRIMARY KEY, evidence TEXT NOT NULL)"))
        connection.execute(text("INSERT INTO qa_history VALUES (1, 'Synthetic immutable document fingerprint')"))
    _run_sqlite_revision(path, command.upgrade, "head")
    with engine.connect() as connection:
        for table in TABLES:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            assert {c["name"] for c in inspect(connection).get_columns(table)} == set(Base.metadata.tables[table].columns.keys())
        assert connection.scalar(text("SELECT evidence FROM qa_history")) == "Synthetic immutable document fingerprint"
    migration = Path(__file__).resolve().parents[1] / "backend/alembic/versions/20261009_0033_durable_source_review.py"
    spec = importlib.util.spec_from_file_location("qa_durable_review_migration", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as connection:
        # Deliberately unreferenced QA identifiers; this isolated engine has FK
        # checking disabled and is used only to exercise the downgrade guard.
        connection.execute(text("INSERT INTO catalog_extraction_sessions "
            "(revision_id,assembly_id,scope_key,selection_digest,selection,created_by_id,created_at) "
            "VALUES (1,1,'QA','qa','[]',1,CURRENT_TIMESTAMP)"))
    with engine.begin() as connection, pytest.raises(RuntimeError, match="history cannot be discarded"):
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM catalog_extraction_sessions")) == 1
        assert connection.scalar(text("SELECT evidence FROM qa_history")) == "Synthetic immutable document fingerprint"
    engine.dispose()
