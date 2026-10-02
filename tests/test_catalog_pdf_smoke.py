"""Arbitrary-PDF QA does not connect to a DB, mutate the PDF or expose paths."""

import json
import runpy
import subprocess
import sys
from pathlib import Path

from catalog_extraction_fixtures import manual

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "catalog_spare_parts_smoke.py"


def test_offline_smoke_uses_actual_pipeline_and_arbitrary_basename(tmp_path, monkeypatch):
    import sqlalchemy

    def forbidden(*args, **kwargs):
        raise AssertionError("QA must never open a database")
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    path = tmp_path / "arbitrary-unknown-maker.pdf"
    source = manual(repeated=True, missing=True, item_description=True)
    path.write_bytes(source)
    analyzer = runpy.run_path(str(SCRIPT))["extract_pages"]
    report = analyzer(path, [2], no_ocr=True)
    assert path.read_bytes() == source and list(tmp_path.iterdir()) == [path]
    assert str(tmp_path) not in json.dumps(report)
    assert report["extracted_parts"] == 4 and report["selected_pages"] == [2]
    assert report["document_pages"] == 2 and report["ocr_pages"] == 0
    assert report["pages"][0]["tables"][0]["schema"]["mapping"]["2"] == "description"
    assert not any(key in report for key in ["roles", "groups", "hotspots"])



def test_cli_json_and_sanitized_failure_without_absolute_path(tmp_path):
    path = tmp_path / "arbitrary.pdf"
    path.write_bytes(manual(item_description=True))
    result = subprocess.run([sys.executable, str(SCRIPT), str(path), "--page", "2", "--no-ocr"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and json.loads(result.stdout)["extracted_parts"] == 4
    path.write_bytes(b"not a pdf")
    result = subprocess.run([sys.executable, str(SCRIPT), str(path), "--page", "1"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and json.loads(result.stdout)["error"] == "catalog_source_invalid_pdf"
    assert str(tmp_path) not in result.stdout + result.stderr
