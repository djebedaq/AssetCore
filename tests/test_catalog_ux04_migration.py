"""Upgrade real pre-UX04 binding rows without rewriting references/history."""

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from test_migrations import _run_sqlite_revision


def test_existing_single_binding_upgrade_is_lossless_and_allows_two_catalogs(tmp_path):
    path = tmp_path / "ux04-upgrade-only.db"
    _run_sqlite_revision(path, command.upgrade, "20261009_0033")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        # The initial bootstrap creates current metadata. Reproduce exactly the
        # old 0025 binding shape to exercise the actual ALTER/rebuild, with FK
        # checking off only in this deliberately minimal migration fixture.
        connection.execute(text("DROP TABLE catalog_asset_bindings"))
        connection.execute(text("CREATE TABLE catalog_asset_bindings (id INTEGER PRIMARY KEY, catalog_id INTEGER NOT NULL "
            "REFERENCES catalog_definitions(id), machine_id INTEGER NOT NULL UNIQUE REFERENCES machines(id), "
            "created_by_id INTEGER NOT NULL REFERENCES users(id), created_at DATETIME NOT NULL)"))
        connection.execute(text("CREATE INDEX ix_catalog_asset_bindings_catalog_id ON catalog_asset_bindings(catalog_id)"))
        connection.execute(text("INSERT INTO catalog_asset_bindings VALUES (71,11,21,1,'2026-10-01')"))
        connection.execute(text("CREATE TABLE qa_immutable_history (id INTEGER PRIMARY KEY, evidence TEXT)"))
        connection.execute(text("INSERT INTO qa_immutable_history VALUES (1,'Synthetic QA fixed revision and document digest')"))
    engine.dispose()

    _run_sqlite_revision(path, command.upgrade, "head")
    with engine.begin() as connection:
        assert connection.execute(text("SELECT id,catalog_id,machine_id,created_by_id,created_at,is_active,deactivated_at "
            "FROM catalog_asset_bindings WHERE id=71")).one() == (71,11,21,1,"2026-10-01",1,None)
        connection.execute(text("INSERT INTO catalog_asset_bindings (catalog_id,machine_id,created_by_id,created_at) VALUES (12,21,1,'2026-10-13')"))
        constraints = inspect(connection).get_unique_constraints("catalog_asset_bindings")
        assert any(item["column_names"] == ["catalog_id", "machine_id"] for item in constraints)
        assert not any(item["column_names"] == ["machine_id"] for item in constraints)
        assert connection.scalar(text("SELECT evidence FROM qa_immutable_history")) == "Synthetic QA fixed revision and document digest"
    engine.dispose()


def test_downgrade_cannot_silently_reactivate_a_removed_link(tmp_path):
    path = tmp_path / "ux04-inactive-upgrade-only.db"
    _run_sqlite_revision(path, command.upgrade, "head")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO catalog_asset_bindings (catalog_id,machine_id,created_by_id,created_at,is_active) "
            "VALUES (11,21,1,'2026-10-13',false)"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="Inactive catalog bindings"):
        _run_sqlite_revision(path, command.downgrade, "20261009_0033")

