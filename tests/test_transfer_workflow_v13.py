from __future__ import annotations

import io
import zipfile

from app.models import (
    GeneratedDocument,
    Location,
    Machine,
    ProtocolDocument,
    Repair,
    TransferProtocol,
)
from sqlalchemy import func, select


def _issue(client, headers, issue_payload, finalize_signatures, *machine_ids: int):
    response = client.post(
        "/api/transfers/bulk-issue",
        headers=headers,
        json=issue_payload(*machine_ids),
    )
    assert response.status_code == 201, response.text
    finalize_signatures(client, response)
    return response.json()


def _return(client, headers, finalize_signatures, transfers: list[dict], status: str):
    response = client.post(
        "/api/transfers/bulk-return",
        headers=headers,
        json={
            "document_language": "bg",
            "items": [
                {
                    "transfer_id": transfer["transfer_id"],
                    "machine_id": transfer["machine_id"],
                    "condition_text": "Проверено състояние при приемане",
                    "result_text": "Резултат от приемния преглед",
                    "notes": "Проследима тестова бележка",
                    "next_status": status,
                }
                for transfer in transfers
            ],
        },
    )
    assert response.status_code == 200, response.text
    finalize_signatures(client, response)
    return response.json()


def test_batch_details_keep_issue_documents_and_add_real_return_documents(
    client,
    auth_headers,
    machine_ids,
    issue_payload,
    finalize_signatures,
    session_factory,
):
    issued = _issue(
        client,
        auth_headers,
        issue_payload,
        finalize_signatures,
        machine_ids["4"],
        machine_ids["5"],
    )
    before = client.get(
        f"/api/transfer-batches/{issued['batch_id']}", headers=auth_headers
    )
    assert before.status_code == 200, before.text
    before_body = before.json()
    assert before_body["machine_numbers"] == ["4", "5"]
    assert all(len(item["issue_documents"]) == 2 for item in before_body["transfers"])
    assert all(item["return_documents"] == [] for item in before_body["transfers"])
    issue_document_ids = {
        document["id"]
        for item in before_body["transfers"]
        for document in item["issue_documents"]
    }
    with session_factory() as session:
        original_hashes = {
            document.id: document.sha256
            for document in session.scalars(
                select(ProtocolDocument).where(
                    ProtocolDocument.id.in_(issue_document_ids)
                )
            )
        }

    returned = _return(
        client,
        auth_headers,
        finalize_signatures,
        issued["transfers"],
        "READY",
    )
    after = client.get(
        f"/api/transfer-batches/{issued['batch_id']}", headers=auth_headers
    ).json()
    assert all(len(item["issue_documents"]) == 2 for item in after["transfers"])
    assert all(len(item["return_documents"]) == 2 for item in after["transfers"])
    assert {
        document["id"]
        for item in after["transfers"]
        for document in item["issue_documents"]
    } == issue_document_ids
    with session_factory() as session:
        assert {
            document.id: document.sha256
            for document in session.scalars(
                select(ProtocolDocument).where(
                    ProtocolDocument.id.in_(issue_document_ids)
                )
            )
        } == original_hashes

    archive = client.get(
        f"/api/transfer-batches/{returned['batch_id']}/documents.zip",
        headers=auth_headers,
    )
    assert archive.status_code == 200, archive.text
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        names = zipped.namelist()
    assert len(names) == 8
    assert sum(name.endswith(".docx") for name in names) == 4
    assert sum(name.endswith(".pdf") for name in names) == 4


def test_return_for_repair_creates_one_traceable_case_and_blocks_reissue(
    client,
    auth_headers,
    machine_ids,
    issue_payload,
    finalize_signatures,
    session_factory,
):
    issued = _issue(
        client,
        auth_headers,
        issue_payload,
        finalize_signatures,
        machine_ids["7"],
    )
    transfer = issued["transfers"][0]
    returned = _return(
        client, auth_headers, finalize_signatures, [transfer], "REPAIR"
    )

    with session_factory() as session:
        repair = session.scalar(
            select(Repair).where(
                Repair.source_return_transfer_id == transfer["transfer_id"]
            )
        )
        assert repair is not None
        assert repair.source_return_document_id == returned["returned"][0][
            "official_document_id"
        ]
        assert repair.source_return_batch_id == returned["batch_id"]
        assert repair.status == "ACCEPTED"
        machine = session.get(Machine, transfer["machine_id"])
        workshop = session.scalar(select(Location).where(Location.name == "Цех"))
        assert machine.status == "REPAIR"
        assert machine.location_id == workshop.id

    availability = client.get(
        "/api/transfers/availability", headers=auth_headers
    ).json()
    item = next(value for value in availability if value["machine_id"] == transfer["machine_id"])
    assert item["available"] is False
    assert item["unavailable_reason"] == "Машина №7 е в ремонт."
    rejected_issue = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(transfer["machine_id"]),
    )
    assert rejected_issue.status_code == 409

    rejected_return = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": transfer["transfer_id"],
                    "machine_id": transfer["machine_id"],
                    "condition_text": "Повторно приемане",
                    "result_text": "Не трябва да бъде записано",
                    "next_status": "REPAIR",
                }
            ]
        },
    )
    assert rejected_return.status_code == 409
    with session_factory() as session:
        assert session.scalar(
            select(func.count(Repair.id)).where(
                Repair.source_return_transfer_id == transfer["transfer_id"]
            )
        ) == 1


def test_missing_workshop_rejects_return_without_partial_changes(
    client,
    auth_headers,
    machine_ids,
    issue_payload,
    finalize_signatures,
    session_factory,
):
    issued = _issue(
        client,
        auth_headers,
        issue_payload,
        finalize_signatures,
        machine_ids["4"],
    )
    transfer = issued["transfers"][0]
    with session_factory() as session:
        workshop = session.scalar(select(Location).where(Location.name == "Цех"))
        workshop.is_active = False
        session.commit()

    response = client.post(
        "/api/transfers/bulk-return",
        headers=auth_headers,
        json={
            "items": [
                {
                    "transfer_id": transfer["transfer_id"],
                    "machine_id": transfer["machine_id"],
                    "condition_text": "Проверено състояние",
                    "result_text": "Проверен резултат",
                    "next_status": "READY",
                }
            ]
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workshop_location_missing"
    with session_factory() as session:
        stored = session.get(TransferProtocol, transfer["transfer_id"])
        machine = session.get(Machine, transfer["machine_id"])
        assert stored.is_active is True
        assert stored.return_status is None
        assert machine.status == "ISSUED"
        assert session.scalar(
            select(func.count(GeneratedDocument.id)).where(
                GeneratedDocument.transfer_id == stored.id,
                GeneratedDocument.document_type == "TRANSFER_RETURN",
            )
        ) == 0


def test_inactive_ready_machine_is_not_available_or_issuable(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    with session_factory() as session:
        machine = session.get(Machine, machine_ids["4"])
        machine.is_active = False
        session.commit()

    availability = client.get(
        "/api/transfers/availability", headers=auth_headers
    ).json()
    item = next(value for value in availability if value["machine_id"] == machine_ids["4"])
    assert item["available"] is False
    assert "деактивирана" in item["unavailable_reason"]
    response = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert response.status_code == 409
    with session_factory() as session:
        assert session.scalar(select(func.count(TransferProtocol.id))) == 0


def test_inactive_issue_location_is_rejected_without_partial_transfer(
    client, auth_headers, machine_ids, issue_payload, session_factory
):
    with session_factory() as session:
        location = session.get(Location, 1)
        location.is_active = False
        session.commit()

    response = client.post(
        "/api/transfers/bulk-issue",
        headers=auth_headers,
        json=issue_payload(machine_ids["4"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "locations_unavailable"
    assert response.json()["detail"]["unavailable_location_ids"] == [1]
    with session_factory() as session:
        assert session.scalar(select(func.count(TransferProtocol.id))) == 0
