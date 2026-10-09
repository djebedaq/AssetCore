"""Explicit CI rehearsal on empty disposable databases, never a deployment.

Bootstrap the existing QA fixtures before loading app modules. Database URLs
come from the existing PostgreSQL smoke environment and are never printed.
"""
# ruff: noqa: E402
import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tests"), str(ROOT / "tests/postgres")]
import conftest  # noqa: F401,E402
from alembic import command
from alembic.config import Config
from app.catalog import service as runtime
from app.catalog_admin import publication
from app.catalog_admin.service import bind_asset
from app.documents.part_request_documents import make_part_request_documents
from app.industrial_api import create_multi_part_request
from app.industrial_schemas import MultiPartRequestCreate
from app.models import (
    CatalogDefinition,
    CatalogDiagram,
    CatalogPositionHotspot,
    CatalogRevisionAssembly,
    CatalogRevisionPart,
    GeneratedDocument,
    Machine,
    PartCatalog,
    PartRequestLine,
    PartVisualSnapshot,
    RepairKit,
    RepairKitComponent,
    User,
)
from app.part_requests.service import load_request
from app.seed import seed_database
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from test_catalog_publication_postgres import _setup

source_url = make_url(os.environ["ASSETCORE_POSTGRES_SOURCE_URL"])
assert source_url.drivername == "postgresql+psycopg"
assert source_url.database and "_test_" in source_url.database, "Disposable PostgreSQL URL required"
SOURCE = source_url.set(database="assetcore_test_upgrade_source").render_as_string(hide_password=False)
RESTORE = source_url.set(database="assetcore_test_upgrade_restore").render_as_string(hide_password=False)

def migrate(engine, target, downgrade=False):
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        (command.downgrade if downgrade else command.upgrade)(config, target)


def capture(engine, columns=None, *, audit_limit=None):
    inspector = inspect(engine)
    columns = columns or {table: [c["name"] for c in inspector.get_columns(table)]
                          for table in inspector.get_table_names() if table != "alembic_version"}
    state = {}
    with engine.connect() as connection:
        for table, names in columns.items():
            quoted = ",".join('"' + name + '"' for name in names)
            query = f'SELECT {quoted} FROM "{table}"'
            if table == "audit_logs" and audit_limit is not None:
                query += " WHERE id <= :audit_limit"
            rows = [tuple(row) for row in connection.execute(text(query), {"audit_limit": audit_limit})]
            encoded = sorted(json.dumps(row, default=str, sort_keys=True, ensure_ascii=False) for row in rows)
            state[table] = (len(rows), hashlib.sha256(json.dumps(encoded).encode()).hexdigest())
    return columns, state


def operation(args, environment):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError("QA operation failed: " + Path(args[0]).name + "\n" + result.stderr)


def backup(directory, environment, actor_id):
    operation(["scripts/backup_database.py", "--output-dir", str(directory),
               "--actor-user-id", str(actor_id)], environment)
    backups = list(directory.glob("*.acbackup"))
    assert len(backups) == 1
    operation(["scripts/verify_backup.py", str(backups[0])], environment)
    return backups[0]


def publish(factory, revision_id):
    from catalog_review_helpers import verify_service_sources
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        for assembly_id in db.scalars(select(CatalogRevisionAssembly.id).where(
                CatalogRevisionAssembly.revision_id == revision_id)):
            verify_service_sources(db, actor, assembly_id)
        preview = publication.readiness(db, revision_id)
        assert preview["ready"]
        publication.publish(db, actor, revision_id, preview["publication_digest"],
                            preview["current_published_revision_id"], True)


def main():
    engine = create_engine(SOURCE)
    assert not inspect(engine).get_table_names(), "Upgrade rehearsal requires an empty disposable source"
    with create_engine(RESTORE).connect() as restore_connection:
        assert not inspect(restore_connection).get_table_names(), "Restore target must be empty"
    factory = sessionmaker(engine, autoflush=False)
    migrate(engine, "head")
    with factory() as db:
        seed_database(db)
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        actor_id = actor.id
        v2_part = db.scalar(select(PartCatalog).where(PartCatalog.is_active.is_(True)))
        machine_id = db.scalar(select(Machine.id).where(
            Machine.inventory_number.in_(v2_part.compatible_machine_numbers)))
        old_request = create_multi_part_request(MultiPartRequestCreate(machine_id=machine_id,
            lines=[{"catalog_part_id": v2_part.id, "description": "QA historical request", "quantity": 1}]),
            user=actor, db=db)
        assert db.query(Machine).count() == 19
    migrate(engine, "20260924_0024", downgrade=True)
    environment = dict(os.environ, DATABASE_URL=SOURCE,
                       BACKUP_ENCRYPTION_KEY=base64.b64encode(os.urandom(32)).decode(),
                       PG_DUMP="/usr/lib/postgresql/16/bin/pg_dump",
                       PG_RESTORE="/usr/lib/postgresql/16/bin/pg_restore", PSQL="/usr/lib/postgresql/16/bin/psql")
    with TemporaryDirectory(prefix="builder-upgrade-backup-") as temporary:
        pre = Path(temporary) / "pre"
        pre.mkdir()
        backup(pre, environment, actor_id)
        # Backup adds an audited operation. Compare the migration against the
        # state after that legitimate operation, not against the earlier state.
        columns, before = capture(engine)
        migrate(engine, "head")
        assert capture(engine, columns)[1] == before
        with factory() as db:
            for _ in range(2):
                seed_database(db)
            assert load_request(db, old_request["id"]) is not None
            anchors = {"parts": db.query(PartCatalog).count(), "kits": db.query(RepairKit).count(),
                       "components": db.query(RepairKitComponent).count(), "diagrams": db.query(CatalogDiagram).count(),
                       "verified_hotspots": db.query(CatalogPositionHotspot).filter_by(is_verified=True).count(),
                       "verified_inventory": db.query(Machine).count()}
            assert anchors == dict(parts=611, kits=7, components=84, diagrams=12,
                                   verified_hotspots=818, verified_inventory=19)
        catalog_id, revisions = _setup(factory, suffix="_BACKUP")
        revision_id = revisions[0][0]
        publish(factory, revision_id)
        machine_ids = []
        with factory() as db:
            catalog = db.get(CatalogDefinition, catalog_id)
            actor = db.get(User, actor_id)
            for number in ("QA_BACKUP_A", "QA_BACKUP_B"):
                machine = Machine(inventory_number=number, name="QA backup asset", category="QA",
                                  category_id=catalog.asset_category_id, brand="QA", model="QA")
                db.add(machine)
                db.commit()
                machine_ids.append(machine.id)
                bind_asset(db, actor, catalog_id, machine.id)
                assert runtime.machine_catalog(db, machine.id)["supported"]
            live = db.scalar(select(PartCatalog).where(PartCatalog.builder_revision_id == revision_id))
            request = create_multi_part_request(MultiPartRequestCreate(machine_id=machine_ids[0],
                lines=[{"catalog_part_id": live.id, "description": "QA publication request", "quantity": 1}]),
                user=actor, db=db)
            records = make_part_request_documents(db, load_request(db, request["id"]), actor_id)
            db.add_all(records)
            db.commit()
            snapshot_sha = db.scalar(select(PartVisualSnapshot.sha256).join(
                PartRequestLine, PartVisualSnapshot.line_id == PartRequestLine.id).where(PartRequestLine.request_id == request["id"]))
            doc_hashes = {record.format: record.sha256 for record in records}
            clone = publication.clone(db, actor, revision_id, "B", "QA backup revision")
            next_id = clone["id"]
            next_part = db.scalar(select(CatalogRevisionPart).where(
                CatalogRevisionPart.assembly_id.in_(select(CatalogRevisionAssembly.id).where(
                    CatalogRevisionAssembly.revision_id == next_id))))
            next_part.name_bg = "QA next publication"
            db.commit()
        publish(factory, next_id)
        with factory() as db:
            seed_database(db)
            db.commit()
            for machine_id in machine_ids:
                assert runtime.machine_catalog(db, machine_id)["dataset_version"] == f"CATALOG_BUILDER_R{next_id}"
        all_columns, expected = capture(engine)
        with engine.connect() as connection:
            audit_limit = connection.scalar(text("SELECT coalesce(max(id), 0) FROM audit_logs"))
        post = Path(temporary) / "post"
        post.mkdir()
        archive = backup(post, environment, actor_id)
        restored = create_engine(RESTORE)
        migrate(restored, "head")
        operation(["scripts/restore_database.py", str(archive), "--confirm", "RESTORE_ASSETCORE",
                   "--actor-user-id", str(actor_id)], dict(environment, DATABASE_URL=RESTORE))
        actual = capture(restored, all_columns, audit_limit=audit_limit)[1]
        # Restore legitimately appends an event. Every preceding audit row,
        # and every row/column of the other tables, must remain exact.
        assert actual == expected
        with sessionmaker(restored)() as db:
            for machine_id in machine_ids:
                assert runtime.machine_catalog(db, machine_id)["dataset_version"] == f"CATALOG_BUILDER_R{next_id}"
            assert {record.format: record.sha256 for record in db.scalars(select(GeneratedDocument).where(
                GeneratedDocument.part_request_id == request["id"]))} == doc_hashes
            assert snapshot_sha in set(db.scalars(select(PartVisualSnapshot.sha256)))
        restored.dispose()
    engine.dispose()
    print(json.dumps({"pre_builder_upgrade": "passed", "encrypted_builder_restore": "passed",
                      "shared_binding_count": 2, "immutable_request_documents": "passed",
                      "head": "20261009_0033", "anchors": anchors}, sort_keys=True))


if __name__ == "__main__":
    main()
