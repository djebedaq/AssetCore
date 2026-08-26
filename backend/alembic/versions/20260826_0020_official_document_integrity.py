"""Harden official document current-version ownership integrity.

Revision ID: 20260826_0020
Revises: 20260818_0019
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "20260826_0020"
down_revision = "20260818_0019"
branch_labels = None
depends_on = None

OWNER_INDEX = "uq_official_document_version_owner"
OWNER_CONSTRAINT = "fk_official_documents_current_version_owner"
POSTGRES_FUNCTION = "assetcore_guard_official_document_version_owner"
POSTGRES_TRIGGER = "trg_official_document_versions_current_owner"
SQLITE_TRIGGERS = (
    "trg_official_documents_current_version_insert",
    "trg_official_documents_current_version_update",
    "trg_official_document_versions_current_owner_insert",
    "trg_official_document_versions_current_owner_update",
    "trg_official_document_versions_current_owner_delete",
)


def _historical_audit(bind: sa.Connection) -> dict[str, int]:
    queries = {
        "current_version_null": """
            SELECT COUNT(*) FROM official_documents
            WHERE current_version_id IS NULL
        """,
        "current_version_target_missing": """
            SELECT COUNT(*)
            FROM official_documents AS document
            LEFT JOIN official_document_versions AS version
              ON version.id = document.current_version_id
            WHERE document.current_version_id IS NOT NULL AND version.id IS NULL
        """,
        "current_version_wrong_owner": """
            SELECT COUNT(*)
            FROM official_documents AS document
            JOIN official_document_versions AS version
              ON version.id = document.current_version_id
            WHERE version.document_id <> document.id
        """,
        "current_version_shared": """
            SELECT COUNT(*) FROM (
              SELECT current_version_id
              FROM official_documents
              WHERE current_version_id IS NOT NULL
              GROUP BY current_version_id
              HAVING COUNT(*) > 1
            ) AS shared_current
        """,
        "orphan_document_version": """
            SELECT COUNT(*)
            FROM official_document_versions AS version
            LEFT JOIN official_documents AS document
              ON document.id = version.document_id
            WHERE document.id IS NULL
        """,
    }
    return {
        name: int(bind.execute(sa.text(statement)).scalar_one())
        for name, statement in queries.items()
    }


def _create_sqlite_guards() -> None:
    op.execute(
        """
        CREATE TRIGGER trg_official_documents_current_version_insert
        BEFORE INSERT ON official_documents
        WHEN NEW.current_version_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM official_document_versions AS version
            WHERE version.id = NEW.current_version_id
              AND version.document_id = NEW.id
          )
        BEGIN
          SELECT RAISE(ABORT, 'official_document_current_version_owner');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_documents_current_version_update
        BEFORE UPDATE OF id, current_version_id ON official_documents
        WHEN NEW.current_version_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM official_document_versions AS version
            WHERE version.id = NEW.current_version_id
              AND version.document_id = NEW.id
          )
        BEGIN
          SELECT RAISE(ABORT, 'official_document_current_version_owner');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_document_versions_current_owner_insert
        BEFORE INSERT ON official_document_versions
        WHEN EXISTS (
          SELECT 1 FROM official_documents AS document
          WHERE document.current_version_id = NEW.id
            AND document.id <> NEW.document_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'official_document_current_version_owner');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_document_versions_current_owner_update
        BEFORE UPDATE OF id, document_id ON official_document_versions
        WHEN EXISTS (
          SELECT 1 FROM official_documents AS document
          WHERE document.current_version_id = OLD.id
            AND (NEW.id <> OLD.id OR NEW.document_id <> document.id)
        ) OR EXISTS (
          SELECT 1 FROM official_documents AS document
          WHERE document.current_version_id = NEW.id
            AND document.id <> NEW.document_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'official_document_current_version_owner');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_official_document_versions_current_owner_delete
        BEFORE DELETE ON official_document_versions
        WHEN EXISTS (
          SELECT 1 FROM official_documents AS document
          WHERE document.current_version_id = OLD.id
        )
        BEGIN
          SELECT RAISE(ABORT, 'official_document_current_version_owner');
        END
        """
    )


def _create_postgresql_guards(
    audit: dict[str, int], *, owner_constraint_exists: bool
) -> None:
    if not owner_constraint_exists:
        op.execute(
            f"""
            ALTER TABLE official_documents
            ADD CONSTRAINT {OWNER_CONSTRAINT}
            FOREIGN KEY (id, current_version_id)
            REFERENCES official_document_versions (document_id, id)
            NOT VALID
            """
        )
    op.execute(
        f"""
        CREATE FUNCTION {POSTGRES_FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF EXISTS (
              SELECT 1 FROM official_documents
              WHERE current_version_id = OLD.id
            ) THEN
              RAISE EXCEPTION 'official_document_current_version_owner'
                USING ERRCODE = 'foreign_key_violation';
            END IF;
            RETURN OLD;
          END IF;

          IF TG_OP = 'UPDATE' AND EXISTS (
            SELECT 1 FROM official_documents
            WHERE current_version_id = OLD.id
              AND (NEW.id <> OLD.id OR NEW.document_id <> id)
          ) THEN
            RAISE EXCEPTION 'official_document_current_version_owner'
              USING ERRCODE = 'foreign_key_violation';
          END IF;

          IF EXISTS (
            SELECT 1 FROM official_documents
            WHERE current_version_id = NEW.id AND id <> NEW.document_id
          ) THEN
            RAISE EXCEPTION 'official_document_current_version_owner'
              USING ERRCODE = 'foreign_key_violation';
          END IF;
          RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {POSTGRES_TRIGGER}
        BEFORE INSERT OR UPDATE OR DELETE
        ON official_document_versions
        FOR EACH ROW EXECUTE FUNCTION {POSTGRES_FUNCTION}()
        """
    )
    if not owner_constraint_exists and not (
        audit["current_version_target_missing"]
        or audit["current_version_wrong_owner"]
    ):
        op.execute(
            f"ALTER TABLE official_documents VALIDATE CONSTRAINT {OWNER_CONSTRAINT}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    audit = _historical_audit(bind)
    print(
        "Official document integrity preflight: "
        + json.dumps(audit, sort_keys=True)
    )
    inspector = sa.inspect(bind)
    if OWNER_INDEX not in {
        item["name"]
        for item in inspector.get_indexes("official_document_versions")
    }:
        op.create_index(
            OWNER_INDEX,
            "official_document_versions",
            ["document_id", "id"],
            unique=True,
        )
    owner_constraint_exists = OWNER_CONSTRAINT in {
        item.get("name")
        for item in inspector.get_foreign_keys("official_documents")
    }
    if bind.dialect.name == "sqlite":
        _create_sqlite_guards()
    elif bind.dialect.name == "postgresql":
        _create_postgresql_guards(
            audit,
            owner_constraint_exists=owner_constraint_exists,
        )
    else:
        raise RuntimeError(
            "Official document integrity migration supports PostgreSQL and SQLite only."
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for trigger in reversed(SQLITE_TRIGGERS):
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    elif bind.dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS {POSTGRES_TRIGGER} ON official_document_versions")
        op.execute(f"DROP FUNCTION IF EXISTS {POSTGRES_FUNCTION}()")
        op.drop_constraint(
            OWNER_CONSTRAINT,
            "official_documents",
            type_="foreignkey",
        )
    op.drop_index(OWNER_INDEX, table_name="official_document_versions")
