"""Synthetic layout regressions, independent of OEM rows and control files."""

import copy

import fitz
import pytest
from app.catalog_admin.parts_extraction import (
    extraction,
    ledger,
    native_grid,
    panels,
    process,
    raster,
)
from app.catalog_admin.parts_extraction.schema import header_candidates
from app.settings import settings
from test_catalog_durable_review import extract, readiness, resume
from test_catalog_guided_builder import assign
from test_catalog_selected_extraction import BASE, checked, upload, workspace


def vector_pdf(*, closed=False, partial=False, repeat=False, footer=True, panels_count=1):
    """Open per-cell edges, three header lines, extra languages, unequal rows."""
    doc = fitz.open()
    page = doc.new_page(width=620 * panels_count, height=300)
    edges = [20, 55, 125, 165, 310, 440, 585]
    levels = [30, 72, 96, 132, 156]
    headings = ["Pos.\nPosition\nPos.", "Artikelnr.\nPart number\nArticle no.",
        "Menge\nQuantity\nQty", "Beschreibung\nDescription\nDescription", "Description", "Designation"]
    cells = [["7", "0001-A.02", "2", "QA original", "QA english", "QA french"],
        ["11", "" if partial else "0002-B.03", "" if partial else "3", "QA wrapped\ntext", "QA translated", "QA autre"],
        [h.splitlines()[0] for h in headings] if repeat else ["31", "0001-A.02", "1\neach", "QA retained", "QA retained", "QA retained"]]
    for panel in range(panels_count):
        xs = [x + panel * 620 for x in edges]
        for y in levels:
            for left, right in zip(xs, xs[1:]):
                page.draw_line((left, y), (right, y), width=.3)
        if closed:
            for x in xs:
                page.draw_line((x, levels[0]), (x, levels[-1]), width=.3)
        for row, top, bottom in zip([headings, *cells], levels, levels[1:]):
            for value, left, right in zip(row, xs, xs[1:]):
                for line, text in enumerate(value.splitlines()):
                    assert top + 8 + line * 9 < bottom
                    page.insert_text((left + 2, top + 8 + line * 9), text, fontsize=7)
        if footer:
            page.insert_text((xs[0], 175), "Document QA revision 2.4", fontsize=8)
    return doc


def run(page):
    return extraction.extract_page(page, {**process.configuration(settings), "ocr_enabled": False})


@pytest.mark.parametrize("closed", [False, True])
def test_native_local_multilingual_columns_preserve_raw_cells_and_quantities(closed, monkeypatch):
    monkeypatch.setattr(raster, "extract", lambda *a, **k: pytest.fail("Native geometry must not require OCR"))
    with vector_pdf(closed=closed) as doc:
        result = run(doc[0])
    assert len(result["rows"]) == 3
    assert [r["payload"]["part_number"] for r in result["rows"]] == ["0001-A.02", "0002-B.03", "0001-A.02"]
    assert [r["payload"]["quantity"] for r in result["rows"]] == ["2", "3", None]
    assert result["rows"][1]["payload"]["description"] == "QA wrapped text"
    assert result["rows"][1]["raw_values"]["description"] == "QA wrapped\ntext"
    assert result["rows"][2]["payload"]["quantity_raw"] == "1 each"
    assert result["rows"][2]["raw_values"]["quantity"] == "1\neach"
    assert "QUANTITY_UNCERTAIN" in result["rows"][2]["warnings"]
    assert not result["ocr_used"]
    assert result["quality"]["state"] == "NEEDS_REVIEW"
    assert all(r["confidence"] <= .7 for r in result["rows"])


@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("ordering", [[0, 1, 2, 3, 4], [4, 2, 0, 3, 1], [2, 3, 1, 0, 4]])
def test_repeated_panel_roles_have_local_schemas_in_different_orders(count, ordering):
    headers = ["No.", "Code", "Name", "Specifications", "Qty."]
    rows, tables = panels.parse([headers[i] for _ in range(count) for i in ordering],
        [[value for panel in range(count) for value in [
            ["7", "0001-A.02", "QA seal", "QA spec", str(panel + 2)][i] for i in ordering]]],
        [[0, 30, count * 250, 50]], [0, 10, count * 250, 50], list(range(0, count * 250 + 1, 50)))
    assert len(rows) == len(tables) == count
    assert [r["payload"]["quantity"] for r in rows] == [str(i + 2) for i in range(count)]
    assert all(r["payload"]["part_number"] == "0001-A.02" for r in rows)
    assert len({tuple(r["bbox"]) for r in rows}) == count
    assert all(t["schema"]["state"] == "RESOLVED" for t in tables)


@pytest.mark.parametrize("count", [2, 3])
def test_open_panels_keep_distinct_occurrences_and_stable_identity(count):
    with vector_pdf(panels_count=count) as doc:
        result = run(doc[0])
    assert len(result["rows"]) == count * 3
    assert len({ledger.row_key(row) for row in result["rows"]}) == count * 3
    assert all(row["method"] == "NATIVE_TABLE" for row in result["rows"])
    assert sum(row["payload"]["quantity_raw"] == "1 each" for row in result["rows"]) == count
    drifted = copy.deepcopy(result["rows"])
    for row in drifted:
        row["bbox"] = [v + .02 for v in row["bbox"]]
    assert [ledger.row_key(row) for row in drifted] == [ledger.row_key(row) for row in result["rows"]]


def test_blank_cells_and_repeated_header_do_not_disappear_or_become_verified():
    with vector_pdf(partial=True, repeat=True) as doc:
        result = run(doc[0])
    assert len(result["rows"]) == 2
    assert result["rows"][1]["payload"]["part_number"] == ""
    assert {"MISSING_PART_NUMBER", "QUANTITY_UNCERTAIN"} <= set(result["rows"][1]["warnings"])
    assert result["quality"]["state"] == "NEEDS_REVIEW"
    assert result["quality"]["observed_rows"] == 2


def test_vector_budget_is_fail_closed(monkeypatch):
    monkeypatch.setattr(native_grid, "MAX_SEGMENTS", 4)
    with vector_pdf() as doc:
        result = run(doc[0])
    assert "VECTOR_GRID_LIMIT" in result["warnings"]
    assert result["quality"]["state"] == "NEEDS_REVIEW"


def test_endpoint_clustering_cannot_chain_two_distinct_boundaries():
    assert len(native_grid.clusters([1, 1.7, 2.4, 3.1])) == 2


def test_conflicting_header_roles_remain_ambiguous():
    assert len(header_candidates("Quantity\nPart number")) == 2
    assert len(header_candidates("Item")) == len(header_candidates("No.")) == 2


def test_repeated_ambiguous_item_is_resolved_locally_by_other_columns_and_content():
    rows, tables = panels.parse(["Item", "Part No", "Description", "Qty"] * 2,
        [["7", "QA-0001", "QA seal", "2", "7", "QA-0001", "QA seal", "3"]],
        [[0, 20, 400, 40]], [0, 0, 400, 40], list(range(0, 401, 50)))
    assert [row["payload"]["quantity"] for row in rows] == ["2", "3"]
    assert all(table["schema"]["state"] == "RESOLVED" and table["schema"]["margin"] >= 1 for table in tables)


def test_layout_line_folding_does_not_change_nonbreaking_spaces_or_punctuation():
    rows, _ = panels.parse(["Pos", "Part No", "Description", "Qty"],
        [["1", "00A-I.01", "QA\u00a0seal - original", "1\u00a0each"], ["9", "00B-O.02", "QA control", "2"]],
        [[0, 20, 400, 40], [0, 40, 400, 60]], [0, 0, 400, 60], [0, 50, 150, 350, 400])
    assert rows[0]["payload"]["description"] == "QA\u00a0seal - original"
    assert rows[0]["payload"]["quantity_raw"] == "1\u00a0each"
    assert rows[0]["payload"]["part_number"] == "00A-I.01"


def test_unknown_panel_boundaries_do_not_guess_an_identity():
    headers = ["Pos", "Part No", "Description", "Qty", "Notes", "Pos", "Part No", "Description", "Qty"]
    assert panels.regions(headers) == [(0, len(headers))]


def test_panel_occurrences_retry_corrections_and_publication_use_durable_api(client, auth_headers, session_factory):
    catalog, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    with vector_pdf(panels_count=2) as pdf:
        raw = pdf.tobytes()
    artifact = checked(upload(client, auth_headers, revision, raw), 201)
    page = assign(client, auth_headers, page, artifact, [1], "SPARE_PARTS_LIST")
    source = page["sources"][0]
    first = extract(client, auth_headers, page, source)
    assert len({row["candidate_id"] for row in first["rows"]}) == 6
    assert any(row["candidate_state"] == "CONFLICT" for row in first["rows"])
    row = first["rows"][0]
    checked(client.patch(f"{BASE}/extraction-candidates/{row['candidate_id']}", headers=auth_headers,
        json={"expected_version": row["candidate_version"], "values": {**row["payload"], "part_number": "QA-HUMAN-CORRECTION"}}))
    retried = extract(client, auth_headers, page, source)
    assert [r["candidate_id"] for r in first["rows"]] == [r["candidate_id"] for r in retried["rows"]]
    assert retried["rows"][0]["payload"]["part_number"] == "QA-HUMAN-CORRECTION"
    state = resume(client, auth_headers, page)["sources"][0]
    assert state["review_state"] != "VERIFIED"
    current = readiness(client, auth_headers, revision)
    assert not current["ready"]
    rejected = client.post(f"{BASE}/revisions/{revision['id']}/publish", headers=auth_headers, json={
        "confirmed": True, "expected_publication_digest": current["publication_digest"],
        "expected_current_published_revision_id": None})
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "catalog_publication_not_ready"
    revisions = checked(client.get(f"{BASE}/catalogs/{catalog['id']}/revisions", headers=auth_headers))
    assert next(r for r in revisions if r["id"] == revision["id"])["status"] == "DRAFT"
