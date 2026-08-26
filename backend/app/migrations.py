from __future__ import annotations

import hashlib
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import NullPool

from .settings import settings

_LOCAL_MIGRATION_LOCK = threading.Lock()
_POSTGRES_LOCK_ID = int.from_bytes(
    hashlib.sha256(b"AssetCore:alembic:migrations:v1").digest()[:8],
    byteorder="big",
    signed=True,
)


class MigrationLockTimeout(RuntimeError):
    pass


class MigrationExecutionError(RuntimeError):
    pass


def migration_lock_id() -> int:
    return _POSTGRES_LOCK_ID


def migration_config() -> Config:
    backend_root = Path(__file__).resolve().parents[1]
    configuration = Config(str(backend_root / "alembic.ini"))
    configuration.set_main_option("script_location", str(backend_root / "alembic"))
    return configuration


def expected_heads() -> tuple[str, ...]:
    return tuple(sorted(ScriptDirectory.from_config(migration_config()).get_heads()))


def current_heads(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        return tuple(sorted(MigrationContext.configure(connection).get_current_heads()))


def database_is_at_head(engine: Engine) -> bool:
    return current_heads(engine) == expected_heads()


def _migration_engine() -> Engine:
    connect_args: dict[str, object]
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
    else:
        connect_args = {"connect_timeout": settings.db_connect_timeout_seconds}
    return create_engine(
        settings.database_url,
        poolclass=NullPool,
        connect_args=connect_args,
    )


@contextmanager
def migration_guard(
    connection: Connection,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    """Serialize Alembic runs without exposing connection information."""
    if connection.dialect.name == "postgresql":
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while time.monotonic() < deadline:
            acquired = bool(
                connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": _POSTGRES_LOCK_ID},
                ).scalar_one()
            )
            connection.commit()
            if acquired:
                break
            time.sleep(min(0.25, max(deadline - time.monotonic(), 0)))
        if not acquired:
            raise MigrationLockTimeout(
                "Timed out waiting for the AssetCore PostgreSQL migration lock."
            )
        try:
            yield
        finally:
            connection.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": _POSTGRES_LOCK_ID},
            )
            connection.commit()
        return

    acquired = _LOCAL_MIGRATION_LOCK.acquire(timeout=timeout_seconds)
    if not acquired:
        raise MigrationLockTimeout(
            "Timed out waiting for the local AssetCore migration lock."
        )
    try:
        yield
    finally:
        _LOCAL_MIGRATION_LOCK.release()


def run_migrations() -> None:
    """Upgrade to head under a bounded cross-process PostgreSQL advisory lock."""
    migration_engine = _migration_engine()
    try:
        with migration_engine.connect() as connection:
            with migration_guard(
                connection,
                timeout_seconds=settings.migration_lock_timeout_seconds,
            ):
                configuration = migration_config()
                configuration.attributes["connection"] = connection
                command.upgrade(configuration, "head")
    except MigrationLockTimeout:
        raise
    except Exception:
        raise MigrationExecutionError(
            "AssetCore could not complete the database migration safely."
        ) from None
    finally:
        migration_engine.dispose()


def main() -> int:
    try:
        run_migrations()
    except MigrationLockTimeout:
        print("migration_status=lock_timeout", file=sys.stderr)
        return 2
    except MigrationExecutionError:
        print("migration_status=failed", file=sys.stderr)
        return 1
    print("migration_status=complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
