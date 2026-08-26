"""Run PostgreSQL migrations plus a real encrypted backup/restore round trip.

The two connection URLs must be supplied through environment variables and
must point to distinct databases whose names clearly identify them as tests.
No URL, password, encryption key, or dump content is printed.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import (  # noqa: E402
    Machine,
    OfficialDocument,
    OfficialDocumentStatus,
    OfficialDocumentVersion,
    User,
)
from app.official_documents.integrity import (  # noqa: E402
    set_current_version,
    validate_official_document_integrity,
)
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


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return config


def _expected_head() -> str:
    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    if not head:
        raise RuntimeError("Alembic does not expose a single current head revision.")
    return head


def _upgrade(url: str) -> None:
    previous = settings.database_url
    try:
        settings.database_url = url
        command.upgrade(_alembic_config(), "head")
    finally:
        settings.database_url = previous


def _downgrade(url: str, revision: str) -> None:
    previous = settings.database_url
    try:
        settings.database_url = url
        command.downgrade(_alembic_config(), revision)
    finally:
        settings.database_url = previous


def _revision(url: str) -> str:
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()


def _verify_safe_catalog_downgrade_round_trip(url: str) -> None:
    _downgrade(url, "20260810_0018")
    _upgrade(url)
    if _revision(url) != _expected_head():
        raise RuntimeError("PostgreSQL catalog migration round trip missed head.")


def _verify_guarded_catalog_downgrade(url: str) -> None:
    try:
        _downgrade(url, "20260810_0018")
    except RuntimeError as caught:
        if "Cannot downgrade PARTS_CATALOG_V2 to 0018 safely" not in str(caught):
            raise
    else:
        raise RuntimeError("Incompatible PostgreSQL catalog downgrade was not blocked.")

    engine = create_engine(url, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        if _revision(url) != _expected_head():
            raise RuntimeError("Guarded PostgreSQL downgrade changed Alembic head.")
        if "catalog_diagrams" not in inspector.get_table_names():
            raise RuntimeError("Guarded PostgreSQL downgrade removed the v2 schema.")
        if "source_record_key" not in {
            column["name"] for column in inspector.get_columns("part_catalog")
        }:
            raise RuntimeError("Guarded PostgreSQL downgrade removed v2 columns.")
        with engine.connect() as connection:
            source_rows = connection.execute(
                text(
                    "SELECT COUNT(*) FROM part_catalog "
                    "WHERE source_version = 'PARTS_CATALOG_V2'"
                )
            ).scalar_one()
        if source_rows != 611:
            raise RuntimeError("Guarded PostgreSQL downgrade changed catalog rows.")
    finally:
        engine.dispose()


def _verify_official_document_integrity(url: str, actor_id: int) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with Session(engine) as db:
            report = validate_official_document_integrity(db)
            if not (
                report["valid"]
                and report["schema"]["composite_foreign_key"]
                and report["schema"]["postgresql_version_trigger_guard"]
            ):
                raise RuntimeError(
                    "PostgreSQL official document ownership guard is not active."
                )
            documents: list[tuple[OfficialDocument, OfficialDocumentVersion]] = []
            for suffix in ("A", "B"):
                document = OfficialDocument(
                    document_number=f"POSTGRES-INTEGRITY-QA-{suffix}",
                    document_type="PART_REQUEST",
                    created_by_id=actor_id,
                )
                db.add(document)
                db.flush()
                digest = hashlib.sha256(suffix.encode()).hexdigest()
                version = OfficialDocumentVersion(
                    document_id=document.id,
                    version=1,
                    status=OfficialDocumentStatus.DRAFT.value,
                    language="bg",
                    snapshot={"qa": "postgres-integrity"},
                    snapshot_sha256=digest,
                    signing_sha256=digest,
                    prepared_by_id=actor_id,
                )
                db.add(version)
                db.flush()
                set_current_version(db, document, version)
                db.flush()
                documents.append((document, version))
            documents[1][0].current_version_id = documents[0][1].id
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
            else:
                raise RuntimeError(
                    "PostgreSQL accepted a current version owned by another document."
                )
    finally:
        engine.dispose()


def main() -> None:
    source_url = _safe_test_url("ASSETCORE_POSTGRES_SOURCE_URL")
    restore_url = _safe_test_url("ASSETCORE_POSTGRES_RESTORE_URL")
    if source_url == restore_url:
        raise SystemExit("Source and restore test databases must be different.")
    if not os.environ.get("PG_DUMP") or not os.environ.get("PG_RESTORE"):
        raise SystemExit("PG_DUMP and PG_RESTORE must identify the PostgreSQL client tools.")

    _upgrade(source_url)
    _verify_safe_catalog_downgrade_round_trip(source_url)
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

    _verify_official_document_integrity(source_url, actor_id)

    _verify_guarded_catalog_downgrade(source_url)

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
            if restored_inventory != expected_inventory or revision != _expected_head():
                raise RuntimeError("The restored PostgreSQL database differs from the source QA database.")
    finally:
        restore_engine.dispose()
    print("PostgreSQL migration and encrypted backup/restore round trip passed.")


if __name__ == "__main__":
    main()
