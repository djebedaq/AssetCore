"""Additional 03D parser boundary fault injection using synthetic bytes only."""

import subprocess
import sys

import pytest
from app.catalog_admin.parts_extraction import process
from fastapi import HTTPException


@pytest.mark.parametrize("output", [b"{", b"[]", b"\xff"])
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
