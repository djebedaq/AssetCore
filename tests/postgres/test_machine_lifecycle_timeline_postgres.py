"""Real PostgreSQL parity for ASSET-03A; reuse the migrated disposable schema."""

from datetime import timedelta

import pytest
from app.assets.timeline import machine_timeline
from app.assets.timeline_schemas import TimelineCategory
from app.models import TransferProtocol
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from timeline_scenarios import AT, fingerprint, parity_scenario

pytestmark = pytest.mark.postgres


def test_asset03a_timeline_exact_scope_chronology_pagination_and_read_only_on_postgres(pg_factory):  # noqa: F811
    with pg_factory() as db:
        assert db.bind.dialect.name == "postgresql"
        actor, expected = parity_scenario(db)
        target = expected["4"]
        before = fingerprint(db)
        pages = [
            machine_timeline(
                db, machine_id=target["machine_id"], user=actor, page=page, page_size=5
            )
            for page in (1, 2, 3)
        ]
        assert [p.count for p in pages] == [5, 5, 2]
        assert all(p.total == 12 and p.total_pages == 3 for p in pages)
        assert [(p.has_previous, p.has_next) for p in pages] == [
            (False, True),
            (True, True),
            (True, False),
        ]
        items = [item for page in pages for item in page.items]
        assert [i.event_key for i in items] == target[
            "keys"
        ]  # Same explicit SQLite expected chronology.
        assert len({i.event_key for i in items}) == 12
        assert all(i.machine_id == target["machine_id"] for i in items)
        assert "MACHINE-14" not in "".join(p.model_dump_json() for p in pages)
        assert {
            i.related.official_document_id for i in items if i.category == TimelineCategory.DOCUMENT
        } == set(target["official_ids"])
        assert all(
            i.source_type == "official_document"
            for i in items
            if i.category == TimelineCategory.DOCUMENT
        )
        assert [i.event_type for i in items if i.category == TimelineCategory.TRANSFER] == [
            "TRANSFER_ISSUED"
        ]
        assert [i.event_type for i in items if i.category == TimelineCategory.REPAIR] == [
            "ACCEPTED"
        ]
        assert {i.event_type for i in items if i.category == TimelineCategory.PARTS} == {
            "PART_USED",
            "PART_REQUEST_CREATED",
            "PART_REQUEST_SUBMITTED",
            "PART_REQUEST_APPROVED",
            "PART_REQUEST_ORDERED",
            "PART_REQUEST_PARTIALLY_DELIVERED",
        }
        for category, count in (
            ("asset", 1),
            ("transfer", 1),
            ("repair", 1),
            ("parts", 6),
            ("document", 3),
        ):
            filtered = machine_timeline(
                db,
                machine_id=target["machine_id"],
                user=actor,
                category=TimelineCategory(category),
                page_size=2,
            )
            assert filtered.total == count and filtered.count == min(2, count)
        assert (
            machine_timeline(db, machine_id=target["machine_id"], user=actor, page_size=5)
            == pages[0]
        )
        assert (
            machine_timeline(db, machine_id=target["machine_id"], user=actor, page=100).items == []
        )
        db.expire_all()
        assert fingerprint(db) == before
        assert not db.new and not db.dirty and not db.deleted

        # A second committed fixture state proves real issue/request/return
        # ordering, not just an issue-only lifecycle. The GET remains read-only.
        movement = db.get(TransferProtocol, target["transfer_id"])
        movement.is_active = False
        movement.return_status = "COMPLETED"
        movement.return_requested_at = AT + timedelta(hours=1)
        movement.returned_at = AT + timedelta(hours=2)
        movement.return_previous_status = "ISSUED"
        movement.return_next_status = "REPAIR"
        db.commit()
        completed_before = fingerprint(db)
        completed = machine_timeline(
            db, machine_id=target["machine_id"], user=actor, category=TimelineCategory.TRANSFER
        )
        assert [i.event_type for i in completed.items] == [
            "TRANSFER_RETURNED",
            "TRANSFER_RETURN_REQUESTED",
            "TRANSFER_ISSUED",
        ]
        assert [i.occurred_at for i in completed.items] == [
            AT + timedelta(hours=2),
            AT + timedelta(hours=1),
            AT - timedelta(days=1),
        ]
        assert completed.items[0].status_after == "REPAIR"
        assert completed.total == completed.count == 3
        assert fingerprint(db) == completed_before
        assert not db.new and not db.dirty and not db.deleted
