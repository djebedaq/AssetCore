"""Arbitrary-PDF QA does not connect to a DB, mutate the PDF or expose paths."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

from catalog_ingest_fixtures import manual

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "catalog_pdf_smoke.py"


def test_offline_smoke_uses_actual_pipeline_and_arbitrary_basename(tmp_path, monkeypatch):
    import sqlalchemy

    def forbidden(*args, **kwargs):
        raise AssertionError("QA must never open a database")
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    path = tmp_path / "arbitrary-unknown-maker.pdf"
    source = manual(repeated=True, missing=True, item_description=True)
    path.write_bytes(source)
    analyzer = runpy.run_path(str(SCRIPT))["analyze_pdf"]
    report = analyzer(path, details=True, no_ocr=True)
    assert path.read_bytes() == source and list(tmp_path.iterdir()) == [path]
    assert report["filename"] == path.name and str(tmp_path) not in json.dumps(report)
    assert report["extracted_parts"] == 4 and report["resolved_bom_schemas"] == 1
    assert report["native_pages"] == 2 and report["ocr_pages"] == 0
    assert report["roles"]["SPARE_PARTS_LIST"] == 1 and report["roles"]["EXPLODED_SCHEME"] == 1
    assert report["hotspots"] == {"EXACT": 2, "MULTIPLE_CANDIDATES": 1, "NOT_FOUND": 1, "LOW_CONFIDENCE": 0}
    assert report["pages"][1]["tables"][0]["schema"]["mapping"]["2"] == "description"


def test_cli_json_and_sanitized_failure_without_absolute_path(tmp_path):
    path = tmp_path / "arbitrary.pdf"
    path.write_bytes(manual(item_description=True))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path), "--no-ocr"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and json.loads(result.stdout)["extracted_parts"] == 4
    path.write_bytes(b"not a pdf")
    result = subprocess.run([sys.executable, str(SCRIPT), str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and json.loads(result.stdout)["error"] == "catalog_source_invalid_pdf"
    assert str(tmp_path) not in result.stdout + result.stderr
