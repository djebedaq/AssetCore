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
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogSourceBlob,
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
    assert sorted(result.status for result in outcomes) == [204, 409]
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


def test_collecting_unused_pdf_races_safely_with_another_catalog_reusing_it(pg_factory):
    from app.catalog_admin import source_storage
    page, preview, catalog_id, _, _ = prepared(pg_factory)
    with pg_factory() as db:
        original = db.get(CatalogRevisionArtifact, preview["source"]["artifact_id"])
        content, digest, blob_id = original.content, original.sha256, original.source_blob_id
        owner_id = original.created_by_id
        catalog = CatalogDefinition(code="QA_UX04_SHARED", asset_category_id=db.get(CatalogDefinition, catalog_id).asset_category_id,
            name_bg="QA", name_en="QA", name_ru="QA", created_by_id=owner_id)
        db.add(catalog)
        db.flush()
        revision = CatalogRevision(catalog_id=catalog.id, revision_code="QA", created_by_id=owner_id)
        db.add(revision)
        db.flush()
        assembly = CatalogRevisionAssembly(revision_id=revision.id, code="QA", name_bg="QA", name_en="QA", name_ru="QA", created_by_id=owner_id)
        db.add(assembly)
        db.commit()
        target_id = assembly.id
    def reuse(db, actor):
        blob = source_storage.shared_blob(db, content, digest)
        db.add(CatalogRevisionArtifact(assembly_id=target_id, title="Synthetic QA reused original", filename="qa.pdf",
            media_type="application/pdf", source_blob=blob, stored_content=b"", sha256=digest, page_count=2, created_by_id=actor.id))
        db.commit()
    outcomes = race(pg_factory, CatalogSourceBlob, blob_id, [
        lambda db, actor: draft_deletion.remove(db, actor, "catalog", catalog_id), reuse], success_status=200, expected_statuses=[200, 200])
    assert [result.status for result in outcomes] == [200, 200]
    with pg_factory() as db:
        retained = db.scalar(select(CatalogRevisionArtifact).where(CatalogRevisionArtifact.assembly_id == target_id))
        assert retained.content == content and retained.sha256 == digest
        assert db.scalar(select(func.count(CatalogSourceBlob.id)).where(CatalogSourceBlob.sha256 == digest)) == 1
