"""Real PostgreSQL races for 01C uniqueness and atomic import."""

import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin.parts import create_part, import_confirm, import_preview, map_pages
from app.catalog_admin.schemas import PartCreate, PartImportPreview, PartPageMapCreate
from app.models import (
    AssetCategory,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
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
        category = AssetCategory(code="QA_PART_RACE", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        catalog = CatalogDefinition(code="QA_PART_RACE", asset_category_id=category.id,
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
                                         role="SPARE_PARTS_LIST", created_by_id=actor.id)
        db.add(page)
        db.commit()
        return assembly.id, page.id


def race(pg_factory, operation):
    barrier = Barrier(3, timeout=15)

    def worker():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                operation(db, actor)
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        barrier.wait()
        return sorted(future.result(timeout=50) for future in futures)


def test_part_and_mapping_races(pg_factory):
    assembly_id, page_id = setup(pg_factory)
    outcomes = race(pg_factory, lambda db, actor: create_part(
        db, actor, assembly_id, PartCreate(position="12", part_number="A", name_en="QA")))
    assert outcomes == [201, 409]
    with pg_factory() as db:
        part_id = db.scalar(select(CatalogRevisionPart.id).where(CatalogRevisionPart.assembly_id == assembly_id))
    outcomes = race(pg_factory, lambda db, actor: map_pages(
        db, actor, part_id, PartPageMapCreate(visual_page_ids=[page_id])))
    assert outcomes == [201, 409]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id)).where(
            CatalogRevisionPart.assembly_id == assembly_id)) == 1
        assert db.scalar(select(func.count(CatalogRevisionPartPageMap.id)).where(
            CatalogRevisionPartPageMap.part_id == part_id)) == 1


def test_import_confirm_races_manual_create(pg_factory):
    assembly_id, _ = setup(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        preview = import_preview(db, actor, assembly_id, PartImportPreview(
            filename="parts.csv", content_base64=base64.b64encode(
                b"position,part_number,name_en\n7,X,QA\n").decode()))
    barrier = Barrier(3, timeout=15)

    def worker(importing):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                if importing:
                    import_confirm(db, actor, assembly_id, preview["token"], True)
                else:
                    create_part(db, actor, assembly_id, PartCreate(position="7", part_number="X", name_en="QA"))
                return 201
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.submit(worker, True), pool.submit(worker, False)
        barrier.wait()
        assert sorted([left.result(timeout=50), right.result(timeout=50)]) == [201, 409]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id)).where(
            CatalogRevisionPart.assembly_id == assembly_id,
            CatalogRevisionPart.position == "7", CatalogRevisionPart.part_number == "X")) == 1
