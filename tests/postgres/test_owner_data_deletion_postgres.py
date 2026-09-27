"""Actual PostgreSQL insert/delete overlap in a disposable migrated QA schema."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from app.governance import owner_data_deletion as service
from app.models import AssetCategory, AuditLog, Machine, Repair, User
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from test_concurrency import pg_factory as pg_factory

pytestmark = pytest.mark.postgres


def prepare(factory, kind):
    with factory() as db:
        owner_id = db.scalar(select(User.id).where(User.is_system_owner.is_(True)))
        if kind == service.ResourceType.ASSET_CATEGORY:
            item = AssetCategory(code="QA_DELETE_PG", name_bg="QA")
        else:
            item = Machine(inventory_number="QA-DELETE-PG", name="QA", category="QA", brand="QA")
        db.add(item)
        db.commit()
        identifier = item.id
        data = service.preview(db, db.get(User, owner_id), kind, identifier)
        assert data["can_delete"]
        return owner_id, identifier, data["confirmation_text"]


def insert_reference(db, kind, identifier):
    if kind == service.ResourceType.ASSET_CATEGORY:
        db.add(
            Machine(
                inventory_number="QA-PG-REFERENCE",
                name="QA",
                category="QA_DELETE_PG",
                brand="QA",
                category_id=identifier,
            )
        )
    else:
        db.add(Repair(machine_id=identifier, reported_problem="QA PostgreSQL overlap"))
    db.flush()


def execute(factory, owner_id, kind, identifier, phrase, pid, ready):
    with factory() as db:
        pid.append(db.scalar(text("SELECT pg_backend_pid()")))
        actor = db.get(User, owner_id)
        ready.set()
        request = Request(
            {
                "type": "http",
                "headers": [(b"x-request-id", b"owner-data-pg")],
                "client": ("127.0.0.1", 1234),
                "method": "POST",
                "path": "/api/owner/data-deletion",
            }
        )
        try:
            service.execute(
                db,
                actor,
                kind,
                identifier,
                service.ExecuteRequest(current_password="AssetCore123!", confirmation_text=phrase),
                request,
            )
            return 200, None
        except HTTPException as exc:
            return exc.status_code, exc.detail["code"]


def wait_for_lock(factory, pid):
    deadline = monotonic() + 10
    with factory() as db:
        while monotonic() < deadline:
            db.execute(text("SELECT pg_stat_clear_snapshot()"))
            if db.scalar(
                text(
                    "SELECT wait_event_type = 'Lock' AND cardinality(pg_blocking_pids(pid)) > 0 "
                    "FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": pid},
            ):
                return
            sleep(0.025)
    pytest.fail("Expected PostgreSQL transaction did not wait on a real lock")


@pytest.mark.parametrize(
    "kind", [service.ResourceType.ASSET_CATEGORY, service.ResourceType.MACHINE]
)
def test_reference_committing_after_preview_blocks_delete(pg_factory, kind):
    owner_id, identifier, phrase = prepare(pg_factory, kind)
    pid, ready = [], Event()
    with pg_factory() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        insert_reference(writer, kind, identifier)
        future = pool.submit(execute, pg_factory, owner_id, kind, identifier, phrase, pid, ready)
        try:
            assert ready.wait(10)
            wait_for_lock(pg_factory, pid[0])
        finally:
            writer.commit()
        assert future.result(timeout=30) == (409, "deletion_blocked")
    with pg_factory() as db:
        assert db.get(service.RESOURCE_MODELS[kind], identifier)
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "OWNER_PERMANENT_DELETE")
            )
            == 0
        )


@pytest.mark.parametrize(
    "kind", [service.ResourceType.ASSET_CATEGORY, service.ResourceType.MACHINE]
)
def test_writer_cannot_create_orphan_while_owner_deletes(pg_factory, kind, monkeypatch):
    owner_id, identifier, phrase = prepare(pg_factory, kind)
    locked, release, ready = Event(), Event(), Event()
    pid, writer_pid = [], []
    original = service._lock_dependencies

    def hold_lock(db, resource):
        original(db, resource)
        locked.set()
        assert release.wait(12)

    monkeypatch.setattr(service, "_lock_dependencies", hold_lock)

    def writer():
        with pg_factory() as db:
            writer_pid.append(db.scalar(text("SELECT pg_backend_pid()")))
            ready.set()
            try:
                insert_reference(db, kind, identifier)
                db.commit()
                return "unexpected_commit"
            except IntegrityError:
                db.rollback()
                return "fk_rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        delete_future = pool.submit(
            execute, pg_factory, owner_id, kind, identifier, phrase, pid, Event()
        )
        assert locked.wait(10)
        writer_future = pool.submit(writer)
        try:
            assert ready.wait(10)
            wait_for_lock(pg_factory, writer_pid[0])
        finally:
            release.set()
        assert delete_future.result(timeout=30) == (200, None)
        assert writer_future.result(timeout=30) == "fk_rejected"
    with pg_factory() as db:
        assert db.get(service.RESOURCE_MODELS[kind], identifier) is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "OWNER_PERMANENT_DELETE")
            )
            == 1
        )
