from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

from app.models import (
    AuditLog,
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    PartRequestLine,
    User,
)
from app.part_requests.service import load_request
from app.security import hash_password
from app.workflow import business_conflict
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql


def _add_user(session_factory, *, email: str, role: str) -> None:
    with session_factory() as session:
        session.add(
            User(
                email=email,
                full_name=f"Test {role}",
                first_name="Test",
                middle_name="Canonical",
                last_name=role.title(),
                job_title=f"Test {role}",
                profile_status="PROFILE_COMPLETE",
                password_hash=hash_password("StrongPass123!"),
                role=role,
                preferred_language="bg",
                is_active=True,
            )
        )
        session.commit()


def _login(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "StrongPass123!"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_postgresql_lock_targets_only_the_canonical_request_row():
    class CapturingSession:
        bind = SimpleNamespace(dialect=postgresql.dialect())
        statement = None

        def scalar(self, statement):
            self.statement = statement
            return None

    session = CapturingSession()
    assert load_request(session, 42, lock=True) is None
    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE OF part_requests" in sql


def _catalog_payload(client, headers, machine_id: int, *, submit: bool) -> tuple[dict, dict]:
    part = client.get("/api/catalog/parts", headers=headers).json()[0]
    payload = {
        "machine_id": machine_id,
        "priority": "NORMAL",
        "language": "bg",
        "reason": "test-only canonical catalog request",
        "submit_for_approval": submit,
        "lines": [
            {
                "catalog_part_id": part["id"],
                "position": part["position"],
                "part_number": part["part_number"],
                "description": part["description"],
                "quantity": 2,
                "unit": part["unit"],
                "source_document": part["source_document"],
                "source_page": part["source_page"],
            }
        ],
    }
    return part, payload


def _create_approved_request(client, headers, machine_id: int) -> tuple[dict, dict, dict]:
    part, payload = _catalog_payload(client, headers, machine_id, submit=True)
    created = client.post("/api/part-requests/multi", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    approved = client.post(
        f"/api/part-requests/{created.json()['id']}/decision",
        headers=headers,
        json={"decision": "APPROVED", "note": "test-only approval"},
    )
    assert approved.status_code == 200, approved.text
    return part, payload, created.json()


def test_catalog_create_and_submit_is_atomic_and_preserves_exact_line(
    client, auth_headers, machine_ids, session_factory
):
    part, payload = _catalog_payload(
        client, auth_headers, machine_ids["9"], submit=True
    )
    response = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=payload
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "WAITING_APPROVAL"
    assert body["submitted_at"] is not None
    assert body["machine_id"] == machine_ids["9"]
    assert body["requested_by_name"]
    assert len(body["lines"]) == 1
    assert body["lines"][0]["catalog_part_id"] == part["id"]
    assert body["lines"][0]["part_number"] == part["part_number"]
    assert body["lines"][0]["quantity"] == 2

    with session_factory() as session:
        stored = session.get(PartRequest, body["id"])
        line = session.scalar(
            select(PartRequestLine).where(PartRequestLine.request_id == body["id"])
        )
        assert stored.status == "WAITING_APPROVAL"
        assert line.catalog_part_id == part["id"]
        audits = session.scalars(
            select(AuditLog)
            .where(AuditLog.entity_type == "part_request", AuditLog.entity_id == body["id"])
            .order_by(AuditLog.id)
        ).all()
        assert [entry.action for entry in audits] == [
            "Създадена многоредова заявка за части",
            "Заявката е изпратена за одобрение",
        ]
        submitted_details = json.loads(audits[-1].details)
        assert submitted_details["previous_status"] == "DRAFT"
        assert submitted_details["new_status"] == "WAITING_APPROVAL"


def test_atomic_catalog_submit_rolls_back_request_lines_and_audit_on_failure(
    client, auth_headers, machine_ids, session_factory, monkeypatch
):
    import app.industrial_api as industrial_api

    _, payload = _catalog_payload(
        client, auth_headers, machine_ids["9"], submit=True
    )
    with session_factory() as session:
        before = (
            session.scalar(select(func.count(PartRequest.id))),
            session.scalar(select(func.count(PartRequestLine.id))),
            session.scalar(select(func.count(AuditLog.id))),
        )

    def fail_submit(*_args, **_kwargs):
        raise business_conflict(
            "test_atomic_submit_failure", "Тестов атомичен отказ."
        )

    monkeypatch.setattr(industrial_api, "submit_for_approval", fail_submit)
    response = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=payload
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "test_atomic_submit_failure"
    with session_factory() as session:
        after = (
            session.scalar(select(func.count(PartRequest.id))),
            session.scalar(select(func.count(PartRequestLine.id))),
            session.scalar(select(func.count(AuditLog.id))),
        )
    assert after == before


def test_pending_action_count_is_permission_aware_canonical_and_not_seen_state(
    client, auth_headers, machine_ids, session_factory, viewer_headers
):
    _add_user(
        session_factory, email="director-parts@example.invalid", role="director"
    )
    _add_user(
        session_factory, email="mechanic-parts@example.invalid", role="mechanic"
    )
    director_headers = _login(client, "director-parts@example.invalid")
    mechanic_headers = _login(client, "mechanic-parts@example.invalid")
    _, payload = _catalog_payload(
        client, auth_headers, machine_ids["9"], submit=True
    )
    created = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=payload
    )
    assert created.status_code == 201, created.text

    first_count = client.get(
        "/api/part-requests/pending-action-count", headers=director_headers
    )
    assert first_count.status_code == 200
    assert first_count.json() == {"pending_action_count": 1}
    assert client.get(
        "/api/part-requests/pending-action-count", headers=mechanic_headers
    ).json() == {"pending_action_count": 0}
    assert client.get(
        "/api/part-requests/pending-action-count", headers=viewer_headers
    ).status_code == 403

    assert client.get(
        "/api/part-requests/multi", headers=director_headers
    ).status_code == 200
    assert client.get(
        "/api/part-requests/pending-action-count", headers=director_headers
    ).json() == {"pending_action_count": 1}

    decision = client.post(
        f"/api/part-requests/{created.json()['id']}/decision",
        headers=director_headers,
        json={"decision": "APPROVED", "note": "test-only authorized decision"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["decided_by_name"] == "Test director"
    assert client.get(
        "/api/part-requests/pending-action-count", headers=auth_headers
    ).json() == {"pending_action_count": 0}
    assert client.get(
        "/api/part-requests/pending-action-count", headers=director_headers
    ).json() == {"pending_action_count": 0}


def test_legacy_draft_remains_visible_and_uses_canonical_submit(
    client, auth_headers, machine_ids
):
    _, payload = _catalog_payload(
        client, auth_headers, machine_ids["9"], submit=False
    )
    created = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=payload
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "DRAFT"
    listed = client.get("/api/part-requests/multi", headers=auth_headers)
    assert listed.status_code == 200
    assert created.json()["id"] in {item["id"] for item in listed.json()}
    submitted = client.post(
        f"/api/part-requests/{created.json()['id']}/submit", headers=auth_headers
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "WAITING_APPROVAL"


def test_official_part_request_documents_require_approval_and_are_registered(
    client, auth_headers, machine_ids, session_factory
):
    part, payload = _catalog_payload(
        client, auth_headers, machine_ids["9"], submit=True
    )
    created = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=payload
    )
    request_id = created.json()["id"]
    premature = client.post(
        f"/api/part-requests/{request_id}/documents", headers=auth_headers
    )
    assert premature.status_code == 409, premature.text
    assert premature.json()["detail"]["code"] == "part_request_not_approved"

    approved = client.post(
        f"/api/part-requests/{request_id}/decision",
        headers=auth_headers,
        json={"decision": "APPROVED", "note": "test-only approval"},
    )
    assert approved.status_code == 200, approved.text
    generated = client.post(
        f"/api/part-requests/{request_id}/documents?language=bg",
        headers=auth_headers,
    )
    assert generated.status_code == 201, generated.text
    body = generated.json()
    assert body["document_number"] == created.json()["request_reference"]
    assert {item["format"] for item in body["documents"]} == {"docx", "pdf"}
    assert all(
        item["download_endpoint"]
        == f"/generated-documents/{item['id']}/download"
        for item in body["documents"]
    )
    registry = client.get("/api/official-documents", headers=auth_headers)
    assert registry.status_code == 200, registry.text
    assert body["document_number"] in {
        item["document_number"] for item in registry.json()
    }

    with session_factory() as session:
        documents = session.scalars(
            select(GeneratedDocument).where(
                GeneratedDocument.part_request_id == request_id
            )
        ).all()
        assert len(documents) == 2
        assert all(item.snapshot["request_id"] == request_id for item in documents)
        assert all(item.snapshot["machine_id"] == machine_ids["9"] for item in documents)
        assert all(item.snapshot["reason"] == payload["reason"] for item in documents)
        assert all(item.snapshot["lines"][0]["catalog_part_id"] == part["id"] for item in documents)
        assert all(item.snapshot["lines"][0]["quantity"] == 2 for item in documents)
        official = session.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == body["document_number"]
            )
        )
        assert official is not None
        version = session.get(OfficialDocumentVersion, official.current_version_id)
        assert version is not None
        canonical_state = {
            "documents": sorted(
                (
                    document.id,
                    document.document_number,
                    document.format,
                    document.sha256,
                    json.dumps(document.snapshot, ensure_ascii=False, sort_keys=True),
                )
                for document in documents
            ),
            "official_id": official.id,
            "official_number": official.document_number,
            "version_id": version.id,
            "version_number": version.version,
            "snapshot_sha256": version.snapshot_sha256,
            "docx_sha256": version.docx_sha256,
            "pdf_sha256": version.pdf_sha256,
            "snapshot": json.dumps(version.snapshot, ensure_ascii=False, sort_keys=True),
        }
        assert version.snapshot["request_id"] == request_id
        assert version.snapshot["status"] == "APPROVED"
        assert version.snapshot["lines"][0]["catalog_part_id"] == part["id"]
        decision_audit = session.scalar(
            select(AuditLog).where(
                AuditLog.entity_type == "part_request",
                AuditLog.entity_id == request_id,
                AuditLog.action == "Решение по заявка за части",
            )
        )
        assert json.loads(decision_audit.details)["new_status"] == "APPROVED"

    repeated = client.post(
        f"/api/part-requests/{request_id}/documents?language=bg",
        headers=auth_headers,
    )
    assert repeated.status_code == 409, repeated.text
    assert repeated.json()["detail"]["code"] == "part_request_protocol_already_generated"
    assert repeated.json()["detail"]["document_number"] == body["document_number"]
    assert {item["format"] for item in repeated.json()["detail"]["documents"]} == {
        "docx",
        "pdf",
    }

    with session_factory() as session:
        documents = session.scalars(
            select(GeneratedDocument)
            .where(GeneratedDocument.part_request_id == request_id)
            .order_by(GeneratedDocument.id)
        ).all()
        official_documents = session.scalars(
            select(OfficialDocument).where(
                OfficialDocument.document_type == "PART_REQUEST",
                OfficialDocument.document_number == body["document_number"],
            )
        ).all()
        assert len(official_documents) == 1
        versions = session.scalars(
            select(OfficialDocumentVersion).where(
                OfficialDocumentVersion.document_id == official_documents[0].id
            )
        ).all()
        version = versions[0]
        repeated_state = {
            "documents": sorted(
                (
                    document.id,
                    document.document_number,
                    document.format,
                    document.sha256,
                    json.dumps(document.snapshot, ensure_ascii=False, sort_keys=True),
                )
                for document in documents
            ),
            "official_id": official_documents[0].id,
            "official_number": official_documents[0].document_number,
            "version_id": version.id,
            "version_number": version.version,
            "snapshot_sha256": version.snapshot_sha256,
            "docx_sha256": version.docx_sha256,
            "pdf_sha256": version.pdf_sha256,
            "snapshot": json.dumps(version.snapshot, ensure_ascii=False, sort_keys=True),
        }
        assert len(documents) == 2
        assert len(versions) == 1
        assert repeated_state == canonical_state
        assert not any("-V2" in document.document_number for document in documents)

    cancelled = client.patch(
        f"/api/part-requests/{request_id}/fulfillment",
        headers=auth_headers,
        json={"status": "CANCELLED", "lines": []},
    )
    assert cancelled.status_code == 200, cancelled.text
    listed = client.get("/api/part-requests/multi", headers=auth_headers)
    listed_request = next(item for item in listed.json() if item["id"] == request_id)
    assert {item["id"] for item in listed_request["documents"]} == {
        item["id"] for item in body["documents"]
    }
    for document in listed_request["documents"]:
        downloaded = client.get(
            f"/api{document['download_endpoint']}", headers=auth_headers
        )
        assert downloaded.status_code == 200, downloaded.text
    after_cancellation = client.post(
        f"/api/part-requests/{request_id}/documents?language=bg",
        headers=auth_headers,
    )
    assert after_cancellation.status_code == 409, after_cancellation.text
    assert after_cancellation.json()["detail"]["code"] == (
        "part_request_protocol_already_generated"
    )


def test_concurrent_part_request_generation_creates_one_canonical_protocol(
    client, auth_headers, machine_ids, session_factory
):
    _, _, created = _create_approved_request(
        client, auth_headers, machine_ids["9"]
    )
    barrier = Barrier(2)

    def generate() -> int:
        barrier.wait()
        return client.post(
            f"/api/part-requests/{created['id']}/documents?language=bg",
            headers=auth_headers,
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: generate(), range(2)))
    assert statuses == [201, 409]

    with session_factory() as session:
        documents = session.scalars(
            select(GeneratedDocument).where(
                GeneratedDocument.part_request_id == created["id"]
            )
        ).all()
        official_documents = session.scalars(
            select(OfficialDocument).where(
                OfficialDocument.document_type == "PART_REQUEST",
                OfficialDocument.document_number == created["request_reference"],
            )
        ).all()
        assert len(official_documents) == 1
        versions = session.scalars(
            select(OfficialDocumentVersion).where(
                OfficialDocumentVersion.document_id == official_documents[0].id
            )
        ).all()
        assert len(documents) == 2
        assert {document.format for document in documents} == {"docx", "pdf"}
        assert {document.document_number for document in documents} == {
            created["request_reference"]
        }
        assert len(versions) == 1


def test_cancelled_part_request_cannot_create_first_protocol(
    client, auth_headers, machine_ids, session_factory
):
    _, _, created = _create_approved_request(
        client, auth_headers, machine_ids["9"]
    )
    cancelled = client.patch(
        f"/api/part-requests/{created['id']}/fulfillment",
        headers=auth_headers,
        json={"status": "CANCELLED", "lines": []},
    )
    assert cancelled.status_code == 200, cancelled.text
    generated = client.post(
        f"/api/part-requests/{created['id']}/documents?language=bg",
        headers=auth_headers,
    )
    assert generated.status_code == 409, generated.text
    assert generated.json()["detail"]["code"] == (
        "part_request_cancelled_no_protocol_generation"
    )
    with session_factory() as session:
        assert session.scalar(
            select(func.count(GeneratedDocument.id)).where(
                GeneratedDocument.part_request_id == created["id"]
            )
        ) == 0
        assert session.scalar(
            select(func.count(OfficialDocument.id)).where(
                OfficialDocument.document_number == created["request_reference"]
            )
        ) == 0
