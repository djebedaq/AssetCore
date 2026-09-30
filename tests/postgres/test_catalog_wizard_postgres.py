"""Real PostgreSQL whole-catalog confirmation and generated-code races."""

import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin import wizard
from app.catalog_admin.schemas import PartImportPreview, SimpleCatalogCreate
from app.models import CatalogDefinition, CatalogRevisionAssembly, CatalogRevisionPart, User
from fastapi import HTTPException
from sqlalchemy import func, select
from test_catalog_builder_parts_postgres import race, setup
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def test_whole_catalog_confirm_race_is_atomic(pg_factory):
    assembly_id, _ = setup(pg_factory)
    with pg_factory() as db:
        group = db.get(CatalogRevisionAssembly, assembly_id)
        revision_id = group.revision_id
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        preview = wizard.import_preview(db, actor, revision_id, PartImportPreview(
            filename="qa.csv", content_base64=base64.b64encode(
                f"assembly_code,position,part_number,name,source_page\n{group.code},1,QA-A,QA,1\n"
                f"{group.code},2,QA-B,QA,1\n".encode()
            ).decode()))
        db.rollback()
    outcomes = race(pg_factory, lambda db, actor: wizard.import_confirm(
        db, actor, revision_id, preview["token"], False))
    assert outcomes == [201, 409]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id)).where(
            CatalogRevisionPart.assembly_id == assembly_id)) == 2


def test_generated_catalog_codes_concurrent_same_name(pg_factory):
    assembly_id, _ = setup(pg_factory)
    with pg_factory() as db:
        assembly = db.get(CatalogRevisionAssembly, assembly_id)
        from app.models import CatalogRevision
        revision = db.get(CatalogRevision, assembly.revision_id)
        category_id = db.get(CatalogDefinition, revision.catalog_id).asset_category_id
    barrier = Barrier(2, timeout=15)
    def create():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                return wizard.create_catalog(db, actor, SimpleCatalogCreate(
                    name="QA same name", asset_category_id=category_id))
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert all(isinstance(result, dict) for result in results)
    assert results[0]["code"] != results[1]["code"]
    assert all(result["draft_revision_count"] == 1 for result in results)


def test_group_codes_concurrent_same_name_are_deterministic(pg_factory):
    assembly_id, _ = setup(pg_factory)
    with pg_factory() as db:
        revision_id = db.get(CatalogRevisionAssembly, assembly_id).revision_id
    barrier = Barrier(2, timeout=15)
    def create():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            return wizard.create_group(db, actor, revision_id, "Blasting Head")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: create(), range(2)))
    assert {result["code"] for result in results} == {"BLASTING_HEAD", "BLASTING_HEAD_2"}
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        assert wizard.create_group(db, actor, revision_id, "Blasting Head")["code"] == "BLASTING_HEAD_3"
