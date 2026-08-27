"""Cross-platform, isolated AssetCore release verification.

The verifier never opens the configured production database. It builds a
temporary SQLite database, uses the verified seed and generates QA documents in
an isolated directory. Full pytest/frontend/Docker checks remain orchestrated
by ``verify_release.ps1`` and CI.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402
from app.authorization_inventory import build_authorization_inventory  # noqa: E402
from app.catalog.sources import CATALOG_VERSION  # noqa: E402
from app.catalog.validation import validate_catalog_v2  # noqa: E402
from app.database import Base  # noqa: E402
from app.licensing import evaluate_license  # noqa: E402
from app.main import app, health  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    DocumentTemplateVersion,
    InstallationOwnership,
    Machine,
    PartCatalog,
    ProfileStatus,
    SignatureSlot,
    User,
    UserRole,
)
from app.official_documents.integrity import (  # noqa: E402
    validate_official_document_integrity,
)
from app.seed import seed_database  # noqa: E402
from app.settings import settings  # noqa: E402
from app.template_engine import validate_template  # noqa: E402
from sqlalchemy import create_engine, func, inspect, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.scripts.document_qa import generate as generate_document_qa  # noqa: E402
from backend.scripts.migration_history import validate_migration_release  # noqa: E402
from scripts.dependency_inventory import write_inventory  # noqa: E402

EXPECTED_INVENTORY = {"4", "5", "7", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24"}
EXPECTED_SERIALS = {
    "7": "G41200143", "17": "G41200203", "18": "G41200204",
    "9": "G39300296", "10": "G39300297", "11": "G39300298",
    "12": "G39300299", "13": "G39300415", "14": "G39300416",
    "15": "G39300417", "16": "G39300418", "20": "2512005",
    "21": "2512004", "22": "2512001", "23": "2512003", "24": "2512002",
}
EXPECTED_ROLES = {"administrator", "director", "mechanic", "observer"}


class Verification:
    def __init__(self) -> None:
        self.results: list[dict] = []

    def check(self, name: str, condition: bool, details: str = "") -> None:
        self.results.append({"name": name, "passed": bool(condition), "details": details})
        print(f"{'PASS' if condition else 'FAIL'}: {name}{' — ' + details if details else ''}")


def _tracked_files() -> list[str]:
    if (ROOT / ".git").exists():
        result = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        )
        return [line.strip().replace("\\", "/") for line in result.stdout.splitlines()]
    excluded_parts = {
        ".git", ".pytest_cache", ".ruff_cache", ".tmp", "__pycache__",
        "node_modules", "dist", ".pnpm-store",
    }
    return [
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & excluded_parts)
    ]


def _seed_literal() -> list[dict]:
    tree = ast.parse((BACKEND / "app" / "seed.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "MACHINES" for target in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("MACHINES seed literal was not found.")


def _verify_migrations(verification: Verification) -> None:
    with tempfile.TemporaryDirectory(prefix="assetcore-migration-release-") as temp_name:
        database_path = Path(temp_name) / "migration-check.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        previous_url = settings.database_url
        previous_env = os.environ.get("DATABASE_URL")
        try:
            settings.database_url = database_url
            os.environ["DATABASE_URL"] = database_url
            config = Config(str(BACKEND / "alembic.ini"))
            config.set_main_option("script_location", str(BACKEND / "alembic"))
            expected_head = ScriptDirectory.from_config(config).get_current_head()
            command.upgrade(config, "head")
            migration_engine = create_engine(database_url)
            try:
                with migration_engine.connect() as connection:
                    revision = connection.exec_driver_sql(
                        "SELECT version_num FROM alembic_version"
                    ).scalar_one()
                    tables = set(inspect(connection).get_table_names())
                verification.check(
                    "Alembic migrations достигат текущия head",
                    revision == expected_head
                    and {
                        "installation_ownership",
                        "software_licenses",
                        "emergency_access_sessions",
                        "official_document_versions",
                        "document_signatures",
                    }
                    <= tables,
                )
                with Session(migration_engine) as migration_db:
                    integrity = validate_official_document_integrity(migration_db)
                    verification.check(
                        "OfficialDocument current version integrity guard е активен",
                        integrity["valid"]
                        and integrity["blocking_count"] == 0
                        and integrity["schema"]["owner_unique_index"]
                        and (
                            integrity["schema"]["composite_foreign_key"]
                            or integrity["schema"]["sqlite_trigger_guard"]
                        ),
                        (
                            f"blocking={integrity['blocking_count']}, "
                            f"tolerated={integrity['tolerated_history_count']}"
                        ),
                    )
            finally:
                migration_engine.dispose()
        finally:
            settings.database_url = previous_url
            if previous_env is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous_env


def run(output: Path) -> Verification:
    verification = Verification()
    migration_history = validate_migration_release()
    verification.check(
        "Всички Alembic миграции са защитени и непроменени",
        migration_history["valid"],
        (
            f"protected={migration_history['protected_count']}, "
            f"missing={len(migration_history['missing'])}, "
            f"mismatched={len(migration_history['mismatched'])}, "
            f"new={len(migration_history['new_unprotected_migrations'])}"
        ),
    )
    if not migration_history["valid"]:
        return verification
    dependency_inventory = write_inventory(output)
    verification.check(
        "Dependency manifests и инсталирани версии съвпадат; CycloneDX SBOM е създаден",
        dependency_inventory["valid"],
        f"python={dependency_inventory['python_packages']}, frontend={dependency_inventory['frontend_packages']}",
    )
    authorization_inventory = build_authorization_inventory(app)
    verification.check(
        "FastAPI authorization inventory е пълен",
        authorization_inventory.valid,
        (
            f"routes={len(authorization_inventory.routes)}, "
            f"errors={len(authorization_inventory.errors)}"
        ),
    )
    _verify_migrations(verification)
    tracked = _tracked_files()
    unsafe_suffixes = (".db", ".sqlite", ".sqlite3", ".dump", ".backup", ".pem", ".key", ".p12", ".pfx")
    unsafe = [name for name in tracked if name.casefold().endswith(unsafe_suffixes) or Path(name).name == ".env"]
    verification.check("Няма проследявана локална база, backup, secret или private key", not unsafe, ", ".join(unsafe))

    seed = _seed_literal()
    numbers = {str(item["inventory_number"]) for item in seed}
    serials = {str(item["inventory_number"]): item.get("serial_number") for item in seed}
    verification.check("Регистърът съдържа точно 19 HPWJ машини", len(seed) == 19 and numbers == EXPECTED_INVENTORY)
    verification.check("Потвърдените серийни номера са непроменени", all(serials.get(number) == value for number, value in EXPECTED_SERIALS.items()))
    verification.check("Ролите са точно четири", {role.value for role in UserRole} == EXPECTED_ROLES)
    verification.check("Няма забранени owner/approval роли", not ({"SYSTEM_OWNER", "OWNER", "SUPERVISOR", "APPROVER", "TECHNICIAN", "MANAGER"} & {role.name for role in UserRole}))

    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for root in (BACKEND / "app", ROOT / "frontend" / "src")
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".py", ".ts", ".tsx"}
    )
    verification.check("Няма вграден private signing key", "BEGIN PRIVATE KEY" not in source_text and "private_signing_key" not in source_text.casefold())
    verification.check("Няма вградена production/admin парола", "admin_password: str =" not in source_text.casefold())

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    settings.owner_email = "release-verification@assetcore.invalid"
    settings.owner_first_name = "Евтим"
    settings.owner_middle_name = "Станиславов"
    settings.owner_last_name = "Горанов"
    settings.owner_job_title = "Системен администратор"
    settings.owner_initial_password = secrets.token_urlsafe(32)
    with Session(engine) as db:
        seed_database(db)
        verification.check("Връзката към изолираната database работи", db.scalar(select(func.count(User.id))) == 1)
        machines = list(db.scalars(select(Machine)))
        verification.check("Database seed съдържа точния регистър", len(machines) == 19 and {item.inventory_number for item in machines} == EXPECTED_INVENTORY)
        owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        ownership = db.scalar(select(InstallationOwnership))
        verification.check("Owner designation е отделно от RBAC", bool(owner and ownership and ownership.owner_user_id == owner.id and owner.role == "administrator"))
        verification.check("Owner профилът е пълен", bool(owner and owner.profile_status == ProfileStatus.COMPLETE.value))
        verification.check("Няма неочакван непълен seed профил", db.scalar(select(func.count(User.id)).where(User.profile_status == ProfileStatus.INCOMPLETE.value)) == 0)
        published = list(db.scalars(select(DocumentTemplateVersion).where(DocumentTemplateVersion.is_published.is_(True))))
        verification.check(
            "Има 12 публикувани и валидни BG/EN/RU template версии",
            len(published) == 12
            and {item.language for item in published} == {"bg", "en", "ru"}
            and len({item.template_id for item in published}) == 4
            and all(validate_template(item)["valid"] for item in published),
        )
        active_slots = list(
            db.scalars(select(SignatureSlot).where(SignatureSlot.is_active.is_(True)))
        )
        verification.check(
            "Signature slots са backend-конфигурирани без repair handover роли",
            len(active_slots) == 6
            and not any(
                item.document_type == "REPAIR_PROTOCOL" for item in active_slots
            ),
        )
        verification.check("Audit таблицата е достъпна", (db.scalar(select(func.count(AuditLog.id))) or 0) >= 0)
        catalog_count = db.scalar(
            select(func.count(PartCatalog.id)).where(
                PartCatalog.is_active.is_(True),
                PartCatalog.source_version == CATALOG_VERSION,
            )
        ) or 0
        verified_catalog_count = db.scalar(
            select(func.count(PartCatalog.id)).where(
                PartCatalog.is_active.is_(True),
                PartCatalog.is_verified.is_(True),
                PartCatalog.source_version == CATALOG_VERSION,
                PartCatalog.verification_status == "VERIFIED_SOURCE_ROW",
            )
        ) or 0
        catalog_validation = validate_catalog_v2()
        verification.check(
            "Authoritative каталогът съдържа точно 611 проверени source реда",
            catalog_count == 611
            and verified_catalog_count == 611
            and catalog_validation["valid"]
            and catalog_validation["records_by_family"]
            == {
                "FALCH_1000": 244,
                "FALCH_500": 309,
                "HYDWIN_FUSSEN_500": 58,
            },
            (
                f"total={catalog_count}, verified={verified_catalog_count}, "
                f"sources={catalog_validation['source_count']}"
            ),
        )
        verification.check(
            "EN/BG каталогът покрива точно 611 canonical source идентичности",
            catalog_validation["translation_record_count"] == 611
            and catalog_validation["english_translation_coverage"] == 611
            and catalog_validation["bulgarian_translation_coverage"] == 611
            and catalog_validation["orphan_translation_count"] == 0
            and catalog_validation["missing_translation_count"] == 0
            and catalog_validation["duplicate_translation_key_count"] == 0
            and catalog_validation["unchanged_authoritative_source_count"] == 9,
            (
                f"translations={catalog_validation['translation_record_count']}, "
                f"en={catalog_validation['english_translation_coverage']}, "
                f"bg={catalog_validation['bulgarian_translation_coverage']}, "
                f"needs_review={catalog_validation['translation_needs_review_count']}, "
                f"source_hashes={catalog_validation['unchanged_authoritative_source_count']}"
            ),
        )
        licence = evaluate_license(db)
        verification.check("License validation връща контролиран статус", licence.state in {"NOT_INSTALLED", "ACTIVE", "GRACE_PERIOD", "READ_ONLY", "INVALID", "NOT_YET_VALID"})
    engine.dispose()

    verification.check("Application health", health().get("status") == "ok")
    qa = generate_document_qa(output)
    verification.check("DOCX/PDF/template/document hash QA", all(qa["release_checks"].values()))
    required_scripts = {
        "backup_database.py", "restore_database.py", "verify_backup.py",
        "export_documents.py", "verify_document_hashes.py",
    }
    verification.check("Backup/restore/export/hash scripts са налични", required_scripts <= {path.name for path in (ROOT / "scripts").glob("*.py")})
    return verification


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        output = args.output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        verification = run(output)
    else:
        with tempfile.TemporaryDirectory(prefix="assetcore-release-") as temp_name:
            verification = run(Path(temp_name))
    failed = [item for item in verification.results if not item["passed"]]
    print(json.dumps({"passed": not failed, "checks": verification.results}, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
