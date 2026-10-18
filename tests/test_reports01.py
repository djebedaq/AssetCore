import io
import json
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from app.models import Machine, PartRequest, TransferBatch, TransferProtocol, User
from app.permissions import ROLE_PERMISSIONS, Permission, has_permission
from app.reports.exports import export_pdf, export_xlsx, sheets
from app.reports.filters import ReportFilters
from app.reports.service import Reports, hours
from fastapi import HTTPException
from pypdf import PdfReader
from reports01_fixtures import reports_fixture
from sqlalchemy import func, select


@pytest.fixture()
def report_qa(session_factory):
    with session_factory() as db:
        return reports_fixture(db)


def service(session_factory, qa, **changes):
    db = session_factory()
    f = ReportFilters(
        qa["now"].date() - timedelta(days=29), qa["now"].date(), category_id=qa["category_id"]
    )
    from dataclasses import replace

    return db, Reports(db, db.get(User, qa["owner_id"]), replace(f, **changes), qa["now"])


def values(result, field="metrics"):
    return {m["key"]: m["value"] for m in result[field]}


def test_reports_current_categories_and_active_relationship(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("overview")
        assert values(data, "current") == {
            "total_machines": 3,
            "READY": 0,
            "ISSUED": 2,
            "REPAIR": 1,
            "current_repairs": 1,
            "pending_requests": 1,
        }
        assert data["categories"][0]["total"] == 3
        assert (
            db.scalar(
                select(func.count())
                .select_from(Machine)
                .where(Machine.id.not_in(report_qa["machine_ids"]))
            )
            == 19
        )


def test_reports_partial_return_reissue_cycles_are_individual(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        metrics = values(reports.build("usage"))
        assert metrics["issues"] == 5 and metrics["unique_issued"] == 3
        assert metrics["completed_cycles"] == 3 and metrics["active_issues"] == 2
        assert metrics["avg_cycle_hours"] == 56
        assert metrics["issue_hours"] == 42 * 24
        assert metrics["returned_repair"] == 1


@pytest.mark.parametrize(
    "issue_status,batch_status",
    [("AWAITING_SIGNATURE", "ACTIVE"), ("CANCELLED", "ACTIVE"), ("COMPLETED", "CANCELLED")],
)
def test_reports_nonfinal_and_cancelled_issues_excluded(
    session_factory, report_qa, issue_status, batch_status
):
    db, reports = service(session_factory, report_qa)
    with db:
        batch = TransferBatch(
            batch_reference="QA-EXCLUDED", created_by_id=report_qa["owner_id"], status=batch_status
        )
        db.add(batch)
        db.flush()
        db.add(
            TransferProtocol(
                machine_id=report_qa["machine_ids"][0],
                batch_id=batch.id,
                protocol_number="QA-EXCLUDED",
                issue_status=issue_status,
                issued_at=report_qa["now"] - timedelta(days=1),
            )
        )
        db.commit()
        assert values(reports.build("usage"))["issues"] == 5


def test_reports_pending_return_is_not_a_completed_cycle(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        t = db.get(TransferProtocol, report_qa["transfer_ids"][1])
        t.return_status, t.returned_at = "AWAITING_SIGNATURE", report_qa["now"] - timedelta(days=1)
        db.commit()
        assert values(reports.build("usage"))["completed_cycles"] == 3
        assert values(reports.build("usage"))["active_issues"] == 2


def test_reports_period_intersection_and_missing_duration(session_factory, report_qa):
    day = report_qa["now"].date() - timedelta(days=14)
    db, reports = service(session_factory, report_qa, date_from=day, date_to=day)
    with db:
        metrics = values(reports.build("usage"))
        assert metrics["issues"] == 0
        assert metrics["issue_hours"] == 72  # Three cycles overlap all of this local calendar day.
        assert metrics["avg_cycle_hours"] is None


def test_reports_repairs_do_not_count_events_parts_or_linked_returns_twice(
    session_factory, report_qa
):
    db, reports = service(
        session_factory, report_qa, date_from=report_qa["now"].date() - timedelta(days=89)
    )
    with db:
        data = reports.build("repairs")
        metrics = values(data)
        assert metrics["opened"] == 5 and metrics["closed"] == 4
        assert metrics["calendar_hours"] == 24 and metrics["started_hours"] == 23
        assert metrics["avg_repair_minutes"] == 30 and metrics["labor_minutes"] == 45
        assert next(m for m in data["metrics"] if m["key"] == "avg_repair_minutes")["sample"] == 1
        detail = reports.details("repairs", "opened")
        assert detail["total"] == 5 and len({r["id"] for r in detail["items"]}) == 5


def test_reports_attention_five_repairs_original_reasons(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        items = reports.attention()
        assert len(items) == 1
        assert {r["code"] for r in items[0]["reasons"]} == {"frequent", "long", "return"}
        assert items[0]["reasons"][0]["count"] == 5
        assert reports.details("repairs", "attention")["total"] == 5


def test_reports_canonical_deliveries_reversals_units_and_delay(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("requests")
        assert values(data)["delayed"] == 1 and values(data)["waiting_order"] == 0
        delayed = data["delayed"]["items"][0]
        assert delayed["remaining_lines"] == 2 and delayed["elapsed_days"] == 20
        assert [(r["quantity"], r["unit"]) for r in delayed["remaining"]] == [
            ("4", "pcs"),
            ("5.5", "l"),
        ]
        assert sum(row.get("receipts", 0) for row in data["trends"]) == 1


def test_reports_cancelled_request_is_not_overdue(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        request = db.get(PartRequest, report_qa["request_id"])
        request.status, request.cancelled_at = "CANCELLED", report_qa["now"]
        db.commit()
        assert values(reports.build("requests"))["delayed"] == 0
        assert values(reports.build("requests"))["cancelled"] == 1


def test_reports_general_requests_are_included_without_machine_scope(session_factory, report_qa):
    db, reports = service(session_factory, report_qa, category_id=None)
    with db:
        assert values(reports.build("requests"))["created"] == 2
        assert reports.details("requests", "created")["total"] == 2


def test_reports_comparison_distinct_machines(session_factory, report_qa):
    db, reports = service(
        session_factory, report_qa, machine_ids=tuple(report_qa["machine_ids"][:2])
    )
    with db:
        data = reports.build("compare")
        assert len(data["machines"]) == 2
        metrics = {
            i["machine"]["id"]: {m["key"]: m["value"] for m in i["metrics"]["usage"]}
            for i in data["machines"]
        }
        assert metrics[report_qa["machine_ids"][0]]["issues"] == 2
        assert metrics[report_qa["machine_ids"][0]]["completed_cycles"] == 2
        assert metrics[report_qa["machine_ids"][1]]["completed_cycles"] == 0


def test_reports_stable_sql_pagination(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        pages = [reports.details("usage", "issues", page, 2) for page in (1, 2, 3)]
        ids = [r["id"] for page in pages for r in page["items"]]
        assert len(ids) == len(set(ids)) == 5
        assert ids == [r["id"] for r in reports.details("usage", "issues")["items"]]


@pytest.mark.parametrize(
    "role,allowed",
    [("administrator", True), ("director", True), ("mechanic", True), ("observer", False)],
)
def test_reports_permissions_do_not_grant_audit(role, allowed):
    user = User(role=role)
    assert has_permission(user, Permission.REPORTS_VIEW) is allowed
    if role == "mechanic":
        assert not has_permission(user, Permission.AUDIT_VIEW_OPERATIONAL)


def test_reports_underlying_permissions_checked(session_factory, report_qa, monkeypatch):
    db, reports = service(session_factory, report_qa)
    with db:
        monkeypatch.setitem(
            ROLE_PERMISSIONS,
            "mechanic",
            frozenset({Permission.REPORTS_VIEW, Permission.ASSETS_VIEW}),
        )
        user = User(role="mechanic")
        restricted = Reports(db, user, reports.f, reports.now)
        data = restricted.build("overview")
        assert not any(data["capabilities"].values()) and data["attention"] == []
        for kind in ("usage", "repairs", "requests"):
            with pytest.raises(HTTPException) as denied:
                restricted.details(kind, "created")
            assert denied.value.status_code == 403


@pytest.mark.parametrize("language", ["bg", "en", "ru"])
def test_reports_export_content_matches_statistics(session_factory, report_qa, language):
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("usage")
        details = {"usage": reports.details("usage", "issues")["items"]}
        details["usage"][0]["return_damage"] = "=1+1"
        xlsx = export_xlsx(data, details, language)
        with zipfile.ZipFile(io.BytesIO(xlsx)) as z:
            for name in z.namelist():
                ET.fromstring(z.read(name))
            root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
            assert "=1+1" in z.read("xl/worksheets/sheet2.xml").decode()
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            numeric = [float(n.text) for n in root.findall(".//s:v", ns)]
            assert 5 in numeric and 56 in numeric
            assert not root.findall(".//s:f", ns)
        pdf = export_pdf(data, details, language)
        reader = PdfReader(io.BytesIO(pdf))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "REPORTS-QA-T" in text and "56" in text
        assert "{{" not in text
        assert len(reader.pages) >= 2
        assert sheets(data, details, language)[0][1][6][1] == data["current"][0]["value"]


def test_reports_http_authorization_and_invalid_filters(client, auth_headers, viewer_headers):
    assert client.get("/api/reports/overview", headers=viewer_headers).status_code == 403
    for query in (
        "date_from=2026-11-01&date_to=2026-10-01",
        "machine_ids=1,2,3,4,5",
        "machine_ids=no",
        "date_from=1900-01-01",
    ):
        assert client.get("/api/reports/overview?" + query, headers=auth_headers).status_code == 422
    assert client.get("/api/reports/compare", headers=auth_headers).status_code == 422
    assert client.get("/api/reports/overview", headers=auth_headers).status_code == 200


def test_reports_timezone_boundaries_and_previous_calendar_period():
    f = ReportFilters(date(2026, 10, 25), date(2026, 10, 25))
    assert (f.end - f.start).total_seconds() == 25 * 3600
    assert f.includes(f.start) and not f.includes(f.end)
    assert f.previous().date_to == date(2026, 10, 24)
    assert hours(None, f.start) is None and hours(f.end, f.start) is None


def test_reports_uncategorized_and_literal_search(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        machine = db.get(Machine, report_qa["machine_ids"][0])
        machine.category_id = None
        db.commit()
    db, reports = service(session_factory, report_qa, category_id=None, uncategorized=True)
    with db:
        assert any(m["id"] == report_qa["machine_ids"][0] for m in reports.machines)
    db, reports = service(session_factory, report_qa, q="%")
    with db:
        assert reports.machines == []


def test_reports_translation_parity():
    root = Path(__file__).resolve().parents[1]
    labels = json.loads((root / "backend/app/reports/labels.json").read_text(encoding="utf-8"))
    assert labels == json.loads(
        (root / "frontend/src/features/reports/labels.json").read_text(encoding="utf-8")
    )
    assert all(len(v) == 3 and all(v) for v in labels.values())


def test_reports_search_does_not_weaken_objective_attention_history(session_factory, report_qa):
    db, reports = service(session_factory, report_qa, q="KK9000")
    with db:
        assert len(reports.machines) == 1
        assert reports.attention()[0]["reasons"][0]["count"] == 5
        assert reports.details("repairs", "attention")["total"] == 5
        data = reports.build("requests")
        assert data["records"]["items"][0]["official_number"] == "KK9000"


@pytest.mark.parametrize("days,expected", [(14, 0), (15, 1)])
def test_reports_delay_is_strictly_more_than_fourteen_calendar_days(
    session_factory, report_qa, days, expected
):
    db, reports = service(session_factory, report_qa)
    with db:
        request = db.get(PartRequest, report_qa["request_id"])
        request.ordered_at = report_qa["now"] - timedelta(days=days)
        db.commit()
        assert values(reports.build("requests"))["delayed"] == expected


def test_reports_zero_baseline_and_incomplete_history_are_explicit(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("usage")
        issued = next(m for m in data["metrics"] if m["key"] == "issues")
        assert issued["previous"] == 0 and issued["percent"] is None and issued["change"] == 5
        request = PartRequest(
            machine_id=report_qa["machine_ids"][0],
            part_name="Synthetic incomplete history",
            quantity=3,
            status="DELIVERED",
            created_at=report_qa["now"] - timedelta(days=1),
            delivered_at=report_qa["now"],
        )
        db.add(request)
        db.commit()
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("requests")
        assert values(data)["delivered"] == 0
        assert values(data)["delivery_hours"] is None


def test_reports_receipt_drill_is_paginated_by_actual_events(session_factory, report_qa):
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("requests")
        assert values(data)["receipts"] == 1
        records = reports.details("requests", "receipts", page_size=1)
        assert records["total"] == 1
        assert records["items"][0]["original_id"] == report_qa["request_id"]


def test_reports_signed_workflow_reissues_before_original_batch_finishes(
    client, auth_headers, session_factory, issue_payload
):
    from app.models import AssetCategory, ProtocolDocument
    from test_bulk_transfers import complete_signing, return_payload

    with session_factory() as db:
        category = db.scalar(select(AssetCategory).where(AssetCategory.code == "HPWJ"))
        machines = [
            Machine(
                inventory_number=f"REPORTS-SIGNED-QA-{i}",
                name=f"Synthetic signed QA {i}",
                category="HPWJ",
                category_id=category.id,
                brand="QA",
                model="Synthetic",
                status="READY",
            )
            for i in range(3)
        ]
        db.add_all(machines)
        db.commit()
        ids = [m.id for m in machines]
    query = "/api/reports/usage?q=REPORTS-SIGNED-QA"

    def metrics():
        response = client.get(query, headers=auth_headers)
        assert response.status_code == 200
        return values(response.json())

    issued = client.post(
        "/api/transfers/bulk-issue", headers=auth_headers, json=issue_payload(*ids)
    )
    assert issued.status_code == 201
    assert metrics()["issues"] == 0
    complete_signing(client, issued)
    assert metrics()["issues"] == 3
    transfers = issued.json()["transfers"]
    returned = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json=return_payload(transfers[0], transfers[2]),
    )
    assert returned.status_code == 200
    assert metrics()["completed_cycles"] == 0
    complete_signing(client, returned)
    assert metrics()["completed_cycles"] == 2
    with session_factory() as db:
        protected = dict(db.execute(select(ProtocolDocument.id, ProtocolDocument.sha256)).all())
    reissued = client.post(
        "/api/transfers/bulk-issue", headers=auth_headers, json=issue_payload(ids[0], ids[2])
    )
    assert reissued.status_code == 201
    complete_signing(client, reissued)
    result = metrics()
    assert (
        result["issues"] == 5 and result["completed_cycles"] == 2 and result["active_issues"] == 3
    )
    returned_again = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json=return_payload(*reissued.json()["transfers"]),
    )
    assert returned_again.status_code == 200
    complete_signing(client, returned_again)
    result = metrics()
    assert result["completed_cycles"] == 4 and result["active_issues"] == 1
    with session_factory() as db:
        assert db.get(TransferBatch, issued.json()["batch_id"]).status == "PARTIALLY_RETURNED"
        after = dict(db.execute(select(ProtocolDocument.id, ProtocolDocument.sha256)).all())
        assert all(after[identifier] == digest for identifier, digest in protected.items())


def test_reports_export_review_examples(session_factory, report_qa, tmp_path):
    target = Path(os.environ.get("ASSETCORE_REPORTS01_QA_OUTPUT", tmp_path))
    target.mkdir(parents=True, exist_ok=True)
    db, reports = service(session_factory, report_qa)
    with db:
        data = reports.build("overview")
        details = {
            k: reports.details(
                k, {"usage": "issues", "repairs": "opened", "requests": "created"}[k]
            )["items"]
            for k in reports.allowed
        }
        (target / "reports01-qa.pdf").write_bytes(export_pdf(data, details, "bg"))
        (target / "reports01-qa.xlsx").write_bytes(export_xlsx(data, details, "bg"))
