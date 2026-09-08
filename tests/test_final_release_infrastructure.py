from __future__ import annotations

import importlib.util
import shlex
from pathlib import Path

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
    assert module._expected_head() == "20260826_0021"


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
