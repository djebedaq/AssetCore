"""Real migrations, constraints and overlapping transactions in disposable QA schemas."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from app.industrial_api import create_multi_part_request, link_unknown_part_to_catalog
from app.industrial_schemas import MultiPartRequestCreate, UnknownPartCatalogLink
from app.models import (
    AuditLog,
    PartCatalog,
    PartRequest,
    PartRequestLine,
    PartVisualArtifact,
    PartVisualOccurrence,
    PartVisualSnapshot,
    User,
)
from app.part_requests import visual_snapshots
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import DBAPIError
from test_concurrency import ROOT, race
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from visual_snapshot_cases import future_catalog, request_payload

pytestmark = pytest.mark.postgres


def _create(factory, data):
    with factory() as db:
        return create_multi_part_request(
            MultiPartRequestCreate.model_validate(request_payload(data)),
            db.get(User, data["actor_id"]),
            db,
        )


def test_pg_visual_migration_constraints_and_immutability(pg_factory):
    engine = pg_factory.kw["bind"]
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "20260826_0021")
        command.upgrade(config, "head")
    data = future_catalog(pg_factory)
    result = _create(pg_factory, data)
    with pg_factory() as db:
        snapshot = db.scalar(select(PartVisualSnapshot))
        snapshot_values = {
            c.name: getattr(snapshot, c.name) for c in snapshot.__table__.columns if c.name != "id"
        }
        occurrence = db.scalar(select(PartVisualOccurrence))
        occurrence_values = {
            c.name: getattr(occurrence, c.name)
            for c in occurrence.__table__.columns
            if c.name != "id"
        }
        assert snapshot.line_id == result["lines"][0]["id"]
    statements = [
        insert(PartVisualSnapshot).values(**snapshot_values),
        insert(PartVisualSnapshot).values(**{**snapshot_values, "line_id": 999999}),
        insert(PartVisualOccurrence).values(**occurrence_values),
        insert(PartVisualOccurrence).values(
            **{**occurrence_values, "ordinal": 5, "hotspot_id": 999999}
        ),
        insert(PartVisualArtifact).values(
            sha256=data["sha256"], content=data["content"], byte_length=len(data["content"])
        ),
        delete(PartRequestLine).where(PartRequestLine.id == snapshot_values["line_id"]),
        update(PartVisualSnapshot).values(source_id="QA overwritten"),
        update(PartVisualOccurrence).values(x=0.8),
        update(PartVisualArtifact).values(content=b"QA overwritten"),
        delete(PartVisualSnapshot),
        delete(PartVisualOccurrence),
        delete(PartVisualArtifact),
    ]
    for statement in statements:
        with pg_factory() as db:
            with pytest.raises(DBAPIError):
                db.execute(statement)
                db.commit()
    with pg_factory() as db:
        assert db.scalar(select(func.count()).select_from(PartVisualSnapshot)) == 1
        assert db.scalar(select(func.count()).select_from(PartVisualOccurrence)) == 4


def test_pg_concurrent_creations_share_one_artifact(pg_factory, monkeypatch):
    data = future_catalog(pg_factory)
    barrier = Barrier(2, timeout=20)
    original = visual_snapshots._source_artifact

    def synchronized_source(db, *args):
        if not db.info.get("qa_source_waited"):
            db.info["qa_source_waited"] = True
            barrier.wait()
        return original(db, *args)

    monkeypatch.setattr(visual_snapshots, "_source_artifact", synchronized_source)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_create, pg_factory, data) for _ in range(2)]
        results = [future.result(timeout=50) for future in futures]
    assert results[0]["id"] != results[1]["id"]
    with pg_factory() as db:
        assert db.scalar(select(func.count()).select_from(PartVisualSnapshot)) == 2
        assert db.scalar(select(func.count()).select_from(PartVisualArtifact)) == 1
        assert db.scalar(select(func.count()).select_from(PartVisualOccurrence)) == 8


def test_pg_concurrent_unknown_links_have_one_authoritative_binding(pg_factory):
    data = future_catalog(pg_factory)
    with pg_factory() as db:
        other = PartCatalog(
            brand="QA competing",
            part_number="QA competing",
            description="QA competing",
            is_verified=True,
            verification_status="VERIFIED_QA",
            compatible_machine_numbers=["QA-FUTURE-9001"],
        )
        request = PartRequest(machine_id=data["machine_id"], part_name="QA unknown")
        db.add_all([request, other])
        db.flush()
        line = PartRequestLine(
            request_id=request.id,
            description="QA original unknown",
            quantity=1,
            is_unknown_part=True,
            assembly="QA original assembly",
        )
        db.add(line)
        db.commit()
        request_id, line_id, other_id = request.id, line.id, other.id
    operations = [
        lambda db, actor, part_id=part_id: link_unknown_part_to_catalog(
            request_id,
            line_id,
            UnknownPartCatalogLink(catalog_part_id=part_id),
            actor,
            db,
        )
        for part_id in (data["part_id"], other_id)
    ]
    outcomes = race(pg_factory, PartRequest, request_id, operations, success_status=200)
    assert (
        next(item for item in outcomes if item.status == 409).code == "unknown_part_already_linked"
    )
    with pg_factory() as db:
        line = db.get(PartRequestLine, line_id)
        snapshot = db.scalar(select(PartVisualSnapshot))
        assert snapshot.catalog_part_id == line.linked_catalog_part_id
        assert snapshot.captured_at == line.linked_at
        assert snapshot.capture_origin == "CATALOG_LINK"
        assert line.description == "QA original unknown"
        assert db.scalar(select(func.count()).select_from(PartVisualSnapshot)) == 1
        repeated = link_unknown_part_to_catalog(
            request_id,
            line_id,
            UnknownPartCatalogLink(catalog_part_id=line.linked_catalog_part_id),
            db.get(User, data["actor_id"]),
            db,
        )
        assert repeated["lines"][0]["visual_reference"]["snapshot"]["id"] == snapshot.id


@pytest.mark.parametrize("link", [False, True])
def test_pg_snapshot_failure_rolls_back_request_or_link(pg_factory, monkeypatch, link):
    data = future_catalog(pg_factory)
    with pg_factory() as db:
        if link:
            request = PartRequest(machine_id=data["machine_id"], part_name="QA unknown")
            db.add(request)
            db.flush()
            line = PartRequestLine(
                request_id=request.id, description="QA original", quantity=1, is_unknown_part=True
            )
            db.add(line)
            db.commit()
            request_id, line_id = request.id, line.id
        counts = tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (PartRequest, PartRequestLine, AuditLog)
        )
    original = visual_snapshots._occurrences

    def failure(db, part):
        original(db, part)
        raise RuntimeError("QA failure after source persistence")

    monkeypatch.setattr(visual_snapshots, "_occurrences", failure)
    with pytest.raises(RuntimeError, match="QA failure"):
        if link:
            with pg_factory() as db:
                link_unknown_part_to_catalog(
                    request_id,
                    line_id,
                    UnknownPartCatalogLink(catalog_part_id=data["part_id"]),
                    db.get(User, data["actor_id"]),
                    db,
                )
        else:
            _create(pg_factory, data)
    with pg_factory() as db:
        assert counts == tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (PartRequest, PartRequestLine, AuditLog)
        )
        for model in (PartVisualSnapshot, PartVisualOccurrence, PartVisualArtifact):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        if link:
            assert db.get(PartRequestLine, line_id).linked_catalog_part_id is None
