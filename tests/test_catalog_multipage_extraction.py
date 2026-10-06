"""Runtime-only synthetic BOMs: one reference page, many physical sources."""

import hashlib

import fitz
import pytest
from app.catalog_admin.parts_extraction import extraction, process
from app.models import CatalogRevisionPart, CatalogRevisionPartPageMap
from app.settings import settings
from sqlalchemy import select
from test_catalog_guided_builder import assign
from test_catalog_selected_extraction import BASE, checked, upload, workspace


def multipage_pdf(*, count=2, headerless=False, ruled=True, shifted=False, start=1):
    with fitz.open() as pdf:
        page = pdf.new_page(width=850, height=650)
        page.insert_text((40, 40), "Synthetic QA scheme")
        page.draw_rect((60, 90, 400, 300))
        for index in range(count):
            page = pdf.new_page(width=850, height=650)
            xs = [30, 110, 280, 600, 830]
            if shifted and index:
                xs = [30, 190, 360, 680, 830]
            records = ([] if headerless and index else [["No.", "Part No.", "Description", "Qty"]])
            records += [[str(start + index * 5 + row), f"QA-{start + index * 5 + row}", "QA component", "2"] for row in range(5)]
            if ruled:
                for x in xs:
                    page.draw_line((x, 80), (x, 80 + len(records) * 30))
                for row in range(len(records) + 1):
                    page.draw_line((xs[0], 80 + row * 30), (xs[-1], 80 + row * 30))
            for row, values in enumerate(records):
                for x, value in zip(xs, values, strict=False):
                    page.insert_text((x + 4, 100 + row * 30), value, fontsize=10)
        return pdf.tobytes()


@pytest.mark.parametrize("count,headerless,ruled", [(2, False, True), (2, True, True), (2, True, False), (3, True, True), (3, False, False)])
def test_all_selected_sources_confirm_with_exact_evidence(client, auth_headers, session_factory, count, headerless, ruled):
    _, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    content = multipage_pdf(count=count, headerless=headerless, ruled=ruled)
    artifact = checked(upload(client, auth_headers, revision, content), 201)
    page = assign(client, auth_headers, page, artifact, [1], "EXPLODED_SCHEME")
    page = assign(client, auth_headers, page, artifact, list(range(2, count + 2)), "SPARE_PARTS_LIST")
    sources = [source for source in page["sources"] if source["role"] == "SPARE_PARTS_LIST"]
    previews, previous = [], None
    for source in sources:
        result = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
            json={"visual_page_id": source["id"], "continuation_token": previous}))
        assert len(result["rows"]) == 5
        if headerless and source["page_number"] > 2:
            assert result["tables"][0]["schema"]["method"] == "CONTINUATION_SCHEMA"
        previews.append(result)
        previous = result["token"]
    assert [row["payload"]["position"] for result in previews for row in result["rows"]] == [str(i) for i in range(1, count * 5 + 1)]
    for result in previews:
        payload = {"token": result["token"], "rows": [{"index": i, "part": row["payload"]} for i, row in enumerate(result["rows"])], "confirm_warnings": True}
        assert checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers, json=payload))["created_count"] == 5
        assert checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers, json=payload))["created_count"] == 0
    with session_factory() as db:
        parts = list(db.scalars(select(CatalogRevisionPart).where(CatalogRevisionPart.reference_page_id == page["id"])))
        assert len(parts) == count * 5
        for part in parts:
            physical = (int(part.position) - 1) // 5 + 2
            source = next(source for source in sources if source["page_number"] == physical)
            evidence = part.extraction_evidence
            assert evidence["source"] == {"visual_page_id": source["id"], "artifact_id": source["artifact_id"], "sha256": hashlib.sha256(content).hexdigest(), "page_number": physical, "filename": source["filename"]}
            assert evidence["row"]["bbox"] and evidence["row"]["raw_text"] and evidence["extractor"]
            assert list(db.scalars(select(CatalogRevisionPartPageMap.visual_page_id).where(CatalogRevisionPartPageMap.part_id == part.id))) == [source["id"]]


def test_headerless_ruled_page_retains_first_row_for_manual_mapping():
    with fitz.open(stream=multipage_pdf(headerless=True), filetype="pdf") as pdf:
        result = extraction.extract_page(pdf[2], process.configuration(settings))
    assert not result["rows"]
    table = result["tables"][0]
    assert table["schema"]["state"] == "NEEDS_REVIEW"
    assert table["cells"][0][0] == "6" and len(table["cells"]) == 5
    assert "CONTINUATION_UNRESOLVED" in result["warnings"]


def test_incompatible_layout_requires_page_specific_mapping(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    artifact = checked(upload(client, auth_headers, revision, multipage_pdf(headerless=True, shifted=True)), 201)
    page = assign(client, auth_headers, page, artifact, [2, 3], "SPARE_PARTS_LIST")
    first = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers, json={"visual_page_id": page["sources"][0]["id"]}))
    second = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
        json={"visual_page_id": page["sources"][1]["id"], "continuation_token": first["token"]}))
    assert len(first["rows"]) == 5 and not second["rows"]
    mapped = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/mapping", headers=auth_headers,
        json={"token": second["token"], "table_index": 0, "mapping": {"0": "position", "1": "part_number", "2": "description", "3": "quantity"}}))
    assert [row["payload"]["position"] for row in first["rows"] + mapped["rows"]] == [str(i) for i in range(1, 11)]
    assert "CONTINUATION_UNRESOLVED" not in mapped["warnings"]


@pytest.mark.parametrize("headerless", [False, True])
def test_different_documents_are_processed_without_schema_leak(client, auth_headers, session_factory, headerless):
    _, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    first_artifact = checked(upload(client, auth_headers, revision, multipage_pdf()), 201)
    second_artifact = checked(upload(client, auth_headers, revision, multipage_pdf(start=11, headerless=headerless)), 201)
    page = assign(client, auth_headers, page, first_artifact, [2], "SPARE_PARTS_LIST")
    page = assign(client, auth_headers, page, second_artifact, [3], "SPARE_PARTS_LIST")
    first = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers, json={"visual_page_id": page["sources"][0]["id"]}))
    second = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
        json={"visual_page_id": page["sources"][1]["id"], "continuation_token": first["token"]}))
    assert len(first["rows"]) == 5
    assert len(second["rows"]) == (0 if headerless else 5)
    assert first["source"]["sha256"] != second["source"]["sha256"]
    if headerless:
        assert second["tables"][0]["cells"][0][0] == "16"
        assert "CONTINUATION_UNRESOLVED" in second["warnings"]


def test_configured_order_is_used_instead_of_visual_page_id(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    artifact = checked(upload(client, auth_headers, revision, multipage_pdf()), 201)
    page = assign(client, auth_headers, page, artifact, [2, 3], "SPARE_PARTS_LIST")
    ordered_ids = [source["id"] for source in reversed(page["sources"])]
    page = checked(client.post(f"{BASE}/reference-pages/{page['id']}/sources/reorder", headers=auth_headers,
        json={"expected_version": page["version"], "ordered_ids": ordered_ids}))
    assert [source["id"] for source in page["sources"]] == ordered_ids
    assert [source["page_number"] for source in page["sources"]] == [3, 2]
