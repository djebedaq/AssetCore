"""Manufacturer-neutral extraction, coverage, group context and durable identity."""

import copy
import io
import json
import subprocess
import sys
import time
from pathlib import Path

import fitz
import pytest
from app.catalog_admin.parts_extraction import context, extraction, ledger, process, quality, raster
from app.catalog_admin.parts_extraction.tables import parse_region
from app.settings import settings
from catalog_extraction_fixtures import centered_geometry, manual
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select
from test_catalog_durable_review import accept, extract, resume, setup_review
from test_catalog_guided_builder import assign
from test_catalog_multipage_extraction import multipage_pdf
from test_catalog_selected_extraction import BASE, checked, upload, workspace


def test_invalid_find_tables_does_not_suppress_independent_native_layout(monkeypatch):
    _, metadata = parse_region(["Date", "Version", "Page"], [["2026-10-11", "v2.0", "1"]],
        [[10, 10, 250, 30]], [10, 10, 250, 30], "NATIVE_TABLE")
    monkeypatch.setattr(extraction, "ruled_rows", lambda *a, **k: ([], [metadata]))
    def unexpected(*a, **k):
        pytest.fail("A reliable native BOM must not start raster OCR")
    monkeypatch.setattr(raster, "extract", unexpected)
    with fitz.open(stream=manual(), filetype="pdf") as pdf:
        result = extraction.extract_page(pdf[1], process.configuration(settings))
    assert len(result["rows"]) == 4 and not result["ocr_used"]
    assert result["quality"]["state"] == "COMPLETE_CANDIDATES"
    assert any(s.get("rejected") == "DOCUMENT_METADATA" for s in result["strategies"])


@pytest.mark.parametrize("position,number,description,qty", [
    ("!", "0001-A.02", "QA item", "2"), ("", "0001-A.02", "", "?"),
    ("", "", "QA description only", ""), ("13A", "", "QA seal", "wrong"),
    ("", "", "", "")])
def test_physical_partial_and_empty_bands_remain_candidates(position, number, description, qty):
    cells = [["1", "QA-BASE", "QA component", "1"], [position, number, description, qty], ["9", "QA-LAST", "QA last", "2"]]
    rows, table = parse_region(["Pos", "Part No", "Description", "Qty"], cells,
        [[0, 10 + i * 20, 400, 30 + i * 20] for i in range(3)], [0, 0, 400, 70], "IMAGE_CELL_OCR")
    assert len(rows) == 3
    assert rows[1]["payload"]["part_number"] == number
    assert rows[1]["payload"]["position"] == position
    assert rows[1]["warnings"]
    assessment = quality.assessment(rows, table)
    assert assessment["covered_rows"] == assessment["observed_rows"] == 3
    assert assessment["state"] == "NEEDS_REVIEW"


def test_missing_visible_band_is_reported_without_position_sequence_assumptions():
    cells = [[str(i), f"QA-{i}", "QA component", "2"] for i in (1, 9, 48)]
    rows, table = parse_region(["Pos", "Part No", "Description", "Qty"], cells,
        [[0, i * 20, 400, i * 20 + 20] for i in range(3)], [0, 0, 400, 60], "NATIVE_TABLE")
    assert quality.assessment(rows, table)["missing_rows"] == 0
    observed = quality.assessment(rows[:2], table)
    assert observed["missing_rows"] == 1 and "ROW_COVERAGE_INCOMPLETE" in observed["warnings"]


def test_distinct_identical_visible_rows_keep_distinct_identity_under_bbox_drift():
    with fitz.open(stream=centered_geometry(multiple=True), filetype="pdf") as pdf:
        result = extraction.extract_page(pdf[0], {**process.configuration(settings), "ocr_enabled": False})
    assert len(result["rows"]) == 6
    assert len({ledger.row_key(row) for row in result["rows"]}) == 6
    shifted = copy.deepcopy(result["rows"])
    for row in shifted:
        row["bbox"] = [x + .01 for x in row["bbox"]]
    assert [ledger.row_key(row) for row in shifted] == [ledger.row_key(row) for row in result["rows"]]


@pytest.mark.parametrize("foreign", [False, True])
def test_headerless_semantic_context_uses_local_geometry_and_rejects_foreign_pdf(foreign):
    config = {**process.configuration(settings), "ocr_enabled": False, "source_sha256": "a" * 64}
    with fitz.open(stream=multipage_pdf(headerless=True), filetype="pdf") as pdf:
        first = extraction.extract_page(pdf[1], config)
        second = extraction.extract_page(pdf[2], {**config, "context_profiles": context.profiles(first, "b" * 64 if foreign else "a" * 64)})
    assert len(second["rows"]) == (0 if foreign else 5)
    assert second["tables"][0]["cells"][0][0] == "6"
    if not foreign:
        assert second["tables"][0]["schema"]["method"] == "SEMANTIC_GROUP_PROFILE"
        assert second["tables"][0]["geometry"]["normalized_boundaries"] == pytest.approx(first["tables"][0]["geometry"]["normalized_boundaries"])
        assert all("CONTEXT_SCHEMA_INFERRED" in row["warnings"] for row in second["rows"])


@pytest.mark.parametrize("count", [1, 2, 3, 4, 7])
def test_n_selected_lists_and_later_page_context_resume(client, auth_headers, session_factory, monkeypatch, count):
    monkeypatch.setattr(settings, "catalog_ocr_enabled", False)
    _, revision = workspace(client, auth_headers, session_factory)
    assembly = checked(client.get(f"{BASE}/revisions/{revision['id']}/assemblies", headers=auth_headers))[0]
    page = checked(client.post(f"{BASE}/assemblies/{assembly['id']}/reference-pages", headers=auth_headers, json={}), 201)
    artifact = checked(upload(client, auth_headers, revision, multipage_pdf(count=count, headerless=True)), 201)
    page = assign(client, auth_headers, page, artifact, list(range(3, count + 2)) + [2], "SPARE_PARTS_LIST")
    sources = page["sources"]
    first_pass = [extract(client, auth_headers, page, source) for source in sources]
    for source, preview in zip(sources, first_pass, strict=True):
        if preview["quality"]["needs_context"]:
            preview = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers, json={
                "visual_page_id": source["id"], "expected_version": page["version"], "group_context": True, "context_only": True}))
        assert len(preview["rows"]) == 5
        accept(client, auth_headers, page, preview)
    durable = resume(client, auth_headers, page)
    assert len(durable["sources"]) == count
    assert all(source["review_state"] != "VERIFIED" for source in durable["sources"])
    assert sum(len(source["candidates"]) for source in durable["sources"]) == count * 5


def test_stale_group_request_cannot_start_attempt(client, auth_headers, session_factory):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    response = client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers, json={
        "visual_page_id": source["id"], "expected_version": page["version"] + 1, "group_context": True})
    assert response.status_code == 409
    assert not resume(client, auth_headers, page)["sources"][0]["attempts"]


def test_foreign_semantic_profile_uses_only_compatible_local_columns():
    rows, table = parse_region(["Pos", "Part No", "Description", "Qty"],
        [["1", "QA-0001", "QA original", "2"]], [[0, 20, 400, 40]], [0, 0, 400, 40], "NATIVE_TABLE")
    table["geometry"] = {"normalized_boundaries": [0, .1, .3, .9, 1]}
    table["quality"] = quality.assessment(rows, table)
    profile = context.profiles({"tables": [table]}, "a" * 64)[0]
    _, local = parse_region(["Pos", "Part No", "", ""],
        [["9", "QA-LOCAL-009", "QA local description", "3"]], [[50, 100, 800, 130]], [50, 80, 800, 130], "NATIVE_TABLE")
    local["geometry"] = {"normalized_boundaries": [.05, .25, .55, .85, .95]}
    local["schema"]["state"] = "NEEDS_REVIEW"
    resolved, tables = context.resolve([], [local], {"source_sha256": "b" * 64, "context_profiles": [profile]})
    assert resolved[0]["payload"]["part_number"] == "QA-LOCAL-009"
    assert resolved[0]["bbox"] == [50, 100, 800, 130]
    assert tables[0]["geometry"]["normalized_boundaries"] == [.05, .25, .55, .85, .95]
    assert tables[0]["context"]["sha256"] == "a" * 64


def test_native_island_cannot_hide_an_unread_raster_region(monkeypatch):
    from app.catalog_admin.parts_extraction import ocr, region_ocr
    def unavailable(*args, **kwargs):
        raise RuntimeError("QA unavailable")
    monkeypatch.setattr(raster, "extract", unavailable)
    monkeypatch.setattr(region_ocr, "extract", unavailable)
    monkeypatch.setattr(ocr, "textpage", unavailable)
    data = io.BytesIO()
    Image.new("RGB", (400, 400), "white").save(data, format="PNG")
    with fitz.open(stream=manual(), filetype="pdf") as pdf:
        pdf[1].insert_image(fitz.Rect(20, 400, 570, 800), stream=data.getvalue())
        result = extraction.extract_page(pdf[1], {**process.configuration(settings), "ocr_enabled": True})
    assert len(result["rows"]) == 4
    assert result["quality"]["state"] == "NEEDS_REVIEW"
    assert result["quality"]["unresolved_regions"] == 1
    assert "RASTER_COVERAGE_UNRESOLVED" in result["warnings"]


@pytest.mark.parametrize("headers,expected", [
    (["Pos.", "Teile-Nr.", "Benennung", "Menge"], "deu"),
    (["Позиция", "Номер част", "Описание", "Бр."], "bul"),
    (["Позиция", "Номер детали", "Наименование", "Кол-во"], "rus"),
    (["No.", "Part No.", "Item", "Qty"], "eng")])
def test_description_language_comes_from_local_headers_not_header_reading_model(headers, expected):
    assert raster.description_model([{"text": value} for value in headers], "eng") == expected


def test_changed_artifact_bytes_cannot_start_group_worker(client, auth_headers, session_factory):
    from app.models import CatalogRevisionArtifact
    _, _, page, artifact = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    with session_factory() as db:
        db.get(CatalogRevisionArtifact, artifact["id"]).content += b"\n% QA changed source\n"
        db.commit()
    rejected = client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers, json={
        "visual_page_id": source["id"], "expected_version": page["version"], "group_context": True})
    assert rejected.status_code == 422 and rejected.json()["detail"]["code"] == "catalog_source_integrity"
    with session_factory() as db:
        assert not list(db.scalars(select(ledger.Attempt)))
    assert client.post(f"{BASE}/reference-pages/{page['id']}/review-session", headers=auth_headers).status_code == 422


def test_competing_readings_are_preserved_and_require_review():
    rows, table = parse_region(["Pos", "Part No", "Description", "Qty"],
        [["1", "0001-A.02", "QA item", "2"]], [[0, 20, 400, 40]], [0, 0, 400, 40], "NATIVE_TABLE")
    competing, other = copy.deepcopy(rows), copy.deepcopy(table)
    competing[0]["payload"]["part_number"] = "OOO1-A.02"
    chosen, tables, coverage, _ = quality.choose([("A", rows, [table]), ("B", competing, [other])])
    assert chosen[0]["payload"]["part_number"] == "0001-A.02"
    assert tables[0]["competing_readings"][0]["rows"][0]["payload"]["part_number"] == "OOO1-A.02"
    assert coverage["state"] == "NEEDS_REVIEW"
    assert "STRATEGY_DISAGREEMENT" in chosen[0]["warnings"]


def test_broad_layout_cannot_duplicate_an_overlapping_physical_table():
    headers = ["Pos", "Part No", "Description", "Qty"]
    cells = [[str(i), f"QA-{i:04}", "QA item", "2"] for i in range(6)]
    boxes = [[0, i * 20, 400, i * 20 + 20] for i in range(6)]
    incomplete = copy.deepcopy(cells[:3])
    incomplete[0][1] = ""
    first, t1 = parse_region(headers, incomplete, boxes[:3], [0, 0, 400, 60], "NATIVE_TABLE")
    second, t2 = parse_region(headers, cells[3:], boxes[3:], [0, 60, 400, 120], "NATIVE_TABLE")
    broad, t3 = parse_region(headers, cells, boxes, [0, 0, 400, 120], "WORD_LAYOUT")
    strategies = [("A", first + second, [t1, t2]), ("B", broad, [t3])]
    rows, tables, coverage, _ = quality.choose(strategies)
    assert len(rows) == 6
    assert len({tuple(row["bbox"]) for row in rows}) == 6
    assert any(e["reason"] == "DUPLICATE_REGION" for t in tables for e in t.get("excluded_rows", []))
    assert coverage["state"] == "NEEDS_REVIEW"
    assert quality.choose(strategies)[:3] == (rows, tables, coverage)


def test_completed_raster_regions_survive_later_timeout(monkeypatch):
    rows, table = parse_region(["Pos", "Part No", "Description", "Qty"],
        [["1", "0001-A.02", "QA item", "2"]], [[0, 20, 400, 40]], [0, 0, 400, 40], "IMAGE_CELL_OCR")
    def interrupted(*args, **kwargs):
        yield rows, table
        raise TimeoutError("OCR_TIME_BUDGET")
    monkeypatch.setattr(raster, "regions", interrupted)
    kept, tables = raster.extract(None, {})
    assert kept == rows and len(tables) == 1
    assert quality.assessment(kept, tables[0])["state"] == "NEEDS_REVIEW"
    assert "OCR_TIME_BUDGET" in tables[0]["strategy_warnings"]


def test_cleaner_ocr_proposal_cannot_discard_unreadable_physical_rows():
    headers = ["Pos", "Part No", "Description", "Qty"]
    cells = [[str(i), f"QA-{i:04}", "QA item", "" if i in (2, 3) else "2"] for i in range(1, 5)]
    boxes = [[0, i * 20, 400, i * 20 + 20] for i in range(4)]
    physical, grid = parse_region(headers, cells, boxes, [0, 0, 400, 80], "IMAGE_CELL_OCR")
    readable, layout = parse_region(headers, [cells[0], cells[3]], [boxes[0], boxes[3]], [0, 0, 400, 80], "WORD_LAYOUT")
    rows, _, coverage, _ = quality.choose([("CELL", physical, [grid]), ("LAYOUT", readable, [layout])])
    assert len(rows) == 4
    assert {row["payload"]["position"] for row in rows} == {"1", "2", "3", "4"}
    assert all(row["payload"]["quantity"] is None for row in rows if row["payload"]["position"] in {"2", "3"})
    assert coverage["state"] == "NEEDS_REVIEW"


def test_unresolved_grid_columns_cannot_hide_missing_physical_rows():
    headers = ["Pos", "Part No", "Description", "Qty"]
    cells = [[str(i), f"QA-{i:04}", "QA item", "2"] for i in range(1, 5)]
    boxes = [[0, i * 20, 400, i * 20 + 20] for i in range(4)]
    _, grid = parse_region(headers, cells, boxes, [0, 0, 400, 80], "IMAGE_CELL_OCR")
    grid["schema"].update(state="NEEDS_REVIEW", mapping={})
    readable, layout = parse_region(headers, [cells[0], cells[3]], [boxes[0], boxes[3]], [0, 0, 400, 80], "WORD_LAYOUT")
    rows, tables, coverage, _ = quality.choose([("CELL", [], [grid]), ("LAYOUT", readable, [layout])])
    assert len(rows) == 2
    assert coverage["observed_rows"] == 4 and coverage["missing_rows"] == 2
    assert coverage["state"] == "NEEDS_REVIEW" and coverage["needs_context"]
    assert any(t["schema"]["state"] == "NEEDS_REVIEW" and t["cells"] == cells for t in tables)


def test_overlapping_competing_values_require_reconciliation():
    headers = ["Pos", "Part No", "Description", "Qty"]
    cells = [[str(i), f"QA-{i:04}", "QA item", "" if i in (2, 3) else "2"] for i in range(1, 5)]
    boxes = [[0, i * 20, 400, i * 20 + 20] for i in range(4)]
    physical, grid = parse_region(headers, cells, boxes, [0, 0, 400, 80], "IMAGE_CELL_OCR")
    competing = copy.deepcopy([cells[0], cells[3]])
    competing[0][1] = "QA-COMPETING-READING"
    readable, layout = parse_region(headers, competing, [boxes[0], boxes[3]], [0, 0, 400, 80], "WORD_LAYOUT")
    rows, _, coverage, _ = quality.choose([("CELL", physical, [grid]), ("LAYOUT", readable, [layout])])
    ambiguous = [row for row in rows if row["payload"]["position"] == "1"]
    assert len(ambiguous) == 2 and all(row["reconciliation_required"] for row in ambiguous)
    assert {row["payload"]["position"] for row in rows} == {"1", "2", "3", "4"}
    assert coverage["state"] == "NEEDS_REVIEW"


@pytest.mark.parametrize("number,qty,warning", [
    ("00А1-A.02", "2", "IDENTIFIER_MIXED_SCRIPTS"),
    ("0001-A.02", "-2", "QUANTITY_UNCERTAIN"),
    ("0001-A.02", "0", "QUANTITY_IMPLAUSIBLE"),
    ("0001-A.02", "1000001", "QUANTITY_IMPLAUSIBLE"),
    ("00 01-A.02", "2", "IDENTIFIER_SPACING")])
def test_suspicious_original_cells_are_preserved_without_substitution(number, qty, warning):
    rows, table = parse_region(["Pos", "Part No", "Description", "Qty"],
        [["13A", number, "QA original description", qty]], [[0, 20, 400, 40]], [0, 0, 400, 40], "IMAGE_CELL_OCR")
    assert rows[0]["payload"]["part_number"] == number
    assert warning in rows[0]["warnings"]
    assert quality.assessment(rows, table)["state"] == "NEEDS_REVIEW"


def test_identical_occurrences_have_separate_durable_corrections(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    real = process.extract
    visible = [5]
    def identical(*args):
        result = real(*args)
        for row in result["rows"]:
            row["payload"] = copy.deepcopy(result["rows"][0]["payload"])
        result["rows"] = result["rows"][:visible[0]]
        result["rows"], result["tables"], result["quality"], _ = quality.choose([
            ("NATIVE_TABLE", result["rows"], result["tables"])])
        return result
    monkeypatch.setattr(process, "extract", identical)
    preview = extract(client, auth_headers, page, source)
    assert len({r["candidate_id"] for r in preview["rows"]}) == 5
    assert preview["rows"][0]["candidate_state"] == "PENDING"
    assert all(r["candidate_state"] == "CONFLICT" for r in preview["rows"][1:])
    row = preview["rows"][0]
    checked(client.patch(f"{BASE}/extraction-candidates/{row['candidate_id']}", headers=auth_headers, json={
        "expected_version": row["candidate_version"], "values": {**row["payload"], "part_number": "QA-HUMAN-FIRST-OCCURRENCE"}}))
    repeated = extract(client, auth_headers, page, source)
    assert [r["candidate_id"] for r in repeated["rows"]] == [r["candidate_id"] for r in preview["rows"]]
    assert repeated["rows"][0]["payload"]["part_number"] == "QA-HUMAN-FIRST-OCCURRENCE"
    assert all(r["payload"]["part_number"] == row["payload"]["part_number"] for r in repeated["rows"][1:])
    assert len(resume(client, auth_headers, page)["sources"][0]["candidates"]) == 5
    visible[0] = 4
    ambiguous = extract(client, auth_headers, page, source)
    assert all(r["candidate_state"] == "CONFLICT" for r in ambiguous["rows"])
    assert ambiguous["rows"][0]["payload"]["part_number"] == "QA-HUMAN-FIRST-OCCURRENCE"
    assert all(c["state"] == "CONFLICT" for c in resume(client, auth_headers, page)["sources"][0]["candidates"])


def test_identical_visible_rows_require_explicit_link_instead_of_automatic_merge(client, auth_headers, session_factory, monkeypatch):
    _, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    real = process.extract
    def repeated(*args):
        result = real(*args)
        result["rows"] = result["rows"][:2]
        result["rows"][1]["payload"] = copy.deepcopy(result["rows"][0]["payload"])
        result["rows"], result["tables"], result["quality"], _ = quality.choose([
            ("NATIVE_TABLE", result["rows"], result["tables"])])
        return result
    monkeypatch.setattr(process, "extract", repeated)
    preview = extract(client, auth_headers, page, source)
    first, second = preview["rows"]
    assert first["candidate_id"] != second["candidate_id"] and second["candidate_state"] == "CONFLICT"
    rejected = client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers, json={
        "token": preview["token"], "rows": [{"index": 1, "part": second["payload"]}], "confirm_warnings": True})
    assert rejected.status_code == 409
    accepted = checked(client.post(f"{BASE}/reference-pages/{page['id']}/extraction/confirm", headers=auth_headers, json={
        "token": preview["token"], "rows": [{"index": 0, "part": first["payload"]}], "confirm_warnings": True}))
    checked(client.patch(f"{BASE}/extraction-candidates/{second['candidate_id']}", headers=auth_headers, json={
        "expected_version": second["candidate_version"], "action": "LINK_EXISTING", "part_id": accepted["part_ids"][0],
        "reason": "QA explicitly reviewed two separate original rows and chose a shared component identity"}))
    durable = resume(client, auth_headers, page)["sources"][0]
    assert len(durable["candidates"]) == 2 and all(c["state"] == "ACCEPTED" for c in durable["candidates"])
    assert durable["candidates"][0]["original"]["bbox"] != durable["candidates"][1]["original"]["bbox"]
    assert len(checked(client.get(f"{BASE}/reference-pages/{page['id']}/parts", headers=auth_headers))) == 1


@pytest.mark.skipif(sys.platform == "win32", reason="Unix process-group termination; Windows uses the existing Job Object")
@pytest.mark.parametrize("crash", [False, True])
def test_timeout_kills_worker_and_child_without_application_environment(tmp_path, monkeypatch, crash):
    marker = tmp_path / "child.json"
    launch = subprocess.Popen
    workers = []
    def fake_worker(args, **kwargs):
        program = ("import os,sys,subprocess,json,time; from pathlib import Path; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)']); "
            f"Path({str(marker)!r}).write_text(json.dumps([child.pid,'SECRET_KEY' in os.environ])); "
            + ("sys.exit(1)" if crash else "time.sleep(120)"))
        worker = launch([sys.executable, "-c", program], **kwargs)
        workers.append(worker)
        return worker
    monkeypatch.setenv("SECRET_KEY", "QA-DO-NOT-INHERIT")
    monkeypatch.setattr(process.subprocess, "Popen", fake_worker)
    with pytest.raises(HTTPException) as error:
        process.extract(b"invalid synthetic PDF", "page", 1, {"timeout": 2})
    assert error.value.detail["code"] == ("catalog_extraction_resource_limit" if crash else "catalog_extraction_timeout")
    pid, inherited_secret = json.loads(marker.read_text())
    assert not inherited_secret and workers[0].poll() is not None
    status = Path(f"/proc/{pid}/stat")
    # Match the existing production Compose init:true contract. Require reaping,
    # including zombies, rather than merely checking that CPU use has stopped.
    deadline = time.monotonic() + 2
    while status.exists() and time.monotonic() < deadline:
        time.sleep(.02)
    assert not status.exists()
