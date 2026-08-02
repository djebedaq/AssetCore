"""Run PostgreSQL migrations plus a real encrypted backup/restore round trip.

The two connection URLs must be supplied through environment variables and
must point to distinct databases whose names clearly identify them as tests.
No URL, password, encryption key, or dump content is printed.
"""

from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import Machine, User  # noqa: E402
from app.seed import seed_database  # noqa: E402
from app.settings import settings  # noqa: E402


def _safe_test_url(variable: str) -> str:
    value = os.environ.get(variable, "")
    parsed = urlparse(value.replace("postgresql+psycopg://", "postgresql://", 1))
    database = parsed.path.lstrip("/").casefold()
    if parsed.scheme not in {"postgresql", "postgres"} or not database:
        raise SystemExit(f"{variable} must contain a PostgreSQL URL.")
    if not any(marker in database for marker in ("test", "qa")):
        raise SystemExit(f"{variable} must point to an explicitly named test database.")
    return value


def _upgrade(url: str) -> None:
    previous = settings.database_url
    try:
        settings.database_url = url
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(config, "head")
    finally:
        settings.database_url = previous


def main() -> None:
    source_url = _safe_test_url("ASSETCORE_POSTGRES_SOURCE_URL")
    restore_url = _safe_test_url("ASSETCORE_POSTGRES_RESTORE_URL")
    if source_url == restore_url:
        raise SystemExit("Source and restore test databases must be different.")
    if not os.environ.get("PG_DUMP") or not os.environ.get("PG_RESTORE"):
        raise SystemExit("PG_DUMP and PG_RESTORE must identify the PostgreSQL client tools.")

    _upgrade(source_url)
    source_engine = create_engine(source_url, pool_pre_ping=True)
    previous_settings = (
        settings.owner_email,
        settings.owner_job_title,
        settings.owner_initial_password,
    )
    try:
        settings.owner_email = "postgres-qa-owner@assetcore.invalid"
        settings.owner_job_title = "PostgreSQL QA operator"
        settings.owner_initial_password = secrets.token_urlsafe(32)
        with Session(source_engine) as db:
            seed_database(db)
            owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            if owner is None:
                raise RuntimeError("The isolated PostgreSQL seed did not create its owner.")
            actor_id = owner.id
            expected_inventory = sorted(db.scalars(select(Machine.inventory_number)))
    finally:
        (
            settings.owner_email,
            settings.owner_job_title,
            settings.owner_initial_password,
        ) = previous_settings
        source_engine.dispose()

    backup_key = base64.b64encode(secrets.token_bytes(32)).decode()
    with tempfile.TemporaryDirectory(prefix="assetcore-postgres-roundtrip-") as temp_name:
        temp = Path(temp_name)
        environment = os.environ.copy()
        environment["DATABASE_URL"] = source_url
        environment["BACKUP_ENCRYPTION_KEY"] = backup_key
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "backup_database.py"),
                "--output-dir",
                str(temp),
                "--actor-user-id",
                str(actor_id),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        backups = list(temp.glob("*.acbackup"))
        if len(backups) != 1:
            raise RuntimeError("The PostgreSQL QA backup was not produced exactly once.")
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "verify_backup.py"),
                str(backups[0]),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )
        _upgrade(restore_url)
        environment["DATABASE_URL"] = restore_url
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "restore_database.py"),
                str(backups[0]),
                "--confirm",
                "RESTORE_ASSETCORE",
                "--actor-user-id",
                str(actor_id),
            ],
            cwd=ROOT,
            env=environment,
            check=True,
        )

    restore_engine = create_engine(restore_url, pool_pre_ping=True)
    try:
        with Session(restore_engine) as db:
            restored_inventory = sorted(db.scalars(select(Machine.inventory_number)))
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if restored_inventory != expected_inventory or revision != "20260801_0006":
                raise RuntimeError("The restored PostgreSQL database differs from the source QA database.")
    finally:
        restore_engine.dispose()
    print("PostgreSQL migration and encrypted backup/restore round trip passed.")


if __name__ == "__main__":
    main()
