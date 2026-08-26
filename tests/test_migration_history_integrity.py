from __future__ import annotations

import json
import shutil
from pathlib import Path

from backend.scripts.migration_history import (
    DEFAULT_MANIFEST,
    DEFAULT_VERSIONS_DIR,
    normalized_sha256,
    validate_migration_history,
)

OFFICIAL_DOCUMENT_INTEGRITY_MIGRATION = (
    "20260826_0020_official_document_integrity.py"
)
OFFICIAL_DOCUMENT_INTEGRITY_SHA256 = (
    "8129ca08d3c7c8717c3a563713c55e1478d4cd60812dac4d0e2bd90d9fbcb5f6"
)
AUTH_SESSION_MIGRATION = "20260826_0021_auth_session_hardening.py"
AUTH_SESSION_SHA256 = (
    "02d49643efc60b3bcf8da2831e11864f21e297e0cc40a32bd2a18b9d3e4bfeac"
)


def test_current_migration_history_baseline_protects_revision_0020():
    report = validate_migration_history()
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))

    assert report["valid"] is True
    assert report["protected_count"] >= 20
    assert report["missing"] == []
    assert report["mismatched"] == []
    assert (
        manifest["protected"][OFFICIAL_DOCUMENT_INTEGRITY_MIGRATION]
        == OFFICIAL_DOCUMENT_INTEGRITY_SHA256
    )
    assert report["protected_count"] >= 21
    assert manifest["protected"][AUTH_SESSION_MIGRATION] == AUTH_SESSION_SHA256


def test_current_protected_baseline_allows_a_future_revision(tmp_path: Path):
    baseline_report = validate_migration_history()
    baseline_unprotected = set(baseline_report["new_unprotected_migrations"])
    versions = tmp_path / "versions"
    shutil.copytree(DEFAULT_VERSIONS_DIR, versions)
    future_revision = versions / "20990101_0021_future.py"
    future_revision.write_text("revision = '0021'\n", encoding="utf-8")

    report = validate_migration_history(
        versions_dir=versions,
        manifest_path=DEFAULT_MANIFEST,
    )

    assert report["valid"] is True
    assert report["missing"] == []
    assert report["mismatched"] == []
    assert future_revision.name not in baseline_unprotected
    assert set(report["new_unprotected_migrations"]) == baseline_unprotected | {
        future_revision.name
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
