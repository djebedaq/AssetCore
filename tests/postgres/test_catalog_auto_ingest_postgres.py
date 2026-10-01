"""Migrated PostgreSQL: actual extraction, competing starts/reviews, rollback."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.catalog_admin import visual_sources
from app.catalog_admin.ingest import review, runs
from app.catalog_admin.ingest.schemas import BulkItem, BulkReview, CandidateReview
from app.models import (
    CatalogIngestCandidate,
    CatalogIngestRun,
    CatalogSourceBlob,
    User,
)
from catalog_ingest_fixtures import manual
from fastapi import HTTPException
from sqlalchemy import func, select
from test_catalog_builder_parts_postgres import setup
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def create_source(factory):
    assembly_id, _ = setup(factory)
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        artifact = visual_sources.store_artifact(db, actor, assembly_id, manual(), "qa-auto.pdf", "QA source")
    return artifact


def test_postgres_competing_analysis_identity_and_optimistic_review(pg_factory):
    artifact = create_source(pg_factory)
    barrier = Barrier(2)
    def start():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait(timeout=10)
            return runs.start(db, actor, artifact["id"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: start(), range(2)))
    assert results[0]["id"] == results[1]["id"]
    run_id = results[0]["id"]
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        while runs.load_run(db, run_id).status == "RUNNING":
            result = runs.advance(db, actor, run_id)
        assert result["status"] == "COMPLETED", result
        group = db.scalar(select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run_id,
            CatalogIngestCandidate.kind == "GROUP"))
        candidate_id, version = group.id, group.version
    barrier = Barrier(2)
    def accept():
        with pg_factory() as db:
            actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            barrier.wait(timeout=10)
            try:
                review.review_one(db, actor, run_id, candidate_id, CandidateReview(action="ACCEPT", expected_version=version))
                return 200
            except HTTPException as exc:
                db.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: accept(), range(2))) == [200, 409]
    with pg_factory() as db:
        assert db.scalar(select(func.count(CatalogIngestRun.id))) == 1
        assert db.get(CatalogIngestCandidate, candidate_id).version == version + 1
        assert db.scalar(select(func.count(CatalogSourceBlob.id)).where(CatalogSourceBlob.sha256 == artifact["sha256"])) == 1


def test_postgres_review_batch_rolls_back_unmapped_parts(pg_factory):
    artifact = create_source(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        run = runs.start(db, actor, artifact["id"])
        while run["status"] == "RUNNING":
            run = runs.advance(db, actor, run["id"])
        assert run["status"] == "COMPLETED"
        rows = db.scalars(select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run["id"],
            CatalogIngestCandidate.kind.in_(["GROUP", "PART"]))).all()
        ids = [row.id for row in rows]
        with pytest.raises(HTTPException):
            review.bulk(db, actor, run["id"], BulkReview(action="ACCEPT",
                items=[BulkItem(id=row.id, expected_version=row.version) for row in rows]))
        db.rollback()
        assert all(row.state != "ACCEPTED" for row in db.scalars(select(CatalogIngestCandidate).where(
            CatalogIngestCandidate.id.in_(ids))).all())


def test_postgres_lease_prevents_two_page_workers(pg_factory, monkeypatch):
    artifact = create_source(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        run = runs.start(db, actor, artifact["id"])
        from datetime import timedelta

        from app.models import utcnow
        job = db.get(CatalogIngestRun, run["id"])
        job.claim_token, job.claim_expires_at = "QA lease", utcnow() + timedelta(minutes=2)
        db.commit()
        def unexpected(*args, **kwargs):
            pytest.fail("A second lease holder must never start extraction")
        monkeypatch.setattr(runs.process, "extract", unexpected)
        result = runs.advance(db, actor, run["id"])
        assert result["processed_pages"] == 0
        assert db.scalar(select(func.count(CatalogIngestCandidate.id))) == 0
