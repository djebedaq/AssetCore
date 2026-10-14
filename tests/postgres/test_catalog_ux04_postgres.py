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
from catalog_binding_fixtures import legacy_binding
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


def test_accepted_row_autosaves_share_the_catalog_lock_and_reject_stale_values(pg_factory):
    from app.catalog_admin.parts_extraction import review
    from app.catalog_admin.parts_extraction.schemas import CandidateEdit
    from app.models import User
    page, preview, catalog_id, _, _ = prepared(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        service.confirm(db, actor, page["id"], ExtractConfirm(token=preview["token"],
            rows=[{"index": index, "part": row["payload"]} for index, row in enumerate(preview["rows"])], confirm_warnings=True))
        candidate = review.workspace(db, actor, page["assembly_id"], page["id"])["sources"][0]["candidates"][0]
    outcomes = race(pg_factory, CatalogDefinition, catalog_id, [
        lambda db, actor: review.edit_candidate(db, actor, candidate["id"], CandidateEdit(
            expected_version=candidate["version"], values={"quantity": "3"})),
        lambda db, actor: review.edit_candidate(db, actor, candidate["id"], CandidateEdit(
            expected_version=candidate["version"], values={"quantity": "4"})),
    ], success_status=200)
    assert sorted(result.status for result in outcomes) == [200, 409]
    with pg_factory() as db:
        assert int(db.get(CatalogRevisionPart, candidate["part_id"]).quantity) in {3, 4}


def test_catalog_and_machine_model_edits_cannot_race_to_an_incompatible_binding(pg_factory):
    from app.assets.service import update_machine
    from app.catalog_admin import service as catalogs
    from app.catalog_admin.schemas import CatalogUpdate
    from app.models import AssetCategory, Machine, User
    from app.schemas import MachineUpdate
    _, _, catalog_id, _, _ = prepared(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        catalog = db.get(CatalogDefinition, catalog_id)
        catalog.manufacturer = "QA"
        machine = Machine(inventory_number="QA_UX04_MODEL_RACE", name="QA ONLY", category_id=catalog.asset_category_id,
            category=db.get(AssetCategory, catalog.asset_category_id).code,
            brand="QA", model="QA_MODEL_A")
        db.add(machine)
        db.commit()
        machine_id = machine.id
        db.add(CatalogRevision(catalog_id=catalog_id, revision_code="QA-PUBLISHED", status="PUBLISHED", created_by_id=actor.id))
        db.commit()
        catalogs.bind_asset(db, actor, catalog_id, machine_id, compatibility_confirmed=True)
    outcomes = race(pg_factory, CatalogDefinition, catalog_id, [
        lambda db, actor: catalogs.update_catalog(db, actor, catalog_id, CatalogUpdate(model_reference="QA_MODEL_A")),
        lambda db, actor: update_machine(machine_id, MachineUpdate(model="QA_MODEL_B"), actor, db),
    ], success_status=200)
    assert sorted(result.status for result in outcomes) == [200, 409]
    with pg_factory() as db:
        assert catalogs.compatibility(db.get(CatalogDefinition, catalog_id), db.get(Machine, machine_id)) != "INCOMPATIBLE"


def test_postgres_upgrade_preserves_an_existing_single_binding_and_allows_a_second(pg_factory):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from app.catalog_admin import service as catalogs
    from app.models import AssetCategory, CatalogAssetBinding, Machine, User
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(code="QA_UX04_MIGRATION", name_bg="QA", name_en="QA", name_ru="QA", capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        machine = Machine(inventory_number="QA_UX04_MIGRATION", name="QA ONLY", category_id=category.id, category=category.code, brand="QA", model="QA")
        items = [CatalogDefinition(code=f"QA_UX04_MIGRATION_{index}", asset_category_id=category.id,
            name_bg="QA", name_en="QA", name_ru="QA", manufacturer="QA", model_reference="QA", created_by_id=actor.id) for index in range(2)]
        db.add_all([machine, *items])
        db.commit()
        machine_id, catalog_ids = machine.id, [item.id for item in items]
        legacy_binding(db, actor, catalog_ids[0], machine_id)
        original = db.scalar(select(CatalogAssetBinding))
        before = (original.id, original.catalog_id, original.machine_id, original.created_by_id, original.created_at)
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "backend/alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/alembic"))
    engine = pg_factory.kw["bind"]
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "20261009_0033")
        command.upgrade(config, "head")
    with pg_factory() as db:
        original = db.scalar(select(CatalogAssetBinding))
        assert (original.id, original.catalog_id, original.machine_id, original.created_by_id, original.created_at) == before
        assert original.is_active and original.deactivated_at is None
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        db.add(CatalogRevision(catalog_id=catalog_ids[1], revision_code="QA-PUBLISHED", status="PUBLISHED", created_by_id=actor.id))
        db.commit()
        catalogs.bind_asset(db, actor, catalog_ids[1], machine_id)
        assert db.scalar(select(func.count(CatalogAssetBinding.id)).where(CatalogAssetBinding.machine_id == machine_id)) == 2
