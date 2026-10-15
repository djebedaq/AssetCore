"""Real PostgreSQL race against the unique Builder machine binding constraint."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin.service import bind_asset
from app.models import (
    AssetCategory,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    Machine,
    User,
)
from fastapi import HTTPException
from sqlalchemy import func, select
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("same_catalog", [False, True])
def test_catalog_pair_uniqueness_allows_distinct_catalogs_concurrently(pg_factory, same_catalog):
    with pg_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(code="QA_BUILDER_RACE", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        machine = Machine(inventory_number="QA_BUILDER_RACE_ASSET", name="QA", category=category.code,
                          category_id=category.id, brand="QA")
        db.add(machine)
        first = CatalogDefinition(code="QA_RACE_FIRST", asset_category_id=category.id,
                                  name_bg="QA", name_en="QA", name_ru="QA", created_by_id=owner.id)
        second = CatalogDefinition(code="QA_RACE_SECOND", asset_category_id=category.id,
                                   name_bg="QA", name_en="QA", name_ru="QA", created_by_id=owner.id)
        db.add_all([first, second])
        db.flush()
        db.add_all([CatalogRevision(catalog_id=row.id, revision_code="QA", status="PUBLISHED", created_by_id=owner.id) for row in [first, second]])
        db.commit()
        machine_id, catalog_ids = machine.id, [first.id, second.id]
        if same_catalog:
            catalog_ids = [first.id, first.id]

    barrier = Barrier(3, timeout=15)

    def worker(catalog_id: int):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                bind_asset(db, actor, catalog_id, machine_id, compatibility_confirmed=True)
                return 201, None
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, catalog_id) for catalog_id in catalog_ids]
        barrier.wait()
        outcomes = [future.result(timeout=50) for future in futures]
    assert sorted(outcomes, key=lambda result: result[0]) == (
        [(201, None), (409, "catalog_asset_already_bound")] if same_catalog else [(201, None), (201, None)])
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogAssetBinding.id)).where(
            CatalogAssetBinding.machine_id == machine_id)) == (1 if same_catalog else 2)
