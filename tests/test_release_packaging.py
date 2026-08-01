from __future__ import annotations

from pathlib import Path

from scripts import build_release, verify_release


def test_release_exclusions_cover_local_data_secrets_and_temporary_documents():
    excluded = (
        "assetcore.db",
        "local.sqlite3",
        ".env.production",
        "private_keys/signing.pem",
        "secrets/token.txt",
        ".pytest_cache/state",
        "backend/__pycache__/models.pyc",
        "backend/.venv/Lib/site-packages/fastapi/__init__.py",
        "frontend/tsconfig.tsbuildinfo",
        ".tmp/generated.docx",
        "docs/~$temporary.docx",
    )
    assert all(build_release.is_excluded(Path(name)) for name in excluded)
    assert not build_release.is_excluded(Path("backend/resources/templates/transfer_issue-bg-v2.docx"))


def test_release_verifier_lists_files_without_git_metadata(tmp_path, monkeypatch):
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "app.py").write_text("# release copy", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "state").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(verify_release, "ROOT", tmp_path)
    assert verify_release._tracked_files() == ["backend/app.py"]
