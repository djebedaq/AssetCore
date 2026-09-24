"""The 0023 to 0024 upgrade on a disposable real PostgreSQL schema."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from app.models import AssetCategory, Machine
from sqlalchemy import func, inspect, select
from test_concurrency import ROOT
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def test_pg_existing_0023_asset_schema_upgrades_without_losing_hpwj(pg_factory):
    engine = pg_factory.kw["bind"]
    with pg_factory() as db:
        pressures = {
            row.inventory_number: row.pressure_bar
            for row in db.scalars(select(Machine)).all()
        }
        assert len(pressures) == 19
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "20260923_0023")
        assert "capabilities" not in {
            column["name"] for column in inspect(connection).get_columns("asset_categories")
        }
        command.upgrade(config, "head")
        assert next(column for column in inspect(connection).get_columns("machines")
                    if column["name"] == "pressure_bar")["nullable"]
    with pg_factory() as db:
        assert {
            row.inventory_number: row.pressure_bar
            for row in db.scalars(select(Machine)).all()
        } == pressures
        hpwj = db.scalar(select(AssetCategory).where(AssetCategory.code == "HPWJ"))
        assert hpwj is not None and "HAS_PRESSURE" in hpwj.capabilities
        category = AssetCategory(code="QA_GENERIC_ASSET", name_bg="QA asset")
        db.add(category)
        db.flush()
        db.add(Machine(
            inventory_number="QA-PG-GENERIC", name="QA generic asset",
            category="QA_GENERIC_ASSET", category_id=category.id, brand="QA",
            pressure_bar=None,
        ))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Machine)) == 20
        assert db.scalar(select(Machine.pressure_bar).where(
            Machine.inventory_number == "QA-PG-GENERIC"
        )) is None
