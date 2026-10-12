"""Nested worker evidence is untrusted, including after a zero exit code."""

import copy
import hashlib
import json
import subprocess
import sys

import fitz
import pytest
from app.catalog_admin.parts_extraction import extraction, process
from app.settings import settings
from catalog_extraction_fixtures import contextual_table
from fastapi import HTTPException
from test_catalog_durable_review import extract, readiness, resume, setup_review
from test_catalog_selected_extraction import BASE


@pytest.fixture
def worker_evidence():
    raw = contextual_table(ruled=True)
    with fitz.open(stream=raw, filetype="pdf") as pdf:
        evidence = extraction.extract_page(pdf[0], {**process.configuration(settings), "ocr_enabled": False})
    for row in evidence["rows"]:
        row["provenance"] = {"sha256": hashlib.sha256(raw).hexdigest(), "physical_page": 1,
            "pipeline_version": evidence["pipeline_version"]}
    assert evidence["rows"] and evidence["tables"] and evidence["words"]
    return evidence


# Delete fields as well as corrupting types: a top-level dict alone is not a row,
# table, quality assessment or mapping that downstream code can safely consume.
INVALID = [
    (("rows",), [{}]),
    (("rows", 0, "payload"), None),
    (("rows", 0, "payload"), {}),
    (("rows", 0, "payload", "position"), []),
    (("rows", 0, "payload", "part_number"), 123),
    (("rows", 0, "payload", "description"), {}),
    (("rows", 0, "payload", "quantity"), []),
    (("rows", 0, "payload", "quantity_raw"), False),
    (("rows", 0, "payload", "technical_notes"), []),
    (("rows", 0, "payload", "unexpected_part_attribute"), "unsafe"),
    (("rows", 0, "warnings"), None),
    (("rows", 0, "warnings"), [{}]),
    (("rows", 0, "bbox"), [1, 2]),
    (("rows", 0, "bbox"), [0, 0, "5", 10]),
    (("rows", 0, "confidence"), True),
    (("rows", 0, "raw_values"), []),
    (("rows", 0, "raw_cells"), [{}]),
    (("rows", 0, "source_row_indices"), [None]),
    (("rows", 0, "occurrence_key"), {}),
    (("rows", 0, "schema"), {}),
    (("rows", 0, "provenance"), {}),
    (("tables",), [{}]),
    (("tables", 0, "headers"), [1]),
    (("tables", 0, "cells"), [None]),
    (("tables", 0, "sample_cells"), [[{}]]),
    (("tables", 0, "row_boxes"), [[0, 1]]),
    (("tables", 0, "row_boxes"), []),
    (("tables", 0, "row_count"), "2"),
    (("tables", 0, "schema"), {}),
    (("tables", 0, "schema", "mapping"), {"bad": "position"}),
    (("tables", 0, "schema", "mapping"), {"0": []}),
    (("tables", 0, "schema", "warnings"), [None]),
    (("tables", 0, "schema", "score"), "high"),
    (("tables", 0, "geometry"), None),
    (("tables", 0, "geometry", "normalized_boundaries"), [0, {}]),
    (("tables", 0, "geometry", "warnings"), {}),
    (("tables", 0, "quality"), None),
    (("tables", 0, "quality", "warnings"), [{}]),
    (("tables", 0, "excluded_rows"), [None]),
    (("tables", 0, "page_width"), "wide"),
    (("quality",), {}),
    (("quality", "state"), []),
    (("quality", "candidate_rows"), True),
    (("quality", "needs_context"), []),
    (("quality", "physical_coverage"), {"missing_rows": []}),
    (("warnings",), [None]),
    (("words",), [{}]),
    (("words", 0, "text"), []),
    (("words", 0, "bbox"), [0, 0, 1]),
    (("rotation_matrix",), [1, 0]),
    (("width",), float("nan")),
    (("additional_evidence",), {"score": float("inf")}),
    (("rows", 0, "bbox"), [0, 0, 10**400, 10]),
    (("rows", 0, "schema", "mapping"), []),
    (("rows", 0, "provenance", "physical_page"), True),
    (("tables", 0, "schema", "alternatives"), [None]),
    (("tables", 0, "anchors"), [None]),
    (("quality", "missing_rows"), -1),
    (("words", 0, "line"), False),
]


def damaged(evidence, path, value):
    result = copy.deepcopy(evidence)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return result


def inject(monkeypatch, evidence):
    launch = subprocess.Popen
    encoded = json.dumps(evidence, ensure_ascii=True)

    def output(args, **kwargs):
        program = f"from pathlib import Path; Path({args[4]!r}).write_text({encoded!r}, encoding='utf-8')"
        return launch([sys.executable, "-c", program], **kwargs)

    monkeypatch.setattr(process.subprocess, "Popen", output)


@pytest.mark.parametrize("path,value", INVALID, ids=[".".join(map(str, p)) + f"-{i}" for i, (p, _) in enumerate(INVALID)])
def test_nested_invalid_evidence_rejected_at_real_process_boundary(monkeypatch, worker_evidence, path, value):
    with monkeypatch.context() as patch:
        inject(patch, damaged(worker_evidence, path, value))
        with pytest.raises(HTTPException) as error:
            process.extract(b"Synthetic boundary QA", "page", 1, {"timeout": 5})
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "catalog_extraction_resource_limit"


@pytest.mark.parametrize("path", [("rows", 0, "payload"), ("rows", 0, "warnings"),
    *(("rows", 0, "payload", key) for key in ("position", "part_number", "description", "quantity", "quantity_raw")),
    *(("rows", 0, key) for key in ("bbox", "raw_text", "schema", "provenance")),
    *(("tables", 0, key) for key in ("headers", "cells", "row_boxes", "quality")),
    ("tables", 0, "schema", "warnings"), ("quality", "missing_rows")])
def test_required_nested_field_cannot_be_absent(monkeypatch, worker_evidence, path):
    target = worker_evidence
    for key in path[:-1]:
        target = target[key]
    del target[path[-1]]
    inject(monkeypatch, worker_evidence)
    with pytest.raises(HTTPException) as error:
        process.extract(b"Synthetic boundary QA", "page", 1, {"timeout": 5})
    assert error.value.status_code == 422


def test_valid_partial_evidence_is_preserved_without_normalizing(monkeypatch, worker_evidence):
    row = worker_evidence["rows"][0]
    row["payload"].update(position="", part_number="", description=None, quantity=None, quantity_raw="?")
    row["warnings"] = ["MISSING_POSITION", "MISSING_PART_NUMBER", "MISSING_DESCRIPTION", "QUANTITY_UNCERTAIN"]
    inject(monkeypatch, worker_evidence)
    assert process.extract(b"Synthetic boundary QA", "page", 1, {"timeout": 5}) == worker_evidence


def test_excessively_nested_json_rejected_and_capacity_released(monkeypatch):
    launch = subprocess.Popen
    encoded = "[" * 1100 + "0" + "]" * 1100

    def output(args, **kwargs):
        program = f"from pathlib import Path; Path({args[4]!r}).write_text({encoded!r})"
        return launch([sys.executable, "-c", program], **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(process.subprocess, "Popen", output)
        with pytest.raises(HTTPException) as error:
            process.extract(b"Synthetic depth QA", "page", 1, {"timeout": 5})
        assert error.value.status_code == 422
    with fitz.open() as pdf:
        pdf.new_page()
        assert process.extract(pdf.tobytes(), "validate", 1, {"timeout": 5, "max_pages": 1}) == {"page_count": 1}


def test_partial_rows_reach_durable_review_as_unconfirmed_candidates(client, auth_headers, session_factory,
        monkeypatch, worker_evidence):
    _, _, page, artifact = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    for row in worker_evidence["rows"]:
        row["provenance"].update(sha256=artifact["sha256"], physical_page=source["page_number"])
    row = worker_evidence["rows"][0]
    row["payload"].update(position="", part_number="", description=None, quantity=None, quantity_raw="?")
    row["warnings"] = ["MISSING_POSITION", "MISSING_PART_NUMBER", "MISSING_DESCRIPTION", "QUANTITY_UNCERTAIN"]
    inject(monkeypatch, worker_evidence)
    preview = extract(client, auth_headers, page, source)
    current = resume(client, auth_headers, page)["sources"][0]
    assert len(preview["rows"]) == len(current["candidates"]) == 2
    assert current["processing_state"] == "SUCCEEDED" and current["review_state"] != "VERIFIED"
    assert all(candidate["state"] == "PENDING" and candidate["part_id"] is None for candidate in current["candidates"])
    assert current["candidates"][0]["values"] == row["payload"]
    assert current["candidates"][0]["original"]["raw_cells"] == row["raw_cells"]
    assert current["candidates"][0]["original"]["warnings"] == row["warnings"]


@pytest.mark.parametrize("path,value", [INVALID[0], INVALID[1], INVALID[28], INVALID[40]])
def test_http_rejection_finishes_attempt_and_allows_retry(client, auth_headers, session_factory,
        monkeypatch, worker_evidence, path, value):
    revision, _, page, _ = setup_review(client, auth_headers, session_factory)
    source = next(s for s in page["sources"] if s["role"] == "SPARE_PARTS_LIST")
    original = extract(client, auth_headers, page, source)
    candidate = original["rows"][0]
    correction = {**candidate["payload"], "part_number": "QA-HUMAN-PRESERVED"}
    saved = client.patch(f"{BASE}/extraction-candidates/{candidate['candidate_id']}", headers=auth_headers,
        json={"expected_version": candidate["candidate_version"], "values": correction})
    assert saved.status_code == 200
    with monkeypatch.context() as patch:
        inject(patch, damaged(worker_evidence, path, value))
        response = client.post(f"{BASE}/reference-pages/{page['id']}/extract", headers=auth_headers,
            json={"visual_page_id": source["id"]})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "catalog_extraction_resource_limit"
    current = resume(client, auth_headers, page)["sources"][0]
    assert current["processing_state"] == "FAILED" and current["review_state"] != "VERIFIED"
    assert [a["state"] for a in current["attempts"]] == ["SUCCEEDED", "FAILED"]
    assert current["attempts"][-1]["error_code"] == "catalog_extraction_resource_limit"
    assert len(current["candidates"]) == len(original["rows"])
    assert current["preview"]["rows"][0]["payload"] == correction
    assert not readiness(client, auth_headers, revision)["ready"]
    retry = extract(client, auth_headers, page, source)
    assert retry["rows"][0]["payload"] == correction
    assert [r["candidate_id"] for r in retry["rows"]] == [r["candidate_id"] for r in original["rows"]]
    current = resume(client, auth_headers, page)["sources"][0]
    assert current["processing_state"] == "SUCCEEDED" and current["review_state"] != "VERIFIED"
    assert [a["state"] for a in current["attempts"]] == ["SUCCEEDED", "FAILED", "SUCCEEDED"]
