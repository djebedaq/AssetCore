"""The independent comparator cannot pass a subset or hide a failed exit code."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import catalog_oem_layout_qa as qa


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    monkeypatch.setattr(qa, "CASES", [("synthetic/layout", "synthetic.pdf", "2,4")])
    expected = [{"source_document_sha256": "a" * 64, "source_page": page, "position": "7",
        "part_number": "QA-0001-A.02", "quantity": 2, "quantity_raw": "2", "original_name": "QA seal"} for page in (2, 4)]
    control = tmp_path / "backend/resources/catalog/v2/synthetic/layout.json"
    control.parent.mkdir(parents=True)
    control.write_text(json.dumps({"records": expected}))
    outputs = [{"physical_page": row["source_page"], "resources": {}, "result": {"rows": [{
        "payload": {"position": row["position"], "part_number": row["part_number"],
            "quantity": "2", "quantity_raw": "2", "description": "QA seal"},
        "provenance": {"sha256": "a" * 64, "physical_page": row["source_page"]}}]}} for row in expected]
    return [{"case": "synthetic/layout", "report": {"source_sha256": "a" * 64, "runs": [{"pages": outputs}]}}]


@pytest.mark.parametrize("omission", ["case", "page", "duplicate_case", "duplicate_page", "source"])
def test_incomplete_or_substituted_corpus_cannot_pass(corpus, omission):
    broken = copy.deepcopy(corpus)
    if omission == "case":
        broken = []
    elif omission == "duplicate_case":
        broken *= 2
    elif omission == "page":
        broken[0]["report"]["runs"][0]["pages"].pop()
    elif omission == "duplicate_page":
        broken[0]["report"]["runs"][0]["pages"][1] = broken[0]["report"]["runs"][0]["pages"][0]
    else:
        broken[0]["report"]["source_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="QA_"):
        qa.compare(broken)


@pytest.mark.parametrize("changed", [False, True])
def test_exact_fields_and_cli_status(corpus, changed, tmp_path, monkeypatch):
    if changed:
        corpus[0]["report"]["runs"][0]["pages"][0]["result"]["rows"][0]["payload"]["quantity_raw"] = "02"
    report, output = tmp_path / "report.json", tmp_path / "comparison.json"
    report.write_text(json.dumps(corpus))
    monkeypatch.setattr(sys, "argv", ["qa", "compare", "--report", str(report), "--output", str(output)])
    assert qa.main() == (1 if changed else 0)
    compared = json.loads(output.read_text())
    assert compared["passed"] is (not changed)
    assert compared["cases"][0]["pages"][0]["automatic_exact_acceptance"] == ("FAIL" if changed else "PASS")
