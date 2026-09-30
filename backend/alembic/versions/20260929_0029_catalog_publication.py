"""Live Builder publication lineage and 80-character positions.

Revision ID: 20260929_0029
Revises: 20260928_0028
"""

import sqlalchemy as sa
from alembic import op

revision = "20260929_0029"
down_revision = "20260928_0028"
branch_labels = None
depends_on = None


LINEAGE = {
    "part_catalog": (
        ("builder_revision_id", "catalog_revisions.id"),
        ("builder_part_id", "catalog_revision_parts.id"),
    ),
    "technical_documents": (("builder_artifact_id", "catalog_revision_artifacts.id"),),
    "repair_kits": (
        ("builder_revision_id", "catalog_revisions.id"),
        ("builder_kit_id", "catalog_revision_repair_kits.id"),
    ),
    "repair_kit_components": (("builder_component_id", "catalog_revision_repair_kit_components.id"),),
    "catalog_diagrams": (
        ("builder_revision_id", "catalog_revisions.id"),
        ("builder_visual_page_id", "catalog_revision_visual_pages.id"),
    ),
    "catalog_visual_sources": (
        ("builder_revision_id", "catalog_revisions.id"),
        ("builder_visual_page_id", "catalog_revision_visual_pages.id"),
    ),
    "catalog_visual_part_maps": (("builder_part_page_map_id", "catalog_revision_part_page_maps.id"),),
    "catalog_position_hotspots": (
        ("builder_revision_id", "catalog_revisions.id"),
        ("builder_hotspot_id", "catalog_revision_position_hotspots.id"),
    ),
}
UNIQUE_SOURCES = {
    "builder_part_id", "builder_artifact_id", "builder_kit_id", "builder_component_id",
    "builder_visual_page_id", "builder_part_page_map_id", "builder_hotspot_id",
}


def _position_width(length: int) -> None:
    for table in ("part_catalog", "catalog_position_hotspots", "part_request_lines"):
        current = next(column for column in sa.inspect(op.get_bind()).get_columns(table)
                       if column["name"] == "position")
        if getattr(current["type"], "length", None) == length:
            continue
        with op.batch_alter_table(table) as batch:
            batch.alter_column("position", existing_type=sa.String(40 if length == 80 else 80),
                               type_=sa.String(length), existing_nullable=table != "catalog_position_hotspots")


def upgrade() -> None:
    _position_width(80)
    for table, changes in {
        "part_requests": (("part_name", sa.String(255), sa.Text(), False),),
        "part_request_lines": (("description", sa.String(500), sa.Text(), False),),
        "repair_kits": (("name", sa.String(255), sa.Text(), False),),
        "part_catalog": (("description", sa.String(500), sa.Text(), False),
                         ("category", sa.String(120), sa.String(255), True),
                         ("unit", sa.String(40), sa.String(80), True)),
    }.items():
        columns = {column["name"]: column for column in sa.inspect(op.get_bind()).get_columns(table)}
        for name, old, new, nullable in changes:
            current = columns[name]["type"]
            if type(current) is type(new) and getattr(current, "length", None) == getattr(new, "length", None):
                continue
            with op.batch_alter_table(table) as batch:
                batch.alter_column(name, existing_type=old, type_=new, existing_nullable=nullable)
    if "uq_catalog_current_publication" not in {
            index["name"] for index in sa.inspect(op.get_bind()).get_indexes("catalog_revisions")}:
        op.create_index("uq_catalog_current_publication", "catalog_revisions", ["catalog_id"], unique=True,
                        postgresql_where=sa.text("status = 'PUBLISHED'"),
                        sqlite_where=sa.text("status = 'PUBLISHED'"))
    diagram_constraints = {item["name"] for item in sa.inspect(op.get_bind()).get_unique_constraints("catalog_diagrams")}
    if "uq_catalog_diagram_source_document_page" not in diagram_constraints:
        with op.batch_alter_table("catalog_diagrams") as batch:
            if "uq_catalog_diagram_source_page" in diagram_constraints:
                batch.drop_constraint("uq_catalog_diagram_source_page", type_="unique")
            batch.create_unique_constraint("uq_catalog_diagram_source_document_page",
                                           ["source_id", "technical_document_id", "page_number"])
    for table, columns in LINEAGE.items():
        existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}
        for name, target in columns:
            if name in existing:
                continue
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column(name, sa.Integer(), nullable=True))
                batch.create_foreign_key(f"{table}_{name}_fkey", target.split(".")[0], [name], ["id"])
                batch.create_index(f"ix_{table}_{name}", [name], unique=name in UNIQUE_SOURCES)
    kit_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("repair_kits")}
    with op.batch_alter_table("repair_kits") as batch:
        for name in ("name_bg", "name_en", "name_ru"):
            if name not in kit_columns:
                batch.add_column(sa.Column(name, sa.String(255), nullable=True))
    indexes = {index["name"]: index for index in sa.inspect(op.get_bind()).get_indexes("repair_kits")}
    if indexes.get("ix_repair_kits_code", {}).get("unique"):
        op.drop_index("ix_repair_kits_code", table_name="repair_kits")
        op.create_index("ix_repair_kits_code", "repair_kits", ["code"])
    if "uq_legacy_repair_kit_code" not in indexes:
        op.create_index("uq_legacy_repair_kit_code", "repair_kits", ["code"], unique=True,
                        postgresql_where=sa.text("builder_kit_id IS NULL"),
                        sqlite_where=sa.text("builder_kit_id IS NULL"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM catalog_revisions WHERE status IN ('PUBLISHED', 'RETIRED')")):
        raise RuntimeError("Cannot downgrade: published catalog evidence exists")
    if any(bind.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE {name} IS NOT NULL"))
           for table, columns in LINEAGE.items() for name, _ in columns):
        raise RuntimeError("Cannot downgrade: publication lineage exists")
    for table in ("part_catalog", "catalog_position_hotspots", "part_request_lines"):
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE length(position) > 40")):
            raise RuntimeError("Cannot downgrade: a position exceeds 40 characters")
    if bind.scalar(sa.text("SELECT count(*) FROM part_catalog WHERE length(description) > 500")):
        raise RuntimeError("Cannot downgrade: a part description exceeds 500 characters")
    if bind.scalar(sa.text("SELECT count(*) FROM part_requests WHERE length(part_name) > 255")):
        raise RuntimeError("Cannot downgrade: a request title exceeds 255 characters")
    if bind.scalar(sa.text("SELECT count(*) FROM part_request_lines WHERE length(description) > 500")):
        raise RuntimeError("Cannot downgrade: a request line exceeds 500 characters")
    if bind.scalar(sa.text("SELECT count(*) FROM repair_kits WHERE length(name) > 255")):
        raise RuntimeError("Cannot downgrade: a repair kit name exceeds 255 characters")
    if bind.scalar(sa.text("SELECT count(*) FROM part_catalog WHERE length(category) > 120 OR length(unit) > 40")):
        raise RuntimeError("Cannot downgrade: a part field exceeds its old width")
    op.drop_index("uq_legacy_repair_kit_code", table_name="repair_kits")
    op.drop_index("ix_repair_kits_code", table_name="repair_kits")
    op.create_index("ix_repair_kits_code", "repair_kits", ["code"], unique=True)
    with op.batch_alter_table("repair_kits") as batch:
        for name in ("name_bg", "name_en", "name_ru"):
            batch.drop_column(name)
    for table, columns in reversed(tuple(LINEAGE.items())):
        inspector = sa.inspect(op.get_bind())
        indexes = {index["name"] for index in inspector.get_indexes(table)}
        foreign_keys = {key["name"] for key in inspector.get_foreign_keys(table)}
        with op.batch_alter_table(table) as batch:
            for name, _ in reversed(columns):
                if f"ix_{table}_{name}" in indexes:
                    batch.drop_index(f"ix_{table}_{name}")
                if f"{table}_{name}_fkey" in foreign_keys:
                    batch.drop_constraint(f"{table}_{name}_fkey", type_="foreignkey")
                batch.drop_column(name)
    op.drop_index("uq_catalog_current_publication", table_name="catalog_revisions")
    with op.batch_alter_table("catalog_diagrams") as batch:
        batch.drop_constraint("uq_catalog_diagram_source_document_page", type_="unique")
        batch.create_unique_constraint("uq_catalog_diagram_source_page", ["source_id", "page_number"])
    with op.batch_alter_table("part_catalog") as batch:
        batch.alter_column("description", existing_type=sa.Text(), type_=sa.String(500), existing_nullable=False)
        batch.alter_column("category", existing_type=sa.String(255), type_=sa.String(120), existing_nullable=True)
        batch.alter_column("unit", existing_type=sa.String(80), type_=sa.String(40), existing_nullable=True)
    with op.batch_alter_table("part_request_lines") as batch:
        batch.alter_column("description", existing_type=sa.Text(), type_=sa.String(500), existing_nullable=False)
    with op.batch_alter_table("part_requests") as batch:
        batch.alter_column("part_name", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False)
    with op.batch_alter_table("repair_kits") as batch:
        batch.alter_column("name", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False)
    _position_width(40)
