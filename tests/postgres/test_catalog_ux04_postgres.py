"""Overlapping PostgreSQL draft deletion/confirmation on the catalog lock."""

import pytest
from app.catalog_admin import draft_deletion
from app.catalog_admin.parts_extraction import service
from app.catalog_admin.parts_extraction.schemas import ExtractConfirm
from app.models import (
    CatalogDefinition,
    CatalogExtractionAttempt,
    CatalogExtractionSource,
    CatalogRevision,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
)
from sqlalchemy import func, select
from test_catalog_guided_builder_postgres import selected_source
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_concurrency import race

pytestmark = pytest.mark.postgres


def prepared(factory):
    page, preview = selected_source(factory)
    with factory() as db:
        assembly = db.get(CatalogRevisionAssembly, page["assembly_id"])
        catalog_id = db.get(CatalogRevision, assembly.revision_id).catalog_id
        identity = preview["source"]["visual_page_id"]
        plan = draft_deletion.preview(db, "source", identity)
        return page, preview, catalog_id, identity, plan


def test_two_draft_deletions_only_one_executes_and_neither_leaves_orphans(pg_factory):
    _, _, catalog_id, identity, plan = prepared(pg_factory)
    outcomes = race(pg_factory, CatalogDefinition, catalog_id, [
        lambda db, actor: draft_deletion.remove(db, actor, "source", identity, plan["digest"])] * 2,
        success_status=204)
    assert sorted(result.status for result in outcomes) == [204, 404]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogExtractionSource.id))) == 0
        assert db.scalar(select(func.count(CatalogExtractionAttempt.id))) == 0


def test_confirmation_racing_deletion_is_atomic_and_preview_detects_new_parts(pg_factory):
    page, preview, catalog_id, identity, plan = prepared(pg_factory)
    data = ExtractConfirm(token=preview["token"], rows=[{"index": index, "part": row["payload"]}
        for index, row in enumerate(preview["rows"])], confirm_warnings=True)
    outcomes = race(pg_factory, CatalogDefinition, catalog_id, [
        lambda db, actor: draft_deletion.remove(db, actor, "source", identity, plan["digest"]),
        lambda db, actor: service.confirm(db, actor, page["id"], data)], success_status=200)
    statuses = sorted(result.status for result in outcomes)
    assert statuses in ([200, 409], [200, 422])
    with pg_factory() as db:
        sources = db.scalar(select(func.count(CatalogExtractionSource.id)))
        parts = db.scalar(select(func.count(CatalogRevisionPart.id)))
        assert (sources, parts) in [(0, 0), (1, len(preview["rows"]))]
