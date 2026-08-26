from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .settings import Settings, settings


def build_engine(configuration: Settings) -> Engine:
    """Build a SQLite- or PostgreSQL-appropriate engine without logging its URL."""
    common: dict[str, Any] = {
        "pool_pre_ping": configuration.db_pool_pre_ping,
    }
    if configuration.database_url.startswith("sqlite"):
        common["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        connect_args: dict[str, Any] = {
            "connect_timeout": configuration.db_connect_timeout_seconds,
        }
        if configuration.db_statement_timeout_ms:
            connect_args["options"] = (
                f"-c statement_timeout={configuration.db_statement_timeout_ms}"
            )
        common.update(
            {
                "connect_args": connect_args,
                "pool_size": configuration.db_pool_size,
                "max_overflow": configuration.db_max_overflow,
                "pool_timeout": configuration.db_pool_timeout_seconds,
                "pool_recycle": (
                    configuration.db_pool_recycle_seconds
                    if configuration.db_pool_recycle_seconds
                    else -1
                ),
            }
        )
    configured_engine = create_engine(configuration.database_url, **common)
    if configuration.database_url.startswith("sqlite"):
        event.listen(configured_engine, "connect", _configure_sqlite)
    return configured_engine


def _configure_sqlite(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


engine = build_engine(settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
