"""Run the HTTP acceptance cases on a fresh Alembic-migrated PostgreSQL schema."""
import pytest
from app.catalog_admin import hotspots, parts, publication
from app.catalog_admin.schemas import PartUpdate
from app.models import (
    AuditLog,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionPositionHotspot,
    PartCatalog,
    User,
)
from sqlalchemy import func, select
from test_catalog_publication_postgres import _setup
from test_catalog_ux05 import (  # noqa: F401
    test_actual_integrity_errors_remain_blocking,
    test_confirmed_parts_publish_with_optional_review_and_coverage,
    test_legacy_assembly_scope_allows_zero_markers_but_rejects_invalid_geometry,
    test_old_accepted_parts_and_same_flow_inspection_need_no_source_attestation,
    test_stale_digest_never_materializes,
    test_unverified_marker_stays_unverified_and_hidden,
)
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_concurrency import race

pytestmark = pytest.mark.postgres


@pytest.fixture
def session_factory(pg_factory):
    return pg_factory


def warning_draft(factory):
    catalog_id, revisions = _setup(factory)
    revision_id, part_id = revisions[0]
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        parts.update_part(db, actor, part_id, PartUpdate(quantity="2"))
        marker = db.scalar(select(CatalogRevisionPositionHotspot))
        hotspots.delete_hotspot(db, actor, marker.id, marker.version)
        result = publication.readiness(db, revision_id)
        assert result["ready"] and result["summary"]["reviewed_source_count"] == 0
        assert {w["code"] for w in result["warnings"]} == {
            "catalog_publication_source_review_required", "catalog_publication_hotspot_coverage"}
    return catalog_id, revision_id, part_id, result


def test_warning_publication_and_edit_overlap_on_postgres_catalog_lock(pg_factory):
    catalog_id, revision_id, part_id, result = warning_draft(pg_factory)
    outcomes = race(pg_factory, CatalogDefinition, catalog_id, [
        lambda db, actor: publication.publish(db, actor, revision_id, result["publication_digest"], None, True),
        lambda db, actor: parts.update_part(db, actor, part_id, PartUpdate(quantity="3")),
    ], success_status=200)
    assert sorted(o.status for o in outcomes) == [200, 409]
    with pg_factory() as db:
        published = db.get(CatalogRevision, revision_id).status == "PUBLISHED"
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.builder_revision_id == revision_id)) == int(published)
        assert db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_type == "catalog_revision",
            AuditLog.entity_id == revision_id, AuditLog.action == "CATALOG_REVISION_PUBLISHED")) == int(published)


def test_warning_publication_materialization_failure_rolls_back_all_rows_and_audit(pg_factory, monkeypatch):
    _, revision_id, _, result = warning_draft(pg_factory)
    with pg_factory() as db:
        before = db.scalar(select(func.count(AuditLog.id)))
    original = publication._materialize
    def fail(*args):
        original(*args)
        raise RuntimeError("QA atomic rollback")
    monkeypatch.setattr(publication, "_materialize", fail)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        with pytest.raises(RuntimeError, match="QA atomic rollback"):
            publication.publish(db, actor, revision_id, result["publication_digest"], None, True)
    with pg_factory() as db:
        assert db.get(CatalogRevision, revision_id).status == "DRAFT"
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.builder_revision_id == revision_id)) == 0
        assert db.scalar(select(func.count(AuditLog.id))) == before
