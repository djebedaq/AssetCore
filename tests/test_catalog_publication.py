"""Disposable Builder publication integration; no verified seed data is changed."""

import base64
import io

import pytest
from app.catalog.importer import import_authoritative_catalog
from app.catalog.sources import CATALOG_VERSION
from app.catalog_admin import publication
from app.documents import part_request_documents
from app.documents.part_request_grouped_visuals import prepare_appendix
from app.models import (
    AssetCategory,
    CatalogDefinition,
    CatalogDiagram,
    CatalogPositionHotspot,
    CatalogRevision,
    CatalogRevisionArtifact,
    CatalogVisualPartMap,
    CatalogVisualSource,
    GeneratedDocument,
    Machine,
    PartCatalog,
    PartVisualSnapshot,
    RepairKit,
    TechnicalDocument,
    User,
)
from app.part_requests.service import load_request
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from test_catalog_builder_parts import BASE, source, workspace


def test_publish_binding_request_and_clone(client, auth_headers, session_factory, monkeypatch):
    catalog_id, revision_id, assembly_id, _ = workspace(client, auth_headers, session_factory)
    _, spare_page_id, scheme_page_id, _ = source(client, auth_headers, assembly_id)
    position = "P" * 80
    created = client.post(f"{BASE}/assemblies/{assembly_id}/parts", headers=auth_headers, json={
        "position": position, "part_number": "QA-PART", "name_bg": "Тестова част",
        "name_en": "Test part", "name_ru": "Тестовая деталь",
    })
    assert created.status_code == 201, created.text
    part_id = created.json()["id"]
    assert client.post(f"{BASE}/parts/{part_id}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare_page_id]}).status_code == 201
    hotspot = client.post(f"{BASE}/visual-pages/{scheme_page_id}/hotspots", headers=auth_headers,
                          json={"position": position, "x": .2, "y": .3, "width": .1, "height": .1})
    assert hotspot.status_code == 201, hotspot.text
    verified = client.post(f"{BASE}/hotspots/{hotspot.json()['id']}/verify", headers=auth_headers,
                           json={"expected_version": hotspot.json()["version"]})
    assert verified.status_code == 200, verified.text
    kit = client.post(f"{BASE}/assemblies/{assembly_id}/repair-kits", headers=auth_headers,
                      json={"code": "QA_KIT", "name_bg": "Тестов комплект",
                            "source_visual_page_id": spare_page_id})
    assert kit.status_code == 201, kit.text
    component = client.post(f"{BASE}/repair-kits/{kit.json()['id']}/components",
                            headers=auth_headers, json={"part_id": part_id, "quantity": 2})
    assert component.status_code == 201, component.text
    with session_factory() as db:
        catalog = db.get(CatalogDefinition, catalog_id)
        category = db.get(AssetCategory, catalog.asset_category_id)
        machine = Machine(inventory_number="QA_PUB_A", name="QA_PUB_A",
                          category=category.code, category_id=category.id,
                          brand="QA brand", model="QA model")
        other = Machine(inventory_number="QA_PUB_B", name="QA_PUB_B",
                        category=category.code, category_id=category.id,
                        brand="QA brand", model="QA model")
        db.add_all([machine, other])
        db.commit()
        machine_id, other_id = machine.id, other.id
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_id}",
                       headers=auth_headers).status_code == 201
    before = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
    assert before.status_code == 200 and not before.json()["supported"]
    preview = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness", headers=auth_headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["ready"], preview.json()
    stale = client.post(f"{BASE}/revisions/{revision_id}/publish", headers=auth_headers,
                        json={"expected_publication_digest": "0" * 64,
                              "expected_current_published_revision_id": None, "confirmed": True})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "catalog_publication_stale"
    published = client.post(f"{BASE}/revisions/{revision_id}/publish", headers=auth_headers,
                            json={"expected_publication_digest": preview.json()["publication_digest"],
                                  "expected_current_published_revision_id": None, "confirmed": True})
    assert published.status_code == 200, published.text
    catalog = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers)
    assert catalog.status_code == 200 and catalog.json()["supported"], catalog.text
    runtime_source = catalog.json()["assemblies"][0]["source_id"]
    detail = client.get(f"/api/catalog/v2/assemblies/{runtime_source}?machine_id={machine_id}",
                        headers=auth_headers)
    assert detail.status_code == 200, detail.text
    diagram = detail.json()["diagrams"][0]
    assert client.get(f"/api{diagram['download_endpoint']}", headers=auth_headers).status_code == 200
    assert client.get(f"/api{diagram['preview_endpoint']}", headers=auth_headers).status_code == 200
    runtime_part = detail.json()["parts"][0]
    assert runtime_part["position"] == position
    assert runtime_part["description_en"] == "Test part"
    generic = client.get(f"/api/catalog/parts?machine_id={machine_id}&brand=QA%20brand&model=QA%20model",
                         headers=auth_headers)
    assert generic.status_code == 200 and [item["id"] for item in generic.json()] == [runtime_part["id"]]
    assert client.get(f"/api/catalog/v2/assemblies/{runtime_source}?machine_id={other_id}",
                      headers=auth_headers).status_code != 200
    kits = client.get(f"/api/catalog/v2/repair-kits?machine_id={machine_id}", headers=auth_headers)
    assert kits.status_code == 200 and len(kits.json()) == 1, kits.text
    runtime_kit = kits.json()[0]
    assert runtime_kit["code"] == "QA_KIT"
    assert runtime_kit["components"][0]["part_id"] == runtime_part["id"]
    legacy_kits = client.get("/api/repair-kits", headers=auth_headers)
    assert legacy_kits.status_code == 200
    assert runtime_kit["id"] not in {item["id"] for item in legacy_kits.json()}
    kit_request = client.post("/api/part-requests/multi", headers=auth_headers,
                              json={"machine_id": machine_id, "repair_kit_id": runtime_kit["id"],
                                    "repair_kit_mode": "KIT", "lines": [
                                        {"description": "QA kit", "quantity": 1}]})
    assert kit_request.status_code == 201, kit_request.text
    request_payload = {"machine_id": machine_id, "submit_for_approval": True,
                       "lines": [{"catalog_part_id": runtime_part["id"],
                        "position": position, "description": "Test part", "quantity": 1}]}
    request = client.post("/api/part-requests/multi", headers=auth_headers, json=request_payload)
    assert request.status_code == 201, request.text
    assert request.json()["lines"][0]["position"] == position
    assert request.json()["lines"][0]["visual_reference"]["state"] == "verified_visual_references"
    with session_factory() as db:
        appendix = prepare_appendix(db, load_request(db, request.json()["id"]))
        assert [page.role for page in appendix.pages] == ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]
    approved = client.post(f"/api/part-requests/{request.json()['id']}/decision", headers=auth_headers,
                           json={"decision": "APPROVED", "note": "QA approval"})
    assert approved.status_code == 200, approved.text
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    generated = client.post(f"/api/part-requests/{request.json()['id']}/documents?language=bg",
                            headers=auth_headers)
    assert generated.status_code == 201, generated.text
    with session_factory() as db:
        records = db.scalars(select(GeneratedDocument).where(
            GeneratedDocument.part_request_id == request.json()["id"])).all()
        assert {item.format for item in records} == {"docx", "pdf"}
        historical_documents = {item.format: item.sha256 for item in records}
        historical_snapshot = db.scalar(select(PartVisualSnapshot).where(
            PartVisualSnapshot.line_id == request.json()["lines"][0]["id"])).sha256
    request_payload["machine_id"] = other_id
    rejected = client.post("/api/part-requests/multi", headers=auth_headers, json=request_payload)
    assert rejected.status_code == 409
    clone = client.post(f"{BASE}/revisions/{revision_id}/clone", headers=auth_headers,
                        json={"revision_code": "B", "change_note": "QA next revision"})
    assert clone.status_code == 201 and clone.json()["status"] == "DRAFT", clone.text
    clone_id = clone.json()["id"]
    clone_assemblies = client.get(f"{BASE}/revisions/{clone_id}/assemblies", headers=auth_headers).json()
    clone_parts = client.get(f"{BASE}/assemblies/{clone_assemblies[0]['id']}/parts", headers=auth_headers).json()
    assert clone_parts[0]["position"] == position and clone_parts[0]["source_pages"]
    assert client.patch(f"{BASE}/parts/{clone_parts[0]['id']}", headers=auth_headers,
                        json={"name_en": "Next test part"}).status_code == 200
    next_preview = client.get(f"{BASE}/revisions/{clone_id}/publication-readiness", headers=auth_headers)
    assert next_preview.status_code == 200 and next_preview.json()["ready"], next_preview.text
    next_published = client.post(f"{BASE}/revisions/{clone_id}/publish", headers=auth_headers,
                                 json={"expected_publication_digest": next_preview.json()["publication_digest"],
                                       "expected_current_published_revision_id": revision_id,
                                       "confirmed": True})
    assert next_published.status_code == 200, next_published.text
    old_rejected = client.post("/api/part-requests/multi", headers=auth_headers,
                               json={"machine_id": machine_id, "lines": [{"catalog_part_id": runtime_part["id"],
                                     "description": "Test part", "quantity": 1}]})
    assert old_rejected.status_code == 409
    with session_factory() as db:
        assert db.get(CatalogRevision, revision_id).status == "RETIRED"
        assert db.get(CatalogRevision, clone_id).status == "PUBLISHED"
        assert not db.scalar(select(PartCatalog).where(PartCatalog.builder_part_id == part_id)).is_active
        assert db.scalar(select(CatalogDiagram).where(CatalogDiagram.builder_revision_id == revision_id))
        assert db.scalar(select(CatalogPositionHotspot).where(CatalogPositionHotspot.builder_revision_id == revision_id))
        assert db.scalar(select(CatalogVisualPartMap).where(CatalogVisualPartMap.builder_part_page_map_id.is_not(None)))
        assert db.scalar(select(RepairKit).where(RepairKit.builder_revision_id == revision_id))
        assert db.scalar(select(PartVisualSnapshot).where(
            PartVisualSnapshot.line_id == request.json()["lines"][0]["id"])).sha256 == historical_snapshot
        assert {item.format: item.sha256 for item in db.scalars(select(GeneratedDocument).where(
            GeneratedDocument.part_request_id == request.json()["id"])).all()} == historical_documents
        import_authoritative_catalog(db, db.get(User, 1))
        db.commit()
        assert db.scalar(select(func.count(PartCatalog.id)).where(
            PartCatalog.source_version == CATALOG_VERSION, PartCatalog.is_active.is_(True))) == 611
        assert db.scalar(select(func.count(PartCatalog.id)).where(
            PartCatalog.builder_revision_id == clone_id, PartCatalog.is_active.is_(True))) == 1
        assert db.scalar(select(func.count(RepairKit.id)).where(
            RepairKit.builder_revision_id == clone_id, RepairKit.is_active.is_(True))) == 1


def test_separate_pdf_pages_group_two_requested_positions(client, auth_headers, session_factory):
    catalog_id, revision_id, assembly_id, _ = workspace(client, auth_headers, session_factory)

    def visual(role, marker):
        stream = io.BytesIO()
        document = canvas.Canvas(stream)
        document.drawString(50, 700, marker)
        document.showPage()
        document.save()
        uploaded = client.post(f"{BASE}/assemblies/{assembly_id}/artifacts", headers=auth_headers,
                               json={"title": marker, "filename": f"{marker}.pdf",
                                     "media_type": "application/pdf",
                                     "content_base64": base64.b64encode(stream.getvalue()).decode()})
        assert uploaded.status_code == 201, uploaded.text
        page = client.post(f"{BASE}/artifacts/{uploaded.json()['id']}/visual-pages",
                           headers=auth_headers, json={"role": role, "page_numbers": [1]})
        assert page.status_code == 201, page.text
        return page.json()[0]["id"], uploaded.json()["sha256"]

    scheme, scheme_hash = visual("EXPLODED_SCHEME", "QA_SCHEME")
    spare, spare_hash = visual("SPARE_PARTS_LIST", "QA_LIST")
    assert scheme_hash != spare_hash
    for number in (10, 11):
        created = client.post(f"{BASE}/assemblies/{assembly_id}/parts", headers=auth_headers,
                              json={"position": str(number), "part_number": f"QA-{number}",
                                    "name_bg": f"Тест {number}", "name_en": f"Test {number}"})
        assert created.status_code == 201, created.text
        assert client.post(f"{BASE}/parts/{created.json()['id']}/source-pages", headers=auth_headers,
                           json={"visual_page_ids": [spare]}).status_code == 201
        hotspot = client.post(f"{BASE}/visual-pages/{scheme}/hotspots", headers=auth_headers,
                              json={"position": str(number), "x": .1 * number / 10,
                                    "y": .2, "width": .05, "height": .05})
        assert hotspot.status_code == 201, hotspot.text
        assert client.post(f"{BASE}/hotspots/{hotspot.json()['id']}/verify", headers=auth_headers,
                           json={"expected_version": hotspot.json()["version"]}).status_code == 200
    with session_factory() as db:
        catalog = db.get(CatalogDefinition, catalog_id)
        category = db.get(AssetCategory, catalog.asset_category_id)
        machine = Machine(inventory_number="QA_SEPARATE_PDFS", name="QA_SEPARATE_PDFS",
                          category=category.code, category_id=category.id,
                          brand="QA brand", model="QA model")
        db.add(machine)
        db.commit()
        machine_id = machine.id
    assert client.post(f"{BASE}/catalogs/{catalog_id}/assets/{machine_id}", headers=auth_headers).status_code == 201
    preview = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness", headers=auth_headers).json()
    assert preview["ready"], preview
    published = client.post(f"{BASE}/revisions/{revision_id}/publish", headers=auth_headers,
                            json={"expected_publication_digest": preview["publication_digest"],
                                  "expected_current_published_revision_id": None, "confirmed": True})
    assert published.status_code == 200, published.text
    runtime = client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers).json()
    detail = client.get(f"/api/catalog/v2/assemblies/{runtime['assemblies'][0]['source_id']}?machine_id={machine_id}",
                        headers=auth_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["diagrams"][0]["source_pdf_sha256"] == scheme_hash
    assert {item["source_document_sha256"] for item in detail.json()["parts"]} == {spare_hash}
    part_ids = [item["id"] for item in detail.json()["parts"]]
    created = client.post("/api/part-requests/multi", headers=auth_headers,
                          json={"machine_id": machine_id, "lines": [
                              {"catalog_part_id": item, "description": "QA", "quantity": 1}
                              for item in part_ids]})
    assert created.status_code == 201, created.text
    with session_factory() as db:
        appendix = prepare_appendix(db, load_request(db, created.json()["id"]))
        assert [page.role for page in appendix.pages] == ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]
        assert [page.artifact_sha256 for page in appendix.pages] == [scheme_hash, spare_hash]
        assert len(appendix.pages[0].contributions) == 2
        assert len(appendix.pages[1].contributions) == 2
        assert {item["marker"] for item in appendix.pages[0].contributions} == {1, 2}


def test_publish_failure_rolls_back_all_live_materialization(client, auth_headers, session_factory, monkeypatch):
    _, revision_id, assembly_id, _ = workspace(client, auth_headers, session_factory)
    _, spare_page_id, _, _ = source(client, auth_headers, assembly_id)
    part = client.post(f"{BASE}/assemblies/{assembly_id}/parts", headers=auth_headers,
                       json={"position": "QA-ROLLBACK", "part_number": "QA-ROLLBACK",
                             "name_bg": "Тестова част"})
    assert part.status_code == 201, part.text
    assert client.post(f"{BASE}/parts/{part.json()['id']}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare_page_id]}).status_code == 201
    preview = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness",
                         headers=auth_headers).json()
    assert preview["ready"], preview
    original = publication._materialize

    def fail_after_live_rows(*args):
        original(*args)
        raise RuntimeError("QA forced rollback after materialization")

    monkeypatch.setattr(publication, "_materialize", fail_after_live_rows)
    with session_factory() as db:
        actor = db.get(User, 1)
        with pytest.raises(RuntimeError, match="QA forced rollback"):
            publication.publish(db, actor, revision_id, preview["publication_digest"], None, True)
    with session_factory() as db:
        assert db.get(CatalogRevision, revision_id).status == "DRAFT"
        assert db.scalar(select(func.count(PartCatalog.id)).where(PartCatalog.builder_revision_id == revision_id)) == 0
        assert db.scalar(select(func.count(CatalogDiagram.id)).where(CatalogDiagram.builder_revision_id == revision_id)) == 0
        assert db.scalar(select(func.count(CatalogVisualSource.id)).where(CatalogVisualSource.builder_revision_id == revision_id)) == 0
        assert db.scalar(select(func.count(RepairKit.id)).where(RepairKit.builder_revision_id == revision_id)) == 0
        assert db.scalar(select(func.count(TechnicalDocument.id)).where(
            TechnicalDocument.builder_artifact_id.is_not(None))) == 0


def test_readiness_blocks_incomplete_graph_and_corrupt_source(client, auth_headers, session_factory):
    _, revision_id, assembly_id, _ = workspace(client, auth_headers, session_factory)
    artifact_id, spare_page_id, scheme_page_id, _ = source(client, auth_headers, assembly_id)
    part = client.post(f"{BASE}/assemblies/{assembly_id}/parts", headers=auth_headers,
                       json={"position": "QA-READINESS", "part_number": "QA-READINESS",
                             "name_bg": "Тестова част"})
    assert part.status_code == 201, part.text
    hotspot = client.post(f"{BASE}/visual-pages/{scheme_page_id}/hotspots", headers=auth_headers,
                          json={"position": "QA-READINESS", "x": .2, "y": .3,
                                "width": .1, "height": .1})
    assert hotspot.status_code == 201, hotspot.text
    preview = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness",
                         headers=auth_headers).json()
    assert {item["code"] for item in preview["errors"]} >= {
        "catalog_publication_part_incomplete", "catalog_publication_hotspot_unverified"}
    assert client.post(f"{BASE}/parts/{part.json()['id']}/source-pages", headers=auth_headers,
                       json={"visual_page_ids": [spare_page_id]}).status_code == 201
    assert client.post(f"{BASE}/hotspots/{hotspot.json()['id']}/verify", headers=auth_headers,
                       json={"expected_version": hotspot.json()["version"]}).status_code == 200
    with session_factory() as db:
        artifact = db.get(CatalogRevisionArtifact, artifact_id)
        original_content = artifact.content
        artifact.content = b"%PDF-corrupt QA bytes"
        db.commit()
    invalid = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness",
                         headers=auth_headers).json()
    assert not invalid["ready"]
    assert "catalog_publication_source_invalid" in {item["code"] for item in invalid["errors"]}
    with session_factory() as db:
        db.get(CatalogRevisionArtifact, artifact_id).content = original_content
        db.commit()
    valid = client.get(f"{BASE}/revisions/{revision_id}/publication-readiness",
                       headers=auth_headers).json()
    assert valid["ready"], valid
