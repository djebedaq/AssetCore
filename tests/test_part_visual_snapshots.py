from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from alembic import command
from app.documents.part_request_documents import (
    _request_snapshot,
    build_part_request_docx,
    build_part_request_pdf,
)
from app.models import (
    AuditLog,
    CatalogPositionHotspot,
    PartCatalog,
    PartHotspot,
    PartRequest,
    PartRequestLine,
    PartVisualArtifact,
    PartVisualOccurrence,
    PartVisualSnapshot,
    RepairKit,
    RepairKitComponent,
    TechnicalDocument,
    TechnicalDocumentRevision,
)
from app.part_requests import visual_snapshots
from app.part_requests.service import load_request
from PIL import Image
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError
from test_migrations import _run_sqlite_revision
from visual_snapshot_cases import future_catalog, request_payload


def _create(client, headers, data, **extra):
    response = client.post(
        "/api/part-requests/multi", headers=headers, json={**request_payload(data), **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _url(request):
    return f"/api/part-requests/{request['id']}/lines/{request['lines'][0]['id']}/visual-snapshot"


def _unknown(client, headers, data):
    output = io.BytesIO()
    Image.new("RGB", (8, 8)).save(output, "PNG")
    response = client.post(
        "/api/part-requests/unknown",
        headers=headers,
        json={
            "machine_id": data["machine_id"],
            "assembly": "QA original assembly",
            "description": "QA original unknown",
            "quantity": 2,
            "note": "QA original note",
            "photo": {
                "filename": "qa-unknown.png",
                "media_type": "image/png",
                "content_base64": base64.b64encode(output.getvalue()).decode(),
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _counts(factory):
    with factory() as db:
        return tuple(
            db.scalar(select(func.count()).select_from(model))
            for model in (
                PartRequest,
                PartRequestLine,
                PartVisualSnapshot,
                PartVisualOccurrence,
                PartVisualArtifact,
                AuditLog,
            )
        )


def test_future_catalog_all_occurrences_and_malicious_metadata(
    client, auth_headers, session_factory
):
    data = future_catalog(session_factory)
    request = _create(client, auth_headers, data)
    line = request["lines"][0]
    assert line["catalog_part_id"] == data["part_id"]
    assert line["description"] == "Synthetic QA rotor"
    snapshot = line["visual_reference"]["snapshot"]
    assert snapshot["capture_origin"] == "REQUEST_CREATION"
    assert snapshot["source_id"] == "QA-FUTURE-SOURCE"
    assert snapshot["catalog"]["source_version"] == "QA-REV-42"
    assert snapshot["catalog"]["source_document_sha256"] == data["sha256"]
    assert snapshot["catalog"]["part_number"] == "QA-991122"
    assert snapshot["catalog"]["source_page"] == 2
    assert snapshot["catalog"]["position"] == "QA-P7"
    assert "FALSE" not in json.dumps(snapshot)
    refs = snapshot["visual_references"]
    assert len(refs) == 4
    assert [r["ordinal"] for r in refs] == [1, 2, 3, 4]
    assert [r["page_number"] for r in refs] == [2, 1, 1, 2]
    assert {r["source_kind"] for r in refs} == {"PART_HOTSPOT", "POSITION_HOTSPOT"}
    assert {r["artifact_sha256"] for r in refs} == {data["sha256"]}
    assert all(r["source_metadata"]["revision_id"] == data["revision_id"] for r in refs)
    assert client.get(_url(request), headers=auth_headers).json() == line["visual_reference"]
    second = _create(client, auth_headers, data)
    assert second["lines"][0]["visual_reference"]["snapshot"]["id"] != snapshot["id"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PartVisualArtifact)) == 1
    binary = client.get(_url(request) + "/artifacts/" + data["sha256"], headers=auth_headers)
    assert binary.status_code == 200 and binary.content == data["content"]


def test_live_mutation_deletion_and_new_revision_cannot_change_history(
    client, auth_headers, session_factory
):
    data = future_catalog(session_factory)
    request = _create(client, auth_headers, data)
    before = client.get(_url(request), headers=auth_headers).content
    with session_factory() as db:
        part = db.get(PartCatalog, data["part_id"])
        part.description, part.part_number, part.replaced_by_part_number = (
            "QA changed",
            "QA changed",
            "QA replaced",
        )
        part.source_version, part.revision, part.is_active = "QA-NEW", "QA-NEW", False
        part.source_document = "qa-changed.pdf"
        hotspots = db.scalars(
            select(CatalogPositionHotspot).where(
                CatalogPositionHotspot.diagram_id.in_(data["diagram_ids"])
            )
        ).all()
        hotspots[0].x, hotspots[0].position, hotspots[0].is_verified = 0.7, "QA-NEW", False
        db.delete(hotspots[1])
        db.add(
            CatalogPositionHotspot(
                hotspot_key="QA-added-later",
                diagram_id=data["diagram_ids"][0],
                position="QA-P7",
                x=0.1,
                y=0.1,
                width=0.1,
                height=0.1,
                provenance="QA later",
                is_verified=True,
            )
        )
        direct = db.scalar(select(PartHotspot).where(PartHotspot.part_id == part.id))
        direct.label, direct.x, direct.is_verified = "QA new label", 0.8, False
        document = db.get(TechnicalDocument, data["document_id"])
        document.title, document.revision = "QA replaced", "QA-43"
        document.uploaded_content, document.sha256 = (
            b"QA replaced bytes",
            hashlib.sha256(b"QA replaced bytes").hexdigest(),
        )
        db.add(
            TechnicalDocumentRevision(
                document_id=document.id,
                version=43,
                revision_label="QA-43",
                filename="qa-new.pdf",
                media_type="application/pdf",
                content=document.uploaded_content,
                sha256=document.sha256,
            )
        )
        db.delete(db.get(TechnicalDocumentRevision, data["revision_id"]))
        db.commit()
    after = client.get(_url(request), headers=auth_headers).content
    assert hashlib.sha256(before).hexdigest() == hashlib.sha256(after).hexdigest()
    assert before == after
    assert (
        client.get(_url(request) + "/artifacts/" + data["sha256"], headers=auth_headers).content
        == data["content"]
    )


def test_no_hotspots_is_valid_catalog_provenance(client, auth_headers, session_factory):
    data = future_catalog(session_factory, visuals=False)
    request = _create(client, auth_headers, data)
    result = request["lines"][0]["visual_reference"]
    assert result["state"] == "no_visual_reference_at_capture"
    assert result["snapshot"]["visual_references"] == []
    assert result["snapshot"]["source_record_key"] == "QA-FUTURE-SOURCE:row17"


def test_unknown_link_preserves_original_and_is_idempotent(client, auth_headers, session_factory):
    data = future_catalog(session_factory)
    request = _unknown(client, auth_headers, data)
    original = request["lines"][0]
    assert original["visual_reference"] == {"state": "no_catalog_binding", "snapshot": None}
    link_url = _url(request).replace("visual-snapshot", "link-catalog-part")
    linked = client.post(link_url, headers=auth_headers, json={"catalog_part_id": data["part_id"]})
    assert linked.status_code == 200, linked.text
    line = linked.json()["lines"][0]
    snapshot = line["visual_reference"]["snapshot"]
    assert snapshot["capture_origin"] == "CATALOG_LINK"
    assert snapshot["captured_at"] == line["linked_at"]
    for key in ("description", "assembly", "note", "part_number", "catalog_part_id"):
        assert line[key] == original[key]
    assert linked.json()["attachments"] == request["attachments"]
    repeated = client.post(
        link_url, headers=auth_headers, json={"catalog_part_id": data["part_id"]}
    )
    assert repeated.status_code == 200
    assert repeated.json()["lines"][0]["visual_reference"] == line["visual_reference"]
    with session_factory() as db:
        db.get(PartCatalog, data["part_id"]).description = "QA changed after link"
        db.commit()
    assert client.get(_url(request), headers=auth_headers).json() == line["visual_reference"]


@pytest.mark.parametrize("link", [False, True])
def test_capture_failure_rolls_back_everything(
    client, auth_headers, session_factory, monkeypatch, link
):
    data = future_catalog(session_factory)
    request = _unknown(client, auth_headers, data) if link else None
    before = _counts(session_factory)
    original_capture = visual_snapshots._occurrences

    def fail_after_artifact(db, part):
        original_capture(db, part)
        raise RuntimeError("QA forced failure after artifact persistence")

    monkeypatch.setattr(visual_snapshots, "_occurrences", fail_after_artifact)
    response = (
        client.post(
            _url(request).replace("visual-snapshot", "link-catalog-part"),
            headers=auth_headers,
            json={"catalog_part_id": data["part_id"]},
        )
        if link
        else client.post(
            "/api/part-requests/multi", headers=auth_headers, json=request_payload(data)
        )
    )
    assert response.status_code == 500
    assert _counts(session_factory) == before
    if link:
        with session_factory() as db:
            line = db.get(PartRequestLine, request["lines"][0]["id"])
            assert line.linked_at is None and line.linked_catalog_part_id is None


def test_legacy_read_and_documents_have_no_invented_snapshot(client, auth_headers, session_factory):
    data = future_catalog(session_factory)
    with session_factory() as db:
        request = PartRequest(
            machine_id=data["machine_id"], part_name="QA legacy", status="APPROVED"
        )
        db.add(request)
        db.flush()
        line = PartRequestLine(
            request_id=request.id,
            catalog_part_id=data["part_id"],
            description="QA legacy",
            quantity=1,
        )
        db.add(line)
        db.commit()
        request_id, line_id = request.id, line.id
        assert "visual_snapshot" not in _request_snapshot(request)["lines"][0]
        assert build_part_request_docx(request).startswith(b"PK")
        assert build_part_request_pdf(request).startswith(b"%PDF")
    result = client.get(
        f"/api/part-requests/{request_id}/lines/{line_id}/visual-snapshot", headers=auth_headers
    )
    assert result.json() == {"state": "legacy_snapshot_unavailable", "snapshot": None}


def test_repair_kit_components_and_aggregate(client, auth_headers, session_factory):
    data = future_catalog(session_factory)
    with session_factory() as db:
        kit = RepairKit(
            code="QA-FUTURE-KIT", name="QA kit", is_approved=True, created_by_id=data["actor_id"]
        )
        db.add(kit)
        db.flush()
        db.add(RepairKitComponent(kit_id=kit.id, part_id=data["part_id"], quantity=1))
        db.commit()
        kit_id = kit.id
    components = _create(
        client, auth_headers, data, repair_kit_id=kit_id, repair_kit_mode="COMPONENTS"
    )
    assert components["lines"][0]["visual_reference"]["snapshot"]
    aggregate = _create(
        client,
        auth_headers,
        data,
        repair_kit_id=kit_id,
        repair_kit_mode="KIT",
        lines=[{"description": "QA client kit", "quantity": 1}],
    )
    assert aggregate["lines"][0]["visual_reference"] == {
        "state": "no_catalog_binding",
        "snapshot": None,
    }


def test_authorization_ownership_and_document_reference(
    client, auth_headers, viewer_headers, session_factory
):
    data = future_catalog(session_factory)
    request = _create(client, auth_headers, data)
    url = _url(request)
    assert client.get(url).status_code == 401
    assert client.get(url + "/artifacts/" + data["sha256"]).status_code == 401
    assert client.get(url, headers=viewer_headers).status_code == 403
    assert (
        client.get(url + "/artifacts/" + data["sha256"], headers=viewer_headers).status_code == 403
    )
    assert (
        client.get(
            url.replace(f"/{request['id']}/lines", "/999999/lines"), headers=auth_headers
        ).status_code
        == 404
    )
    assert client.get(url + "/artifacts/" + "0" * 64, headers=auth_headers).status_code == 404
    assert (
        client.post(
            "/api/part-requests/multi", headers=viewer_headers, json=request_payload(data)
        ).status_code
        == 403
    )
    with session_factory() as db:
        stored = load_request(db, request["id"])
        reference = _request_snapshot(stored)["lines"][0]["visual_snapshot"]
        snap = request["lines"][0]["visual_reference"]["snapshot"]
        assert reference == {"id": snap["id"], "sha256": snap["sha256"]}
    assert "file_path" not in json.dumps(snap)


@pytest.mark.parametrize("model", [PartVisualSnapshot, PartVisualOccurrence, PartVisualArtifact])
def test_database_rejects_mutation_and_deletion(client, auth_headers, session_factory, model):
    data = future_catalog(session_factory)
    _create(client, auth_headers, data)
    field = {
        PartVisualSnapshot: "source_id",
        PartVisualOccurrence: "page_number",
        PartVisualArtifact: "byte_length",
    }[model]
    with session_factory() as db:
        with pytest.raises(DBAPIError, match="immutable_part_visual_history"):
            db.execute(update(model).values({field: "QA changed" if field == "source_id" else 8}))
            db.commit()
        db.rollback()
        with pytest.raises(DBAPIError, match="immutable_part_visual_history"):
            db.execute(delete(model))
            db.commit()


def test_corrupt_source_fails_closed_and_rolls_back(client, auth_headers, session_factory):
    data = future_catalog(session_factory)
    with session_factory() as db:
        db.get(TechnicalDocumentRevision, data["revision_id"]).content = b"QA tampered source"
        db.commit()
    before = _counts(session_factory)
    response = client.post(
        "/api/part-requests/multi", headers=auth_headers, json=request_payload(data)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "visual_snapshot_source_integrity_failed"
    assert _counts(session_factory) == before


def test_migration_upgrade_from_base_and_fresh_database(tmp_path: Path):
    import sqlite3

    path = tmp_path / "visual-migration.db"
    _run_sqlite_revision(path, command.upgrade, "head")
    _run_sqlite_revision(path, command.downgrade, "20260826_0021")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO part_requests(id, part_name, quantity, priority, status, created_at) VALUES (990, 'QA legacy', 1, 'NORMAL', 'DRAFT', '2026-01-01')"
        )
        connection.execute(
            "INSERT INTO part_request_lines(id, request_id, description, quantity) VALUES (991, 990, 'QA historical', 1)"
        )
    _run_sqlite_revision(path, command.upgrade, "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM part_visual_snapshots").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT description FROM part_request_lines WHERE id=991"
            ).fetchone()[0]
            == "QA historical"
        )
        assert connection.execute("PRAGMA foreign_key_list(part_visual_snapshots)").fetchall()
        assert (
            connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name LIKE '%part_visual%'"
            ).fetchone()[0]
            == 7
        )
