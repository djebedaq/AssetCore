from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend.scripts.migration_history import (
    DEFAULT_MANIFEST,
    DEFAULT_VERSIONS_DIR,
    normalized_sha256,
    validate_migration_history,
    validate_migration_release,
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


def _cli(versions: Path, manifest: Path, *, strict: bool = False):
    command = [
        sys.executable,
        str(DEFAULT_VERSIONS_DIR.parents[1] / "scripts" / "validate_migration_history.py"),
        "--versions-dir", str(versions),
        "--manifest", str(manifest),
    ]
    if strict:
        command.append("--require-all-protected")
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    return result.returncode, json.loads(result.stdout)


def test_strict_gate_requires_future_revision_protection_in_the_same_release(tmp_path: Path):
    versions = tmp_path / "versions"
    shutil.copytree(DEFAULT_VERSIONS_DIR, versions)
    manifest = tmp_path / "manifest.json"
    shutil.copyfile(DEFAULT_MANIFEST, manifest)
    future = versions / "20990101_9999_future.py"
    future.write_bytes(b"revision = '20990101_9999'\r\n")

    normal_code, normal = _cli(versions, manifest)
    strict_code, strict = _cli(versions, manifest, strict=True)
    assert normal_code == 0
    assert normal["valid"] is True
    assert normal["missing"] == normal["mismatched"] == []
    assert future.name in normal["new_unprotected_migrations"]
    assert strict_code == 1
    assert strict["valid"] is False
    assert strict["history_valid"] is True
    assert strict["new_unprotected_migrations"] == normal["new_unprotected_migrations"]

    # Protect every candidate revision in this temporary manifest only. This
    # models completing a migration in its own PR, not a follow-up release.
    content = json.loads(manifest.read_text(encoding="utf-8"))
    for name in normal["new_unprotected_migrations"]:
        content["protected"][name] = normalized_sha256(versions / name)
    manifest.write_text(json.dumps(content), encoding="utf-8")
    future.write_bytes(future.read_bytes().replace(b"\r\n", b"\n"))

    strict_code, strict = _cli(versions, manifest, strict=True)
    assert strict_code == 0
    assert strict["valid"] is strict["history_valid"] is True
    assert strict["missing"] == strict["mismatched"] == []
    assert strict["new_unprotected_migrations"] == []
    assert strict["protected_count"] == len(content["protected"])
    assert validate_migration_release(versions_dir=versions, manifest_path=manifest) == strict


@pytest.mark.parametrize("failure", ["missing", "mismatched", "new_unprotected_migrations"])
def test_strict_cli_and_release_entrypoint_block_every_migration_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, failure: str,
):
    from scripts import verify_release

    versions = tmp_path / "versions"
    versions.mkdir()
    protected = versions / "0001_protected.py"
    protected.write_bytes(b"revision = '0001'\n")
    manifest = _manifest(tmp_path, {protected.name: normalized_sha256(protected)})
    if failure == "missing":
        protected.unlink()
        affected = protected.name
    elif failure == "mismatched":
        protected.write_bytes(b"revision = '0001'\n# unexpected edit\n")
        affected = protected.name
    else:
        future = versions / "9999_future.py"
        future.write_bytes(b"revision = '9999'\n")
        affected = future.name

    normal_code, normal = _cli(versions, manifest)
    strict_code, strict = _cli(versions, manifest, strict=True)
    assert normal_code == (0 if failure == "new_unprotected_migrations" else 1)
    assert normal["valid"] is (failure == "new_unprotected_migrations")
    assert strict_code == 1
    assert strict["valid"] is False
    assert strict[failure] == [affected]

    # Redirect only the input paths: run the real release gate and CLI exit
    # handling. No database, dependency or document QA should run on rejection.
    monkeypatch.setattr(
        verify_release, "validate_migration_release",
        lambda: validate_migration_release(versions_dir=versions, manifest_path=manifest),
    )
    output = tmp_path / "release"
    monkeypatch.setattr(sys, "argv", ["verify_release.py", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        verify_release.main()
    assert error.value.code == 1
    assert '"passed": false' in capsys.readouterr().out
    assert list(output.iterdir()) == []


def test_current_release_baseline_has_no_unprotected_migrations():
    # This is deliberately the strict release contract, not the history
    # validator contract: newly completed revisions must join this PR's manifest.
    report = validate_migration_release()
    assert report["valid"] is report["history_valid"] is True
    assert report["protected_count"] >= 21
    assert report["missing"] == report["mismatched"] == []
    assert report["new_unprotected_migrations"] == []
