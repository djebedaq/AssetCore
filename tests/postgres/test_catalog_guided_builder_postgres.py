"""Migrated PostgreSQL locks: selected-list confirmation and stale page editing."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin import parts, reference_pages, visual_sources
from app.catalog_admin.parts_extraction import service
from app.catalog_admin.parts_extraction.schemas import (
    ExtractConfirm,
    ExtractSelection,
    PageCreate,
    PageUpdate,
    SourceAssign,
)
from app.catalog_admin.schemas import PartCreate
from app.models import CatalogRevisionPart, CatalogRevisionPartPageMap, CatalogSourceBlob, User
from catalog_extraction_fixtures import manual
from fastapi import HTTPException
from sqlalchemy import func, select
from test_catalog_builder_parts_postgres import setup
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def selected_source(factory):
    assembly_id, _ = setup(factory)
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        artifact = visual_sources.store_artifact(db, actor, assembly_id, manual(), "qa-selected.pdf", "QA selected list")
        page = reference_pages.create(db, actor, assembly_id, PageCreate())
        page = reference_pages.assign(db, actor, page["id"], SourceAssign(expected_version=page["version"],
            artifact_id=artifact["id"], page_numbers=[2], roles=["SPARE_PARTS_LIST"]))
        result = service.preview(db, actor, page["id"], ExtractSelection(visual_page_id=page["sources"][0]["id"]))
        return page, result


def test_competing_confirmation_is_atomic_and_idempotent(pg_factory):
    page, preview = selected_source(pg_factory)
    data = ExtractConfirm(token=preview["token"], rows=[{"index": index, "part": row["payload"]}
        for index, row in enumerate(preview["rows"])], confirm_warnings=True)
    barrier = Barrier(2)
    def confirm():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait(timeout=15)
            return service.confirm(db, actor, page["id"], data)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(), range(2)))
    assert sorted(result["created_count"] for result in results) == [0, 4]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 4
        assert db.scalar(select(func.count(CatalogRevisionPartPageMap.id))) == 4
        assert db.scalar(select(func.count(CatalogSourceBlob.id))) == 1


def test_stale_page_edit_rejected_and_same_position_and_number_isolated(pg_factory):
    page, _ = selected_source(pg_factory)
    barrier = Barrier(2)
    def update():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait(timeout=15)
            try:
                reference_pages.update(db, actor, page["id"], PageUpdate(expected_version=page["version"], title="QA human label"))
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: update(), range(2))) == [200, 409]
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        second = reference_pages.create(db, actor, page["assembly_id"], PageCreate())
        payload = PartCreate(position="1", part_number="QA-SAME", description="Exact human source text")
        first_part = parts.create_part(db, actor, page["assembly_id"], payload, reference_page_id=page["id"])
        second_part = parts.create_part(db, actor, page["assembly_id"], payload, reference_page_id=second["id"])
        assert first_part["id"] != second_part["id"] and first_part["reference_page_id"] != second_part["reference_page_id"]
