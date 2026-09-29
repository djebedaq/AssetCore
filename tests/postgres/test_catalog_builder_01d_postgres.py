"""Real PostgreSQL races for draft kit uniqueness and hotspot verification."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin.hotspots import create_hotspot, set_verified, update_hotspot
from app.catalog_admin.repair_kits import add_component, create_kit
from app.catalog_admin.schemas import (
    HotspotCreate,
    HotspotUpdate,
    RepairKitComponentCreate,
    RepairKitCreate,
)
from app.models import (
    AssetCategory,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPositionHotspot,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    User,
)
from fastapi import HTTPException
from sqlalchemy import func, select
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def setup(pg_factory):
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(code="QA_01D_RACE", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        catalog = CatalogDefinition(code="QA_01D_RACE", asset_category_id=category.id,
                                    name_bg="QA", name_en="QA", name_ru="QA", created_by_id=actor.id)
        db.add(catalog)
        db.flush()
        revision = CatalogRevision(catalog_id=catalog.id, revision_code="A", created_by_id=actor.id)
        db.add(revision)
        db.flush()
        assembly = CatalogRevisionAssembly(revision_id=revision.id, code="PUMP", name_bg="QA",
                                           name_en="QA", name_ru="QA", created_by_id=actor.id)
        db.add(assembly)
        db.flush()
        artifact = CatalogRevisionArtifact(assembly_id=assembly.id, title="QA", filename="qa.pdf",
                                           media_type="application/pdf", content=b"%PDF-test",
                                           sha256="a" * 64, page_count=1, created_by_id=actor.id)
        db.add(artifact)
        db.flush()
        page = CatalogRevisionVisualPage(artifact_id=artifact.id, page_number=1,
                                         role="EXPLODED_SCHEME", created_by_id=actor.id)
        db.add(page)
        part = CatalogRevisionPart(assembly_id=assembly.id, position="12", part_number="QA",
                                   name_en="QA", created_by_id=actor.id)
        db.add(part)
        db.commit()
        return assembly.id, page.id, part.id


def race(pg_factory, operation):
    start = Barrier(3, timeout=15)

    def worker():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            start.wait()
            try:
                operation(db, actor)
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        start.wait()
        return sorted(future.result(timeout=50) for future in futures)


def test_duplicate_kit_code_and_component_races(pg_factory):
    assembly_id, _, part_id = setup(pg_factory)
    outcomes = race(pg_factory, lambda db, actor: create_kit(
        db, actor, assembly_id, RepairKitCreate(code="KIT_SEALS", name_en="QA")))
    assert outcomes == [201, 409]
    with pg_factory() as db:
        kit_id = db.scalar(select(CatalogRevisionRepairKit.id).where(
            CatalogRevisionRepairKit.assembly_id == assembly_id))
    outcomes = race(pg_factory, lambda db, actor: add_component(
        db, actor, kit_id, RepairKitComponentCreate(part_id=part_id, quantity=1)))
    assert outcomes == [201, 409]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionRepairKit.id)).where(
            CatalogRevisionRepairKit.assembly_id == assembly_id)) == 1
        assert db.scalar(select(func.count(CatalogRevisionRepairKitComponent.id)).where(
            CatalogRevisionRepairKitComponent.kit_id == kit_id)) == 1


def test_verify_geometry_race_never_marks_changed_geometry_verified(pg_factory):
    assembly_id, page_id, _ = setup(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        original = create_hotspot(db, actor, page_id, HotspotCreate(
            position="12", x=.1, y=.2, width=.1, height=.1))
    hotspot_id, version = original["id"], original["version"]
    start = Barrier(3, timeout=15)

    def worker(verify: bool):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            start.wait()
            try:
                if verify:
                    set_verified(db, actor, hotspot_id, version, True)
                else:
                    update_hotspot(db, actor, hotspot_id, HotspotUpdate(expected_version=version, x=.3))
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(worker, True)
        right = pool.submit(worker, False)
        start.wait()
        assert sorted([left.result(timeout=50), right.result(timeout=50)]) == [200, 409]
    with pg_factory() as db:
        current = db.get(CatalogRevisionPositionHotspot, hotspot_id)
        assert current.version == 2
        assert (current.x == .1 and current.is_verified) or (current.x == .3 and not current.is_verified)
        if not current.is_verified:
            assert current.verified_by_id is None and current.verified_at is None
