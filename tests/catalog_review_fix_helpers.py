"""Real publication/search regressions using disposable synthetic QA records."""

import hashlib
import io
import json

import pytest
from app.application_errors import ApplicationError
from app.catalog import service as runtime
from app.catalog_admin import publication, service
from app.models import (
    AssetCategory,
    AuditLog,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionVisualPage,
    Machine,
    PartCatalog,
    TechnicalDocument,
    User,
    utcnow,
)
from catalog_binding_fixtures import legacy_binding
from catalog_review_helpers import verify_service_sources
from reportlab.pdfgen import canvas
from sqlalchemy import inspect, select


def context(db):
    actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
    category = AssetCategory(code="QA_REVIEW_FIX", name_bg="QA", name_en="QA", name_ru="QA",
        capabilities=["HAS_PARTS_CATALOG"])
    db.add(category)
    db.flush()
    machines = [Machine(inventory_number=f"QA_REVIEW_FIX_{index}", name="Synthetic QA only",
        category=category.code, category_id=category.id, brand="QA", model="QA") for index in range(2)]
    db.add_all(machines)
    db.commit()
    return actor, category, machines


def draft(db, actor, category, label, count):
    catalog = CatalogDefinition(code=f"QA_REVIEW_FIX_{label}", asset_category_id=category.id,
        name_bg="QA", name_en="QA", name_ru="QA", manufacturer="QA", model_reference="QA", created_by_id=actor.id)
    db.add(catalog)
    db.flush()
    revision = CatalogRevision(catalog_id=catalog.id, revision_code="QA", created_by_id=actor.id)
    db.add(revision)
    db.flush()
    assembly = CatalogRevisionAssembly(revision_id=revision.id, code="QA", name_bg="QA", name_en="QA", name_ru="QA", created_by_id=actor.id)
    db.add(assembly)
    db.flush()
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(40, 800, "Synthetic QA review-fix source")
    for index in range(count):
        pdf.drawString(40 + index * 50, 750, str(index + 1))
        pdf.drawString(40, 680 - index * 22, f"{index + 1}  QA-{label}-{index}  QA fairness match {label}  Quantity 1")
    pdf.showPage()
    pdf.save()
    content = stream.getvalue()
    artifact = CatalogRevisionArtifact(assembly_id=assembly.id, title="Synthetic QA source", filename="qa.pdf",
        media_type="application/pdf", content=content, sha256=hashlib.sha256(content).hexdigest(), page_count=1, created_by_id=actor.id)
    db.add(artifact)
    db.flush()
    scheme, spare = [CatalogRevisionVisualPage(artifact_id=artifact.id, page_number=1, role=role, created_by_id=actor.id)
        for role in ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]]
    db.add_all([scheme, spare])
    db.flush()
    for index in range(count):
        part = CatalogRevisionPart(assembly_id=assembly.id, position=str(index + 1), part_number=f"QA-{label}-{index}",
            description=f"QA fairness match {label}", quantity=1, created_by_id=actor.id)
        db.add(part)
        db.flush()
        db.add(CatalogRevisionPartPageMap(part_id=part.id, visual_page_id=spare.id, created_by_id=actor.id))
        db.add(CatalogRevisionPositionHotspot(visual_page_id=scheme.id, position=part.position,
            x=(40 + index * 50) / 595, y=.09, width=.04, height=.04, provenance="MANUAL_VERIFIED",
            is_verified=True, verified_by_id=actor.id, verified_at=utcnow(), created_by_id=actor.id))
    db.commit()
    return catalog, revision, assembly


def publish(db, actor, revision, assembly):
    verify_service_sources(db, actor, assembly.id)
    ready = publication.readiness(db, revision.id)
    assert ready["ready"]
    publication.publish(db, actor, revision.id, ready["publication_digest"], ready["current_published_revision_id"], True)


def assert_search_fairness(factory):
    with factory() as db:
        actor, category, machines = context(db)
        entries, identities = [], []
        for label, count in [("A", 5), ("B", 2), ("UNBOUND", 3), ("DRAFT", 3)]:
            catalog, revision, assembly = draft(db, actor, category, label, count)
            if label != "DRAFT":
                publish(db, actor, revision, assembly)
            entries.append((catalog, revision, assembly))
            identities.append(list(db.scalars(select(PartCatalog.id).where(
                PartCatalog.builder_revision_id == revision.id).order_by(PartCatalog.position))))
        def search(limit, source_id=None, query="QA fairness"):
            return [part["id"] for part in runtime.search(db, machine_id=machines[0].id,
                query=query, source_id=source_id, limit=limit)]
        service.bind_asset(db, actor, entries[0][0].id, machines[0].id)
        # Preserve the original single-catalog ordering and limit behavior.
        single = search(4)
        assert single == identities[0][:4]
        service.bind_asset(db, actor, entries[1][0].id, machines[0].id)
        legacy_binding(db, actor, entries[3][0].id, machines[0].id)
        first, second = identities[:2]
        expected = [first[0], second[0], first[1], second[1], *first[2:]]
        for limit in [1, 2, 3, 4, 5, 7, 10]:
            assert search(limit) == expected[:limit]
        assert search(4) == search(4) == search(4)
        assert search(4, publication.source_id(entries[0][2])) == single
        assert search(4, publication.source_id(entries[1][2])) == second
        assert search(10, query="NO_SUCH_SYNTHETIC_QA_VALUE") == []
        for index in [2, 3]:
            with pytest.raises(ApplicationError) as error:
                search(4, publication.source_id(entries[index][2]))
            assert error.value.code == "catalog_runtime_binding_mismatch"
        service.unbind_asset(db, actor, entries[1][0].id, machines[0].id)
        assert search(4) == single
        with pytest.raises(ApplicationError):
            search(4, publication.source_id(entries[1][2]))
        service.bind_asset(db, actor, entries[1][0].id, machines[0].id)
        document = db.scalar(select(TechnicalDocument).where(TechnicalDocument.builder_artifact_id.in_(
            select(CatalogRevisionArtifact.id).where(CatalogRevisionArtifact.assembly_id == entries[1][2].id))))
        document.sha256 = "0" * 64
        db.commit()
        # Integrity of later catalogs must still be checked when limit=1.
        with pytest.raises(ApplicationError) as error:
            search(1)
        assert error.value.code == "catalog_publication_integrity_failed"


def assert_publication_active_binding_count(factory, with_active_binding):
    with factory() as db:
        actor, category, machines = context(db)
        catalog, revision, assembly = draft(db, actor, category, "AUDIT", 1)
        legacy_binding(db, actor, catalog.id, machines[0].id)
        service.unbind_asset(db, actor, catalog.id, machines[0].id)
        if with_active_binding:
            legacy_binding(db, actor, catalog.id, machines[1].id)
        columns = [attribute.key for attribute in inspect(AuditLog).column_attrs]
        before = {row.id: tuple(getattr(row, key) for key in columns) for row in db.scalars(select(AuditLog))}
        publish(db, actor, revision, assembly)
        event = db.scalar(select(AuditLog).where(AuditLog.entity_type == "catalog_revision",
            AuditLog.entity_id == revision.id, AuditLog.action == "CATALOG_REVISION_PUBLISHED"))
        assert json.loads(event.details)["bound_asset_count"] == int(with_active_binding)
        bindings = list(db.scalars(select(CatalogAssetBinding).where(CatalogAssetBinding.catalog_id == catalog.id)))
        assert len(bindings) == 1 + int(with_active_binding)
        assert sum(row.is_active for row in bindings) == int(with_active_binding)
        assert before == {row.id: tuple(getattr(row, key) for key in columns)
            for row in db.scalars(select(AuditLog).where(AuditLog.id.in_(before)))}
