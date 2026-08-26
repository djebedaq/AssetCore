from __future__ import annotations

import base64
import hashlib
import sys
import threading
from dataclasses import dataclass, field

from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .catalog.sources import (
    CATALOG_VERSION,
    dataset_sources,
    ensure_source_integrity,
)
from .database import SessionLocal, engine
from .licensing import evaluate_license, validate_public_key_configuration
from .migrations import database_is_at_head, migration_guard, run_migrations
from .models import PartCatalog, TechnicalDocument
from .seed import seed_database
from .settings import Settings, settings


class RuntimeDependencyError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _check(status: str, code: str) -> dict[str, str]:
    return {"status": status, "code": code}


@dataclass
class RuntimeState:
    phase: str = "starting"
    checks: dict[str, dict[str, str]] = field(default_factory=dict)
    failure_code: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def begin_startup(self) -> None:
        with self._lock:
            self.phase = "starting"
            self.checks = {}
            self.failure_code = None

    def mark_ready(self, checks: dict[str, dict[str, str]]) -> None:
        with self._lock:
            self.phase = "ready"
            self.checks = {name: dict(value) for name, value in checks.items()}
            self.failure_code = None

    def mark_failed(self, code: str) -> None:
        with self._lock:
            self.phase = "failed"
            self.failure_code = code

    def mark_stopping(self) -> None:
        with self._lock:
            self.phase = "stopping"

    def snapshot(self) -> tuple[str, dict[str, dict[str, str]], str | None]:
        with self._lock:
            return (
                self.phase,
                {name: dict(value) for name, value in self.checks.items()},
                self.failure_code,
            )


runtime_state = RuntimeState()


def verify_cryptography(configuration: Settings = settings) -> dict[str, str]:
    material = configuration.signature_encryption_key or configuration.secret_key
    if not material:
        raise RuntimeDependencyError("cryptography_configuration_missing")
    try:
        cipher = Fernet(
            base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
        )
        probe = b"assetcore-runtime-crypto-check"
        if cipher.decrypt(cipher.encrypt(probe)) != probe:
            raise ValueError("round-trip mismatch")
    except Exception:
        raise RuntimeDependencyError("cryptography_configuration_invalid") from None
    return _check("pass", "cryptography_operational")


def verify_catalog(session: Session) -> dict[str, str]:
    sources = dataset_sources()
    try:
        for source in sources:
            ensure_source_integrity(str(source["source_id"]))
    except Exception:
        raise RuntimeDependencyError("catalog_source_integrity_failed") from None

    expected_records = sum(int(source.get("record_count") or 0) for source in sources)
    active_records = session.scalar(
        select(func.count(PartCatalog.id)).where(
            PartCatalog.is_active.is_(True),
            PartCatalog.source_version == CATALOG_VERSION,
        )
    ) or 0
    active_sources = session.scalar(
        select(func.count(func.distinct(TechnicalDocument.source_id))).where(
            TechnicalDocument.is_active.is_(True),
            TechnicalDocument.dataset_version == CATALOG_VERSION,
            TechnicalDocument.source_id.is_not(None),
        )
    ) or 0
    if active_records != expected_records or active_sources != len(sources):
        raise RuntimeDependencyError("catalog_database_state_incomplete")
    return _check("pass", "catalog_integrity_verified")


def verify_license(session: Session, configuration: Settings = settings) -> dict[str, str]:
    if not configuration.license_enforcement_enabled:
        return _check("pass", "license_not_applicable")
    try:
        validate_public_key_configuration(configuration.license_public_key)
        state = evaluate_license(session)
    except Exception:
        raise RuntimeDependencyError("license_evaluation_failed") from None
    return _check(
        "pass",
        "license_evaluated_read_only" if state.read_only else "license_evaluated",
    )


def verify_startup_dependencies(
    *,
    database_engine: Engine = engine,
    session_factory: sessionmaker = SessionLocal,
    configuration: Settings = settings,
) -> dict[str, dict[str, str]]:
    try:
        if not database_is_at_head(database_engine):
            raise RuntimeDependencyError("database_schema_behind")
    except RuntimeDependencyError:
        raise
    except Exception:
        raise RuntimeDependencyError("database_unavailable") from None

    try:
        with session_factory() as session:
            catalog = verify_catalog(session)
            license_check = verify_license(session, configuration)
    except RuntimeDependencyError:
        raise
    except Exception:
        raise RuntimeDependencyError("database_unavailable") from None
    return {
        "configuration": _check("pass", "configuration_valid"),
        "catalog": catalog,
        "cryptography": verify_cryptography(configuration),
        "license": license_check,
    }


def prepare_database() -> None:
    """One-shot migration and idempotent canonical bootstrap command."""
    run_migrations()
    # Hold the same cross-process lock while the canonical seed/import runs.
    # This prevents simultaneous one-shot prepare commands from racing the
    # idempotent, multi-commit bootstrap after both have reached Alembic head.
    with engine.connect() as lock_connection:
        with migration_guard(
            lock_connection,
            timeout_seconds=settings.migration_lock_timeout_seconds,
        ):
            with SessionLocal() as session:
                seed_database(session)


def initialize_runtime() -> None:
    runtime_state.begin_startup()
    try:
        if settings.migration_strategy == "startup":
            prepare_database()
        checks = verify_startup_dependencies()
    except RuntimeDependencyError as exc:
        runtime_state.mark_failed(exc.code)
        raise RuntimeError(f"AssetCore startup check failed: {exc.code}") from None
    except Exception:
        runtime_state.mark_failed("startup_preparation_failed")
        raise RuntimeError("AssetCore startup preparation failed safely.") from None
    runtime_state.mark_ready(checks)


def readiness_report(
    *,
    database_engine: Engine = engine,
    state: RuntimeState = runtime_state,
) -> tuple[int, dict[str, object]]:
    phase, cached_checks, failure_code = state.snapshot()
    runtime_check = (
        _check("pass", "runtime_ready")
        if phase == "ready"
        else _check("fail", failure_code or f"runtime_{phase}")
    )
    try:
        actual_heads = database_is_at_head(database_engine)
        database_check = _check("pass", "database_connected")
        schema_check = (
            _check("pass", "database_schema_current")
            if actual_heads
            else _check("fail", "database_schema_behind")
        )
    except Exception:
        database_check = _check("fail", "database_unavailable")
        schema_check = _check("fail", "database_schema_unverified")

    checks = {
        "runtime": runtime_check,
        "database": database_check,
        "schema": schema_check,
        "configuration": cached_checks.get(
            "configuration", _check("fail", "configuration_unverified")
        ),
        "catalog": cached_checks.get(
            "catalog", _check("fail", "catalog_integrity_unverified")
        ),
        "cryptography": cached_checks.get(
            "cryptography", _check("fail", "cryptography_unverified")
        ),
        "license": cached_checks.get(
            "license", _check("fail", "license_unverified")
        ),
    }
    ready = all(check["status"] == "pass" for check in checks.values())
    return (
        200 if ready else 503,
        {
            "status": "ready" if ready else "not_ready",
            "service": "AssetCore",
            "checks": checks,
        },
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    command_name = arguments[0] if arguments else "prepare"
    try:
        if command_name == "migrate":
            run_migrations()
        elif command_name == "prepare":
            prepare_database()
            verify_startup_dependencies()
        else:
            print("runtime_status=invalid_command", file=sys.stderr)
            return 2
    except Exception:
        print(f"runtime_status={command_name}_failed", file=sys.stderr)
        return 1
    print(f"runtime_status={command_name}_complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
