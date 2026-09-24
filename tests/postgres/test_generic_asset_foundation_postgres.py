"""The 0023 to 0024 upgrade on a disposable real PostgreSQL schema."""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from app.assets.service import category_navigation, create_machine, machines, update_machine
from app.models import AssetCategory, Machine, User
from app.schemas import MachineCreate, MachineUpdate
from fastapi import HTTPException
from sqlalchemy import func, inspect, select
from test_concurrency import ROOT
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def test_pg_registry_counts_and_canonical_filter(pg_factory):
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.email == "admin@assetcore.local"))
        assert actor is not None
        category = AssetCategory(code="QA_PG_REGISTRY", name_bg="Тестова категория")
        db.add(category)
        db.flush()
        db.add_all([
            Machine(
                inventory_number=f"QA-PG-REGISTRY-{index}", name=f"QA asset {index}",
                brand="QA", category=category.code, category_id=category.id,
            ) for index in range(3)
        ])
        db.commit()

        navigation = {item["code"]: item for item in category_navigation(actor, db)}
        assert navigation["HPWJ"]["asset_count"] == 19
        assert navigation[category.code]["asset_count"] == 3
        assert len(machines(actor, db, category_id=category.id)) == 3
        assert len(machines(actor, db)) == 22


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


def test_pg_pressure_capability_rejects_invalid_native_machine_state(pg_factory):
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.email == "admin@assetcore.local"))
        assert actor is not None
        generic = AssetCategory(code="QA_PG_NO_PRESSURE", name_bg="Тестов актив")
        db.add(generic)
        db.flush()

        with pytest.raises(HTTPException) as create_error:
            create_machine(MachineCreate(
                inventory_number="QA-PG-PRESSURE-REJECT", name="QA", brand="QA",
                category_id=generic.id, pressure_bar=500,
            ), actor, db)
        assert create_error.value.status_code == 422
        assert create_error.value.detail["code"] == "pressure_not_applicable"

        created = create_machine(MachineCreate(
            inventory_number="QA-PG-NO-PRESSURE", name="QA", brand="QA",
            category_id=generic.id,
        ), actor, db)
        assert created.pressure_bar is None

        with pytest.raises(HTTPException) as update_error:
            update_machine(
                created.id, MachineUpdate(pressure_bar=500), actor, db,
            )
        assert update_error.value.status_code == 422
        assert update_error.value.detail["code"] == "pressure_not_applicable"
        db.expire_all()
        persisted = db.get(Machine, created.id)
        assert persisted.category_id == generic.id
        assert persisted.pressure_bar is None
