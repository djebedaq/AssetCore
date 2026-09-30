"""Publication serialization and rollback against an isolated real PostgreSQL schema."""

import hashlib
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin import publication
from app.catalog_admin.parts import update_part
from app.catalog_admin.schemas import PartUpdate
from app.industrial_api import create_multi_part_request
from app.industrial_schemas import MultiPartRequestCreate
from app.models import (
    AssetCategory,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogDiagram,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionRepairKit,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    CatalogVisualPartMap,
    CatalogVisualSource,
    Machine,
    PartCatalog,
    PartRequest,
    PartRequestLine,
    RepairKit,
    TechnicalDocument,
    User,
    utcnow,
)
from fastapi import HTTPException
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def _pdf() -> bytes:
    stream = io.BytesIO()
    document = canvas.Canvas(stream)
    document.drawString(50, 700, "QA publication")
    document.showPage()
    document.save()
    return stream.getvalue()


def _setup(factory, revision_codes=("A",), suffix=""):
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(code=f"QA_PUBLISH_RACE{suffix}", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        catalog = CatalogDefinition(code=f"QA_PUBLISH_RACE{suffix}", asset_category_id=category.id,
                                    name_bg="QA", name_en="QA", name_ru="QA", created_by_id=actor.id)
        db.add(catalog)
        db.flush()
        revisions = []
        for code in revision_codes:
            revision = CatalogRevision(catalog_id=catalog.id, revision_code=code,
                                       status="DRAFT", created_by_id=actor.id)
            db.add(revision)
            db.flush()
            assembly = CatalogRevisionAssembly(revision_id=revision.id, code="PUMP",
                                               name_bg="QA", name_en="QA", name_ru="QA",
                                               created_by_id=actor.id)
            db.add(assembly)
            db.flush()
            raw = _pdf()
            artifact = CatalogRevisionArtifact(assembly_id=assembly.id, title="QA source",
                                               filename="qa.pdf", media_type="application/pdf",
                                               content=raw, sha256=hashlib.sha256(raw).hexdigest(),
                                               page_count=1, created_by_id=actor.id)
            db.add(artifact)
            db.flush()
            scheme = CatalogRevisionVisualPage(artifact_id=artifact.id, page_number=1,
                                               role="EXPLODED_SCHEME", created_by_id=actor.id)
            spare = CatalogRevisionVisualPage(artifact_id=artifact.id, page_number=1,
                                              role="SPARE_PARTS_LIST", created_by_id=actor.id)
            db.add_all([scheme, spare])
            db.flush()
            part = CatalogRevisionPart(assembly_id=assembly.id, position="12",
                                       part_number=f"QA-{code}", name_bg="Тест",
                                       name_en="Test", created_by_id=actor.id)
            db.add(part)
            db.flush()
            db.add(CatalogRevisionPartPageMap(part_id=part.id, visual_page_id=spare.id,
                                              created_by_id=actor.id))
            db.add(CatalogRevisionPositionHotspot(visual_page_id=scheme.id, position="12",
                                                  x=.1, y=.1, width=.1, height=.1,
                                                  provenance="MANUAL_VERIFIED", is_verified=True,
                                                  verified_by_id=actor.id, verified_at=utcnow(),
                                                  version=1, created_by_id=actor.id))
            kit = CatalogRevisionRepairKit(assembly_id=assembly.id, code="QA_KIT",
                                           name_bg="Комплект", source_visual_page_id=spare.id,
                                           created_by_id=actor.id)
            db.add(kit)
            db.flush()
            db.add(CatalogRevisionRepairKitComponent(kit_id=kit.id, part_id=part.id,
                                                     quantity=1, quantity_raw="1",
                                                     created_by_id=actor.id))
            revisions.append((revision.id, part.id))
        db.commit()
        return catalog.id, revisions


def _preview(factory, revision_id):
    with factory() as db:
        result = publication.readiness(db, revision_id)
        assert result["ready"], result
        return result


def test_competing_publishers_have_one_current_revision(pg_factory):
    catalog_id, revisions = _setup(pg_factory, ("A", "B"))
    previews = {revision_id: _preview(pg_factory, revision_id) for revision_id, _ in revisions}
    barrier = Barrier(3, timeout=15)

    def worker(revision_id):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                publication.publish(db, actor, revision_id,
                                    previews[revision_id]["publication_digest"], None, True)
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, revision_id) for revision_id, _ in revisions]
        barrier.wait()
        assert sorted(f.result(timeout=60) for f in futures) == [200, 409]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevision.id)).where(
            CatalogRevision.catalog_id == catalog_id, CatalogRevision.status == "PUBLISHED")) == 1
        assert db.scalar(select(func.count(PartCatalog.id)).where(
            PartCatalog.builder_revision_id.is_not(None))) == 1


def test_publish_and_part_edit_serialize_to_valid_state(pg_factory):
    _, revisions = _setup(pg_factory)
    revision_id, part_id = revisions[0]
    preview = _preview(pg_factory, revision_id)
    barrier = Barrier(3, timeout=15)

    def publish_worker():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                publication.publish(db, actor, revision_id, preview["publication_digest"], None, True)
                return 200
            except HTTPException as exc:
                return exc.status_code

    def edit_worker():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                update_part(db, actor, part_id, PartUpdate(name_bg="Нова тестова част"))
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = pool.submit(publish_worker), pool.submit(edit_worker)
        barrier.wait()
        results = [left.result(timeout=60), right.result(timeout=60)]
    assert sorted(results) in ([200, 409], [409, 200])
    with pg_factory() as db:
        revision = db.get(CatalogRevision, revision_id)
        draft = db.get(CatalogRevisionPart, part_id)
        live = db.scalar(select(PartCatalog).where(PartCatalog.builder_part_id == part_id))
        if revision.status == "PUBLISHED":
            assert live and live.name_bg == draft.name_bg
        else:
            assert revision.status == "DRAFT" and live is None


def test_publish_rollback_removes_every_live_row(pg_factory, monkeypatch):
    _, revisions = _setup(pg_factory)
    revision_id, _ = revisions[0]
    preview = _preview(pg_factory, revision_id)
    original = publication._materialize

    def fail_after_materialization(*args):
        original(*args)
        raise RuntimeError("QA forced publication rollback")

    monkeypatch.setattr(publication, "_materialize", fail_after_materialization)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        with pytest.raises(RuntimeError, match="QA forced publication rollback"):
            publication.publish(db, actor, revision_id, preview["publication_digest"], None, True)
    with pg_factory() as db:
        assert db.get(CatalogRevision, revision_id).status == "DRAFT"
        for model, column in ((PartCatalog, PartCatalog.builder_revision_id),
                              (RepairKit, RepairKit.builder_revision_id),
                              (CatalogDiagram, CatalogDiagram.builder_revision_id),
                              (CatalogVisualSource, CatalogVisualSource.builder_revision_id)):
            assert db.scalar(select(func.count(model.id)).where(column == revision_id)) == 0
        assert db.scalar(select(func.count(CatalogVisualPartMap.id)).where(
            CatalogVisualPartMap.builder_part_page_map_id.is_not(None))) == 0
        assert db.scalar(select(func.count(TechnicalDocument.id)).where(
            TechnicalDocument.builder_artifact_id.is_not(None))) == 0


def test_database_rejects_second_current_publication(pg_factory):
    catalog_id, revisions = _setup(pg_factory, ("A", "B"))
    first_id, _ = revisions[0]
    second_id, _ = revisions[1]
    preview = _preview(pg_factory, first_id)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        publication.publish(db, actor, first_id, preview["publication_digest"], None, True)
    with pg_factory() as db, pytest.raises(IntegrityError):
        db.get(CatalogRevision, second_id).status = "PUBLISHED"
        db.commit()
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogRevision.id)).where(
            CatalogRevision.catalog_id == catalog_id,
            CatalogRevision.status == "PUBLISHED")) == 1


def test_scoped_kit_codes_publish_concurrently(pg_factory):
    first_catalog_id, first = _setup(pg_factory, suffix="_ONE")
    second_catalog_id, second = _setup(pg_factory, suffix="_TWO")
    first_id, second_id = first[0][0], second[0][0]
    previews = {item: _preview(pg_factory, item) for item in (first_id, second_id)}
    barrier = Barrier(3, timeout=15)

    def worker(revision_id):
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            publication.publish(db, actor, revision_id,
                                previews[revision_id]["publication_digest"], None, True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, item) for item in (first_id, second_id)]
        barrier.wait()
        for future in futures:
            future.result(timeout=60)
    with pg_factory() as db:
        assert first_catalog_id != second_catalog_id
        assert db.scalar(select(func.count(RepairKit.id)).where(
            RepairKit.builder_revision_id.in_((first_id, second_id)),
            RepairKit.code == "QA_KIT", RepairKit.is_active.is_(True))) == 2


def test_request_and_publication_choose_one_consistent_revision(pg_factory):
    catalog_id, revisions = _setup(pg_factory, ("A", "B"))
    first_id, second_id = revisions[0][0], revisions[1][0]
    first_preview = _preview(pg_factory, first_id)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        publication.publish(db, actor, first_id, first_preview["publication_digest"], None, True)
        catalog = db.get(CatalogDefinition, catalog_id)
        category = db.get(AssetCategory, catalog.asset_category_id)
        machine = Machine(inventory_number="QA_PUBLISH_REQUEST", name="QA",
                          category=category.code, category_id=category.id,
                          brand="QA", model="QA")
        db.add(machine)
        db.flush()
        db.add(CatalogAssetBinding(catalog_id=catalog_id, machine_id=machine.id,
                                   created_by_id=actor.id))
        db.commit()
        machine_id = machine.id
        old_part_id = db.scalar(select(PartCatalog.id).where(PartCatalog.builder_revision_id == first_id))
    second_preview = _preview(pg_factory, second_id)
    barrier = Barrier(3, timeout=15)

    def request_worker():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                result = create_multi_part_request(MultiPartRequestCreate(
                    machine_id=machine_id, lines=[{"catalog_part_id": old_part_id,
                                                   "description": "QA request", "quantity": 1}]),
                    user=actor, db=db)
                return 201, result["id"]
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, None

    def publish_worker():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            publication.publish(db, actor, second_id,
                                second_preview["publication_digest"], first_id, True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        request_future, publish_future = pool.submit(request_worker), pool.submit(publish_worker)
        barrier.wait()
        request_status, request_id = request_future.result(timeout=60)
        publish_future.result(timeout=60)
    assert request_status in (201, 409)
    with pg_factory() as db:
        assert db.get(CatalogRevision, second_id).status == "PUBLISHED"
        if request_status == 201:
            request = db.get(PartRequest, request_id)
            line = db.scalar(select(PartRequestLine).where(PartRequestLine.request_id == request_id))
            assert request.machine_id == machine_id and line.catalog_part_id == old_part_id
        else:
            assert db.scalar(select(func.count(PartRequest.id)).where(
                PartRequest.machine_id == machine_id)) == 0
