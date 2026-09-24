"""Signed lifecycle regressions; QA-only assets in disposable test databases."""
from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime

import pytest
from app.models import (
    AssetCategory,
    AuditLog,
    DocumentParticipant,
    DocumentSignature,
    GeneratedDocument,
    Machine,
    MachineEvent,
    OfficialDocument,
    OfficialDocumentVersion,
    ProtocolDocument,
    SignatureSession,
    TransferBatch,
    TransferProtocol,
)
from sqlalchemy import select
from test_bulk_transfers import complete_signing, return_payload


@pytest.fixture()
def qa_machines(session_factory):
    with session_factory() as db:
        category = AssetCategory(code="QA_LIFECYCLE", name_bg="Тестови активи")
        db.add(category)
        db.flush()
        machines = [Machine(inventory_number=f"QA-LIFECYCLE-{letter}",
                            name=f"Synthetic QA machine {letter}", category=category.code,
                            category_id=category.id, brand="SYNTHETIC QA",
                            status="READY", location_id=1) for letter in "ABCDEFGH"]
        db.add_all(machines)
        db.commit()
        return [machine.id for machine in machines]


def issue(client, headers, issue_payload, ids, *, sign=True):
    response = client.post("/api/transfers/bulk-issue", headers=headers, json=issue_payload(*ids))
    assert response.status_code == 201, response.text
    if sign:
        complete_signing(client, response)
    return response.json()


def receive(client, headers, transfers, *, sign=True):
    response = client.post("/api/transfers/bulk-return", headers=headers,
                           json=return_payload(*transfers))
    assert response.status_code == 200, response.text
    if sign:
        complete_signing(client, response)
    return response.json()


def read(client, headers, path):
    response = client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def lifecycles(client, headers):
    return read(client, headers, "/api/transfer-batches?view=lifecycles")


def progress(item, total, returned, issued):
    assert (item["total_machines"], item["returned_machines"], item["still_issued_machines"]) == (
        total, returned, issued
    )


HISTORY_MODELS = (TransferBatch, TransferProtocol, OfficialDocument, OfficialDocumentVersion,
                  DocumentParticipant, DocumentSignature, SignatureSession, ProtocolDocument,
                  GeneratedDocument, AuditLog, MachineEvent)


def fingerprint(db):
    """Hash every domain/history column, including encrypted blobs, without exposing them."""
    return {model.__tablename__: hashlib.sha256(repr(db.execute(
        select(model.__table__).order_by(model.id)
    ).all()).encode()).hexdigest() for model in HISTORY_MODELS}


def test_full_return_preserves_operations_documents_signatures_and_read_only_projection(
    client, auth_headers, session_factory, issue_payload, qa_machines
):
    issued = issue(client, auth_headers, issue_payload, qa_machines[:2])
    progress(lifecycles(client, auth_headers)[0], 2, 0, 2)
    with session_factory() as db:
        original = db.get(TransferBatch, issued["batch_id"])
        issue_manifest, issue_hash = original.issue_manifest, original.issue_manifest_sha256
        issue_document_ids = [row["official_document_id"] for row in issued["transfers"]]
        issue_document_ids.append(issued["signing_document_id"])
        versions_before = [(row.id, row.snapshot_sha256, row.signing_sha256, row.docx_sha256, row.pdf_sha256)
                           for row in db.scalars(select(OfficialDocumentVersion).where(
                               OfficialDocumentVersion.document_id.in_(issue_document_ids)))]
        signatures_before = [row.id for row in db.scalars(select(DocumentSignature))]
    returned = receive(client, auth_headers, issued["transfers"])
    with session_factory() as db:
        issue_batch = db.get(TransferBatch, issued["batch_id"])
        return_batch = db.get(TransferBatch, returned["batch_id"])
        assert issue_batch.id != return_batch.id
        assert len(issue_batch.transfers) == 2 and not return_batch.transfers
        assert issue_batch.issue_manifest == issue_manifest
        assert issue_batch.issue_manifest_sha256 == issue_hash
        assert return_batch.return_manifest["operation"] == "RETURN"
        assert {item["issue_batch_id"] for item in return_batch.return_manifest["machines"]} == {issue_batch.id}
        assert {item["transfer_id"] for item in return_batch.return_manifest["machines"]} == {
            t.id for t in issue_batch.transfers}
        assert all(t.return_status == "COMPLETED" and not t.is_active for t in issue_batch.transfers)
        assert len(list(db.scalars(select(TransferProtocol)))) == 2
        assert len(list(db.scalars(select(TransferBatch)))) == 2
        assert len(list(db.scalars(select(OfficialDocument)))) == 6
        assert len(list(db.scalars(select(DocumentSignature)))) == 12
        assert set(signatures_before).issubset(db.scalars(select(DocumentSignature.id)))
        assert versions_before == [(row.id, row.snapshot_sha256, row.signing_sha256, row.docx_sha256, row.pdf_sha256)
                                   for row in db.scalars(select(OfficialDocumentVersion).where(
                                       OfficialDocumentVersion.document_id.in_(issue_document_ids)))]
        before = fingerprint(db)
    operations = read(client, auth_headers, "/api/transfer-batches")
    assert [item["operation"] for item in operations] == ["RETURN", "ISSUE"]
    result = lifecycles(client, auth_headers)
    assert [item["batch_id"] for item in result] == [issued["batch_id"]]
    progress(result[0], 2, 2, 0)
    assert result[0]["status"] == "RETURNED"
    assert result[0]["cancellable_batch_ids"] == []
    operation = result[0]["return_operations"][0]
    assert operation["batch_id"] == returned["batch_id"]
    assert operation["signing_document_id"] == returned["signing_document_id"]
    assert operation["batch_manifest_sha256"] == returned["batch_manifest_sha256"]
    for batch_id, kind in ((issued["batch_id"], "ISSUE"), (returned["batch_id"], "RETURN")):
        details = read(client, auth_headers, f"/api/transfer-batches/{batch_id}")
        assert details["operation"] == kind
        for transfer in details["transfers"]:
            for key in ("issue_documents", "return_documents"):
                assert {doc["format"] for doc in transfer[key]} == {"docx", "pdf"}
                for document in transfer[key]:
                    downloaded = client.get(document["download_endpoint"], headers=auth_headers)
                    assert downloaded.status_code == 200
                    assert downloaded.content.startswith(b"PK" if document["format"] == "docx" else b"%PDF")
        archive = client.get(details["zip_download_endpoint"], headers=auth_headers)
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            assert len(zipped.namelist()) == 8
    with session_factory() as db:
        assert fingerprint(db) == before


@pytest.mark.parametrize("sizes", [(1, 1), (2, 1, 1)])
def test_successive_partial_returns_keep_one_lifecycle(
    client, auth_headers, issue_payload, qa_machines, sizes
):
    total = sum(sizes)
    issued = issue(client, auth_headers, issue_payload, qa_machines[:total])
    offset = 0
    operation_ids = []
    for size in sizes:
        returned = receive(client, auth_headers, issued["transfers"][offset:offset + size])
        operation_ids.append(returned["batch_id"])
        offset += size
        result = lifecycles(client, auth_headers)
        assert len(result) == 1 and result[0]["batch_id"] == issued["batch_id"]
        progress(result[0], total, offset, total - offset)
        assert result[0]["status"] == ("RETURNED" if offset == total else "PARTIALLY_RETURNED")
        assert [op["batch_id"] for op in result[0]["return_operations"]] == operation_ids[::-1]
        assert len(read(client, auth_headers, "/api/transfer-batches")) == 1 + len(operation_ids)


def test_independent_batches_and_reissue_same_machine_remain_distinct(
    client, auth_headers, issue_payload, qa_machines, session_factory
):
    first = issue(client, auth_headers, issue_payload, qa_machines[:2])
    second = issue(client, auth_headers, issue_payload, qa_machines[2:4])
    receive(client, auth_headers, first["transfers"])
    receive(client, auth_headers, second["transfers"])
    later = issue(client, auth_headers, issue_payload, qa_machines[:1])
    # Equal timestamps and misleading reference prefixes must not change identity/order.
    with session_factory() as db:
        for batch in db.scalars(select(TransferBatch)):
            batch.created_at = datetime(2026, 1, 1)
            batch.batch_reference = f"QA-IDENTICAL-SHAPE-{batch.id}"
        db.commit()
    result = lifecycles(client, auth_headers)
    assert [row["batch_id"] for row in result] == [later["batch_id"], second["batch_id"], first["batch_id"]]
    progress(result[0], 1, 0, 1)
    for item in result[1:]:
        progress(item, 2, 2, 0)
    assert first["transfers"][0]["transfer_id"] != later["transfers"][0]["transfer_id"]
    assert not result[0]["return_operations"]


def test_pending_cross_batch_return_cancels_exact_operation_and_preserves_issue(
    client, auth_headers, issue_payload, qa_machines, session_factory
):
    first = issue(client, auth_headers, issue_payload, qa_machines[:2])
    second = issue(client, auth_headers, issue_payload, qa_machines[2:4])
    selection = [first["transfers"][0], second["transfers"][0]]
    pending = receive(client, auth_headers, selection, sign=False)
    for lifecycle in lifecycles(client, auth_headers):
        assert lifecycle["cancellable_batch_ids"] == [pending["batch_id"]]
        op = lifecycle["return_operations"][0]
        assert op["issue_batch_ids"] == [first["batch_id"], second["batch_id"]]
        assert op["signing_status"] == "AWAITING_SIGNATURE"
    # Targeting either issue is rejected before any history or signing mutation.
    with session_factory() as db:
        before = fingerprint(db)
    for issued in (first, second):
        response = client.post(f"/api/transfer-batches/{issued['batch_id']}/cancel",
                               headers=auth_headers, json={"reason": "QA wrong target"})
        assert response.status_code == 409
    with session_factory() as db:
        assert fingerprint(db) == before
    response = client.post(f"/api/transfer-batches/{pending['batch_id']}/cancel",
                           headers=auth_headers, json={"reason": "QA cancelled return"})
    assert response.status_code == 200
    assert response.json()["cancelled_transfers"] == 2
    assert response.json()["invalidated_signing_sessions"] == 2
    for task in pending["signing_tasks"]:
        assert client.get(task["signing_endpoint"]).status_code != 200
    for item in lifecycles(client, auth_headers):
        progress(item, 2, 0, 2)
        assert item["status"] == "ACTIVE"
        assert not item["cancellable_batch_ids"]
        assert item["return_operations"][0]["signing_status"] == "CANCELLED"
    # A retry is a fresh operation; old cancelled history must never become cancellable.
    completed = receive(client, auth_headers, selection)
    for item in lifecycles(client, auth_headers):
        progress(item, 2, 1, 1)
        assert [op["batch_id"] for op in item["return_operations"]] == [completed["batch_id"], pending["batch_id"]]
        assert not item["cancellable_batch_ids"]
    old = read(client, auth_headers, f"/api/transfer-batches/{pending['batch_id']}")
    assert old["status"] == "CANCELLED" and not old["cancellable_batch_ids"]
    assert old["returned_machines"] == 0 and old["awaiting_signature_machines"] == 0
    assert all(t["return_status"] == "CANCELLED" and t["return_documents"] == [] for t in old["transfers"])
    assert all(t["returned_at"] is None for t in old["transfers"])
    for value, expected_files in ((pending, 4), (completed, 8)):
        archive = client.get(f"/api/transfer-batches/{value['batch_id']}/documents.zip", headers=auth_headers)
        assert archive.status_code == 200
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            assert len(zipped.namelist()) == expected_files
    for issued in (first, second):
        detail = read(client, auth_headers, f"/api/transfer-batches/{issued['batch_id']}")
        assert sum(len(t["return_documents"]) for t in detail["transfers"]) == 2
    with session_factory() as db:
        assert db.get(TransferBatch, pending["batch_id"]).cancellation_reason == "QA cancelled return"
        assert len(list(db.scalars(select(TransferProtocol)))) == 4


def test_pending_issue_and_completed_history_cancellation(
    client, auth_headers, issue_payload, qa_machines
):
    pending = issue(client, auth_headers, issue_payload, qa_machines[:2], sign=False)
    assert lifecycles(client, auth_headers)[0]["cancellable_batch_ids"] == [pending["batch_id"]]
    cancelled = client.post(f"/api/transfer-batches/{pending['batch_id']}/cancel",
                            headers=auth_headers, json={"reason": "QA cancelled issue"})
    assert cancelled.status_code == 200
    assert lifecycles(client, auth_headers)[0]["status"] == "CANCELLED"
    later = issue(client, auth_headers, issue_payload, qa_machines[:2])
    returned = receive(client, auth_headers, later["transfers"])
    for value in (later, returned):
        response = client.post(f"/api/transfer-batches/{value['batch_id']}/cancel",
                               headers=auth_headers, json={"reason": "QA cannot cancel history"})
        assert response.status_code == 409
    assert len(lifecycles(client, auth_headers)) == 2


def test_legacy_issue_without_manifest_and_view_validation(
    client, auth_headers, issue_payload, qa_machines, session_factory
):
    issued = issue(client, auth_headers, issue_payload, qa_machines[:1])
    with session_factory() as db:
        batch = db.get(TransferBatch, issued["batch_id"])
        # Legacy records predate batch signing; fixture-only historical shape.
        batch.issue_manifest = None
        batch.issue_manifest_sha256 = None
        batch.issue_signing_document_id = None
        batch.issue_signing_status = None
        batch.batch_reference = "RET-IS-ONLY-TEXT"
        db.commit()
    receive(client, auth_headers, issued["transfers"])
    result = lifecycles(client, auth_headers)
    assert len(result) == 1 and result[0]["batch_id"] == issued["batch_id"]
    assert result[0]["batch_reference"] == "RET-IS-ONLY-TEXT"
    progress(result[0], 1, 1, 0)
    assert client.get("/api/transfer-batches?view=unknown", headers=auth_headers).status_code == 422
    assert client.get("/api/transfer-batches?view=lifecycles").status_code == 401
