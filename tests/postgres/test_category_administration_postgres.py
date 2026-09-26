"""ASSET-01D configuration and asset writes overlap on real PostgreSQL locks."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

import pytest
from app.assets.custom_fields import update_custom_fields
from app.assets.service import create_machine
from app.industrial_schemas import (
    CategoryFieldUpdate,
    CategoryUpdate,
    CustomFieldValueInput,
    CustomFieldValuesUpdate,
)
from app.master_data.service import update_category, update_category_field
from app.models import AssetCategory, CategoryFieldDefinition, Machine, MachineFieldValue, User
from app.schemas import MachineCreate
from fastapi import HTTPException
from sqlalchemy import select, text
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def _overlap(factory, model, identifier, blocked, commit_first):
    """Hold the canonical row until the other connection demonstrably waits."""
    worker_pid = Queue()

    def worker():
        with factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            # Deliberately preload the definition: the locked query must refresh
            # ORM identity-map state after the first transaction commits.
            definition = db.get(model, identifier)
            assert definition is not None
            worker_pid.put(db.scalar(text("SELECT pg_backend_pid()")))
            try:
                blocked(db, actor)
                return 200, None
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail["code"]

    with factory() as db, ThreadPoolExecutor(max_workers=1) as pool:
        db.scalar(select(model).where(model.id == identifier).with_for_update())
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        future = pool.submit(worker)
        try:
            pid = worker_pid.get(timeout=12)
            deadline = monotonic() + 10
            while monotonic() < deadline:
                db.execute(text("SELECT pg_stat_clear_snapshot()"))
                waiting = db.scalar(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE pid = :pid "
                    "AND wait_event_type = 'Lock' AND cardinality(pg_blocking_pids(pid)) > 0"
                ), {"pid": pid})
                if waiting == 1:
                    break
                assert not future.done(), "Writer did not wait for the configuration lock."
                sleep(0.025)
            else:
                pytest.fail("Configuration and value transactions did not overlap.")
            commit_first(db, actor)
        finally:
            db.rollback()
        return future.result(timeout=50)


@pytest.mark.parametrize("admin_first", [True, False])
def test_pg_pressure_removal_and_asset_creation_are_serialized(pg_factory, admin_first):
    with pg_factory() as db:
        category = AssetCategory(
            code="QA_PG_ADMIN_PRESSURE", name_bg="Тестова категория",
            capabilities=["HAS_PRESSURE"],
        )
        db.add(category)
        db.commit()
        category_id = category.id

    def remove(db, actor):
        update_category(category_id, CategoryUpdate(capabilities=[]), actor, db)

    def create(db, actor):
        create_machine(MachineCreate(
            inventory_number="QA-PG-ADMIN-PRESSURE", name="Тестов актив", brand="QA",
            category_id=category_id, pressure_bar=500,
        ), actor, db)

    result = _overlap(
        pg_factory, AssetCategory, category_id,
        create if admin_first else remove, remove if admin_first else create,
    )
    assert result == ((422, "pressure_not_applicable") if admin_first else
                      (409, "category_capability_in_use"))
    with pg_factory() as db:
        category = db.get(AssetCategory, category_id)
        asset = db.scalar(select(Machine).where(Machine.category_id == category_id))
        if admin_first:
            assert category.capabilities == [] and asset is None
        else:
            assert category.capabilities == ["HAS_PRESSURE"] and asset.pressure_bar == 500


@pytest.mark.parametrize("admin_first", [True, False])
def test_pg_field_semantics_and_value_writes_are_serialized(pg_factory, admin_first):
    with pg_factory() as db:
        category = AssetCategory(code="QA_PG_ADMIN_FIELD", name_bg="Тестова категория")
        db.add(category)
        db.flush()
        field = CategoryFieldDefinition(
            category_id=category.id, code="QA_CHOICE", label_bg="Тестов избор",
            field_type="SELECT", options=["A", "B"],
        )
        asset = Machine(
            inventory_number="QA-PG-ADMIN-FIELD", name="Тестов актив", brand="QA",
            category=category.code, category_id=category.id,
        )
        db.add_all([field, asset])
        db.flush()
        db.add(MachineFieldValue(machine_id=asset.id, field_id=field.id, value="A"))
        db.commit()
        category_id, field_id, asset_id = category.id, field.id, asset.id

    def narrow(db, actor):
        update_category_field(category_id, field_id, CategoryFieldUpdate(options=["A"]), actor, db)

    def write(db, actor):
        update_custom_fields(asset_id, CustomFieldValuesUpdate(values=[
            CustomFieldValueInput(field_id=field_id, value="B"),
        ]), actor, db)

    result = _overlap(
        pg_factory, CategoryFieldDefinition, field_id,
        write if admin_first else narrow, narrow if admin_first else write,
    )
    assert result == ((422, "invalid_custom_field_value") if admin_first else
                      (409, "category_field_values_incompatible"))
    with pg_factory() as db:
        field = db.get(CategoryFieldDefinition, field_id)
        values = db.scalars(select(MachineFieldValue).where(
            MachineFieldValue.machine_id == asset_id, MachineFieldValue.field_id == field_id,
        )).all()
        assert len(values) == 1
        assert (field.options, values[0].value) == ((["A"], "A") if admin_first else
                                                  (["A", "B"], "B"))
