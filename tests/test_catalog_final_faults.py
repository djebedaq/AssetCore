"""Additional 03D parser boundary fault injection using synthetic bytes only."""

import subprocess
import sys

import pytest
from app.catalog_admin.parts_extraction import process
from fastapi import HTTPException


@pytest.mark.parametrize("output", [b"{", b"[]", b"\xff", b"{}", b'{"rows": {}}', b'{"error": []}'])
def test_malformed_worker_evidence_is_a_controlled_failure(monkeypatch, output):
    launch = subprocess.Popen

    def malformed(args, **kwargs):
        program = f"from pathlib import Path; Path({args[4]!r}).write_bytes({output!r})"
        return launch([sys.executable, "-c", program], **kwargs)

    monkeypatch.setattr(process.subprocess, "Popen", malformed)
    with pytest.raises(HTTPException) as rejected:
        process.extract(b"QA invalid PDF", "page", 1, {"timeout": 5})
    assert rejected.value.status_code == 422
    assert rejected.value.detail["code"] == "catalog_extraction_resource_limit"


@pytest.mark.skipif(sys.platform == "win32", reason="Unix worker RLIMIT_AS; Windows uses a Job Object")
def test_worker_memory_pressure_fails_without_attempting_host_exhaustion(monkeypatch):
    import fitz
    launch = subprocess.Popen

    def memory_pressure(args, **kwargs):
        # Exercise the real worker.main limits before a deliberately oversized
        # allocation. RLIMIT_AS rejects it; no 2 GiB buffer reaches host RAM.
        program = """
from app.catalog_admin.parts_extraction import worker
def pressure(*args):
    return b'x' * (2 * 1024**3)
worker.extract_page = pressure
worker.main()
"""
        return launch([sys.executable, "-c", program, *args[3:]], **kwargs)

    monkeypatch.setattr(process.subprocess, "Popen", memory_pressure)
    with fitz.open() as document:
        document.new_page().insert_text((40, 40), "Synthetic memory boundary QA")
        result = process.extract(document.tobytes(), "page", 1, {"timeout": 5})
    assert result == {"error": "catalog_extraction_page_failed"}
    # The failed worker must have released its lease for normal parsing.
    monkeypatch.setattr(process.subprocess, "Popen", launch)
    with fitz.open() as document:
        document.new_page()
        assert process.extract(document.tobytes(), "validate", 1, {"timeout": 5, "max_pages": 1}) == {"page_count": 1}
