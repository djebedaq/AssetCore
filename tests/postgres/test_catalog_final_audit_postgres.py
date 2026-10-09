"""Boundary lengths and edit/publish races in isolated PostgreSQL schemas."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from app.catalog.runtime_context import published_binding
from app.catalog_admin import publication
from app.catalog_admin.hotspots import update_hotspot
from app.catalog_admin.repair_kits import update_kit
from app.catalog_admin.schemas import HotspotUpdate, RepairKitUpdate
from app.catalog_admin.service import bind_asset
from app.industrial_api import create_multi_part_request
from app.industrial_schemas import MultiPartRequestCreate
from app.models import (
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogDiagram,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPositionHotspot,
    CatalogRevisionRepairKit,
    Machine,
    PartCatalog,
    PartRequestLine,
    PartVisualSnapshot,
    RepairKit,
    TechnicalDocument,
    User,
)
from catalog_review_helpers import verify_service_sources
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from test_catalog_publication_postgres import _preview, _setup
from test_concurrency import ROOT
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def test_failed_replacement_preserves_current_publication_and_all_live_rows(pg_factory, monkeypatch):
    catalog_id, revisions = _setup(pg_factory, ("A", "B"))
    first_id, second_id = revisions[0][0], revisions[1][0]
    preview = _preview(pg_factory, first_id)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        publication.publish(db, actor, first_id, preview["publication_digest"], None, True)
        before = {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                  for model in (PartCatalog, RepairKit, CatalogDiagram, TechnicalDocument)}
    preview = _preview(pg_factory, second_id)
    original = publication._materialize

    def failing_materialization(*args):
        original(*args)
        raise RuntimeError("QA replacement rollback")

    monkeypatch.setattr(publication, "_materialize", failing_materialization)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        with pytest.raises(RuntimeError, match="QA replacement rollback"):
            publication.publish(db, actor, second_id, preview["publication_digest"], first_id, True)
    with pg_factory() as db:
        assert db.get(CatalogRevision, first_id).status == "PUBLISHED"
        assert db.get(CatalogRevision, second_id).status == "DRAFT"
        assert db.scalar(select(CatalogRevision.id).where(
            CatalogRevision.catalog_id == catalog_id, CatalogRevision.status == "PUBLISHED")) == first_id
        assert {model.__tablename__: db.scalar(select(func.count()).select_from(model))
                for model in (PartCatalog, RepairKit, CatalogDiagram, TechnicalDocument)} == before


def test_request_selection_locks_an_unbound_machine_until_transaction_finishes(pg_factory):
    catalog_id, _ = _setup(pg_factory)
    with pg_factory() as db:
        catalog = db.get(CatalogDefinition, catalog_id)
        machine = Machine(inventory_number="QA_BIND_RACE", name="QA", category="QA",
                          category_id=catalog.asset_category_id, brand="QA", model="QA")
        db.add(machine)
        db.commit()
        machine_id = machine.id
    with pg_factory() as reader:
        assert published_binding(reader, reader.get(Machine, machine_id), lock=True) is None
        with pg_factory() as writer:
            writer.execute(text("SET LOCAL lock_timeout = '100ms'"))
            actor = writer.scalar(select(User).where(User.is_system_owner.is_(True)))
            with pytest.raises(OperationalError) as caught:
                bind_asset(writer, actor, catalog_id, machine_id)
            assert caught.value.orig.sqlstate == "55P03"
            writer.rollback()
        reader.rollback()
    with pg_factory() as writer:
        actor = writer.scalar(select(User).where(User.is_system_owner.is_(True)))
        bind_asset(writer, actor, catalog_id, machine_id)
        assert writer.scalar(select(CatalogAssetBinding).where(
            CatalogAssetBinding.machine_id == machine_id)).catalog_id == catalog_id


@pytest.mark.parametrize("kind", ["hotspot", "kit"])
def test_publish_serializes_with_hotspot_and_kit_edits(pg_factory, kind):
    _, revisions = _setup(pg_factory)
    revision_id, _ = revisions[0]
    preview = _preview(pg_factory, revision_id)
    with pg_factory() as db:
        hotspot_id = db.scalar(select(CatalogRevisionPositionHotspot.id))
        kit_id = db.scalar(select(CatalogRevisionRepairKit.id))
    barrier = Barrier(3, timeout=15)

    def publisher():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                publication.publish(db, actor, revision_id, preview["publication_digest"], None, True)
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    def editor():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait()
            try:
                if kind == "hotspot":
                    update_hotspot(db, actor, hotspot_id, HotspotUpdate(expected_version=1, x=.2))
                else:
                    update_kit(db, actor, kit_id, RepairKitUpdate(expected_version=1, name_bg="QA edited"))
                return 200
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        publishing, editing = pool.submit(publisher), pool.submit(editor)
        barrier.wait()
        assert sorted((publishing.result(timeout=60), editing.result(timeout=60))) == [200, 409]
    with pg_factory() as db:
        revision = db.get(CatalogRevision, revision_id)
        live = db.scalar(select(PartCatalog).where(PartCatalog.builder_revision_id == revision_id))
        if revision.status == "PUBLISHED":
            assert live is not None
            assert db.get(CatalogRevisionPositionHotspot, hotspot_id).x == .1
            assert db.get(CatalogRevisionRepairKit, kit_id).name_bg == "Комплект"
        else:
            assert revision.status == "DRAFT" and live is None


def test_maximum_names_and_position_publish_without_truncation_and_guard_downgrade(pg_factory):
    catalog_id, revisions = _setup(pg_factory)
    revision_id, part_id = revisions[0]
    position = "P" * 80
    title = "С" * 255 + " — " + "Д" * 255
    with pg_factory() as db:
        assembly = db.scalar(select(CatalogRevisionAssembly))
        artifact = db.scalar(select(CatalogRevisionArtifact))
        assembly.name_bg, artifact.title = "С" * 255, "Д" * 255
        db.get(CatalogRevisionPart, part_id).position = position
        db.scalar(select(CatalogRevisionPositionHotspot)).position = position
        db.commit()
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        verify_service_sources(db, actor, assembly.id)
    preview = _preview(pg_factory, revision_id)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        publication.publish(db, actor, revision_id, preview["publication_digest"], None, True)
        assert db.scalar(select(CatalogDiagram).where(
            CatalogDiagram.builder_revision_id == revision_id)).title == title
        live = db.scalar(select(PartCatalog).where(PartCatalog.builder_part_id == part_id))
        assert live.position == position
        catalog = db.get(CatalogDefinition, catalog_id)
        machine = Machine(inventory_number="QA_MAXIMUM", name="QA", category="QA",
                          category_id=catalog.asset_category_id, brand="QA", model="QA")
        db.add(machine)
        db.flush()
        db.add(CatalogAssetBinding(catalog_id=catalog_id, machine_id=machine.id, created_by_id=actor.id))
        db.commit()
        request = create_multi_part_request(MultiPartRequestCreate(machine_id=machine.id,
            lines=[{"catalog_part_id": live.id, "description": "QA", "quantity": 1}]), user=actor, db=db)
        line = db.scalar(select(PartRequestLine).where(PartRequestLine.request_id == request["id"]))
        assert line.position == position
        assert db.scalar(select(PartVisualSnapshot).where(PartVisualSnapshot.line_id == line.id)) is not None
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with pg_factory.kw["bind"].begin() as connection:
        config.attributes["connection"] = connection
        with pytest.raises(RuntimeError, match="history cannot be discarded"):
            command.downgrade(config, "20260929_0029")
        # Retain the preceding migration's PostgreSQL truncation assertion too.
        import importlib.util

        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        path = ROOT / "backend/alembic/versions/20261001_0031_catalog_auto_ingest.py"
        spec = importlib.util.spec_from_file_location("qa_ingest_migration", path)
        ingest_migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ingest_migration)
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="shared or guided source evidence"):
                ingest_migration.downgrade()
        path = ROOT / "backend/alembic/versions/20260930_0030_catalog_diagram_titles.py"
        spec = importlib.util.spec_from_file_location("qa_title_migration", path)
        title_migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(title_migration)
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="title exceeds 500"):
                title_migration.downgrade()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261009_0033"
