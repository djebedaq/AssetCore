"""UX04 ownership/concurrency contracts in a new disposable SQLite database."""

import base64
from datetime import timedelta

import fitz
import pytest
from app.catalog.runtime_context import published_bindings
from app.catalog_admin import draft_deletion, reference_pages, service, visual_sources, wizard
from app.catalog_admin.parts_extraction.schemas import PageCreate, SourceAssign
from app.catalog_admin.schemas import ArtifactUpload, SimpleCatalogCreate
from app.database import Base
from app.models import (
    AssetCategory,
    AuditLog,
    CatalogAssetBinding,
    CatalogExtractionAttempt,
    CatalogExtractionCandidate,
    CatalogExtractionSession,
    CatalogExtractionSource,
    CatalogRevision,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionReferencePage,
    CatalogRevisionVisualPage,
    CatalogSourceBlob,
    Machine,
    User,
    utcnow,
)
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session


@pytest.fixture()
def qa(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ux04-qa.db'}")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as db:
        actor = User(
            email="ux04@assetcore.invalid",
            full_name="Isolated QA operator",
            role="administrator",
            password_hash="QA unavailable",
        )
        category = AssetCategory(
            code="QA_UX04",
            name_bg="QA",
            name_en="QA",
            name_ru="QA",
            capabilities=["HAS_PARTS_CATALOG"],
        )
        db.add_all([actor, category])
        db.commit()
        yield db, actor, category
    engine.dispose()


def catalog(qa, name="Isolated QA catalog"):
    db, actor, category = qa
    item = wizard.create_catalog(
        db,
        actor,
        SimpleCatalogCreate(
            name=name, asset_category_id=category.id, manufacturer="QA", model_reference="QA"
        ),
    )
    revision = db.scalar(select(CatalogRevision).where(CatalogRevision.catalog_id == item["id"]))
    return item, revision


def group(qa, revision, name="QA user assembly"):
    db, actor, _ = qa
    assembly = wizard.create_group(db, actor, revision.id, name)
    page = reference_pages.create(db, actor, assembly["id"], PageCreate())
    return assembly, page


def pdf(qa, assembly):
    db, actor, _ = qa
    with fitz.open() as document:
        for number in range(1, 7):
            page = document.new_page()
            page.insert_text((30, 40), f"Synthetic isolated UX04 source page {number}")
        content = document.tobytes()
    return visual_sources.upload_artifact(
        db,
        actor,
        assembly["id"],
        ArtifactUpload(
            title="Isolated QA PDF",
            filename="qa.pdf",
            media_type="application/pdf",
            content_base64=base64.b64encode(content).decode(),
        ),
    )


def assign(qa, page, artifact, selections):
    db, actor, _ = qa
    return reference_pages.assign(
        db,
        actor,
        page["id"],
        SourceAssign(
            expected_version=page["version"], artifact_id=artifact["id"], selections=selections
        ),
    )


def test_user_assemblies_many_schemes_lists_order_and_shared_pdf(qa):
    db, _, _ = qa
    _, revision = catalog(qa)
    assert not list(db.scalars(select(CatalogRevisionAssembly)))
    assemblies = [group(qa, revision, name) for name in ["QA Chassis", "QA Boom", "QA Blasting"]]
    source = pdf(qa, assemblies[0][0])
    first = assign(
        qa,
        assemblies[0][1],
        source,
        [
            {"page_number": 2, "roles": ["EXPLODED_SCHEME"]},
            {"page_number": 1, "roles": ["EXPLODED_SCHEME"]},
            {"page_number": 5, "roles": ["SPARE_PARTS_LIST"]},
            {"page_number": 3, "roles": ["SPARE_PARTS_LIST"]},
            {"page_number": 6, "roles": ["SPARE_PARTS_LIST"]},
        ],
    )
    second = assign(
        qa,
        assemblies[1][1],
        source,
        [{"page_number": 4, "roles": ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]}],
    )
    assert [row["page_number"] for row in first["sources"]] == [2, 1, 5, 3, 6]
    assert first["scheme_count"] == 2 and first["spare_list_count"] == 3
    assert second["scheme_count"] == second["spare_list_count"] == 1
    assert db.scalar(select(func.count(CatalogRevisionAssembly.id))) == 3
    assert db.scalar(select(func.count(CatalogSourceBlob.id))) == 1


@pytest.mark.parametrize("kind", ["source", "group", "assembly", "document", "revision", "catalog"])
def test_delete_processed_draft_atomically_preserves_other_owners_and_source_blob(qa, kind):
    db, actor, _ = qa
    item, revision = catalog(qa)
    assembly, page = group(qa, revision)
    artifact = pdf(qa, assembly)
    page = assign(qa, page, artifact, [{"page_number": 1, "roles": ["SPARE_PARTS_LIST"]}])
    source_id = page["sources"][0]["id"]
    other_assembly, other_page = group(qa, revision, "QA other owner")
    other_page = assign(
        qa, other_page, artifact, [{"page_number": 2, "roles": ["SPARE_PARTS_LIST"]}]
    )
    protected_catalog, protected_revision = catalog(qa, "QA immutable anchor")
    protected_revision.status = "PUBLISHED"
    protected_revision.published_at = utcnow()
    db.commit()
    # Explicit synthetic ledger represents finished OCR and edited candidate data.
    active = CatalogExtractionSession(
        revision_id=revision.id,
        assembly_id=assembly["id"],
        reference_page_id=page["id"],
        scope_key="QA",
        selection_digest="0" * 64,
        selection=[],
        created_by_id=actor.id,
    )
    db.add(active)
    db.flush()
    source = CatalogExtractionSource(
        session_id=active.id,
        visual_page_id=source_id,
        source_blob_id=db.scalar(select(CatalogSourceBlob.id)),
        source={},
        processing_state="SUCCEEDED",
        review_state="NEEDS_REVIEW",
    )
    db.add(source)
    db.flush()
    db.add(
        CatalogExtractionAttempt(
            source_id=source.id,
            kind="EXTRACTION",
            state="SUCCEEDED",
            extractor="QA",
            actor_id=actor.id,
            deadline_at=utcnow() + timedelta(minutes=1),
            evidence={"synthetic_qa": True},
        )
    )
    for index in range(19):
        part = CatalogRevisionPart(
            assembly_id=assembly["id"],
            reference_page_id=page["id"],
            position=str(index),
            part_number=f"QA-{index}",
            created_by_id=actor.id,
        )
        db.add(part)
        db.flush()
        db.add(
            CatalogRevisionPartPageMap(
                part_id=part.id, visual_page_id=source_id, created_by_id=actor.id
            )
        )
        db.add(
            CatalogExtractionCandidate(
                source_id=source.id,
                stable_key=str(index),
                original={},
                values={},
                state="ACCEPTED",
                part_id=part.id,
                part_created_at=part.created_at,
                updated_by_id=actor.id,
            )
        )
    db.commit()
    root = {
        "catalog": item["id"],
        "revision": revision.id,
        "assembly": assembly["id"],
        "group": page["id"],
        "source": source_id,
        "document": artifact["id"],
    }[kind]
    preview = draft_deletion.preview(db, kind, root)
    assert preview["counts"]["catalog_revision_parts"] == 19 and not preview["blockers"]
    draft_deletion.remove(db, actor, kind, root, preview["digest"])
    assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 0
    assert db.scalar(select(func.count(CatalogExtractionCandidate.id))) == 0
    assert db.scalar(select(func.count(CatalogExtractionAttempt.id))) == 0
    assert db.scalar(select(func.count(CatalogSourceBlob.id))) == 1
    assert db.get(CatalogRevision, protected_revision.id).status == "PUBLISHED"
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "CATALOG_DRAFT_DELETED"))
    if kind not in {"catalog", "revision"}:
        assert db.get(CatalogRevisionReferencePage, other_page["id"])
        assert db.get(CatalogRevisionVisualPage, other_page["sources"][0]["id"])


def test_stale_preview_published_guard_and_multiple_active_bindings(qa):
    db, actor, category = qa
    item, revision = catalog(qa)
    second, second_revision = catalog(qa, "QA second catalog")
    machine = Machine(
        inventory_number="QA_UX04_ONLY",
        name="QA",
        category=category.code,
        category_id=category.id,
        brand="QA",
        model="QA",
    )
    db.add(machine)
    db.commit()
    service.bind_asset(db, actor, item["id"], machine.id)
    service.bind_asset(db, actor, second["id"], machine.id)
    assert not published_bindings(db, machine)
    before = draft_deletion.preview(db, "revision", revision.id)
    group(qa, revision)
    with pytest.raises(HTTPException) as stale:
        draft_deletion.remove(db, actor, "revision", revision.id, before["digest"])
    assert stale.value.detail["code"] == "catalog_delete_stale"
    revision.status = second_revision.status = "PUBLISHED"
    revision.published_at = second_revision.published_at = utcnow()
    db.commit()
    assert len(published_bindings(db, machine)) == 2
    with pytest.raises(HTTPException) as protected:
        draft_deletion.preview(db, "catalog", item["id"])
    assert protected.value.detail["code"] == "catalog_delete_published_protected"
    service.unbind_asset(db, actor, item["id"], machine.id)
    assert len(published_bindings(db, machine)) == 1
    assert db.scalar(select(func.count(CatalogAssetBinding.id))) == 2


def test_model_compatibility_requires_explicit_ambiguous_confirmation(qa):
    db, actor, category = qa
    item, _ = catalog(qa)
    machine = Machine(
        inventory_number="QA_UX04_MODEL",
        name="QA",
        category=category.code,
        category_id=category.id,
        brand="QA",
        model="OTHER",
    )
    db.add(machine)
    db.commit()
    with pytest.raises(HTTPException) as mismatch:
        service.bind_asset(db, actor, item["id"], machine.id, True)
    assert mismatch.value.detail["code"] == "catalog_asset_model_mismatch"
    machine.model = None
    db.commit()
    with pytest.raises(HTTPException) as ambiguous:
        service.bind_asset(db, actor, item["id"], machine.id)
    assert ambiguous.value.detail["code"] == "catalog_asset_compatibility_confirmation_required"
    service.bind_asset(db, actor, item["id"], machine.id, True)


def test_late_worker_cannot_recreate_deleted_draft_sources(qa, monkeypatch):
    from app.catalog_admin.parts_extraction import process
    from app.catalog_admin.parts_extraction import service as extraction
    from app.catalog_admin.parts_extraction.schemas import ExtractSelection
    from catalog_ux04_fixtures import workflow_pdf
    db, actor, _ = qa
    _, revision = catalog(qa)
    assembly, page = group(qa, revision)
    artifact = visual_sources.upload_artifact(db, actor, assembly["id"], ArtifactUpload(
        title="QA worker", filename="qa-worker.pdf", media_type="application/pdf", content_base64=base64.b64encode(workflow_pdf()).decode()))
    page = assign(qa, page, artifact, [{"page_number": 6, "roles": ["SPARE_PARTS_LIST"]}])
    identity = page["sources"][0]["id"]
    actor_id = actor.id
    original = process.extract
    def delete_while_working(*args, **kwargs):
        with Session(db.get_bind(), autoflush=False) as deleting:
            draft_deletion.remove(deleting, deleting.get(User, actor_id), "source", identity)
        return original(*args, **kwargs)
    monkeypatch.setattr(process, "extract", delete_while_working)
    with pytest.raises(HTTPException) as stale:
        extraction.preview(db, actor, page["id"], ExtractSelection(visual_page_id=identity))
    assert stale.value.detail["code"] == "catalog_reference_page_stale"
    assert db.scalar(select(func.count(CatalogExtractionAttempt.id))) == 0
    assert db.scalar(select(func.count(CatalogExtractionSource.id))) == 0
