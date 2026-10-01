"""Actual selected-table extraction, page-scoped publication and immutable requests."""

import hashlib
import io

import fitz
from app.documents import part_request_documents
from app.documents.part_request_grouped_visuals import prepare_appendix
from app.models import CatalogRevisionPart, CatalogSourceBlob, GeneratedDocument, Machine, PartVisualSnapshot
from app.part_requests.service import load_request
from catalog_extraction_fixtures import contextual_table
from docx import Document
from sqlalchemy import func, select
from test_catalog_selected_extraction import BASE, checked, upload, workspace


def guided_pdf():
    pdf = fitz.open()
    lists = {3: [("1", "QA-P1", "Shaft", "1"), ("1", "QA-P1-ALT", "Shaft variant", "1"),
                 ("2", "QA-P1-B", "Bearing", "2")],
             4: [("3", "QA-P1-C", "Seal", "1")], 6: [("1", "QA-P2", "Tank", "1")]}
    for number in range(1, 7):
        page = pdf.new_page()
        page.insert_text((40, 40), "Synthetic QA source for explicitly chosen physical page")
        if number in lists:
            for x, header in zip([40, 120, 280, 490], ["Pos", "Part No.", "Description", "Qty"], strict=True):
                page.insert_text((x, 100), header)
            for i, row in enumerate(lists[number]):
                for x, value in zip([40, 120, 280, 490], row, strict=True):
                    page.insert_text((x, 130 + i * 22), value)
        else:
            page.insert_text((80, 150), "1")
            page.insert_text((200, 180), "2")
            page.insert_text((300, 250), "3")
            page.draw_rect(fitz.Rect(60, 160, 400, 400))
    content = pdf.tobytes()
    pdf.close()
    return content


def assign(client, headers, page, artifact, numbers, role):
    return checked(client.post(f"{BASE}/reference-pages/{page['id']}/sources", headers=headers,
        json={"expected_version": page["version"], "artifact_id": artifact["id"],
              "page_numbers": numbers, "roles": [role]}))


def test_repeated_position_multi_scheme_extraction_publication_two_machines_and_parts_doc(client, auth_headers, session_factory, monkeypatch):
    catalog, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    pages = [checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
             for _ in range(2)]
    content = guided_pdf()
    artifact = checked(upload(client, auth_headers, revision, content), 201)
    duplicate = checked(upload(client, auth_headers, revision, content), 201)
    assert duplicate["duplicate"] and duplicate["id"] == artifact["id"]
    pages[0] = assign(client, auth_headers, pages[0], artifact, [1, 2], "EXPLODED_SCHEME")
    pages[0] = assign(client, auth_headers, pages[0], artifact, [3, 4], "SPARE_PARTS_LIST")
    pages[1] = assign(client, auth_headers, pages[1], artifact, [5], "EXPLODED_SCHEME")
    pages[1] = assign(client, auth_headers, pages[1], artifact, [6], "SPARE_PARTS_LIST")
    assert pages[0]["scheme_count"] == pages[0]["spare_list_count"] == 2
    accepted = {}
    for page in pages:
        prior = None
        for source in [item for item in page["sources"] if item["role"] == "SPARE_PARTS_LIST"]:
            result = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
                json={"visual_page_id": source["id"], "continuation_token": prior}))
            assert result["rows"] and result["method"] == "NATIVE"
            prior = result["token"]
            rows = [{"index": index, "part": row["payload"]} for index, row in enumerate(result["rows"])]
            payload = {"token": result["token"], "rows": rows, "confirm_warnings": True}
            confirmed = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers, json=payload))
            repeated = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers, json=payload))
            assert confirmed["created_count"] == len(rows) and repeated["created_count"] == 0
        accepted[page["id"]] = checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))
        for part in accepted[page["id"]]:
            assert part["reference_page_id"] == page["id"]
            assert len(part["source_pages"]) == 1 and part["source_pages"][0]["sha256"] == hashlib.sha256(content).hexdigest()
        schemes = [item for item in page["sources"] if item["role"] == "EXPLODED_SCHEME"]
        for index, position in enumerate(sorted({part["position"] for part in accepted[page["id"]]})):
            source = schemes[index % len(schemes)]
            hotspot = checked(client.post(f"{BASE}/visual-pages/{source['id']}/hotspots", headers=auth_headers,
                json={"position": position, "x": .1 + index * .1, "y": .2, "width": .03, "height": .03}), 201)
            assert not hotspot["is_verified"]
            checked(client.post(f"{BASE}/hotspots/{hotspot['id']}/verify", headers=auth_headers,
                json={"expected_version": hotspot["version"]}))
    # Same position belongs to distinct logical pages; variants are only local.
    first = next(part for part in accepted[pages[0]["id"]] if part["part_number"] == "QA-P1")
    second_list = next(item for item in pages[1]["sources"] if item["role"] == "SPARE_PARTS_LIST")
    assert client.post(f"{BASE}/parts/{first['id']}/source-pages", headers=auth_headers,
        json={"visual_page_ids": [second_list["id"]]}).status_code == 422
    second_scheme = next(item for item in pages[1]["sources"] if item["role"] == "EXPLODED_SCHEME")
    assert client.post(f"{BASE}/visual-pages/{second_scheme['id']}/hotspots", headers=auth_headers,
        json={"position": "2", "x": .2, "y": .2, "width": .03, "height": .03}).status_code == 422
    assert client.delete(f"{BASE}/reference-pages/{pages[0]['id']}?expected_version={pages[0]['version']}", headers=auth_headers).status_code == 409
    assert client.delete(f"{BASE}/reference-pages/{pages[1]['id']}/sources/{second_list['id']}?expected_version={pages[1]['version']}", headers=auth_headers).status_code == 409
    ready = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
    assert ready["ready"], ready
    checked(client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=auth_headers,
        json={"expected_publication_digest": ready["publication_digest"], "expected_current_published_revision_id": None, "confirmed": True}))
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogSourceBlob.id))) == 1
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 5
        machines = [Machine(inventory_number=f"QA_GUIDED_{i}", brand="QA", model="QA", serial_number=f"QA-G-{i}",
            category_id=catalog["asset_category_id"], category="QA_AUTO_INGEST", name="QA ONLY") for i in range(2)]
        db.add_all(machines)
        db.commit()
        machine_ids = [item.id for item in machines]
    history = {}
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    for machine_id in machine_ids:
        checked(client.post(f"{BASE}/catalogs/{catalog['id']}/assets/{machine_id}", headers=auth_headers), 201)
        runtime = checked(client.get(f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers))
        assert len(runtime["assemblies"]) == 1
        logical = runtime["assemblies"][0]["pages"]
        assert [page["number"] for page in logical] == [1, 2]
        assert len(logical[0]["diagrams"]) == 2 and len(logical[1]["diagrams"]) == 1
        lines = []
        for page, expected in zip(logical, [{"QA-P1", "QA-P1-ALT", "QA-P1-B", "QA-P1-C"}, {"QA-P2"}], strict=True):
            details = checked(client.get(f"/api/catalog/v2/assemblies/{page['source_id']}?machine_id={machine_id}", headers=auth_headers))
            assert {part["part_number"] for part in details["parts"]} == expected
            for diagram in page["diagrams"]:
                hotspots = checked(client.get(f"/api/catalog/v2/diagrams/{diagram['id']}/hotspots?machine_id={machine_id}", headers=auth_headers))
                for hotspot in hotspots:
                    assert {part["part_number"] for part in hotspot["variants"]} <= expected
            part = next(part for part in details["parts"] if part["position"] == "1")
            lines.append({"catalog_part_id": part["id"], "position": "1", "description": part["description"], "quantity": 1})
        request = checked(client.post("/api/part-requests/multi", headers=auth_headers,
            json={"machine_id": machine_id, "submit_for_approval": True, "lines": lines}), 201)
        checked(client.post(f"/api/part-requests/{request['id']}/decision", headers=auth_headers,
            json={"decision": "APPROVED", "note": "Synthetic verified source"}))
        checked(client.post(f"/api/part-requests/{request['id']}/documents?language=bg", headers=auth_headers), 201)
        with session_factory() as db:
            generated = list(db.scalars(select(GeneratedDocument).where(GeneratedDocument.part_request_id == request["id"])))
            assert {document.format for document in generated} == {"docx", "pdf"}
            record = next(document for document in generated if document.format == "docx")
            docx = Document(io.BytesIO(record.content))
            assert len(docx.inline_shapes) >= 4
            history[request["id"]] = {"documents": {row.id: row.sha256 for row in generated},
                "snapshots": list(db.scalars(select(PartVisualSnapshot.sha256).where(PartVisualSnapshot.line_id.in_([line["id"] for line in request["lines"]])).order_by(PartVisualSnapshot.id)))}
            appendix = prepare_appendix(db, load_request(db, request["id"]))
            assert {page.page_number for page in appendix.pages if page.role == "SPARE_PARTS_LIST"} == {3, 6}
            assert {page.page_number for page in appendix.pages if page.role == "EXPLODED_SCHEME"} == {1, 5}
    assert client.post(f"{BASE}/reference-pages/{pages[1]['id']}/extract", headers=auth_headers,
        json={"visual_page_id": second_list["id"]}).status_code == 409
    assert client.patch(f"{BASE}/reference-pages/{pages[0]['id']}", headers=auth_headers,
        json={"expected_version": pages[0]["version"], "title": "Cannot edit published"}).status_code == 409
    clone = checked(client.post(f"{BASE}/revisions/{revision['id']}/clone", headers=auth_headers,
        json={"revision_code": "QA-NEXT", "change_note": "Synthetic clone verification"}), 201)
    cloned_reference = checked(client.get(f"{BASE}/revisions/{clone['id']}/assemblies", headers=auth_headers))[0]
    cloned = checked(client.get(f"{BASE}/assemblies/{cloned_reference['id']}/reference-pages", headers=auth_headers))
    assert len(cloned) == 2 and {page["stable_key"] for page in cloned} == {page["stable_key"] for page in pages}
    assert {page["id"] for page in cloned}.isdisjoint({page["id"] for page in pages})
    clone_ready = checked(client.get(f"{BASE}/revisions/{clone['id']}/publication-readiness", headers=auth_headers))
    assert clone_ready["ready"], clone_ready
    clone_parts = checked(client.get(f"{BASE}/reference-pages/{cloned[0]['id']}/parts", headers=auth_headers))
    checked(client.patch(f"{BASE}/parts/{clone_parts[0]['id']}", headers=auth_headers,
        json={"description": "Synthetic next revision human edit"}))
    clone_ready = checked(client.get(f"{BASE}/revisions/{clone['id']}/publication-readiness", headers=auth_headers))
    checked(client.post(f"{BASE}/revisions/{clone['id']}/publish", headers=auth_headers,
        json={"expected_publication_digest": clone_ready["publication_digest"],
              "expected_current_published_revision_id": revision["id"], "confirmed": True}))
    with session_factory() as db:
        for request_id, frozen in history.items():
            assert {row.id: row.sha256 for row in db.scalars(select(GeneratedDocument).where(
                GeneratedDocument.part_request_id == request_id))} == frozen["documents"]
            loaded = load_request(db, request_id)
            assert list(db.scalars(select(PartVisualSnapshot.sha256).where(
                PartVisualSnapshot.line_id.in_([line.id for line in loaded.lines])).order_by(PartVisualSnapshot.id))) == frozen["snapshots"]
            assert {page.page_number for page in prepare_appendix(db, loaded).pages if page.role == "SPARE_PARTS_LIST"} == {3, 6}


def test_manual_columns_partial_preview_atomic_confirm_human_edits_and_source_token(client, auth_headers, session_factory, monkeypatch):
    from app.catalog_admin.parts_extraction import process

    _, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    source = contextual_table(["ID", "Number", "Type", "Qty"], [["1", "51", "Seal", "2"], ["4", "54", "Pump", "1"]], ruled=True)
    artifact = checked(upload(client, auth_headers, revision, source), 201)
    page = assign(client, auth_headers, page, artifact, [1], "SPARE_PARTS_LIST")
    calls = []
    actual = process.extract
    def selected_only(content, operation, number, config):
        calls.append((operation, number))
        return actual(content, operation, number, config)
    monkeypatch.setattr(process, "extract", selected_only)
    preview = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
        json={"visual_page_id": page["sources"][0]["id"]}))
    assert calls == [("page", 1)] and not preview["rows"]
    assert preview["tables"][0]["schema"]["state"] == "NEEDS_REVIEW"
    assert preview["tables"][0]["sample_cells"] == [["1", "51", "Seal", "2"], ["4", "54", "Pump", "1"]]
    invalid = {"token": preview["token"], "table_index": 0, "mapping": {"0": "position", "1": "position", "2": "description", "3": "quantity"}}
    assert client.post(f"{BASE}/reference-pages/{page['id']}/extraction/mapping", headers=auth_headers, json=invalid).status_code == 422
    mapped = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/mapping", headers=auth_headers,
        json={**invalid, "mapping": {"0": "position", "1": "part_number", "2": "description", "3": "quantity"}}))
    assert calls == [("page", 1)]  # Human mapping reuses the signed native cells; no repeated OCR/parsing.
    assert [row["payload"]["part_number"] for row in mapped["rows"]] == ["51", "54"]
    rows = [{"index": i, "part": row["payload"]} for i, row in enumerate(mapped["rows"])]
    invalid_rows = [rows[0], {"index": 1, "part": {**rows[1]["part"], "part_number": ""}}]
    assert client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": mapped["token"], "rows": invalid_rows, "confirm_warnings": True}).status_code == 422
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogRevisionPart.id))) == 0
    # Preview row 2 is deliberately rejected by omission; edited row 1 is confirmed.
    edited = [{"index": 0, "part": {**rows[0]["part"], "description": "Human-confirmed source description"}}]
    confirmed = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": mapped["token"], "rows": edited, "confirm_warnings": True}))
    assert confirmed["created_count"] == 1
    repeated = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": mapped["token"], "rows": [rows[0]], "confirm_warnings": True}))
    assert repeated["created_count"] == 0
    with session_factory() as db:
        part = db.get(CatalogRevisionPart, confirmed["part_ids"][0])
        assert part.description == "Human-confirmed source description"
        assert part.extraction_evidence["row"]["raw_cells"] == ["1", "51", "Seal", "2"]
        assert part.extraction_evidence["row"]["bbox"] and part.name_bg is part.name_en is part.name_ru is None
    assert client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers,
        json={"token": mapped["token"][:-1] + "x", "rows": edited}).status_code == 422
    assert client.post(f"{BASE}/reference-pages/{page['id']}/extract", json={"visual_page_id": page["sources"][0]["id"]}).status_code == 401


def test_reference_page_stable_reorder_both_shared_sources_and_stale_assignment(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    assemblies = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))
    second = checked(client.post(f"{BASE}/revisions/{revision['id']}/groups", headers=auth_headers, json={"name": "QA second reference"}), 201)
    first = assemblies[0]
    a = checked(client.post(f"{BASE}/assemblies/{first['id']}/reference-pages", headers=auth_headers, json={}), 201)
    b = checked(client.post(f"{BASE}/assemblies/{first['id']}/reference-pages", headers=auth_headers, json={}), 201)
    c = checked(client.post(f"{BASE}/assemblies/{second['id']}/reference-pages", headers=auth_headers, json={}), 201)
    artifact = checked(upload(client, auth_headers, revision, guided_pdf()), 201)
    assigned = checked(client.post(f"{BASE}/reference-pages/{a['id']}/sources", headers=auth_headers,
        json={"expected_version": a["version"], "artifact_id": artifact["id"], "page_numbers": [3], "roles": ["EXPLODED_SCHEME", "SPARE_PARTS_LIST"]}))
    assert {source["role"] for source in assigned["sources"]} == {"EXPLODED_SCHEME", "SPARE_PARTS_LIST"}
    assert client.post(f"{BASE}/reference-pages/{a['id']}/sources", headers=auth_headers,
        json={"expected_version": a["version"], "artifact_id": artifact["id"], "page_numbers": [4], "roles": ["SPARE_PARTS_LIST"]}).status_code == 409
    assign(client, auth_headers, b, artifact, [3], "SPARE_PARTS_LIST")
    assign(client, auth_headers, c, artifact, [3], "SPARE_PARTS_LIST")
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogSourceBlob.id))) == 1
    stale = {"pages": [{"id": b["id"], "expected_version": b["version"]}, {"id": a["id"], "expected_version": assigned["version"]}]}
    assert client.post(f"{BASE}/assemblies/{first['id']}/reference-pages/reorder", headers=auth_headers, json=stale).status_code == 409
    before = checked(client.get(f"{BASE}/assemblies/{first['id']}/reference-pages", headers=auth_headers))
    assert [row["id"] for row in before] == [a["id"], b["id"]]
    stale["pages"][0]["expected_version"] += 1
    reordered = checked(client.post(f"{BASE}/assemblies/{first['id']}/reference-pages/reorder", headers=auth_headers, json=stale))
    assert [row["id"] for row in reordered] == [b["id"], a["id"]]
    assert reordered[0]["stable_key"] == b["stable_key"]
    assert client.delete(f"{BASE}/artifacts/{artifact['id']}", headers=auth_headers).status_code == 409
    reference_order = {"expected_ids": [first["id"], second["id"]], "ordered_ids": [second["id"], first["id"]]}
    references = checked(client.post(f"{BASE}/revisions/{revision['id']}/references/reorder", headers=auth_headers, json=reference_order))
    assert [row["id"] for row in references] == reference_order["ordered_ids"]
    assert client.post(f"{BASE}/revisions/{revision['id']}/references/reorder", headers=auth_headers, json=reference_order).status_code == 409
    sources = {"expected_version": reordered[1]["version"], "ordered_ids": [row["id"] for row in reversed(assigned["sources"])]}
    source_order = checked(client.post(f"{BASE}/reference-pages/{a['id']}/sources/reorder", headers=auth_headers, json=sources))
    assert [row["id"] for row in source_order["sources"]] == sources["ordered_ids"]
    assert source_order["id"] == a["id"]
    assert client.delete(f"{BASE}/assemblies/{first['id']}", headers=auth_headers).status_code == 409
