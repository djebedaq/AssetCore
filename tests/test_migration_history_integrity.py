from __future__ import annotations

import json
from pathlib import Path

from backend.scripts.migration_history import normalized_sha256, validate_migration_history


def test_current_migration_history_baseline_protects_revision_0020():
    report = validate_migration_history()

    assert report == {
        "valid": True,
        "algorithm": "sha256-normalized-lf",
        "protected_count": 20,
        "missing": [],
        "mismatched": [],
        "new_unprotected_migrations": [],
    }


def _manifest(path: Path, protected: dict[str, str]) -> Path:
    manifest = path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format": 1,
                "algorithm": "sha256-normalized-lf",
                "protected": protected,
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_migration_history_validator_rejects_mismatched_protected_revision(
    tmp_path: Path,
):
    versions = tmp_path / "versions"
    versions.mkdir()
    protected = versions / "0001_protected.py"
    protected.write_text("revision = '0001'\n", encoding="utf-8")
    manifest = _manifest(tmp_path, {protected.name: "0" * 64})

    report = validate_migration_history(
        versions_dir=versions,
        manifest_path=manifest,
    )

    assert report["valid"] is False
    assert report["mismatched"] == [protected.name]
    assert report["missing"] == []


def test_migration_history_validator_accepts_new_unprotected_revision(
    tmp_path: Path,
):
    versions = tmp_path / "versions"
    versions.mkdir()
    protected = versions / "0001_protected.py"
    protected.write_bytes(b"revision = '0001'\r\n")
    new_revision = versions / "0002_new.py"
    new_revision.write_text("revision = '0002'\n", encoding="utf-8")
    manifest = _manifest(
        tmp_path,
        {protected.name: normalized_sha256(protected)},
    )

    report = validate_migration_history(
        versions_dir=versions,
        manifest_path=manifest,
    )

    assert report["valid"] is True
    assert report["new_unprotected_migrations"] == [new_revision.name]
