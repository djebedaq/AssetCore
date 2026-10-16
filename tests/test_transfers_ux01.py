"""Exact partial-return/reissue scenario against disposable SQLite and PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

from app.models import Machine, OfficialDocumentVersion, TransferBatch, TransferProtocol
from sqlalchemy import func, select
from test_bulk_transfers import complete_signing, return_payload
from test_transfer_lifecycle_projection import (  # noqa: F401
    fingerprint,
    issue,
    read,
    receive,
)
from test_transfer_lifecycle_projection import (
    qa_machines as qa_machines,
)


def workspace(client, headers, resource, query=""):
    return read(client, headers, f"/api/workspace/{resource}?{query}")


def test_partial_return_reissue_independent_cycles_and_protocols(
    client, auth_headers, issue_payload, qa_machines, session_factory
):
    # A/B/C stand for the requested 7/8/10 scenario, without touching verified seed assets.
    a, b, c = qa_machines[:3]
    first = issue(client, auth_headers, issue_payload, [a, b, c])
    selected = [first["transfers"][0], first["transfers"][2]]
    pending = client.post("/api/transfers/bulk-return", headers=auth_headers,
                          json=return_payload(*selected))
    assert pending.status_code == 200
    blocked = client.post("/api/transfers/bulk-issue", headers=auth_headers, json=issue_payload(a, c))
    assert blocked.status_code == 409  # Return awaiting signature is still authoritative.
    assert workspace(client, auth_headers, "transfers", "status=completed")["total"] == 0
    assert workspace(client, auth_headers, "transfers", "status=awaiting_return")["total"] == 2
    complete_signing(client, pending)
    with session_factory() as db:
        assert [db.get(Machine, i).status for i in (a, b, c)] == ["READY", "ISSUED", "READY"]
        assert db.get(TransferBatch, first["batch_id"]).status == "PARTIALLY_RETURNED"
    available = {row["machine_id"]: row for row in read(client, auth_headers, "/api/transfers/availability")}
    assert available[a]["available"] and available[c]["available"] and not available[b]["available"]
    old_details = {row["transfer_id"]: workspace(client, auth_headers, f"transfers/{row['transfer_id']}")
                   for row in selected}
    with session_factory() as db:
        old_versions = {v.id: (v.snapshot_sha256, v.signing_sha256, v.docx_sha256, v.pdf_sha256)
                        for v in db.scalars(select(OfficialDocumentVersion))}
        old_transfers = db.execute(select(TransferProtocol.__table__).where(
            TransferProtocol.id.in_([row["transfer_id"] for row in selected]))).all()
    later = issue(client, auth_headers, issue_payload, [a, c])
    assert later["batch_id"] != first["batch_id"]
    assert {row["transfer_id"] for row in later["transfers"]}.isdisjoint(
        row["transfer_id"] for row in first["transfers"])
    assert {row["official_document_id"] for row in later["transfers"]}.isdisjoint(
        row["official_document_id"] for row in first["transfers"])
    assert {row["protocol_number"] for row in later["transfers"]}.isdisjoint(
        row["protocol_number"] for row in first["transfers"])
    active = workspace(client, auth_headers, "batches", "context=active")
    by_id = {row["batch_id"]: row for row in active["items"]}
    assert set(by_id) == {first["batch_id"], later["batch_id"]}
    assert [(by_id[i]["returned_machines"], by_id[i]["still_issued_machines"], by_id[i]["total_machines"])
            for i in (first["batch_id"], later["batch_id"])] == [(2, 1, 3), (0, 2, 2)]
    history = workspace(client, auth_headers, "transfers", "status=completed")
    assert {row["id"] for row in history["items"]} == set(old_details)
    for transfer_id, original in old_details.items():
        assert workspace(client, auth_headers, f"transfers/{transfer_id}")["documents"] == original["documents"]
    with session_factory() as db:
        assert old_transfers == db.execute(select(TransferProtocol.__table__).where(
            TransferProtocol.id.in_(old_details))).all()
        assert old_versions == {v.id: (v.snapshot_sha256, v.signing_sha256, v.docx_sha256, v.pdf_sha256)
                                for v in db.scalars(select(OfficialDocumentVersion).where(
                                    OfficialDocumentVersion.id.in_(old_versions)))}
        outstanding = db.get(TransferProtocol, first["transfers"][1]["transfer_id"])
        assert outstanding.is_active and outstanding.batch_id == first["batch_id"]
    receive(client, auth_headers, later["transfers"])
    for machine_id in (a, c):
        cycles = workspace(client, auth_headers, "transfers", f"status=completed&machine_id={machine_id}")
        assert cycles["total"] == 2
        assert len({row["id"] for row in cycles["items"]}) == 2
        numbers = set()
        with session_factory() as db:
            before = fingerprint(db)
        for row in cycles["items"]:
            detail = workspace(client, auth_headers, f"transfers/{row['id']}")
            assert detail["machine"]["id"] == machine_id
            assert {d["document_type"] for d in detail["documents"]} == {"TRANSFER_ISSUE", "TRANSFER_RETURN"}
            for document in detail["documents"]:
                assert document["document_number"] not in numbers
                numbers.add(document["document_number"])
                assert {f["format"] for f in document["files"]} == {"pdf", "docx"}
                for file in document["files"]:
                    response = client.get("/api" + file["download_endpoint"], headers=auth_headers)
                    assert response.status_code == 200
                    assert response.content.startswith(b"%PDF" if file["format"] == "pdf" else b"PK")
        with session_factory() as db:
            assert fingerprint(db) == before
    assert workspace(client, auth_headers, "batches", "context=active")["total"] == 1
    assert client.post("/api/transfers/bulk-issue", headers=auth_headers, json=issue_payload(b)).status_code == 409
    # A returned machine marked REPAIR remains unavailable with its open repair.
    repair_issue = issue(client, auth_headers, issue_payload, qa_machines[3:4])
    payload = return_payload(*repair_issue["transfers"])
    payload["items"][0]["next_status"] = "REPAIR"
    response = client.post("/api/transfers/bulk-return", headers=auth_headers, json=payload)
    assert response.status_code == 200
    complete_signing(client, response)
    assert client.post("/api/transfers/bulk-issue", headers=auth_headers,
                       json=issue_payload(qa_machines[3])).status_code == 409
    # Independent request sessions race for the now-ready first machine.
    barrier = Barrier(2)
    def race():
        barrier.wait(timeout=20)
        return client.post("/api/transfers/bulk-issue", headers=auth_headers, json=issue_payload(a)).status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(race) for _ in range(2)]
        assert sorted(f.result(timeout=90) for f in futures) == [201, 409]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(TransferProtocol).where(
            TransferProtocol.machine_id == a, TransferProtocol.is_active.is_(True))) == 1


def test_cycle_history_filters_pagination_and_exact_detail_read(
    client, auth_headers, issue_payload, qa_machines, session_factory, viewer_headers
):
    first = issue(client, auth_headers, issue_payload, qa_machines[:2])
    returned = receive(client, auth_headers, first["transfers"])
    later = issue(client, auth_headers, issue_payload, qa_machines[:1])
    receive(client, auth_headers, later["transfers"])
    with session_factory() as db:
        category_id = db.get(Machine, qa_machines[0]).category_id
        before = fingerprint(db)
    base = f"status=completed&category_id={category_id}&machine_id={qa_machines[0]}&page_size=1"
    one = workspace(client, auth_headers, "transfers", base + "&sort=oldest")
    two = workspace(client, auth_headers, "transfers", base + "&sort=oldest&page=2")
    assert one["total"] == 2 and one["has_next"] and two["has_previous"]
    assert one["items"][0]["id"] == first["transfers"][0]["transfer_id"]
    assert two["items"][0]["id"] == later["transfers"][0]["transfer_id"]
    for query, expected in [(returned["returned"][0]["documents"][0]["document_number"], 1),
                            (first["batch_reference"], 1), ("no such protocol", 0)]:
        assert workspace(client, auth_headers, "transfers", base + "&q=" + query)["total"] == expected
    today = datetime.now().date().isoformat()
    assert workspace(client, auth_headers, "transfers", base + f"&date_from={today}&date_to={today}")["total"] == 2
    assert workspace(client, auth_headers, "transfers", base + "&date_to=2000-01-01")["total"] == 0
    transfer_id = first["transfers"][0]["transfer_id"]
    assert client.get(f"/api/workspace/transfers/{transfer_id}").status_code == 401
    assert client.get(f"/api/workspace/transfers/{transfer_id}", headers=viewer_headers).status_code == 403
    assert client.get("/api/workspace/transfers/999999", headers=auth_headers).status_code == 404
    with session_factory() as db:
        assert fingerprint(db) == before


def test_special_records_are_reachable_without_becoming_completed(
    client, auth_headers, issue_payload, qa_machines
):
    pending = issue(client, auth_headers, issue_payload, qa_machines[:1], sign=False)
    assert workspace(client, auth_headers, "transfers", "status=awaiting_issue")["total"] == 1
    detail = workspace(client, auth_headers, f"transfers/{pending['transfers'][0]['transfer_id']}")
    assert detail["documents"] == []
    cancelled = client.post(f"/api/transfer-batches/{pending['batch_id']}/cancel", headers=auth_headers,
                            json={"reason": "QA explicitly cancelled pending operation"})
    assert cancelled.status_code == 200
    assert workspace(client, auth_headers, "transfers", "status=cancelled")["total"] == 1
    assert workspace(client, auth_headers, "transfers", "status=other")["total"] == 1
    assert workspace(client, auth_headers, "transfers", "status=completed")["total"] == 0


def test_cycle_documents_stay_pinned_when_a_correcting_draft_is_created(
    client, auth_headers, issue_payload, qa_machines, session_factory
):
    issued = issue(client, auth_headers, issue_payload, qa_machines[:1])
    receive(client, auth_headers, issued["transfers"])
    transfer_id = issued["transfers"][0]["transfer_id"]
    original = workspace(client, auth_headers, f"transfers/{transfer_id}")["documents"]
    for document in original:
        revised = client.post(f"/api/official-documents/{document['official_document_id']}/supersede",
                              headers=auth_headers,
                              json={"reason": "Synthetic QA correcting draft", "snapshot": {}})
        assert revised.status_code == 201
    with session_factory() as db:
        before = fingerprint(db)
    archive = workspace(client, auth_headers, f"transfers/{transfer_id}")["documents"]
    assert [(d["official_document_id"], d["version"], d["files"]) for d in archive] == [
        (d["official_document_id"], d["version"], d["files"]) for d in original]
    assert all(d["version_status"] == "SUPERSEDED" for d in archive)
    for document in archive:
        for file in document["files"]:
            assert client.get("/api" + file["download_endpoint"], headers=auth_headers).status_code == 200
    with session_factory() as db:
        assert fingerprint(db) == before
