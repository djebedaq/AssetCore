"""SQLite upgrade preservation and refusal to truncate a Builder caption."""

import pytest
from alembic import command
from app.models import CatalogDiagram, Machine, PartCatalog, TechnicalDocument
from app.seed import seed_database
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_migrations import _run_sqlite_revision


def test_diagram_title_upgrade_preserves_preceding_data_and_downgrade_refuses_long_title(tmp_path):
    path = tmp_path / "catalog-title-upgrade.db"
    _run_sqlite_revision(path, command.upgrade, "head")
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as db:
        seed_database(db)
    engine.dispose()
    _run_sqlite_revision(path, command.downgrade, "20260929_0029")
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as db:
        inventory = list(db.scalars(select(Machine.inventory_number).order_by(Machine.id)))
        parts = [(row.id, row.source_record_key) for row in db.scalars(select(PartCatalog).order_by(PartCatalog.id))]
    engine.dispose()
    _run_sqlite_revision(path, command.upgrade, "head")
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as db:
        assert list(db.scalars(select(Machine.inventory_number).order_by(Machine.id))) == inventory
        assert [(row.id, row.source_record_key) for row in db.scalars(select(PartCatalog).order_by(PartCatalog.id))] == parts
        source = db.scalar(select(TechnicalDocument))
        caption = "QA" * 256
        db.add(CatalogDiagram(source_id="QA_LONG_TITLE", family="QA", assembly="QA",
                              technical_document_id=source.id, page_number=1,
                              title=caption, source_pdf_sha256="a" * 64))
        db.commit()
    engine.dispose()
    with pytest.raises(RuntimeError, match="title exceeds 500"):
        _run_sqlite_revision(path, command.downgrade, "20260929_0029")
    engine = create_engine(f"sqlite:///{path}")
    with Session(engine) as db:
        assert db.scalar(select(CatalogDiagram.title).where(CatalogDiagram.source_id == "QA_LONG_TITLE")) == caption
    engine.dispose()
