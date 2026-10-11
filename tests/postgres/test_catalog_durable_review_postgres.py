"""Real PostgreSQL review/version conflicts behind the publication catalog lock."""
import pytest
from app.catalog_admin import publication
from app.catalog_admin.parts_extraction import ledger, review, service
from app.catalog_admin.parts_extraction.schemas import ExtractConfirm, SourceReview
from app.models import CatalogDefinition, CatalogRevision, CatalogRevisionAssembly, User
from catalog_review_helpers import verify_service_sources
from sqlalchemy import select
from test_catalog_guided_builder_postgres import selected_source
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_concurrency import race

pytestmark = pytest.mark.postgres


def prepared(factory):
    page, preview = selected_source(factory)
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        service.confirm(db, actor, page["id"], ExtractConfirm(token=preview["token"],
            rows=[{"index": i, "part": r["payload"]} for i, r in enumerate(preview["rows"])], confirm_warnings=True))
        verify_service_sources(db, actor, page["assembly_id"], page["id"])
        state = review.workspace(db, actor, page["assembly_id"], page["id"])["sources"][0]
        _, receipt = review.original(db, actor, state["visual_page_id"])
        assembly = db.get(CatalogRevisionAssembly, page["assembly_id"])
        catalog_id = db.get(CatalogRevision, assembly.revision_id).catalog_id
        return page, state, receipt, catalog_id, assembly.revision_id


def test_two_source_approvals_wait_for_catalog_lock_and_only_one_version_wins(pg_factory):
    _, state, receipt, catalog_id, _ = prepared(pg_factory)
    data = SourceReview(expected_version=state["version"], fingerprint=state["fingerprint"],
        inspection_token=receipt, reason="QA compared the exact original before reapproval")
    outcomes = race(pg_factory, CatalogDefinition, catalog_id,
        [lambda db, actor: review.verify(db, actor, state["visual_page_id"], data)] * 2, success_status=200)
    assert sorted(outcome.status for outcome in outcomes) == [200, 409]


def test_candidate_edits_share_catalog_lock_and_reject_stale_version(pg_factory):
    from app.catalog_admin.parts_extraction.schemas import CandidateEdit
    page, preview = selected_source(pg_factory)
    candidate = preview["rows"][0]
    with pg_factory() as db:
        revision_id = db.get(CatalogRevisionAssembly, page["assembly_id"]).revision_id
        catalog_id = db.get(CatalogRevision, revision_id).catalog_id
    data = CandidateEdit(expected_version=candidate["candidate_version"], values={**candidate["payload"],
        "part_number": "QA-CONCURRENT-CORRECTION"})
    outcomes = race(pg_factory, CatalogDefinition, catalog_id,
        [lambda db, actor: review.edit_candidate(db, actor, candidate["candidate_id"], data)] * 2, success_status=200)
    assert sorted(outcome.status for outcome in outcomes) == [200, 409]


def test_owner_catalog_delete_serializes_with_review_and_retains_history(pg_factory):
    import secrets

    from app.governance.owner_data_deletion import ExecuteRequest, ResourceType, execute, preview
    from app.security import hash_password
    from starlette.requests import Request
    _, state, receipt, catalog_id, revision_id = prepared(pg_factory)
    password = secrets.token_urlsafe(32)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        actor.password_hash = hash_password(password)
        db.commit()
        plan = preview(db, actor, ResourceType.CATALOG_DEFINITION, catalog_id)
        assert not plan["can_delete"]
        assert any(item["code"] == "catalog_extraction_sessions" for item in plan["blockers"])
    decision = SourceReview(expected_version=state["version"], fingerprint=state["fingerprint"],
        inspection_token=receipt, reason="QA exact original reviewed while deletion was attempted")
    deletion = ExecuteRequest(current_password=password, confirmation_text=plan["confirmation_text"])
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1234)})
    outcomes = race(pg_factory, CatalogDefinition, catalog_id, [
        lambda db, actor: review.verify(db, actor, state["visual_page_id"], decision),
        lambda db, actor: execute(db, actor, ResourceType.CATALOG_DEFINITION, catalog_id, deletion, request),
    ], success_status=200)
    assert sorted(outcome.status for outcome in outcomes) == [200, 409]
    assert next(outcome.code for outcome in outcomes if outcome.status == 409) == "deletion_blocked"
    with pg_factory() as db:
        assert db.get(CatalogRevision, revision_id).status == "DRAFT"
        assert db.get(ledger.Source, state["id"]).review_state == "VERIFIED"


def test_unprocessed_selected_source_remains_blocker_in_migrated_postgres(pg_factory):
    page, _ = selected_source(pg_factory)
    with pg_factory() as db:
        revision_id = db.get(CatalogRevisionAssembly, page["assembly_id"]).revision_id
        result = publication.readiness(db, revision_id, locked=True)
        assert not result["ready"]
        assert any(issue["code"] == "catalog_publication_source_review_required" for issue in result["errors"])
        source = db.scalar(select(ledger.Source))
        source.processing_state = "FAILED"
        db.commit()
        assert not publication.readiness(db, revision_id)["ready"]


def test_cached_graph_cannot_hide_a_concurrent_edit_before_publication(pg_factory):
    from app.catalog_admin.parts import update_part
    from app.catalog_admin.schemas import PartUpdate
    from fastapi import HTTPException
    from test_catalog_publication_postgres import _setup
    _, revisions = _setup(pg_factory)
    revision_id, part_id = revisions[0]
    with pg_factory() as stale:
        revision = stale.get(CatalogRevision, revision_id)
        held_graph = publication.graph(stale, revision)
        held_sources = list(stale.scalars(select(ledger.Source)))
        old = publication.readiness(stale, revision_id)
        assert old["ready"]
        with pg_factory() as other:
            actor = other.scalar(select(User).where(User.is_system_owner.is_(True)))
            update_part(other, actor, part_id, PartUpdate(part_number="QA-CONCURRENT-EDIT"))
        actor = stale.scalar(select(User).where(User.is_system_owner.is_(True)))
        with pytest.raises(HTTPException) as raised:
            publication.publish(stale, actor, revision_id, old["publication_digest"], None, True)
        assert raised.value.status_code == 409
        stale.rollback()
        assert held_graph["parts"][0].part_number == "QA-CONCURRENT-EDIT"
        assert held_sources[0].review_state == "NEEDS_REVIEW"
        assert revision.status == "DRAFT"


def test_existing_postgres_upgrade_creates_ledger_constraints_without_backfill(pg_factory):
    from alembic import command
    from alembic.config import Config
    from app.models import Base, Machine, PartCatalog
    from sqlalchemy import func, inspect, text
    from sqlalchemy.exc import IntegrityError
    from test_concurrency import ROOT
    engine = pg_factory.kw["bind"]
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    tables = ("catalog_extraction_sessions", "catalog_extraction_sources", "catalog_extraction_attempts",
        "catalog_extraction_candidates", "catalog_source_review_decisions")
    with engine.begin() as connection:
        anchors = (connection.scalar(select(func.count()).select_from(Machine)),
            connection.scalar(select(func.count()).select_from(PartCatalog)))
        config.attributes["connection"] = connection
        command.downgrade(config, "20261009_0032")
        assert not set(tables) & set(inspect(connection).get_table_names())
        command.upgrade(config, "head")
        for table in tables:
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            assert {c["name"] for c in inspect(connection).get_columns(table)} == set(Base.metadata.tables[table].columns.keys())
        assert anchors == (connection.scalar(select(func.count()).select_from(Machine)),
            connection.scalar(select(func.count()).select_from(PartCatalog))) == (19, 611)
    selected_source(pg_factory)
    with pytest.raises(IntegrityError, match="ck_extraction_processing"):
        with engine.begin() as connection:
            connection.execute(text("UPDATE catalog_extraction_sources SET processing_state='INVALID'"))
