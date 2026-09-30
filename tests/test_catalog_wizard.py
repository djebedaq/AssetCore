"""UX-02 uses ephemeral QA records and the unchanged publication/document contract."""

import base64
import io

import pytest
from app.catalog_admin import parts
from app.documents import part_request_documents
from app.documents.part_request_grouped_visuals import prepare_appendix
from app.models import (
    AssetCategory,
    CatalogDefinition,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    GeneratedDocument,
    Machine,
    PartCatalog,
    PartVisualSnapshot,
)
from app.part_requests.service import load_request
from docx import Document
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_catalog_builder_parts import source as second_source

BASE = "/api/admin/catalog-builder"


def checked(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def simple_workspace(client, headers, factory):
    with factory() as db:
        category = AssetCategory(code="QA_WIZARD", name_bg="QA", name_en="QA", name_ru="QA",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.commit()
        category_id = category.id
    catalog = checked(client.post(f"{BASE}/simple/catalogs", headers=headers, json={
        "name": "QA проверка", "asset_category_id": category_id,
        "manufacturer": "QA", "model_reference": "QA",
    }), 201)
    revisions = checked(client.get(f"{BASE}/catalogs/{catalog['id']}/revisions", headers=headers))
    assert len(revisions) == 1 and revisions[0]["status"] == "DRAFT"
    assert revisions[0]["revision_code"] == "REV-1"
    assert catalog["name_bg"] == catalog["name_en"] == catalog["name_ru"] == "QA проверка"
    groups = [checked(client.post(f"{BASE}/revisions/{revisions[0]['id']}/groups", headers=headers,
                                 json={"name": name}), 201) for name in ["QA group A", "QA group B"]]
    pdf = io.BytesIO()
    doc = canvas.Canvas(pdf)
    for text in ["No. Part No. Item Qty", "Exploded view - QA assembly", "Part number Quantity", "Exploded view"]:
        doc.drawString(50, 700, text)
        doc.showPage()
    doc.save()
    artifact = checked(client.post(f"{BASE}/assemblies/{groups[0]['id']}/artifacts", headers=headers, json={
        "title": "QA original", "filename": "qa-original.pdf", "media_type": "application/pdf",
        "content_base64": base64.b64encode(pdf.getvalue()).decode(),
    }), 201)
    return catalog, revisions[0], groups, artifact


def classify(client, headers, artifact, group, numbers, roles):
    return client.post(f"{BASE}/artifacts/{artifact['id']}/classify", headers=headers, json={
        "assembly_id": group["id"], "page_numbers": numbers, "roles": roles,
    })


def preview(client, headers, revision, text):
    return client.post(f"{BASE}/revisions/{revision['id']}/parts/import-preview", headers=headers, json={
        "filename": "qa.csv", "content_base64": base64.b64encode(text.encode("utf-8")).decode(),
    })


def confirm(client, headers, revision, result):
    return client.post(f"{BASE}/revisions/{revision['id']}/parts/import-confirm", headers=headers,
                       json={"token": result["token"]})


def publish(client, headers, revision_id):
    ready = checked(client.get(f"{BASE}/revisions/{revision_id}/workflow", headers=headers))
    assert ready["ready"], ready
    return checked(client.post(f"{BASE}/revisions/{revision_id}/publish", headers=headers, json={
        "expected_publication_digest": ready["publication_digest"],
        "expected_current_published_revision_id": ready["current_published_revision_id"], "confirmed": True,
    }))


def test_simple_flow_late_binding_update_and_immutable_official_evidence(
    client, auth_headers, session_factory, monkeypatch,
):
    catalog, revision, groups, artifact = simple_workspace(client, auth_headers, session_factory)
    for index, group in enumerate(groups):
        checked(classify(client, auth_headers, artifact, group, [1 + 2 * index], ["SPARE_PARTS_LIST"]))
        checked(classify(client, auth_headers, artifact, group, [2 + 2 * index], ["EXPLODED_SCHEME"]))
    documents = checked(client.get(f"{BASE}/revisions/{revision['id']}/documents", headers=auth_headers))
    assert len(documents) == 1 and documents[0]["page_count"] == 4
    assert {page["assembly_id"] for page in documents[0]["assignments"]} == {group["id"] for group in groups}
    with session_factory() as db:
        artifacts = db.scalars(select(CatalogRevisionArtifact)).all()
        assert len(artifacts) == 2
        assert all(item.content == artifacts[0].content and item.sha256 == artifact["sha256"] for item in artifacts)
    csv = ("assembly_code,position,part_number,name,quantity,source_page\n"
           f"{groups[0]['code']},1,QA-A,QA name A,2,1\n{groups[1]['code']},2,QA-B,QA name B,1,3\n")
    result = checked(preview(client, auth_headers, revision, csv))
    assert result["summary"]["valid_rows"] == 2
    assert checked(confirm(client, auth_headers, revision, result))["created_count"] == 2
    for group in groups:
        part = checked(client.get(f"{BASE}/assemblies/{group['id']}/parts", headers=auth_headers))[0]
        assert part["validation_status"] == "READY" and len(part["source_pages"]) == 1
        page = checked(client.get(f"{BASE}/assemblies/{group['id']}/exploded-pages", headers=auth_headers))[0]
        hotspot = checked(client.post(f"{BASE}/visual-pages/{page['visual_page_id']}/hotspots", headers=auth_headers,
                          json={"position": part["position"], "x": .4, "y": .4, "width": .03, "height": .03}), 201)
        checked(client.post(f"{BASE}/hotspots/{hotspot['id']}/verify", headers=auth_headers,
                            json={"expected_version": hotspot["version"]}))
    summary = checked(client.get(f"{BASE}/revisions/{revision['id']}/workflow", headers=auth_headers))
    assert summary["resume_step"] == "review" and summary["progress"]["completed_positions"] == 2
    publish(client, auth_headers, revision["id"])
    assert classify(client, auth_headers, artifact, groups[0], [1], ["SPARE_PARTS_LIST"]).status_code == 409
    assert preview(client, auth_headers, revision, csv).status_code == 409
    assert client.post(f"{BASE}/revisions/{revision['id']}/groups", headers=auth_headers,
                       json={"name": "QA forbidden"}).status_code == 409
    with session_factory() as db:
        category = db.get(AssetCategory, catalog["asset_category_id"])
        machines = [Machine(inventory_number=f"QA_WIZARD_{letter}", name="QA ONLY",
                            category=category.code, category_id=category.id, brand="QA", model="QA",
                            serial_number=f"QA-SERIAL-{letter}") for letter in "ABC"]
        db.add_all(machines)
        db.commit()
        a, b, c = [machine.id for machine in machines]
    def runtime(machine_id):
        return checked(client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers))
    def published_rows():
        with session_factory() as db:
            return [{column.name: getattr(row, column.name) for column in PartCatalog.__table__.columns}
                    for row in db.scalars(select(PartCatalog).where(PartCatalog.builder_revision_id == revision["id"])).all()]
    checked(client.post(f"{BASE}/catalogs/{catalog['id']}/assets/{a}", headers=auth_headers), 201)
    assert runtime(a)["supported"] and not runtime(c)["supported"]
    rows_before = published_rows()
    assert checked(client.get(f"{BASE}/catalogs/{catalog['id']}/eligible-assets?search=QA-SERIAL-B", headers=auth_headers))[0]["id"] == b
    checked(client.post(f"{BASE}/catalogs/{catalog['id']}/assets/{b}", headers=auth_headers), 201)
    assert runtime(b)["supported"] and published_rows() == rows_before
    assert runtime(a)["assemblies"] == runtime(b)["assemblies"]
    source_id = runtime(a)["assemblies"][0]["source_id"]
    detail = checked(client.get(f"/api/catalog/v2/assemblies/{source_id}?machine_id={a}", headers=auth_headers))
    live_part = detail["parts"][0]
    request = checked(client.post("/api/part-requests/multi", headers=auth_headers, json={
        "machine_id": a, "submit_for_approval": True,
        "lines": [{"catalog_part_id": live_part["id"], "position": live_part["position"],
                   "description": "QA name A", "quantity": 1}],
    }), 201)
    checked(client.post(f"/api/part-requests/{request['id']}/decision", headers=auth_headers,
                        json={"decision": "APPROVED", "note": "QA"}))
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    checked(client.post(f"/api/part-requests/{request['id']}/documents?language=bg", headers=auth_headers), 201)
    with session_factory() as db:
        appendix = prepare_appendix(db, load_request(db, request["id"]))
        assert [page.role for page in appendix.pages] == ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]
        snapshot = db.scalar(select(PartVisualSnapshot).where(PartVisualSnapshot.line_id == request["lines"][0]["id"])).sha256
        generated = db.scalars(select(GeneratedDocument).where(GeneratedDocument.part_request_id == request["id"])).all()
        hashes = {item.format: item.sha256 for item in generated}
        assert set(hashes) == {"docx", "pdf"}
        docx_record = next(item for item in generated if item.format == "docx")
        docx_id = docx_record.id
    download = client.get(f"/api/generated-documents/{docx_id}/download", headers=auth_headers)
    assert download.status_code == 200, download.text
    document = Document(io.BytesIO(download.content))
    assert any([cell.text for cell in table.rows[0].cells] == part_request_documents.REQUEST_HEADERS["bg"]
               for table in document.tables)
    draft = checked(client.post(f"{BASE}/catalogs/{catalog['id']}/edit", headers=auth_headers), 201)
    assert draft["revision_code"] == "REV-2" and draft["status"] == "DRAFT"
    assert checked(client.post(f"{BASE}/catalogs/{catalog['id']}/edit", headers=auth_headers), 201)["id"] == draft["id"]
    new_groups = checked(client.get(f"{BASE}/revisions/{draft['id']}/assemblies", headers=auth_headers))
    new_part = checked(client.get(f"{BASE}/assemblies/{new_groups[0]['id']}/parts", headers=auth_headers))[0]
    checked(client.patch(f"{BASE}/parts/{new_part['id']}", headers=auth_headers, json={"name_en": "QA updated"}))
    publish(client, auth_headers, draft["id"])
    for machine in (a, b):
        new_source = runtime(machine)["assemblies"][0]["source_id"]
        updated = checked(client.get(f"/api/catalog/v2/assemblies/{new_source}?machine_id={machine}", headers=auth_headers))
        assert updated["parts"][0]["description_en"] == "QA updated"
    assert not runtime(c)["supported"]
    with session_factory() as db:
        assert db.get(CatalogRevision, revision["id"]).status == "RETIRED"
        assert db.scalar(select(PartVisualSnapshot).where(PartVisualSnapshot.line_id == request["lines"][0]["id"])).sha256 == snapshot
        assert {item.format: item.sha256 for item in db.scalars(select(GeneratedDocument).where(
            GeneratedDocument.part_request_id == request["id"])).all()} == hashes


@pytest.mark.parametrize("row,error", [
    ("MISSING,1,QA-X,QA,1", "catalog_import_group_missing"),
    ("{code},1,QA-X,QA,2", "catalog_part_import_page_missing"),
    ("{code},1,QA-X,QA,", "catalog_part_import_page_required"),
    ("{code},,QA-X,QA,1", "catalog_part_invalid"),
])
def test_whole_import_errors_are_atomic(client, auth_headers, session_factory, row, error):
    _, revision, groups, artifact = simple_workspace(client, auth_headers, session_factory)
    checked(classify(client, auth_headers, artifact, groups[0], [1], ["SPARE_PARTS_LIST"]))
    text = "assembly_code,position,part_number,name,source_page\n" + row.format(code=groups[0]["code"]) + "\n"
    result = checked(preview(client, auth_headers, revision, text))
    assert error in result["rows"][0]["errors"]
    assert confirm(client, auth_headers, revision, result).status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 0


def test_document_roles_suggestions_protection_and_import_stale(client, auth_headers, viewer_headers, session_factory):
    catalog, revision, groups, artifact = simple_workspace(client, auth_headers, session_factory)
    hint = checked(client.get(f"{BASE}/artifacts/{artifact['id']}/suggestions", headers=auth_headers))
    assert hint["requires_confirmation"] and hint["pages"][0]["suggested_role"] == "SPARE_PARTS_LIST"
    assert checked(client.get(f"{BASE}/revisions/{revision['id']}/documents", headers=auth_headers))[0]["assignments"] == []
    checked(classify(client, auth_headers, artifact, groups[0], [1, 2], ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]))
    assert len(checked(client.get(f"{BASE}/revisions/{revision['id']}/documents", headers=auth_headers))[0]["assignments"]) == 4
    checked(classify(client, auth_headers, artifact, groups[0], [2], []))
    text = f"assembly_code,position,part_number,name,source_page\n{groups[0]['code']},1,QA-X,QA,1\n"
    result = checked(preview(client, auth_headers, revision, text))
    checked(classify(client, auth_headers, artifact, groups[1], [3], ["SPARE_PARTS_LIST"]))
    assert confirm(client, auth_headers, revision, result).status_code == 409
    result = checked(preview(client, auth_headers, revision, text))
    tampered = {**result, "token": result["token"] + "x"}
    assert confirm(client, auth_headers, revision, tampered).status_code == 422
    checked(confirm(client, auth_headers, revision, result))
    assert classify(client, auth_headers, artifact, groups[1], [1], ["SPARE_PARTS_LIST"]).status_code == 409
    assert classify(client, auth_headers, artifact, groups[0], [1], []).status_code == 409
    assert classify(client, auth_headers, artifact, groups[0], [1], ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]).status_code == 200
    template = client.get(f"{BASE}/revisions/{revision['id']}/parts/template", headers=auth_headers)
    assert template.status_code == 200 and template.content.startswith(b"\xef\xbb\xbf")
    assert "assembly_code,position,part_number,name" in template.content.decode("utf-8-sig")
    second_catalog = checked(client.post(f"{BASE}/simple/catalogs", headers=auth_headers, json={
        "name": "QA проверка", "asset_category_id": catalog["asset_category_id"],
    }), 201)
    assert second_catalog["code"] != catalog["code"]
    other_revision = checked(client.get(f"{BASE}/catalogs/{second_catalog['id']}/revisions", headers=auth_headers))[0]
    other_group = checked(client.post(f"{BASE}/revisions/{other_revision['id']}/groups", headers=auth_headers, json={"name": "QA"}), 201)
    assert classify(client, auth_headers, artifact, other_group, [1], ["SPARE_PARTS_LIST"]).status_code == 422
    for path in [f"/revisions/{revision['id']}/workflow", f"/revisions/{revision['id']}/documents",
                 f"/artifacts/{artifact['id']}/suggestions", f"/revisions/{revision['id']}/parts/template"]:
        assert client.get(BASE + path, headers=viewer_headers).status_code == 403
    assert client.post(f"{BASE}/catalogs/{catalog['id']}/edit", headers=viewer_headers).status_code == 403
    assert client.post(f"{BASE}/simple/catalogs", headers=auth_headers, json={
        "name": "   ", "asset_category_id": catalog["asset_category_id"],
    }).status_code == 422
    with session_factory() as db:
        assert db.get(CatalogDefinition, catalog["id"]).is_active


def test_whole_import_duplicate_ambiguity_and_rollback_across_groups(
    client, auth_headers, session_factory, monkeypatch,
):
    _, revision, groups, artifact = simple_workspace(client, auth_headers, session_factory)
    for index, group in enumerate(groups):
        checked(classify(client, auth_headers, artifact, group, [1 + 2 * index], ["SPARE_PARTS_LIST"]))
    headers = "assembly_code,position,part_number,name,source_page,source_artifact_sha256\n"
    row = f"{groups[0]['code']},1,QA-X,QA,1,{artifact['sha256']}\n"
    duplicate = checked(preview(client, auth_headers, revision, headers + row + row))
    assert "catalog_part_import_duplicate_row" in duplicate["rows"][1]["errors"]
    assert confirm(client, auth_headers, revision, duplicate).status_code == 409
    _, _, _, other_sha = second_source(client, auth_headers, groups[0]["id"], "QA second source")
    ambiguous = checked(preview(client, auth_headers, revision,
                                f"assembly_code,position,part_number,name,source_page\n{groups[0]['code']},1,QA-X,QA,1\n"))
    assert "catalog_part_import_page_ambiguous" in ambiguous["rows"][0]["errors"]
    explicit = checked(preview(client, auth_headers, revision, headers + row))
    assert explicit["summary"]["valid_rows"] == 1
    # The same part identity in another group is legitimate; resolve each page exactly.
    both = checked(preview(client, auth_headers, revision,
                           headers + row + f"{groups[1]['code']},1,QA-X,QA,3,{artifact['sha256']}\n"))
    assert both["summary"]["valid_rows"] == 2
    original = parts.insert_preview_rows
    def fail_second_group(db, actor, assembly, revision, catalog, rows):
        created = original(db, actor, assembly, revision, catalog, rows)
        if assembly.id == groups[1]["id"]:
            raise IntegrityError("QA forced atomic conflict", {}, Exception("QA"))
        return created
    monkeypatch.setattr(parts, "insert_preview_rows", fail_second_group)
    assert confirm(client, auth_headers, revision, both).status_code == 409
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 0
    assert other_sha != artifact["sha256"]
