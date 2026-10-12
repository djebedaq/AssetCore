"""The independent QA comparator must consume real occurrences only once."""
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("actual_count", [1, 2])
def test_corpus_comparator_preserves_duplicate_source_occurrences(tmp_path, monkeypatch, actual_count):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import catalog_final_corpus_qa as qa
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    source = "a" * 64
    control = tmp_path / "backend/resources/catalog/v2/synthetic/fixture.json"
    control.parent.mkdir(parents=True)
    record = {"position": "1", "part_number": "QA-CONTROL", "description_en": "Synthetic QA component",
        "quantity": 1, "quantity_raw": "1", "source_page": 2, "source_document_sha256": source}
    control.write_text(json.dumps({"records": [record, record]}), encoding="utf-8")
    payload = {key: record[key] for key in ("position", "part_number", "quantity", "quantity_raw")}
    payload["description"] = record["description_en"]
    report = [{"case": "synthetic/fixture", "report": {"source_sha256": source, "runs": [{"pages": [{
        "physical_page": 2, "result": {"rows": [{"payload": payload, "provenance": {
            "sha256": source, "physical_page": 2}} for _ in range(actual_count)], "quality": {"state": "NEEDS_REVIEW"}},
        "resources": {}}]}]}}]
    page = qa.compare(report)["cases"][0]["pages"][0]
    assert page["expected_rows"] == 2
    assert page["extracted_candidates"] == actual_count
    assert page["exact_rows_unordered_all_five_fields"] == actual_count
    assert page["paired_fields"]["position_number_pair"] == actual_count
    assert page["ordered_exact_fields"]["part_number"] == actual_count
    assert page["quality"]["state"] == "NEEDS_REVIEW"
