"""UX-01 read contracts; every added record is an isolated pytest fixture."""

from datetime import datetime, timedelta

from app.models import (
    AssetCategory,
    Machine,
    MachineEvent,
    PartRequest,
    PartRequestApproval,
    PartRequestLine,
    Repair,
    RepairEvent,
    TransferBatch,
    TransferProtocol,
)
from sqlalchemy import select


def get(client, headers, path):
    response = client.get("/api" + path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def qa_category(db, code, capabilities):
    category = AssetCategory(
        code=code,
        name_bg=f"QA {code}",
        name_en=f"QA {code}",
        name_ru=f"QA {code}",
        capabilities=capabilities,
    )
    db.add(category)
    db.flush()
    return category


def test_dynamic_dashboard_counts_and_capability_navigation(client, auth_headers, session_factory):
    before = get(client, auth_headers, "/dashboard")
    with session_factory() as db:
        category = qa_category(db, "QA_UX_CATEGORY", ["HAS_REPAIR_WORKFLOW"])
        category_id = category.id
        machine = db.scalar(select(Machine).order_by(Machine.id))
        machine.category_id = category.id
        machine.category = category.code
        machine.is_active = False
        db.commit()
    dashboard = get(client, auth_headers, "/dashboard")
    assert dashboard["total_machines"] == before["total_machines"]
    assert (
        sum(item["asset_count"] for item in dashboard["categories"])
        + dashboard["uncategorized_assets"]
        == dashboard["total_machines"]
    )
    assert (
        next(item for item in dashboard["categories"] if item["id"] == category_id)["asset_count"]
        == 1
    )
    assert category_id in {
        item["id"] for item in get(client, auth_headers, "/workspace/categories?module=repairs")
    }
    assert category_id not in {
        item["id"] for item in get(client, auth_headers, "/workspace/categories?module=transfers")
    }
    denied = client.get(f"/api/workspace/batches?category_id={category_id}", headers=auth_headers)
    assert denied.status_code == 422


def test_batch_context_counts_are_based_on_real_issue_and_return_state(
    client, auth_headers, session_factory
):
    with session_factory() as db:
        machines = db.scalars(select(Machine).order_by(Machine.id).limit(4)).all()
        issued = TransferBatch(batch_reference="QA-UX-ISSUED", created_by_id=1)
        draft = TransferBatch(
            batch_reference="QA-UX-DRAFT",
            created_by_id=1,
            issue_signing_status="AWAITING_SIGNATURE",
        )
        db.add_all([issued, draft])
        db.flush()
        for index, machine in enumerate(machines[:3]):
            db.add(
                TransferProtocol(
                    machine_id=machine.id,
                    batch_id=issued.id,
                    protocol_number=f"QA-UX-T-{index}",
                    issue_status="COMPLETED",
                    issued_at=datetime(2026, 10, 1),
                    is_active=index == 2,
                    return_status="COMPLETED" if index < 2 else None,
                    returned_at=datetime(2026, 10, 2) if index < 2 else None,
                )
            )
        db.add(
            TransferProtocol(
                machine_id=machines[3].id,
                batch_id=draft.id,
                protocol_number="QA-UX-DRAFT-T",
                issue_status="AWAITING_SIGNATURE",
                is_active=False,
            )
        )
        db.commit()
        issued_id = issued.id
    active = get(client, auth_headers, "/workspace/batches?context=active")
    assert active["total"] == 1
    assert active["items"][0]["total_machines"] == 3
    assert active["items"][0]["returned_machines"] == 2
    assert active["items"][0]["still_issued_machines"] == 1
    assert active["items"][0]["status"] == "PARTIALLY_RETURNED"
    assert active["items"][0]["stored_status"] == "ACTIVE"
    assert get(client, auth_headers, "/workspace/batches?context=completed")["total"] == 0
    assert (
        get(client, auth_headers, "/workspace/batches?context=pending")["items"][0][
            "issued_machines"
        ]
        == 0
    )
    with session_factory() as db:
        last = db.scalar(
            select(TransferProtocol).where(
                TransferProtocol.batch_id == issued_id, TransferProtocol.is_active.is_(True)
            )
        )
        last.is_active = False
        last.return_status = "COMPLETED"
        last.returned_at = datetime(2026, 10, 3)
        db.commit()
    assert get(client, auth_headers, "/workspace/batches?context=active")["total"] == 0
    completed = get(client, auth_headers, "/workspace/batches?context=completed")
    assert completed["total"] == 1
    assert completed["items"][0]["status"] == "RETURNED"
    assert completed["items"][0]["stored_status"] == "ACTIVE"


def test_repair_category_search_date_sort_pages_and_legacy_access(
    client, auth_headers, session_factory
):
    with session_factory() as db:
        category = qa_category(db, "QA_UX_REPAIRS", ["HAS_REPAIR_WORKFLOW"])
        legacy = qa_category(db, "QA_UX_ARCHIVE", [])
        assets = db.scalars(select(Machine).order_by(Machine.id).limit(2)).all()
        assets[0].category_id = category.id
        assets[1].category_id = legacy.id
        start = datetime(2026, 10, 1, 9)
        for index in range(4):
            db.add(
                Repair(
                    machine_id=assets[index % 2].id,
                    repair_reference=f"QA-UX-R-{index}",
                    reported_problem="QA filter evidence",
                    status="COMPLETED" if index < 2 else "ACCEPTED",
                    opened_at=start + timedelta(days=index),
                )
            )
        db.commit()
        category_id = category.id
    result = get(
        client,
        auth_headers,
        f"/workspace/repairs?category_id={category_id}&q=QA-UX&sort=oldest&page_size=1",
    )
    assert result["total"] == 2 and result["has_next"] and len(result["items"]) == 1
    assert result["items"][0]["repair_reference"] == "QA-UX-R-0"
    second = get(
        client,
        auth_headers,
        f"/workspace/repairs?category_id={category_id}&q=QA-UX&sort=oldest&page_size=1&page=2",
    )
    assert second["items"][0]["repair_reference"] == "QA-UX-R-2"
    assert (
        get(
            client,
            auth_headers,
            f"/workspace/repairs?category_id={category_id}&status=ACCEPTED&date_from=2026-10-03&date_to=2026-10-03",
        )["total"]
        == 1
    )
    assert get(client, auth_headers, "/workspace/repairs?scope=legacy")["total"] == 2
    assert (
        client.get(
            "/api/workspace/repairs?date_from=2026-10-04&date_to=2026-10-01", headers=auth_headers
        ).status_code
        == 422
    )
    assert (
        client.get("/api/workspace/repairs?page_size=101", headers=auth_headers).status_code == 422
    )


def test_machine_search_pagination_capability_and_literal_wildcards(client, auth_headers):
    machines = get(client, auth_headers, "/workspace/machines?page_size=3&sort=oldest")
    assert len(machines["items"]) == 3 and machines["total"] == 19 and machines["has_next"]
    next_page = get(client, auth_headers, "/workspace/machines?page_size=3&sort=oldest&page=2")
    assert {item["id"] for item in machines["items"]}.isdisjoint(
        item["id"] for item in next_page["items"]
    )
    assert get(client, auth_headers, "/workspace/machines?q=%25")["total"] == 0


def test_machine_sort_uses_creation_time_and_stable_ties(client, auth_headers, session_factory):
    with session_factory() as db:
        # Change only the isolated test database; leave the verified seed untouched.
        assets = db.scalars(select(Machine).order_by(Machine.id)).all()
        for asset in assets:
            asset.created_at = datetime(2026, 10, 1)
        assets[0].created_at = datetime(2026, 10, 3)
        assets[1].created_at = datetime(2026, 10, 2)
        oldest_ids = [asset.id for asset in assets[2:]] + [assets[1].id, assets[0].id]
        db.commit()

    for sort, expected in (("oldest", oldest_ids), ("newest", list(reversed(oldest_ids)))):
        actual = []
        for page in range(1, 5):
            result = get(
                client, auth_headers, f"/workspace/machines?sort={sort}&page_size=5&page={page}"
            )
            assert result["total"] == 19 and result["total_pages"] == 4
            actual.extend(item["id"] for item in result["items"])
        assert actual == expected
        assert len(set(actual)) == 19


def test_verified_machine_inventory_keeps_natural_order_across_pages(client, auth_headers):
    numbers = []
    for page in range(1, 5):
        result = get(
            client, auth_headers, f"/workspace/machines?sort=oldest&page_size=5&page={page}"
        )
        numbers.extend(item["inventory_number"] for item in result["items"])
    assert len(numbers) == 19
    assert numbers == sorted(numbers, key=int)
    assert numbers.index("9") < numbers.index("10")


def test_activity_uses_bounded_business_evidence_and_excludes_noise(
    client, auth_headers, session_factory
):
    with session_factory() as db:
        machine = db.scalar(select(Machine).order_by(Machine.id))
        for index in range(12):
            db.add(
                Repair(
                    machine_id=machine.id,
                    repair_reference=f"QA-UX-A-{index}",
                    reported_problem="QA activity evidence",
                    status="ACCEPTED",
                    opened_at=datetime(2026, 10, 1) + timedelta(minutes=index),
                )
            )
        db.add(
            MachineEvent(
                machine_id=machine.id,
                event_type="MACHINE_UPDATED",
                details={"secret": "must not be projected"},
                user_id=1,
                created_at=datetime(2026, 10, 8),
            )
        )
        db.commit()
    activity = get(client, auth_headers, "/dashboard")["recent_activity"]
    assert len(activity) == 8
    assert activity[0]["reference"] == "QA-UX-A-11"
    assert len({item["event_key"] for item in activity}) == 8
    assert {item["event_type"] for item in activity} == {"REPAIR_OPENED"}
    assert all("details" not in item and "secret" not in str(item) for item in activity)
    for item in activity:
        assert (
            get(client, auth_headers, f"/repair-cases/{item['record_id']}")["machine_id"]
            == item["machine_id"]
        )


def test_observer_can_read_only_limited_assets(client, viewer_headers):
    for path in (
        "/dashboard",
        "/workspace/repairs",
        "/workspace/batches",
        "/workspace/requests",
        "/workspace/categories?module=catalog",
        "/workspace/machines?module=transfers",
    ):
        assert client.get("/api" + path, headers=viewer_headers).status_code == 403
    result = get(client, viewer_headers, "/workspace/machines")
    assert result["total"] == 19
    assert all("serial_number" not in item and "notes" not in item for item in result["items"])


def test_requests_follow_machine_or_repair_category_and_keep_general_requests(
    client, auth_headers, session_factory
):
    with session_factory() as db:
        category = qa_category(db, "QA_UX_REQUESTS", [])
        asset = db.scalar(select(Machine).order_by(Machine.id))
        asset.category_id = category.id
        repair = Repair(machine_id=asset.id, repair_reference="QA-UX-LINK", reported_problem="QA")
        db.add(repair)
        db.flush()
        for index, machine_id, repair_id in (
            (0, asset.id, None),
            (1, None, repair.id),
            (2, None, None),
        ):
            request = PartRequest(
                machine_id=machine_id,
                repair_id=repair_id,
                request_reference=f"QA-UX-REQ-{index}",
                part_name="QA",
                reason="QA",
                quantity=1,
                status="DRAFT",
                requested_by_id=1,
                created_at=datetime(2026, 10, 1) + timedelta(days=index),
            )
            db.add(request)
            db.flush()
            db.add(
                PartRequestLine(
                    request_id=request.id,
                    part_number=f"QA-UX-P-{index}",
                    description="QA search evidence",
                    quantity=1,
                    unit="pcs",
                )
            )
        db.commit()
        category_id = category.id
    page = get(
        client,
        auth_headers,
        f"/workspace/requests?category_id={category_id}&page_size=1&sort=oldest",
    )
    assert page["total"] == 2 and page["has_next"]
    assert page["items"][0]["request_reference"] == "QA-UX-REQ-0"
    repair_linked = get(
        client, auth_headers, f"/workspace/requests?category_id={category_id}&q=QA-UX-P-1"
    )
    assert (
        repair_linked["total"] == 1
        and repair_linked["items"][0]["repair_reference"] == "QA-UX-LINK"
    )
    assert get(client, auth_headers, "/workspace/requests?scope=legacy")["total"] == 1
    assert (
        get(client, auth_headers, "/workspace/requests?date_from=2026-10-03&status=DRAFT")["total"]
        == 1
    )


def test_mixed_batches_preserve_exact_membership_and_legacy_access(
    client, auth_headers, session_factory
):
    with session_factory() as db:
        category = qa_category(db, "QA_UX_MIXED", ["HAS_TRANSFER_WORKFLOW"])
        assets = db.scalars(select(Machine).order_by(Machine.id).limit(2)).all()
        assets[1].category_id = category.id
        batch = TransferBatch(batch_reference="QA-UX-MIXED", created_by_id=1)
        db.add(batch)
        db.flush()
        for index, asset in enumerate(assets):
            db.add(
                TransferProtocol(
                    machine_id=asset.id,
                    batch_id=batch.id,
                    protocol_number=f"QA-UX-MIXED-{index}",
                    issue_status="COMPLETED",
                    is_active=True,
                )
            )
        legacy_machine = db.scalar(select(Machine).where(Machine.id.not_in([asset.id for asset in assets])))
        legacy_machine.category_id = None
        legacy_transfer = TransferProtocol(
            machine_id=legacy_machine.id,
            protocol_number="QA-UX-UNBATCHED-ACTIVE",
            issue_status="COMPLETED",
            is_active=True,
        )
        db.add(legacy_transfer)
        db.flush()
        legacy_id = legacy_transfer.id
        db.commit()
        category_id, asset_id = category.id, assets[1].id
    mixed = get(client, auth_headers, "/workspace/batches?scope=mixed")
    assert mixed["total"] == 1 and mixed["items"][0]["mixed_categories"]
    assert get(client, auth_headers, f"/workspace/batches?category_id={category_id}")["total"] == 1
    # A search matching another member must not invent a member in this category.
    assert (
        get(client, auth_headers, f"/workspace/batches?category_id={category_id}&q=QA-UX-MIXED-0")[
            "total"
        ]
        == 0
    )
    with session_factory() as db:
        db.get(Machine, asset_id).category_id = None
        db.commit()
    assert get(client, auth_headers, "/workspace/batches?scope=legacy")["total"] == 1
    records = get(client, auth_headers, "/workspace/transfers?scope=legacy")
    unbatched = next(item for item in records["items"] if item["id"] == legacy_id)
    assert unbatched["batch_id"] is None and unbatched["is_active"]
    assert get(client, auth_headers, "/workspace/transfers?status=completed")["total"] == 0


def test_recent_activity_uses_completion_and_decision_evidence_without_duplicates(
    client, auth_headers, session_factory
):
    with session_factory() as db:
        asset = db.scalar(select(Machine).order_by(Machine.id))
        repair = Repair(
            machine_id=asset.id,
            repair_reference="QA-UX-CLOSED",
            reported_problem="QA",
            status="COMPLETED",
            opened_at=datetime(2026, 10, 1),
            closed_at=datetime(2026, 10, 2),
        )
        db.add(repair)
        db.flush()
        for code in ("COMPLETED", "STATUS_CHANGE"):
            db.add(
                RepairEvent(
                    repair_id=repair.id,
                    event_type=code,
                    status_after="COMPLETED",
                    created_at=repair.closed_at,
                    user_id=1,
                )
            )
        request = PartRequest(
            repair_id=repair.id,
            request_reference="QA-UX-APPROVED",
            part_name="QA",
            reason="QA",
            quantity=1,
            status="DELIVERED",
            requested_by_id=1,
            created_at=datetime(2026, 10, 3),
            decided_at=datetime(2026, 10, 4),
            delivered_at=datetime(2026, 10, 5),
        )
        db.add(request)
        db.flush()
        db.add(
            PartRequestApproval(
                request_id=request.id,
                decision="APPROVED",
                decided_by_id=1,
                decided_at=request.decided_at,
            )
        )
        db.commit()
        asset_id = asset.id
    feed = get(client, auth_headers, "/dashboard")["recent_activity"]
    assert len([item for item in feed if item["event_type"] == "REPAIR_COMPLETED"]) == 1
    approved = next(item for item in feed if item["event_type"] == "PART_REQUEST_APPROVED")
    assert approved["status"] == "APPROVED" and approved["machine_id"] == asset_id
    assert all(item["occurred_at"].endswith("Z") for item in feed)


def test_signed_partial_returns_move_between_workspace_contexts_and_retain_documents(
    client, auth_headers, machine_ids, issue_payload
):
    from test_bulk_transfers import complete_signing, return_payload

    response = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"], machine_ids["5"]),
    )
    assert response.status_code == 201
    assert get(client, auth_headers, "/workspace/batches?context=active")["total"] == 0
    complete_signing(client, response)
    issued = response.json()
    for index, transfer in enumerate(issued["transfers"]):
        returned = client.post(
            "/api/transfers/bulk-return", headers=auth_headers, json=return_payload(transfer)
        )
        assert returned.status_code == 200
        before = get(client, auth_headers, "/workspace/batches?context=active")
        assert before["items"][0]["still_issued_machines"] == 2 - index
        complete_signing(client, returned)
        context = "active" if index == 0 else "completed"
        result = get(client, auth_headers, f"/workspace/batches?context={context}")
        assert result["items"][0]["returned_machines"] == index + 1
        detail = get(client, auth_headers, f"/transfer-batches/{issued['batch_id']}")
        assert len(detail["return_operations"]) == index + 1
        for item in detail["transfers"]:
            assert item["issue_documents"]
        timeline = get(client, auth_headers, f"/machines/{transfer['machine_id']}/timeline")
        assert len({item["event_key"] for item in timeline["items"]}) == len(timeline["items"])
        documents = [item for item in timeline["items"] if item["category"] == "document"]
        assert documents and all(item["files"] for item in documents)
        for item in documents:
            for file in item["files"]:
                assert file["format"] in {"docx", "pdf"}
                assert client.get("/api" + file["download_endpoint"], headers=auth_headers).status_code == 200
    assert get(client, auth_headers, "/workspace/batches?context=active")["total"] == 0
