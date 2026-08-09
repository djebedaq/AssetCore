from __future__ import annotations

import importlib.util
from pathlib import Path

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
    assert module._expected_head() == "20260809_0017"


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
    assert "docker build --pull --tag assetcore:ci ." in workflow
