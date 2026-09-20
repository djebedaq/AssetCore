from __future__ import annotations

import importlib.util
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_postgres_smoke_module():
    path = ROOT / "scripts" / "postgres_smoke_test.py"
    spec = importlib.util.spec_from_file_location("assetcore_postgres_smoke", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_smoke_uses_current_alembic_head() -> None:
    module = _load_postgres_smoke_module()
    assert module._expected_head() == "20260920_0022"


def test_ci_covers_frontend_backend_postgres_and_docker() -> None:
    workflow = (ROOT / ".github" / "workflows" / "check.yml").read_text(
        encoding="utf-8"
    )
    for job in ("frontend:", "backend:", "postgres:", "docker:"):
        assert job in workflow
    assert "pnpm install --frozen-lockfile" in workflow
    assert "python -m pytest -q" in workflow
    assert "python scripts/postgres_smoke_test.py" in workflow
    assert "docker compose config --quiet" in workflow
    steps = yaml.safe_load(workflow)["jobs"]["docker"]["steps"]
    build = next(step["run"] for step in steps if step.get("name") == "Build production image")
    arguments = shlex.split(build)
    assert arguments[:2] == ["docker", "build"]
    assert "--pull" in arguments and arguments[-1] == "."
    assert {arguments[index + 1] for index, value in enumerate(arguments) if value == "--tag"} == {
        "assetcore:ci", "assetcore:$GITHUB_SHA",
    }
    assert arguments[arguments.index("--build-arg") + 1] == "ASSETCORE_RELEASE_SHA=$GITHUB_SHA"
    assert "python scripts/production_compose_smoke.py" in workflow


def test_production_and_ci_require_versioned_postgresql16_clients() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim-trixie AS runtime" in dockerfile
    assert "postgresql-client-16" in dockerfile
    assert "libreoffice-writer postgresql-client \\" not in dockerfile
    assert "Signed-By: /usr/share/keyrings/pgdg.asc" in dockerfile
    assert "B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8" in dockerfile
    assert "RUN python scripts/postgres_toolchain.py --clients-only" in dockerfile

    jobs = yaml.safe_load((ROOT / ".github/workflows/check.yml").read_text(encoding="utf-8"))["jobs"]
    assert jobs["postgres"]["runs-on"] == "ubuntu-24.04"
    environment = jobs["postgres"]["env"]
    for variable, binary in (("PG_DUMP", "pg_dump"), ("PG_RESTORE", "pg_restore"), ("PSQL", "psql")):
        assert environment[variable] == f"/usr/lib/postgresql/16/bin/{binary}"
    steps = jobs["docker"]["steps"]
    assertion = next(step["run"] for step in steps
                     if step.get("name") == "Assert all PostgreSQL client majors in the exact production image")
    assert "assetcore:ci python scripts/postgres_toolchain.py --clients-only" in assertion
    roundtrip = next(step["run"] for step in steps
                    if step.get("name") == "Production image PostgreSQL 16 encrypted round trip and real PG17 rejection")
    assert "postgres:17-trixie" in roundtrip
    assert "ASSETCORE_REQUIRE_POSTGRES_MISMATCH_TEST=true" in roundtrip
    assert "assetcore:ci python scripts/postgres_smoke_test.py" in roundtrip
    assert jobs["docker"]["services"]["postgres"]["image"] == "postgres:16-alpine"


@pytest.mark.parametrize("output,exit_code", [("", 0), ("unexpected failure", 1)])
def test_postgres_negative_smoke_cannot_pass_without_guard_rejection(monkeypatch, output, exit_code) -> None:
    module = _load_postgres_smoke_module()
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], exit_code, "", output))
    with pytest.raises(RuntimeError, match="was not refused by the guard"):
        module._expect_compatibility_rejection([], {})


def test_postgres_negative_smoke_checks_credential_redaction(monkeypatch) -> None:
    module = _load_postgres_smoke_module()
    environment = {
        "DATABASE_URL": "postgresql://qa-user:qa-secret@db/qa-test",
        "BACKUP_ENCRYPTION_KEY": "qa-key",
    }
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess([], 1, "", "postgresql_toolchain_incompatible qa-secret"))
    with pytest.raises(RuntimeError, match="exposed a QA credential"):
        module._expect_compatibility_rejection([], environment)


def test_required_postgres_negative_smoke_cannot_be_skipped(monkeypatch, tmp_path) -> None:
    module = _load_postgres_smoke_module()
    monkeypatch.setenv("ASSETCORE_REQUIRE_POSTGRES_MISMATCH_TEST", "true")
    monkeypatch.delenv("ASSETCORE_POSTGRES_MISMATCH_PG_DUMP", raising=False)
    monkeypatch.delenv("ASSETCORE_POSTGRES_MISMATCH_PG_RESTORE", raising=False)
    with pytest.raises(RuntimeError, match="Both incompatible PostgreSQL QA tools are required"):
        module._verify_mismatched_toolchain_rejection(tmp_path, tmp_path / "unused", {}, "unused", 1)
