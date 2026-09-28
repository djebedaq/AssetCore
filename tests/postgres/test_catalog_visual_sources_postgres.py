"""Real PostgreSQL races against 01B staging uniqueness constraints."""

import base64
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin.schemas import ArtifactUpload, AssemblyCreate, VisualPageCreate
from app.catalog_admin.visual_sources import assign_visual_pages, create_assembly, upload_artifact
from app.models import (
    AssetCategory,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionVisualPage,
    User,
)
from fastapi import HTTPException
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def _race(factory, operation):
    barrier = Barrier(3, timeout=15)

    def worker():
        with factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                return 201, operation(db, actor)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        barrier.wait()
        return [future.result(timeout=50) for future in futures]


def test_assembly_artifact_and_page_role_races(pg_factory):
    with pg_factory() as db:
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(code="QA_VISUAL_RACE", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        catalog = CatalogDefinition(code="QA_VISUAL_RACE_CATALOG", asset_category_id=category.id,
                                    name_bg="QA", name_en="QA", name_ru="QA", created_by_id=owner.id)
        db.add(catalog)
        db.flush()
        revision = CatalogRevision(catalog_id=catalog.id, revision_code="A", created_by_id=owner.id)
        db.add(revision)
        db.commit()
        revision_id = revision.id
    assembly_data = AssemblyCreate(code="PUMP", name_bg="Помпа", name_en="Pump", name_ru="Насос")
    assembly_results = _race(pg_factory, lambda db, actor: create_assembly(db, actor, revision_id, assembly_data))
    assert sorted(status for status, _ in assembly_results) == [201, 409]
    assert next(value for status, value in assembly_results if status == 409) == "catalog_assembly_duplicate"
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionAssembly.id)).where(
            CatalogRevisionAssembly.revision_id == revision_id)) == 1
        assembly_id = db.scalar(select(CatalogRevisionAssembly.id).where(
            CatalogRevisionAssembly.revision_id == revision_id))
    stream = io.BytesIO()
    document = canvas.Canvas(stream)
    document.drawString(40, 700, "QA")
    document.showPage()
    document.save()
    upload = ArtifactUpload(title="QA", filename="qa.pdf", media_type="application/pdf",
                            content_base64=base64.b64encode(stream.getvalue()).decode())
    upload_results = _race(pg_factory, lambda db, actor: upload_artifact(db, actor, assembly_id, upload))
    assert sorted(status for status, _ in upload_results) == [201, 409]
    assert next(value for status, value in upload_results if status == 409) == "catalog_source_duplicate"
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionArtifact.id)).where(
            CatalogRevisionArtifact.assembly_id == assembly_id)) == 1
        artifact_id = db.scalar(select(CatalogRevisionArtifact.id).where(
            CatalogRevisionArtifact.assembly_id == assembly_id))
    assignment = VisualPageCreate(role="EXPLODED_SCHEME", page_numbers=[1])
    page_results = _race(pg_factory, lambda db, actor: assign_visual_pages(db, actor, artifact_id, assignment))
    assert sorted(status for status, _ in page_results) == [201, 409]
    assert next(value for status, value in page_results if status == 409) == "catalog_visual_page_duplicate"
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionVisualPage.id)).where(
            CatalogRevisionVisualPage.artifact_id == artifact_id)) == 1
