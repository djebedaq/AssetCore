from __future__ import annotations

import json
from datetime import timedelta

import pytest
from app.assets.timeline import machine_timeline
from app.assets.timeline_schemas import TimelineCategory
from app.models import (
    MachineEvent,
    OfficialDocumentVersion,
    RepairPart,
    User,
)
from app.permissions import Permission
from sqlalchemy import event
from test_bulk_transfers import issue, perform_return, return_payload
from timeline_scenarios import (
    AT,
    actor_and_machines,
    approval,
    fingerprint,
    legacy,
    machine_event,
    official,
    parity_scenario,
    persist,
    repair,
    repair_event,
    request,
    transfer,
    transition,
)


@pytest.fixture()
def context(session_factory):
    with session_factory() as db:
        actor, machines = actor_and_machines(db)
        yield db, actor, machines["4"]


def read(context, **kwargs):
    db, actor, machine_id = context
    db.commit()  # Fixture mutations belong to the test, never the read service.
    return machine_timeline(db, machine_id=machine_id, user=actor, **kwargs)


def api(client, headers, machine_id, suffix=""):
    result = client.get(f"/api/machines/{machine_id}/timeline{suffix}", headers=headers)
    assert result.status_code == 200
    return result.json()


def test_unknown_empty_and_auth_contract(client, auth_headers, machine_ids):
    assert client.get("/api/machines/999999/timeline", headers=auth_headers).status_code == 404
    assert client.get(f"/api/machines/{machine_ids['4']}/timeline").status_code == 401
    result = api(client, auth_headers, machine_ids["4"])
    assert result == dict(
        machine_id=machine_ids["4"],
        limited_view=False,
        category="all",
        total=0,
        count=0,
        page=1,
        page_size=50,
        total_pages=0,
        has_previous=False,
        has_next=False,
        items=[],
    )


@pytest.mark.parametrize(
    "query", ["page=0", "page_size=0", "page_size=101", "category=invalid", "page=text"]
)
def test_invalid_pagination_category_returns_422(client, auth_headers, machine_ids, query):
    result = client.get(f"/api/machines/{machine_ids['4']}/timeline?{query}", headers=auth_headers)
    assert result.status_code == 422


@pytest.mark.parametrize("role", ["administrator", "director", "mechanic"])
def test_existing_operational_roles_can_read(context, role):
    db, _, machine_id = context
    machine_event(db, machine_id, "MACHINE_CREATED")
    db.commit()
    assert machine_timeline(db, machine_id=machine_id, user=User(role=role)).total == 1


def test_route_uses_existing_assets_view_permission():
    from app.main import app

    route = next(
        r for r in app.routes if getattr(r, "path", None) == "/api/machines/{machine_id}/timeline"
    )
    assert route.methods == {"GET"}
    dependencies = [d.call for d in route.dependant.dependencies]
    assert [getattr(d, "__assetcore_permission__", None) for d in dependencies].count(
        Permission.ASSETS_VIEW.value
    ) == 1


def test_asset_facts_and_allowlisted_metadata(context):
    db, _, machine_id = context
    record = machine_event(
        db,
        machine_id,
        "MACHINE_UPDATED",
        reference="QA-ASSET",
        previous_status="READY",
        new_status="READY",
        previous_location_id=1,
        new_location_id=2,
        details={
            "changed_fields": ["name", "status", "token", {"private": "hidden"}],
            "password": "do-not-return",
            "nested": {"payload": "hidden"},
        },
    )
    item = read(context).items[0]
    assert item.event_key == f"machine_event:{record.id}"
    assert item.occurred_at == AT and item.reference == "QA-ASSET"
    assert item.status_before == item.status_after == "READY"
    assert item.details == {
        "changed_fields": ["name", "status"],
        "previous_location_id": 1,
        "new_location_id": 2,
    }


@pytest.mark.parametrize(
    "return_status,returned_at,active,expected",
    [
        (None, None, True, ["TRANSFER_ISSUED"]),
        ("AWAITING_SIGNATURE", None, True, ["TRANSFER_RETURN_REQUESTED", "TRANSFER_ISSUED"]),
        (
            "COMPLETED",
            AT + timedelta(days=1),
            False,
            ["TRANSFER_RETURNED", "TRANSFER_RETURN_REQUESTED", "TRANSFER_ISSUED"],
        ),
        ("CANCELLED", None, True, ["TRANSFER_ISSUED"]),
        (None, AT + timedelta(days=1), False, ["TRANSFER_ISSUED"]),
    ],
)
def test_transfer_authoritative_milestones_not_inactivity_or_document(
    context, return_status, returned_at, active, expected
):
    db, actor, machine_id = context
    t = transfer(
        db,
        machine_id,
        return_status=return_status,
        returned_at=returned_at,
        is_active=active,
        return_requested_at=AT if return_status in {"AWAITING_SIGNATURE", "COMPLETED"} else None,
        return_next_status="REPAIR",
        return_previous_status="ISSUED",
        return_notes="Recorded return note",
    )
    machine_event(db, machine_id, "TRANSFER_ISSUED", details={"transfer_id": t.id})
    if return_status in {"COMPLETED", "AWAITING_SIGNATURE", "CANCELLED"}:
        machine_event(db, machine_id, "TRANSFER_RETURNED", details={"transfer_id": t.id})
    official(db, actor.id, machine_id, "QA-RETURN-DOC", "TRANSFER_RETURN", transfer_id=t.id)
    result = read(context, category=TimelineCategory.TRANSFER)
    assert [i.event_type for i in result.items] == expected
    assert all(i.reference == t.protocol_number for i in result.items)  # No invented -R number.
    assert all(i.related.transfer_id == t.id for i in result.items)
    if returned_at is not None and return_status == "COMPLETED":
        assert result.items[0].status_after == "REPAIR"
        assert result.items[0].occurred_at == returned_at


def test_pending_issue_is_not_an_issue_and_historical_machine_fallback_is_retained(context):
    db, _, machine_id = context
    t = transfer(db, machine_id, issued_at=None, issue_status="AWAITING_SIGNATURE")
    machine_event(db, machine_id, "TRANSFER_ISSUED", details={"transfer_id": t.id})
    historical = machine_event(db, machine_id, "TRANSFER_ISSUED", reference="LEGACY-ONLY")
    result = read(context, category=TimelineCategory.TRANSFER)
    assert [i.event_key for i in result.items] == [f"machine_event:{historical.id}"]


def test_repair_events_precedence_machine_duplicates_and_sanitized_details(context):
    db, actor, machine_id = context
    r = repair(db, machine_id, status="COMPLETED", closed_at=AT)
    events = [
        repair_event(
            db,
            r.id,
            actor.id,
            code,
            status_before="ACCEPTED" if code != "ACCEPTED" else None,
            status_after="COMPLETED" if code == "COMPLETED" else "ACCEPTED",
            description=f"Recorded {code}",
            structured_data={
                "diagnosis_minutes": 20,
                "test_passed": True,
                "snapshot": {"hidden": "never"},
                "signing_token": "never",
            },
        )
        for code in (
            "ACCEPTED",
            "INSPECTION",
            "CLEANING",
            "DIAGNOSIS",
            "APPROVAL",
            "PARTS",
            "REPAIR_ACTION",
            "TEST",
            "STATUS_CHANGE",
            "COMPLETED",
            "NOTE",
        )
    ]
    machine_event(db, machine_id, "REPAIR_ACCEPTED", details={"repair_id": r.id})
    machine_event(
        db,
        machine_id,
        "REPAIR_STATUS_CHANGED",
        new_status="READY",
        details={"repair_id": r.id, "repair_status": "COMPLETED"},
    )
    machine_event(
        db,
        machine_id,
        "REPAIR_EVENT",
        reference=r.repair_reference,
        details={"event_type": "COMPLETED"},
    )
    result = read(context)
    assert {i.event_key for i in result.items} == {f"repair_event:{e.id}" for e in events}
    assert all(
        i.related.repair_id == r.id and i.reference == r.repair_reference for i in result.items
    )
    assert all(i.description.startswith("Recorded ") for i in result.items)
    assert "never" not in result.model_dump_json()


@pytest.mark.parametrize("canonical_open", [None, "ACCEPTED", "RETURN_DIRECTED_TO_REPAIR"])
def test_repair_timestamp_fallback_only_for_missing_canonical_event(context, canonical_open):
    db, actor, machine_id = context
    r = repair(db, machine_id, status="COMPLETED", closed_at=AT + timedelta(hours=1))
    if canonical_open:
        repair_event(db, r.id, actor.id, canonical_open)
    result = read(context)
    assert [i.event_type for i in result.items] == [
        "REPAIR_COMPLETED",
        canonical_open or "REPAIR_OPENED",
    ]


def test_missing_completion_state_does_not_invent_repair_completion(context):
    db, _, machine_id = context
    repair(db, machine_id, status="REPAIRING", closed_at=AT)
    assert [i.event_type for i in read(context).items] == ["REPAIR_OPENED"]


def test_used_parts_exact_one_to_one_dedup_and_fallback(context):
    db, actor, machine_id = context
    r = repair(db, machine_id)
    values = dict(
        repair_id=r.id,
        catalog_part_id=None,
        part_number="QA-PART",
        quantity=2,
        unit="бр.",
        source="Test-only source",
        description="Operational description",
        created_by_id=actor.id,
        created_at=AT,
    )
    first = persist(db, RepairPart, **values)
    second = persist(db, RepairPart, **values)
    event_row = repair_event(
        db,
        r.id,
        actor.id,
        "PART_ADDED",
        description=first.description,
        structured_data={
            "catalog_part_id": None,
            "part_number": "QA-PART",
            "quantity": 2,
            "unit": "бр.",
            "source": "Test-only source",
        },
    )
    result = read(context, category=TimelineCategory.PARTS)
    assert {i.event_key for i in result.items} == {
        f"repair_part:{second.id}:used",
        f"repair_event:{event_row.id}",
    }
    assert all(
        i.details["quantity"] == 2 and i.details["part_number"] == "QA-PART" for i in result.items
    )


def test_request_milestones_approval_history_and_narrow_audit_fallback(context):
    db, actor, machine_id = context
    r = request(db, machine_id, status="CANCELLED", submitted_at=AT, ordered_at=AT, delivered_at=AT)
    for decision in ("APPROVED", "REJECTED", "RETURNED_FOR_CHANGES", "APPROVED"):
        approval(db, r.id, actor.id, decision, note=f"Recorded {decision}")
    transition(db, r.id, "ORDERED", "PARTIALLY_DELIVERED")
    transition(db, r.id, "PARTIALLY_DELIVERED", "CANCELLED")
    for previous, new in (
        ("DRAFT", "WAITING_APPROVAL"),
        ("WAITING_APPROVAL", "APPROVED"),
        ("APPROVED", "ORDERED"),
        ("PARTIALLY_DELIVERED", "DELIVERED"),
    ):
        transition(db, r.id, previous, new)  # Explicit timestamps/approval win.
    transition(db, r.id, "ORDERED", "CANCELLED", entity_type="user")
    transition(db, r.id, "ORDERED", "CANCELLED", action="Rejected unrelated operation")
    transition(db, r.id, "ORDERED", "CANCELLED", details="not-json")
    transition(db, r.id, "ORDERED", "CANCELLED", details=json.dumps({"new_status": "CANCELLED"}))
    transition(
        db,
        r.id,
        "ORDERED",
        "CANCELLED",
        details=json.dumps({"new_status": {}, "previous_status": []}),
    )
    result = read(context)
    types = [i.event_type for i in result.items]
    assert len(types) == 10 and len({i.event_key for i in result.items}) == 10
    assert types.count("PART_REQUEST_APPROVED") == 2
    for code in (
        "CREATED",
        "SUBMITTED",
        "ORDERED",
        "DELIVERED",
        "REJECTED",
        "RETURNED_FOR_CHANGES",
        "PARTIALLY_DELIVERED",
        "CANCELLED",
    ):
        assert types.count(f"PART_REQUEST_{code}") == 1
    assert all(i.related.part_request_id == r.id for i in result.items)


def test_request_without_history_does_not_guess_decision_or_cancellation_time(context):
    db, _, machine_id = context
    request(db, machine_id, status="CANCELLED", decided_at=AT)
    assert [i.event_type for i in read(context).items] == ["PART_REQUEST_CREATED"]


def test_null_machine_request_uses_exact_repair_link_including_documents(context):
    db, actor, machine_id = context
    r = repair(db, machine_id)
    req = request(db, None, repair_id=r.id)
    doc = official(
        db,
        actor.id,
        None,
        "QA-REPAIR-LINKED-REQUEST",
        "PART_REQUEST",
        snapshot={"request_id": req.id},
    )
    legacy(db, actor.id, None, doc.document_number, "PART_REQUEST", part_request_id=req.id)
    result = read(context)
    assert {
        i.related.part_request_id for i in result.items if i.category == TimelineCategory.PARTS
    } == {req.id}
    docs = [i for i in result.items if i.category == TimelineCategory.DOCUMENT]
    assert len(docs) == 1 and docs[0].related.official_document_id == doc.id


def test_documents_current_version_exact_finalization_time_and_legacy_fallback(context):
    db, actor, machine_id = context
    r = repair(db, machine_id)
    doc = official(
        db,
        actor.id,
        None,
        "QA-CANONICAL",
        "REPAIR_PROTOCOL",
        snapshot={"repair_id": r.id, "secret": "must-not-serialize"},
        version_number=2,
        finalized_at=AT + timedelta(days=1),
    )
    legacy(db, actor.id, machine_id, "QA-OLDER-REPAIR", "REPAIR_PROTOCOL", repair_id=r.id)
    historical = legacy(db, actor.id, machine_id, "QA-LEGACY-ONLY", "PART_REQUEST")
    draft = official(db, actor.id, machine_id, "QA-DRAFT", "PART_REQUEST", finalized_at=None)
    result = read(context, category=TimelineCategory.DOCUMENT)
    assert len(result.items) == 3
    assert result.items[0].event_key == f"official_document:{doc.id}:v2"
    assert result.items[0].event_type == "OFFICIAL_DOCUMENT_FINALIZED"
    assert result.items[0].occurred_at == AT + timedelta(days=1)
    assert {i.event_key for i in result.items} == {
        f"official_document:{doc.id}:v2",
        f"official_document:{draft.id}:v1",
        f"generated_document:{historical[-1].id}",
    }
    assert "must-not-serialize" not in result.model_dump_json()


def test_sqlite_parity_exact_scope_order_pagination_and_read_only(session_factory):
    with session_factory() as db:
        actor, expected = parity_scenario(db)
        target = expected["4"]
        before = fingerprint(db)
        page = machine_timeline(db, machine_id=target["machine_id"], user=actor, page_size=5)
        second = machine_timeline(
            db, machine_id=target["machine_id"], user=actor, page_size=5, page=2
        )
        third = machine_timeline(
            db, machine_id=target["machine_id"], user=actor, page_size=5, page=3
        )
        assert page.total == 12 and page.count == 5 and page.total_pages == 3
        assert not page.has_previous and page.has_next
        assert second.has_previous and second.has_next
        assert third.count == 2 and third.has_previous and not third.has_next
        items = page.items + second.items + third.items
        assert [i.event_key for i in items] == target["keys"]
        assert len({i.event_key for i in items}) == len(items)
        assert all(i.machine_id == target["machine_id"] for i in items)
        assert (
            "MACHINE-14"
            not in page.model_dump_json() + second.model_dump_json() + third.model_dump_json()
        )
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
            assert filtered.total == count and filtered.count == min(count, 2)
            assert all(i.category.value == category for i in filtered.items)
        repeated = machine_timeline(db, machine_id=target["machine_id"], user=actor, page_size=5)
        assert repeated == page
        high = machine_timeline(db, machine_id=target["machine_id"], user=actor, page=100)
        assert high.total == 12 and high.items == [] and not high.has_next
        assert fingerprint(db) == before
        assert not db.new and not db.dirty and not db.deleted


def test_observer_zero_history_counts_and_no_sensitive_queries(
    session_factory, client, viewer_headers
):
    with session_factory() as db:
        _, expected = parity_scenario(db)
    engine = session_factory.kw["bind"]
    sql = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = api(client, viewer_headers, expected["4"]["machine_id"])
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["limited_view"] and result["items"] == []
    assert result["total"] == result["count"] == result["total_pages"] == 0
    assert not result["has_next"] and not result["has_previous"]
    for table in (
        "machine_events",
        "transfer_protocols",
        "repairs",
        "repair_events",
        "part_requests",
        "audit_logs",
        "official_document",
        "generated_document",
        "document_signatures",
    ):
        assert not any(table in statement for statement in sql)


def test_metadata_reads_are_bounded_and_never_hydrate_binary_or_signatures(session_factory):
    with session_factory() as db:
        actor, expected = parity_scenario(db)
        machine_id = expected["4"]["machine_id"]
        engine = session_factory.kw["bind"]

        def collect():
            statements = []

            def capture(conn, cursor, sql, parameters, context, executemany):
                statements.append(sql.lower())

            event.listen(engine, "before_cursor_execute", capture)
            try:
                machine_timeline(db, machine_id=machine_id, user=actor)
            finally:
                event.remove(engine, "before_cursor_execute", capture)
            return statements

        first = collect()
        for index in range(30):
            r = repair(db, machine_id, repair_reference=f"QA-SCALE-{index}")
            repair_event(db, r.id, actor.id, "ACCEPTED")
            official(
                db,
                actor.id,
                None,
                f"QA-SCALE-DOC-{index}",
                "REPAIR_PROTOCOL",
                snapshot={"repair_id": r.id},
            )
        db.commit()
        second = collect()
        assert len(first) == len(second) and len(second) <= 27
        for sql in second:
            assert sql.lstrip().startswith("select")
            assert not any(
                name in sql
                for name in (
                    "pdf_content",
                    "docx_content",
                    "document_signatures",
                    "signature_sessions",
                    "document_participants",
                    "generated_documents.content",
                    "protocol_documents.content",
                )
            )


@pytest.mark.parametrize(
    "private",
    [
        "data:image/png;base64,AA",
        "C:\\private\\file.pdf",
        "/app/private/file.pdf",
        "token=not-a-real-token",
        "A" * 200,
    ],
)
def test_private_payloads_in_description_or_allowed_fields_are_not_exposed(context, private):
    db, actor, machine_id = context
    r = repair(db, machine_id)
    repair_event(
        db,
        r.id,
        actor.id,
        "PART_ADDED",
        description=private,
        structured_data={
            "source": private,
            "signature_image": private,
            "quantity": 2,
            "part_number": {"nested": private},
        },
    )
    result = read(context, category=TimelineCategory.PARTS)
    assert result.count == 1
    assert result.items[0].description is None
    assert result.items[0].details["source"] is None
    assert result.items[0].details["quantity"] == 2
    assert private not in result.model_dump_json()


def test_existing_issue_return_writers_produce_single_timeline_milestones(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    issued = issue(client, auth_headers, issue_payload(machine_ids["4"]))
    assert issued.status_code == 201
    pending = perform_return(
        client, auth_headers, return_payload(issued.json()["transfers"][0]), sign=False
    )
    assert pending.status_code == 200
    before = api(client, auth_headers, machine_ids["4"], "?category=transfer")
    assert [i["event_type"] for i in before["items"]] == [
        "TRANSFER_RETURN_REQUESTED",
        "TRANSFER_ISSUED",
    ]
    from test_bulk_transfers import complete_signing

    complete_signing(client, pending)
    with session_factory() as db:
        before_read = fingerprint(db)
    after = api(client, auth_headers, machine_ids["4"])
    codes = [i["event_type"] for i in after["items"]]
    assert codes.count("TRANSFER_ISSUED") == codes.count("TRANSFER_RETURNED") == 1
    assert codes.count("TRANSFER_RETURN_REQUESTED") == 1
    assert len([i for i in after["items"] if i["category"] == "document"]) == 2
    with session_factory() as db:
        assert fingerprint(db) == before_read


def test_read_service_never_autoflushes_caller_pending_changes(context):
    db, actor, machine_id = context
    db.commit()
    db.autoflush = True
    pending = MachineEvent(machine_id=machine_id, event_type="MACHINE_CREATED", created_at=AT)
    db.add(pending)

    def forbidden_flush(*args):
        raise AssertionError("Timeline attempted an autoflush")

    event.listen(db, "before_flush", forbidden_flush)
    try:
        assert machine_timeline(db, machine_id=machine_id, user=actor).total == 0
        assert pending in db.new
    finally:
        event.remove(db, "before_flush", forbidden_flush)


def test_only_current_document_version_is_loaded(context):
    db, actor, machine_id = context
    doc = official(db, actor.id, machine_id, "QA-VERSIONED", "PART_REQUEST", version_number=2)
    current = db.get(OfficialDocumentVersion, doc.current_version_id)
    persist(
        db,
        OfficialDocumentVersion,
        document_id=doc.id,
        version=1,
        status="SUPERSEDED",
        snapshot={"secret": "old"},
        snapshot_sha256="a" * 64,
        prepared_by_id=actor.id,
        created_at=AT - timedelta(days=1),
    )
    result = read(context, category=TimelineCategory.DOCUMENT)
    assert [i.event_key for i in result.items] == [f"official_document:{doc.id}:v2"]
    assert current.version == 2


@pytest.mark.parametrize(
    "code",
    [
        "MACHINE_CREATED",
        "CUSTOM_FIELDS_UPDATED",
        "ATTACHMENT_ADDED",
        "IMPORTED",
        "LOCATION_CHANGED",
    ],
)
def test_asset_families_stay_real_and_do_not_serialize_arbitrary_values(context, code):
    db, _, machine_id = context
    machine_event(
        db,
        machine_id,
        code,
        details={
            "field_ids": [1, 2, True, "private"],
            "previous": {"hidden": "never"},
            "new": {"hidden": "never"},
            "source": "admin_import",
            "filename": "maintenance.jpg",
            "kind": "PHOTO",
        },
    )
    result = read(context, category=TimelineCategory.ASSET)
    assert [i.event_type for i in result.items] == [code]
    assert "never" not in result.model_dump_json() and "private" not in result.model_dump_json()
    if code == "CUSTOM_FIELDS_UPDATED":
        assert result.items[0].details["field_ids"] == [1, 2]


def test_unknown_or_unlinked_history_does_not_leak_through_document_text(context):
    db, actor, machine_id = context
    machine_event(db, machine_id, "AUTH_LOGIN", details={"password": "not-visible"})
    official(
        db,
        actor.id,
        None,
        "CONTAINS-MACHINE-4",
        "REPAIR_PROTOCOL",
        snapshot={"description": "machine 4", "repair_id": True},
    )
    official(
        db,
        actor.id,
        None,
        "PARTS-CONTAINS-MACHINE-4",
        "PART_REQUEST",
        snapshot={"machine_number": "4", "request_id": "not-an-id"},
    )
    assert read(context).total == 0
